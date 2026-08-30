PÖSSL Telematics Backend V1.1

MQTT callback compatibility fix for paho-mqtt 2.x.

Start normally with START_BACKEND.bat.

Expected successful console output:

Connected to flespi MQTT for device 8846319
Subscribed to device messages and telemetry (message rc=0, telemetry rc=0)

Then check:
http://localhost:8787/health
http://localhost:8787/api/status
