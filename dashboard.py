# Vereisten:
# pip install flask paho-mqtt

import json
import threading
from flask import Flask, render_template_string, jsonify
import paho.mqtt.client as mqtt

# MQTT instellingen
MQTT_BROKER = "test.mosquitto.org"  # Aanpassen naar jouw broker
MQTT_PORT = 1883
MQTT_TOPIC = "race/#"  # Luistert nu naar alle topics onder race/

# Per topic laatste data opslaan
latest_data = {}
# Per topic kolomvolgorde opslaan
topic_columns = {}

# Basisvolgorde voor kolommen per topic
BASE_ORDER_PER_TOPIC = {
    "race/results": ["Rang", "Rugnummer", "Naam", "Team", "AantalPassages", "RaceTijdStr", "AchterstandStr"],
    "race/pass": ["Rugnummer", "Naam", "Team", "TijdStr","VerschilStr" ]
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

# HTML template
html_template = """
<!doctype html>
<html>
<head>
    <title>Belgian Cycling Results</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</head>
<body class="p-4">
    <h1>Voorlopige uitslag - Provisional result</h1>

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
            {{ render_table(data.get(topic, []), columns.get(topic, []), col_titles.get(topic, {})) | safe }}
        </div>
        {% endfor %}
    </div>
    {% else %}
    <p>Geen topics gevonden onder '{{ base_topic }}'</p>
    {% endif %}

<script>
const columnTitlesPerTopic = {{ col_titles|tojson }};

document.addEventListener("DOMContentLoaded", function () {
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

    setInterval(fetchData, 3000);
});

function fetchData() {
    fetch("/data")
        .then(response => response.json())
        .then(json => {
            for (const topic in json.data) {
                const pane = document.querySelector(`[data-topic="${topic}"]`);
                if (pane) {
                    pane.innerHTML = buildTable(json.data[topic], json.columns[topic], topic);
                }
            }
        })
        .catch(err => console.error("Fout bij ophalen data:", err));
}

function buildTable(rows, columns, topic) {
    const columnTitles = columnTitlesPerTopic[topic] || {};
    if (!rows || !columns) {
        return "<p>Geen data ontvangen voor dit topic...</p>";
    }
    let html = '<div class="table-responsive" style="max-height: 70vh; overflow-y: auto;">';
    html += '<table class="table table-bordered table-sm"><thead><tr>';
    for (const col of columns) {
        html += `<th>${columnTitles[col] || col}</th>`;
    }
    html += "</tr></thead><tbody>";
    for (const row of rows) {
        html += "<tr>";
        for (const col of columns) {
            html += `<td>${row[col] !== undefined ? row[col] : ""}</td>`;
        }
        html += "</tr>";
    }
    html += "</tbody></table></div>";
    return html;
}
</script>
</body>
</html>
"""

def render_table(rows, columns, titles):
    if not rows or not columns:
        return "<p>Geen data ontvangen voor dit topic...</p>"
    html = '<div class="table-responsive" style="max-height: 70vh; overflow-y: auto;">'
    html += '<table class="table table-bordered table-sm"><thead><tr>'
    for col in columns:
        html += f"<th>{titles.get(col, col)}</th>"
    html += "</tr></thead><tbody>"
    for row in rows:
        html += "<tr>"
        for col in columns:
            html += f"<td>{row.get(col, '')}</td>"
        html += "</tr>"
    html += "</tbody></table></div>"
    return html

@app.route("/")
def index():
    topics = list(latest_data.keys())
    col_titles_dict = {t: get_column_titles_for_topic(t) for t in topics}
    return render_template_string(
        html_template,
        topics=topics,
        data=latest_data,
        base_topic=MQTT_TOPIC,
        render_table=render_table,
        columns=topic_columns,
        col_titles=col_titles_dict
    )

@app.route("/data")
def get_data():
    col_titles_dict = {t: get_column_titles_for_topic(t) for t in latest_data.keys()}
    return jsonify({"data": latest_data, "columns": topic_columns, "col_titles": col_titles_dict})

def on_connect(client, userdata, flags, rc):
    print("Verbonden met MQTT broker:", rc)
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    global latest_data, topic_columns
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

        print(f"Ontvangen van {msg.topic}")
    except Exception as e:
        print(f"Fout bij verwerken bericht van {msg.topic}:", e)

def start_mqtt():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_forever()

if __name__ == "__main__":
    mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
    mqtt_thread.start()
    app.run(host="0.0.0.0", port=5000)
