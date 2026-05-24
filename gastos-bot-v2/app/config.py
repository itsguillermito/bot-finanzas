"""
Configuración global. Carga variables de entorno con validación.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Telegram
    telegram_bot_token: str
    telegram_allowed_user_id: int
    telegram_webhook_secret: str

    # Anthropic
    anthropic_api_key: str

    # Notion
    notion_api_key: str
    notion_database_id: str
    notion_income_database_id: str = ""  # nueva DB de ingresos

    # General
    timezone: str = "America/Mexico_City"
    public_url: str = ""

    # Reminder window (hora local MX)
    reminder_hour_start: int = 21
    reminder_hour_end: int = 22

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
