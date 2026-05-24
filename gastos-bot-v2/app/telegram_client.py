"""
Wrapper minimalista del Bot API de Telegram.
Sin dependencias pesadas — sólo httpx.
"""
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

API_BASE = f"https://api.telegram.org/bot{settings.telegram_bot_token}"


async def send_message(chat_id: int, text: str, parse_mode: str = "Markdown") -> None:
    """Envía un mensaje al chat. No tira excepción si falla — sólo loggea."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.post(
                f"{API_BASE}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
            )
            if r.status_code != 200:
                logger.warning(f"Telegram sendMessage falló: {r.status_code} {r.text}")
        except Exception as e:
            logger.exception(f"Error mandando mensaje a Telegram: {e}")


async def set_webhook(public_url: str) -> bool:
    """Registra el webhook con Telegram. Devuelve True si OK."""
    webhook_url = f"{public_url.rstrip('/')}/telegram/webhook"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{API_BASE}/setWebhook",
            json={
                "url": webhook_url,
                "secret_token": settings.telegram_webhook_secret,
                "allowed_updates": ["message"],
            },
        )
        ok = r.status_code == 200 and r.json().get("ok", False)
        logger.info(f"setWebhook → {webhook_url} | ok={ok} | resp={r.text[:200]}")
        return ok


async def delete_webhook() -> None:
    """Útil para debug local."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(f"{API_BASE}/deleteWebhook")
