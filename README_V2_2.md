# Pössl Cloud Backend V2.2

Fixes stale Railway telemetry.

- MQTT stays the real-time path.
- Every 60 seconds the backend fetches flespi REST telemetry/all.
- Backend state is hydrated after restart.
- updated_at now follows latest flespi tracker/server timestamp.
- received_at shows backend receipt/sync time.

Deploy by replacing files in the existing private backend repo, then:

git add .
git commit -m "Backend V2.2 telemetry freshness fix"
git push

No Android APK rebuild is required for this backend correction.
