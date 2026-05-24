"""
FastAPI app principal.

Endpoints:
- POST /telegram/webhook → recibe updates de Telegram
- GET  /health           → health check (para uptime monitors)
- POST /admin/set-webhook → registra el webhook con Telegram (manual, una vez)
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Header
from typing import Optional

from app.config import settings
from app import telegram_client, parser, notion_client
from app.scheduler import start_scheduler, stop_scheduler

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    start_scheduler()
    logger.info("App arrancada ✓")
    yield
    # Shutdown
    stop_scheduler()
    logger.info("App apagada")


app = FastAPI(lifespan=lifespan, title="Gastos Bot")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/admin/set-webhook")
async def admin_set_webhook(authorization: Optional[str] = Header(None)):
    """
    Registra el webhook con Telegram apuntando a este server.
    Llámalo una vez tras el deploy. Protegido por el mismo secret del webhook.
    """
    if authorization != f"Bearer {settings.telegram_webhook_secret}":
        raise HTTPException(401, "Unauthorized")
    if not settings.public_url:
        raise HTTPException(400, "PUBLIC_URL no configurada")
    ok = await telegram_client.set_webhook(settings.public_url)
    return {"ok": ok}


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
):
    # 1) Validar que el request realmente viene de Telegram
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        logger.warning("Webhook con secret inválido")
        raise HTTPException(403, "Forbidden")

    update = await request.json()
    message = update.get("message")
    if not message:
        return {"ok": True}  # ignoramos updates que no sean mensajes

    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")

    # 2) Validar que sea el usuario autorizado
    if user_id != settings.telegram_allowed_user_id:
        logger.warning(f"Usuario no autorizado: {user_id}")
        await telegram_client.send_message(
            chat_id,
            "🔒 Lo siento, este bot es privado.",
        )
        return {"ok": True}

    # 3) Comando /start
    if text.startswith("/start"):
        await telegram_client.send_message(
            chat_id,
            "👋 ¡Listo, Guille! Mándame tus gastos en lenguaje natural.\n\n"
            "*Ejemplos:*\n"
            "• `café 50`\n"
            "• `uber 87.50 débito`\n"
            "• `pagué 1,200 de gasolina con crédito en Pemex`\n"
            "• `recurrente Netflix 219`\n\n"
            "También puedes preguntarme:\n"
            "• `¿cuánto llevo este mes?`\n"
            "• `¿qué he gastado hoy?`\n\n"
            "Cada noche entre 9 y 10 pm te recuerdo registrar lo que falte. 🌙",
        )
        return {"ok": True}

    # 4) Parsear con Claude
    parsed = await parser.parse_message(text)
    ptype = parsed.get("type")

    if ptype == "expense" and parsed.get("expense"):
        e = parsed["expense"]
        try:
            fecha_iso = parser.resolve_date(e.get("fecha_relativa", "hoy"))
            await notion_client.create_expense(
                amount=float(e["amount"]),
                description=e["description"],
                category=e["category"],
                subcategory=e["subcategory"],
                fecha_iso=fecha_iso,
                payment_method=e.get("payment_method"),
                merchant=e.get("merchant"),
                tipo=e.get("type", "Necesidad"),
                recurring=bool(e.get("recurring", False)),
                notes=e.get("notes"),
                original_message=text,
            )
            # Confirmación con total del mes
            month_total, _ = await notion_client.get_month_total()
            confirm = (
                f"✅ Registrado:\n"
                f"*{e['description']}* — ${float(e['amount']):,.2f}\n"
                f"_{e['category']} / {e['subcategory']}_"
            )
            if e.get("payment_method"):
                confirm += f" · {e['payment_method']}"
            if e.get("recurring"):
                confirm += " · 🔁 Recurrente"
            confirm += f"\n\n📊 Total del mes: *${month_total:,.2f}*"
            await telegram_client.send_message(chat_id, confirm)
        except Exception as ex:
            logger.exception(f"Error guardando en Notion: {ex}")
            await telegram_client.send_message(
                chat_id, "⚠️ No pude guardar en Notion. Revisa los logs."
            )

    elif ptype == "query_total_month":
        total, count = await notion_client.get_month_total()
        await telegram_client.send_message(
            chat_id,
            f"📊 Este mes llevas *{count}* gasto{'s' if count != 1 else ''} "
            f"por un total de *${total:,.2f}*.",
        )

    elif ptype == "query_total_today":
        total, count = await notion_client.get_today_total()
        await telegram_client.send_message(
            chat_id,
            f"📅 Hoy llevas *{count}* gasto{'s' if count != 1 else ''} "
            f"por un total de *${total:,.2f}*.",
        )

    else:
        msg = parsed.get("response_for_other") or (
            "No entendí. Intenta `café 50` o `uber 87 débito`."
        )
        await telegram_client.send_message(chat_id, msg)

    return {"ok": True}
