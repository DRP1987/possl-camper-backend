PÖSSL Telematics Backend V1.3

For the current Windows test PC, edit .env:

FLESPI_MQTT_HOST=mqtt.flespi.io
FLESPI_MQTT_PORT=1883
FLESPI_MQTT_TLS=false

Keep your Twilio settings exactly as they are.

Then start:
START_BACKEND.bat

Expected console:
flespi MQTT configuration
Host: mqtt.flespi.io
Port: 1883
TLS: OFF

Connected to flespi MQTT for device 8846319

Check:
http://localhost:8787/health
http://localhost:8787/docs

For a future clean production server:
FLESPI_MQTT_PORT=8883
FLESPI_MQTT_TLS=true
