PÖSSL Telematics Backend V1.2

New:
GET  /api/notifications/status
POST /api/notifications/test

Open:
http://localhost:8787/docs

Example:
{
  "sms": true,
  "whatsapp": true,
  "push": false,
  "title": "PÖSSL Test Alert",
  "message": "Backend notification test."
}
