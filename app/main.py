"""
FastAPI app principal.

V2: agrega soporte para ingresos, consultas por periodo financiero (25→24),
y resumen combinado (gastos vs ingresos).
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Header
from typing import Optional

from app.config import settings
from app import telegram_client, parser, notion_client
from app.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    logger.info("App arrancada ✓")
    yield
    stop_scheduler()
    logger.info("App apagada")


app = FastAPI(lifespan=lifespan, title="Gastos Bot")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/admin/set-webhook")
async def admin_set_webhook(authorization: Optional[str] = Header(None)):
    if authorization != f"Bearer {settings.telegram_webhook_secret}":
        raise HTTPException(401, "Unauthorized")
    if not settings.public_url:
        raise HTTPException(400, "PUBLIC_URL no configurada")
    ok = await telegram_client.set_webhook(settings.public_url)
    return {"ok": ok}


async def _handle_expense(chat_id: int, expense: dict, text: str):
    fecha_iso = parser.resolve_date(expense.get("fecha_relativa", "hoy"))
    await notion_client.create_expense(
        amount=float(expense["amount"]),
        description=expense["description"],
        category=expense["category"],
        subcategory=expense["subcategory"],
        fecha_iso=fecha_iso,
        payment_method=expense.get("payment_method"),
        merchant=expense.get("merchant"),
        tipo=expense.get("type", "Necesidad"),
        recurring=bool(expense.get("recurring", False)),
        notes=expense.get("notes"),
        original_message=text,
    )
    # Confirmación con info del periodo
    summary = await notion_client.get_period_summary()
    confirm = (
        f"✅ Gasto registrado:\n"
        f"*{expense['description']}* — ${float(expense['amount']):,.2f}\n"
        f"_{expense['category']} / {expense['subcategory']}_"
    )
    if expense.get("payment_method"):
        confirm += f" · {expense['payment_method']}"
    if expense.get("recurring"):
        confirm += " · 🔁 Recurrente"
    confirm += f"\n\n📊 *Periodo {summary['period_label']}*"
    confirm += f"\nGastado: *${summary['expense_total']:,.2f}*"
    if summary["pct_used"] is not None:
        confirm += f" ({summary['pct_used']:.1f}% del ingreso)"
    await telegram_client.send_message(chat_id, confirm)


async def _handle_income(chat_id: int, income: dict, text: str):
    fecha_iso = parser.resolve_date(income.get("fecha_relativa", "hoy"))
    await notion_client.create_income(
        amount=float(income["amount"]),
        description=income["description"],
        income_type=income.get("income_type", "Otro"),
        quincena=income.get("quincena", "N/A"),
        fecha_iso=fecha_iso,
        source=income.get("source"),
        notes=income.get("notes"),
        original_message=text,
    )
    summary = await notion_client.get_period_summary()
    confirm = (
        f"💰 Ingreso registrado:\n"
        f"*{income['description']}* — ${float(income['amount']):,.2f}\n"
        f"_{income.get('income_type', 'Otro')}_"
    )
    if income.get("quincena") and income["quincena"] != "N/A":
        confirm += f" · {income['quincena']}"
    if income.get("source"):
        confirm += f" · {income['source']}"
    confirm += f"\n\n📊 *Periodo {summary['period_label']}*"
    confirm += f"\nIngresado: *${summary['income_total']:,.2f}*"
    confirm += f"\nGastado: *${summary['expense_total']:,.2f}*"
    if summary["pct_used"] is not None:
        confirm += f" ({summary['pct_used']:.1f}%)"
    confirm += f"\nBalance: *${summary['balance']:,.2f}*"
    await telegram_client.send_message(chat_id, confirm)


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
):
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        logger.warning("Webhook con secret inválido")
        raise HTTPException(403, "Forbidden")

    update = await request.json()
    message = update.get("message")
    if not message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")

    if user_id != settings.telegram_allowed_user_id:
        logger.warning(f"Usuario no autorizado: {user_id}")
        await telegram_client.send_message(chat_id, "🔒 Lo siento, este bot es privado.")
        return {"ok": True}

    # Comando /start
    if text.startswith("/start"):
        await telegram_client.send_message(
            chat_id,
            "👋 ¡Listo, Guille! Tu bot personal de finanzas.\n\n"
            "*Para registrar gastos:*\n"
            "• `café 50`\n"
            "• `uber 87.50 débito`\n"
            "• `pagué 1,200 de gasolina en Pemex`\n"
            "• `recurrente Netflix 219`\n\n"
            "*Para registrar ingresos:*\n"
            "• `hoy me pagaron 14077`\n"
            "• `vales 3566`\n"
            "• `freelance 5000 cliente XYZ`\n\n"
            "*Consultas:*\n"
            "• `¿cuánto llevo este mes?` (periodo 25→24)\n"
            "• `¿qué he gastado hoy?`\n"
            "• `resumen del mes` (gastos vs ingresos)\n\n"
            "Tu mes financiero va del 25 al 24 del siguiente.\n"
            "Cada noche entre 9–10 pm te recuerdo registrar lo que falte. 🌙",
        )
        return {"ok": True}

    # Comando /resumen (atajo)
    if text.startswith("/resumen") or text.startswith("/mes"):
        await _send_period_summary(chat_id)
        return {"ok": True}

    # Parsear con Claude
    parsed = await parser.parse_message(text)
    ptype = parsed.get("type")

    try:
        if ptype == "expense" and parsed.get("expense"):
            await _handle_expense(chat_id, parsed["expense"], text)

        elif ptype == "income" and parsed.get("income"):
            await _handle_income(chat_id, parsed["income"], text)

        elif ptype == "query_total_month":
            summary = await notion_client.get_period_summary()
            msg = (
                f"📊 *Periodo {summary['period_label']}*\n"
                f"Llevas *{summary['expense_count']}* gasto"
                f"{'s' if summary['expense_count'] != 1 else ''} "
                f"por *${summary['expense_total']:,.2f}*."
            )
            if summary["pct_used"] is not None:
                msg += f"\n_{summary['pct_used']:.1f}% del ingreso del periodo._"
            await telegram_client.send_message(chat_id, msg)

        elif ptype == "query_total_today":
            total, count = await notion_client.get_today_total()
            await telegram_client.send_message(
                chat_id,
                f"📅 Hoy llevas *{count}* gasto"
                f"{'s' if count != 1 else ''} por *${total:,.2f}*.",
            )

        elif ptype == "query_income_month":
            total, count, _, _ = await notion_client.get_income_total_period()
            summary_period = notion_client.get_financial_period()
            label = notion_client.format_period_human(summary_period[0], summary_period[1])
            await telegram_client.send_message(
                chat_id,
                f"💰 *Periodo {label}*\n"
                f"Ingresos registrados: *{count}* por *${total:,.2f}*.",
            )

        elif ptype == "query_period_summary":
            await _send_period_summary(chat_id)

        else:
            msg = parsed.get("response_for_other") or (
                "No entendí. Intenta `café 50`, `hoy me pagaron 14000`, o `resumen del mes`."
            )
            await telegram_client.send_message(chat_id, msg)

    except Exception as ex:
        logger.exception(f"Error procesando mensaje: {ex}")
        await telegram_client.send_message(
            chat_id, "⚠️ Hubo un error procesando tu mensaje. Revisa los logs."
        )

    return {"ok": True}


async def _send_period_summary(chat_id: int):
    """Manda el resumen completo del periodo financiero actual."""
    summary = await notion_client.get_period_summary()
    msg = f"📊 *Resumen del periodo {summary['period_label']}*\n\n"
    msg += f"💰 *Ingresos*: ${summary['income_total']:,.2f} "
    msg += f"({summary['income_count']} registro"
    msg += "s" if summary["income_count"] != 1 else ""
    msg += ")\n"
    msg += f"💸 *Gastos*: ${summary['expense_total']:,.2f} "
    msg += f"({summary['expense_count']} gasto"
    msg += "s" if summary["expense_count"] != 1 else ""
    msg += ")\n"
    msg += f"📈 *Balance*: ${summary['balance']:,.2f}\n"
    if summary["pct_used"] is not None:
        emoji = "🟢" if summary["pct_used"] < 70 else ("🟡" if summary["pct_used"] < 90 else "🔴")
        msg += f"\n{emoji} Has usado *{summary['pct_used']:.1f}%* de tu ingreso."
    else:
        msg += "\n_Aún no registras ingresos en este periodo._"
    await telegram_client.send_message(chat_id, msg)
