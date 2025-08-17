from flask import Flask, render_template_string, jsonify, request
# Vereisten:
# pip install flask paho-mqtt flask-socketio

import json
import threading
from flask import Flask, render_template_string, jsonify
import paho.mqtt.client as mqtt
from flask_socketio import SocketIO
from flask import request

# MQTT instellingen
MQTT_BROKER = "test.mosquitto.org"  # Aanpassen naar jouw broker
MQTT_PORT = 1883
MQTT_TOPIC = "race/#"  # Luistert nu naar alle topics onder TEST/

LOG_LEVEL = 2      # 1=basic, 2=TCP data, 3=debug
# Per topic laatste data opslaan
latest_data = {}
# Per topic kolomvolgorde opslaan
topic_columns = {}

# Basisvolgorde voor kolommen per topic
BASE_ORDER_PER_TOPIC = {
    "race/results": ["Rang", "Rugnummer","Naam", "Team", "AantalPassages", "RaceTijdStr", "AchterstandStr"],
    "race/pass": ["Rugnummer", "Transponder", "Naam", "Team", "TijdStr","VerschilStr" ]
}

# Kolomtitel mapping per topic
COLUMN_TITLES_PER_TOPIC = {
    "race/results": {
        "Rang": "Positie",
        "Rugnummer": "Nr",
        "Naam": "Renner",
        "Team": "Ploeg",
        "AantalPassages": "Passages",
        "RaceTijdStr": "Tijd",
        "AchterstandStr": "Achterstand"
    },
    "race/pass": {
        "Rugnummer": "Nr",
        "Naam": "Naam",
        "Transponder": "Transponder",
        "Team": "Ploeg",
        "TijdStr": "Passage",
        "VerschilStr": "Verschil"
    }
}

# Fallback als topic geen specifieke instelling heeft
BASE_ORDER_DEFAULT = ["Rang", "Rugnummer", "Naam", "Team", "AantalPassages", "RaceTijdStr", "AchterstandStr"]
COLUMN_TITLES_DEFAULT = {
    "Rang": "Positie",
    "Rugnummer": "Nr",
    "Naam": "Renner",
    "Team": "Ploeg",
    "AantalPassages": "Passages",
    "RaceTijdStr": "Tijd",
    "AchterstandStr": "Achterstand"
}

def logging(msg, level=1):
    if level <= LOG_LEVEL:
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] {msg}")

def get_base_order_for_topic(topic):
    for prefix, order in BASE_ORDER_PER_TOPIC.items():
        if topic.startswith(prefix):
            return order
    return BASE_ORDER_DEFAULT

def get_column_titles_for_topic(topic):
    for prefix, titles in COLUMN_TITLES_PER_TOPIC.items():
        if topic.startswith(prefix):
            return titles
    return COLUMN_TITLES_DEFAULT

# Flask app
app = Flask(__name__)
socketio = SocketIO(app, async_mode="eventlet")

# HTML template
html_template = """
<!doctype html>
<html>
<head>
    <title>Belgian Cycling Results</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <meta http-equiv="refresh" content="3">
</head>
<body class="p-4">
    <h1>Voorlopige uitslag - Provisional result (<span id="datetime"></span>)</h1>
    <script>
            function updateDateTime() {
                const now = new Date();
                // Datum en tijd in format: 16-08-2025 14:30
                //const formatted = now.getDate().toString().padStart(2,'0') + '-' +
                //                (now.getMonth()+1).toString().padStart(2,'0') + '-' +
                //                now.getFullYear() + ' ' +
                const formatted = now.getHours().toString().padStart(2,'0') + ':' +
                                  now.getMinutes().toString().padStart(2,'0');
                document.getElementById('datetime').textContent = formatted;
            }

           updateDateTime();          // eerste keer tonen
     </script>

    {% if topics %}
    <ul class="nav nav-tabs" id="myTab" role="tablist">
        {% for topic in topics %}
        <li class="nav-item" role="presentation">
            <button class="nav-link {% if loop.first %}active{% endif %}" id="tabbtn{{ loop.index }}"
                    data-bs-toggle="tab" data-bs-target="#tab{{ loop.index }}" type="button" role="tab">
                {{ topic }}
            </button>
        </li>
        {% endfor %}
    </ul>

    <div class="tab-content mt-3">
        {% for topic in topics %}
        <div class="tab-pane fade {% if loop.first %}show active{% endif %}"
             id="tab{{ loop.index }}" role="tabpanel" data-topic="{{ topic }}">
            {% if "pass" in topic %}
            <div class="mb-2" id="search-container-{{ loop.index }}">
                <input type="text" class="form-control" id="searchGrid{{ loop.index }}" placeholder="Zoek in alle kolommen..." oninput="filterGrid('{{ topic }}', {{ loop.index }})">
            </div>
            {% endif %}
            <div id="table-container-{{ loop.index }}">
                {{ render_table(data.get(topic, []), columns.get(topic, []), col_titles.get(topic, {}), topic) | safe }}
            </div>
        </div>
        {% endfor %}
    </div>
    {% else %}
    <p>Geen topics gevonden onder '{{ base_topic }}'</p>
    {% endif %}
<script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
<script>

document.addEventListener("DOMContentLoaded", function () {
    // SocketIO realtime update
    const socket = io();
    socket.on('mqtt_update', function() {
        console.log('Realtime MQTT update ontvangen');
        fetchData();
    });

    // Actie parameter opslaan bij eerste bezoek
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has("admin")) {
        localStorage.setItem("admin", urlParams.get("admin"));
    }

    // Als er geen parameter in de URL staat, maar wel in localStorage → herladen met actie=1
    if (!urlParams.has("admin") && localStorage.getItem("admin") === "1") {
        urlParams.set("admin", "1");
        window.location.search = urlParams.toString();
    }

    // Tab-herstel en event listeners
    const lastTab = localStorage.getItem("activeTab");
    if (lastTab) {
        const tabTriggerEl = document.querySelector(`[data-bs-target="${lastTab}"]`);
        if (tabTriggerEl) {
            const tab = new bootstrap.Tab(tabTriggerEl);
            tab.show();
        }
    }
    document.querySelectorAll('button[data-bs-toggle="tab"]').forEach(button => {
        button.addEventListener('shown.bs.tab', function (event) {
            const target = event.target.getAttribute('data-bs-target');
            localStorage.setItem("activeTab", target);
        });
    });

    // Optioneel: fallback interval
    // setInterval(fetchData, 30000);
});

function filterGrid(topic, tabIndex) {
    const input = document.getElementById('searchGrid' + tabIndex);
    const filter = input.value.trim().toLowerCase();

    // Bewaar filter per topic in localStorage
    localStorage.setItem("filter_" + topic, filter);

    const pane = document.querySelector(`[data-topic="${topic}"]`);
    if (!pane) return;
    const rows = pane.querySelectorAll('tr[data-key]');
    rows.forEach(row => {
        let match = false;
        row.querySelectorAll('td').forEach(cell => {
            if (cell.textContent.toLowerCase().includes(filter)) {
                match = true;
            }
        });
        row.style.display = match || filter === "" ? "" : "none";
    });
}

const columnTitlesPerTopic = {{ col_titles|tojson }};

function fetchData() {
    console.log("fetchData wordt uitgevoerd");
    fetch("/data")
        .then(response => response.json())
        .then(json => {
            console.log(json)
            json.topics.forEach((topic, idx) => {
                const pane = document.querySelector(`[data-topic="${topic}"]`);
                const tableContainer = document.getElementById('table-container-' + (idx + 1));
                if (tableContainer) {
                    tableContainer.innerHTML = buildTable(json.data[topic], json.columns[topic], topic);

                    // Herstel de filter indien aanwezig
                    const savedFilter = localStorage.getItem("filter_" + topic);
                    if (savedFilter && savedFilter !== "") {
                        const input = document.getElementById('searchGrid' + (idx+1));
                        if (input) {
                            input.value = savedFilter;
                            filterGrid(topic, idx+1);
                        }
                    }
                }
            });
        })
        .catch(err => console.error("Fout bij ophalen data:", err));
}


function buildTable(rows, columns, topic) {
    const url = new URL('https://example.com?page=1&sort=desc');
    const params = new URLSearchParams(url.search);
    const isAdmin = params.get('admin') === "1";
    console.log("Build Table - Show action:" + isAdmin );
    const columnTitles = columnTitlesPerTopic[topic] || {};
    if (!rows || !columns) {
        return "<p>Geen data ontvangen voor dit topic...</p>";
    }
    let html = '<div class="table-responsive" style="max-height: 70vh; overflow-y: auto;">';
    html += '<table class="table table-bordered table-sm"><thead><tr>';
    for (const col of columns) {
        html += `<th>${columnTitles[col] || col}</th>`;
    }
    if (topic.includes("pass") && isAdmin) {
       html += "<th>Actie</th>";
    }
    html += "</tr></thead><tbody>";
    for (const row of rows) {
        // Unieke key: rugnummer, tijdstip, topic-type
        const key = `${row['Rugnummer'] || ''}_${row['TijdStr'] || ''}_${topic.includes('pass') ? 'pass' : 'result'}`;
        if (topic.includes("pass")) {
            html += `<tr data-key="${key}">`;
        } else {
            html += `<tr data-key="${key}">`;
        }
        for (const col of columns) {
            html += `<td>${row[col] !== undefined ? row[col] : ""}</td>`;
        }
         if (topic.includes("pass") && isAdmin) {
            html += `<td><button class="btn btn-sm btn-danger" onclick="deleteRow('${row['Rugnummer']}', '${topic}', '${row['TijdStr'] || ''}', '${row['Transponder'] || ''}', '${key}')">🗑️</button></td>`;
        }
        html += "</tr>";
    }
    html += "</tbody></table></div>";
    return html;
}

function deleteRow(rugnummer, topic, tijd, transponder, key) {
    fetch("/delete", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            Rugnummer: rugnummer,
            Topic: topic,
            TijdStr: tijd,
            Transponder: transponder
        })
    }).then(res => res.json())
      .then(json => {
          console.log("Delete response:", json);
          if (json.status === "ok") {
              const row = document.querySelector(`tr[data-key='${key}']`);
              if (row) row.remove();
          }
      })
      .catch(err => console.error("Fout bij delete:", err));
}
</script>
</body>
</html>
"""

def render_table(rows, columns, titles, topic):
    show_actie = request.args.get("admin", "0") == "1"
    if not rows or not columns:
        return "<p>Geen data ontvangen voor dit topic...</p>"
    html = '<div class="table-responsive" style="max-height: 70vh; overflow-y: auto;">'
    html += '<table class="table table-bordered table-sm"><thead><tr>'
    for col in columns:
        html += f"<th>{titles.get(col, col)}</th>"
    if "pass" in topic and show_actie:
        html += "<th>Actie</th>"
    html += "</tr></thead><tbody>"
    for row in rows:
        key = f"{row.get('Rugnummer','')}_{row.get('TijdStr','')}_{'pass' if 'pass' in topic else 'result'}"
        html += f"<tr data-key='{key}'>"
        for col in columns:
            html += f"<td>{row.get(col, '')}</td>"
        if "pass" in topic and  show_actie:
            html += f"<td><button class='btn btn-sm btn-danger' onclick=\"deleteRow('{row.get('Rugnummer','')}', '{topic}', '{row.get('TijdStr','')}', '{row.get('Transponder','')}')\">🗑️</button></td>"
        html += "</tr>"
    html += "</tbody></table></div>"
    return html

@app.route("/")
def index():
    global latest_data, topic_columns
    topics = list(latest_data.keys())

    # Check of ?clear=1 is meegegeven → leegmaken
    if request.args.get("clear", "0") == "1":
        latest_data = {}
        topic_columns = {}
        topics = []  # want alles gewist

    col_titles_dict = {t: get_column_titles_for_topic(t) for t in topics}
    # Actie-kolom toggle
    show_actie = request.args.get("admin", "0") == "1"

    return render_template_string(
        html_template,
        topics=topics,
        data=latest_data,
        base_topic=MQTT_TOPIC,
        render_table=render_table,
        columns=topic_columns,
        col_titles=col_titles_dict,
        show_actie=show_actie
    )

def clean_nan(obj):
    import math
    if isinstance(obj, dict):
        return {k: clean_nan(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_nan(v) for v in obj]
    elif isinstance(obj, float):
        return None if math.isnan(obj) else obj
    else:
        return obj

@app.route("/data")
def get_data():
    col_titles_dict = {t: get_column_titles_for_topic(t) for t in latest_data.keys()}
    cleaned_data = {k: clean_nan(v) for k, v in latest_data.items()}
    import pprint
    logging(f"/data endpoint geeft terug: {pprint.pformat(cleaned_data)}", level=3)
    return jsonify({"data": cleaned_data, "columns": topic_columns, "col_titles": col_titles_dict, "topics": list(latest_data.keys())})
@app.route("/delete", methods=["POST"])
def delete():
    rugnummer = request.json.get("Rugnummer")
    topic = request.json.get("Topic")
    tijd = request.json.get("TijdStr")
    transponder = request.json.get("Transponder")

    if rugnummer and topic:
        delete_topic = f"{topic}/delete"
        payload = {"Rugnummer": rugnummer}
        if tijd:
            payload["TijdStr"] = tijd
        if transponder:
            payload["Transponder"] = transponder
        mqtt_client.publish(delete_topic, json.dumps(payload))
        return jsonify({"status": "ok", "topic": delete_topic, "payload": payload})
    return jsonify({"status": "error", "reason": "geen Rugnummer of topic"}), 400

def on_connect(client, userdata, flags, rc):
    logging(f"Verbonden met MQTT broker: {rc}")
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    global latest_data, topic_columns
    # Negeer alle delete topics
    if msg.topic.endswith("/delete"):
        return
    try:
        payload = msg.payload.decode("utf-8")
        parsed = json.loads(payload)
        latest_data[msg.topic] = parsed

        if isinstance(parsed, list) and parsed:
            all_keys = list(parsed[0].keys())
            col_order_base = get_base_order_for_topic(msg.topic)
            col_order = [k for k in col_order_base if k in all_keys]
            topic_columns[msg.topic] = col_order
        else:
            topic_columns[msg.topic] = get_base_order_for_topic(msg.topic)

        logging(f"Ontvangen van {msg.topic}")
        socketio.emit('mqtt_update')
    except Exception as e:
        logging(f"Fout bij verwerken bericht van {msg.topic}: {e}")

def start_mqtt():
    global mqtt_client
    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.loop_forever()

if __name__ == "__main__":
    mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
    mqtt_thread.start()
    socketio.run(app, host="0.0.0.0", port=5000)
