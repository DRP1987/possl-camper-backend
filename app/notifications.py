import asyncio
import json
import httpx
from twilio.rest import Client
from .config import settings
from .database import Database


class NotificationService:
    def __init__(self, db: Database):
        self.db = db

    def _twilio_ready(self) -> bool:
        return bool(settings.twilio_account_sid and settings.twilio_auth_token)

    def _whatsapp_content_variables(self) -> str | None:
        raw = (settings.twilio_whatsapp_content_variables or "").strip()
        if not raw:
            return None
        # Twilio expects ContentVariables as a JSON-encoded string.
        try:
            parsed = json.loads(raw)
            return json.dumps(parsed, separators=(",", ":"))
        except Exception:
            # Keep an invalid value visible to Twilio so the returned API error
            # explains the configuration problem.
            return raw

    async def _create_sms(self, body: str):
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        if settings.twilio_trial_mode:
            # Twilio trial SMS accepts only a predefined template identifier
            # in the Body field, not arbitrary custom alert text.
            return await asyncio.to_thread(
                client.messages.create,
                body=settings.twilio_sms_trial_template,
                from_=settings.twilio_sms_from,
                to=settings.alert_sms_to,
            )

        return await asyncio.to_thread(
            client.messages.create,
            body=body,
            from_=settings.twilio_sms_from,
            to=settings.alert_sms_to,
        )

    async def _create_whatsapp(self, body: str):
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

        if settings.twilio_trial_mode:
            if not settings.twilio_whatsapp_content_sid:
                raise RuntimeError(
                    "TWILIO_WHATSAPP_CONTENT_SID is empty. Copy the HX... "
                    "ContentSid from Twilio Console -> Messaging -> WhatsApp -> Try out WhatsApp."
                )

            kwargs = {
                "from_": settings.twilio_whatsapp_from,
                "to": settings.alert_whatsapp_to,
                "content_sid": settings.twilio_whatsapp_content_sid,
            }
            variables = self._whatsapp_content_variables()
            if variables:
                kwargs["content_variables"] = variables
            return await asyncio.to_thread(client.messages.create, **kwargs)

        # Paid/production WhatsApp: proactive business-initiated notifications
        # generally need an approved Content Template. If configured, use it.
        if settings.twilio_whatsapp_production_content_sid:
            kwargs = {
                "from_": settings.twilio_whatsapp_from,
                "to": settings.alert_whatsapp_to,
                "content_sid": settings.twilio_whatsapp_production_content_sid,
            }
            variables = self._production_whatsapp_variables(body)
            if variables:
                kwargs["content_variables"] = variables
            return await asyncio.to_thread(client.messages.create, **kwargs)

        # Free-form WhatsApp remains useful inside an active customer-service window.
        return await asyncio.to_thread(
            client.messages.create,
            body=body,
            from_=settings.twilio_whatsapp_from,
            to=settings.alert_whatsapp_to,
        )

    def _production_whatsapp_variables(self, body: str) -> str | None:
        raw = (settings.twilio_whatsapp_production_content_variables or "").strip()
        if raw:
            try:
                parsed = json.loads(raw)
                # Convenience substitution: "{{alert}}" can contain the current
                # generated alert body.
                parsed = {
                    str(k): (body if str(v) == "{{alert}}" else v)
                    for k, v in parsed.items()
                }
                return json.dumps(parsed, separators=(",", ":"))
            except Exception:
                return raw

        # If a production ContentSid is configured but no explicit variable
        # mapping is supplied, expose the complete alert as variable 1.
        return json.dumps({"1": body}, separators=(",", ":"))

    async def _send_sms(self, alert_id: int, body: str):
        try:
            msg = await self._create_sms(body)
            self.db.update_delivery(alert_id, sms_status=f"sent:{msg.sid}")
        except Exception as exc:
            self.db.update_delivery(alert_id, sms_status=f"error:{exc}")

    async def _send_whatsapp(self, alert_id: int, body: str):
        try:
            msg = await self._create_whatsapp(body)
            self.db.update_delivery(alert_id, whatsapp_status=f"sent:{msg.sid}")
        except Exception as exc:
            self.db.update_delivery(alert_id, whatsapp_status=f"error:{exc}")

    async def _send_expo_push(self, tokens: list[str], title: str, body: str):
        payload = [
            {
                "to": t,
                "title": title,
                "body": body,
                "sound": "default",
                "priority": "high",
                "channelId": "camper-alerts",
                "data": {"screen": "alerts"},
            }
            for t in tokens
        ]

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://exp.host/--/api/v2/push/send",
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip, deflate",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

        # Expo can return HTTP 200 but reject individual push messages.
        tickets = result.get("data", []) if isinstance(result, dict) else []
        errors = []
        for idx, ticket in enumerate(tickets):
            if ticket.get("status") == "error":
                errors.append({
                    "token": tokens[idx] if idx < len(tokens) else None,
                    "message": ticket.get("message"),
                    "details": ticket.get("details"),
                })
        if errors:
            raise RuntimeError(f"Expo push rejected message(s): {errors}")

        return result

