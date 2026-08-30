from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    flespi_token: str = ""
    flespi_device_id: int = 8846319
    flespi_mqtt_host: str = "mqtt.flespi.io"
    flespi_mqtt_port: int = 8883
    flespi_mqtt_tls: bool = True

    host: str = "0.0.0.0"
    port: int = 8787
    database_path: str = "/data/camper.db"
    cors_origins: str = "*"

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_sms_from: str = ""
    alert_sms_to: str = ""
    twilio_whatsapp_from: str = ""
    alert_whatsapp_to: str = ""

    # Twilio trial-mode messaging.
    # Trial accounts cannot send arbitrary SMS/WhatsApp text.
    twilio_trial_mode: bool = True
    twilio_sms_trial_template: str = "sms_account_alerts"
    twilio_whatsapp_content_sid: str = ""
    twilio_whatsapp_content_variables: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def db_path(self) -> Path:
        return Path(self.database_path).resolve()

    @property
    def cors_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]


settings = Settings()
