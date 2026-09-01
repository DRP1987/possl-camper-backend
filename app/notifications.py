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

    async def send(
        self,
        alert_id: int,
        title: str,
        message: str,
        *,
        sms_enabled: bool,
        whatsapp_enabled: bool,
        push_enabled: bool,
    ):
        """Deliver a real alert over all enabled channels."""
        body = f"{title}\n{message}"
        tasks = []

        if (
            sms_enabled
            and self._twilio_ready()
            and settings.twilio_sms_from
            and settings.alert_sms_to
        ):
            tasks.append(self._send_sms(alert_id, body))

        if (
            whatsapp_enabled
            and self._twilio_ready()
            and settings.twilio_whatsapp_from
            and settings.alert_whatsapp_to
        ):
            tasks.append(self._send_whatsapp(alert_id, body))

        push_tokens = self.db.push_tokens() if push_enabled else []
        if push_tokens:
            tasks.append(self._send_expo_push(push_tokens, title, message))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_channels(
        self,
        title: str,
        message: str,
        *,
        sms: bool = False,
        whatsapp: bool = False,
        push: bool = False,
    ) -> dict:
        """Send explicit test notifications and ALWAYS return JSON serializable status."""
        body = f"{title}\n{message}"
        result = {
            "sms": {
                "requested": sms,
                "configured": False,
                "status": "not_requested",
            },
            "whatsapp": {
                "requested": whatsapp,
                "configured": False,
                "status": "not_requested",
            },
            "push": {
                "requested": push,
                "configured": False,
                "status": "not_requested",
            },
        }

        if sms:
            configured = bool(
                self._twilio_ready()
                and settings.twilio_sms_from
                and settings.alert_sms_to
            )
            result["sms"]["configured"] = configured
            if not configured:
                result["sms"]["status"] = "not_configured"
            else:
                try:
                    msg = await self._create_sms(body)
                    result["sms"]["status"] = "sent"
                    result["sms"]["sid"] = msg.sid
                except Exception as exc:
                    result["sms"]["status"] = "error"
                    result["sms"]["error"] = str(exc)

        if whatsapp:
            configured = bool(
                self._twilio_ready()
                and settings.twilio_whatsapp_from
                and settings.alert_whatsapp_to
            )
            result["whatsapp"]["configured"] = configured
            if not configured:
                result["whatsapp"]["status"] = "not_configured"
            else:
                try:
                    msg = await self._create_whatsapp(body)
                    result["whatsapp"]["status"] = "sent"
                    result["whatsapp"]["sid"] = msg.sid
                except Exception as exc:
                    result["whatsapp"]["status"] = "error"
                    result["whatsapp"]["error"] = str(exc)

        if push:
            tokens = self.db.push_tokens()
            result["push"]["configured"] = bool(tokens)
            if not tokens:
                result["push"]["status"] = "no_registered_devices"
            else:
                try:
                    expo_result = await self._send_expo_push(
                        tokens,
                        title,
                        message,
                    )
                    result["push"]["status"] = "sent"
                    result["push"]["device_count"] = len(tokens)
                    result["push"]["expo_response"] = expo_result
                except Exception as exc:
                    result["push"]["status"] = "error"
                    result["push"]["error"] = str(exc)

        return result

    async def _send_sms(self, alert_id: int, body: str):
        try:
            msg = await self._create_sms(body)
            self.db.update_delivery(
                alert_id,
                sms_status=f"sent:{msg.sid}",
            )
        except Exception as exc:
            self.db.update_delivery(
                alert_id,
                sms_status=f"error:{exc}",
            )

    async def _send_whatsapp(self, alert_id: int, body: str):
        try:
            msg = await self._create_whatsapp(body)
            self.db.update_delivery(
                alert_id,
                whatsapp_status=f"sent:{msg.sid}",
            )
        except Exception as exc:
            self.db.update_delivery(
                alert_id,
                whatsapp_status=f"error:{exc}",
            )

    async def _send_expo_push(
        self,
        tokens: list[str],
        title: str,
        body: str,
    ):
        payload = [
            {
                "to": token,
                "title": title,
                "body": body,
                "sound": "default",
                "priority": "high",
                "channelId": "camper-alerts",
                "data": {"screen": "alerts"},
            }
            for token in tokens
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

        # Expo may reply HTTP 200 while rejecting an individual token/message.
        tickets = (
            result.get("data", [])
            if isinstance(result, dict)
            else []
        )

        if isinstance(tickets, dict):
            tickets = [tickets]

        errors = []
        for index, ticket in enumerate(tickets):
            if isinstance(ticket, dict) and ticket.get("status") == "error":
                errors.append(
                    {
                        "token": (
                            tokens[index]
                            if index < len(tokens)
                            else None
                        ),
                        "message": ticket.get("message"),
                        "details": ticket.get("details"),
                    }
                )

        if errors:
            raise RuntimeError(
                f"Expo push rejected message(s): {errors}"
            )

        return result
