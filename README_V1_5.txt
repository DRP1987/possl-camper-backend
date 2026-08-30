PÖSSL Telematics Backend V1.5

TWILIO TRIAL CONFIGURATION

Keep:
TWILIO_TRIAL_MODE=true

SMS:
TWILIO_SMS_TRIAL_TEMPLATE=sms_account_alerts

WhatsApp:
Go to Twilio Console -> Messaging -> WhatsApp -> Try out WhatsApp.
Copy the HX... ContentSid shown in the generated API example:

TWILIO_WHATSAPP_CONTENT_SID=HX...

If that provided template needs variables:
TWILIO_WHATSAPP_CONTENT_VARIABLES={"1":"value1","2":"value2"}

If it doesn't:
TWILIO_WHATSAPP_CONTENT_VARIABLES=

Test:
http://localhost:8787/docs

GET  /api/notifications/status
POST /api/notifications/test

After upgrading Twilio:
TWILIO_TRIAL_MODE=false
