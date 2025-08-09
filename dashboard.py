# Vereisten:
# pip install flask paho-mqtt

import json
import threading
from flask import Flask, render_template_string, jsonify
import paho.mqtt.client as mqtt

# MQTT instellingen
MQTT_BROKER = "test.mosquitto.org"  # Aanpassen naar jouw broker
MQTT_PORT = 1883
MQTT_TOPIC = "race/#"  # Luistert naar alle subtopics van race

# Per topic laatste data opslaan
latest_data = {}
# Per topic kolomvolgorde opslaan
topic_columns = {}

# Basisvolgorde voor kolommen
BASE_ORDER = ["Rang", "Rugnummer", "Naam", "Team", "AantalPassages", "RaceTijdStr", "AchterstandStr"]

# Kolomtitel mapping
COLUMN_TITLES = {
    "Rang": "Positie",
    "Rugnummer": "Nr",
    "Naam": "Renner",
    "Team": "Ploeg",
    "AantalPassages": "Passages",
    "RaceTijdStr": "Tijd",
    "AchterstandStr": "Achterstand"
}

# Flask app
app = Flask(__name__)

# HTML template met tabs en AJAX updates
html_template = """
<!doctype html>
<html>
<head>
    <title>VOORLOPIGE UITSLAG - PROVISIONAL RESULTS </title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</head>
<body class="p-4">
    <h1>MQTT Data per Topic</h1>

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
            {{ render_table(data.get(topic, []), columns.get(topic, [])) }}
        </div>
        {% endfor %}
    </div>
    {% else %}
    <p>Geen topics gevonden onder '{{ base_topic }}'</p>
    {% endif %}

<script>
const columnTitles = {{ col_titles|tojson }};

document.addEventListener("DOMContentLoaded", function () {
    // Tab onthouden
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

    // Data elke 3 seconden verversen
    setInterval(fetchData, 3000);
});

function fetchData() {
    fetch("/data")
        .then(response => response.json())
        .then(json => {
            for (const topic in json.data) {
                const pane = document.querySelector(`[data-topic="${topic}"]`);
                if (pane) {
                    pane.innerHTML = buildTable(json.data[topic], json.columns[topic]);
                }
            }
        })
        .catch(err => console.error("Fout bij ophalen data:", err));
}

function buildTable(rows, columns) {
    if (!rows || !columns) {
        return "<p>Geen data ontvangen voor dit topic...</p>";
    }
    let html = '<table class="table table-bordered table-sm"><thead><tr>';
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
    html += "</tbody></table>";
    return html;
}
</script>
</body>
</html>
"""

def render_table(rows, columns):
    if not rows or not columns:
        return "<p>Geen data ontvangen voor dit topic...</p>"
    html = '<table class="table table-bordered table-sm"><thead><tr>'
    for col in columns:
        html += f"<th>{COLUMN_TITLES.get(col, col)}</th>"
    html += "</tr></thead><tbody>"
    for row in rows:
        html += "<tr>"
        for col in columns:
            html += f"<td>{row.get(col, '')}</td>"
        html += "</tr>"
    html += "</tbody></table>"
    return html

@app.route("/")
def index():
    topics = list(latest_data.keys())
    return render_template_string(
        html_template,
        topics=topics,
        data=latest_data,
        base_topic=MQTT_TOPIC,
        render_table=render_table,
        columns=topic_columns,
        col_titles=COLUMN_TITLES
    )

@app.route("/data")
def get_data():
    return jsonify({"data": latest_data, "columns": topic_columns})

# MQTT callbacks
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
            # Alleen kolommen tonen die in BASE_ORDER staan en in de data zitten
            col_order = [k for k in BASE_ORDER if k in all_keys]
            topic_columns[msg.topic] = col_order
        else:
            topic_columns[msg.topic] = BASE_ORDER

        print(f"Ontvangen van {msg.topic}")
    except Exception as e:
        print(f"Fout bij verwerken bericht van {msg.topic}:", e)

# MQTT starten in aparte thread
def start_mqtt():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_forever()

