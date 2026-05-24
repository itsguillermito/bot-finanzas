"""
Scheduler con APScheduler para recordatorio nocturno entre 21:00 y 22:00 hora MX.

V2: el mensaje del recordatorio ahora incluye contexto del periodo financiero
(25→24) en lugar del mes calendario.
"""
import asyncio
import logging
import random
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from app.config import settings
from app.telegram_client import send_message
from app.notion_client import get_today_total, get_period_summary

logger = logging.getLogger(__name__)

scheduler: AsyncIOScheduler | None = None


async def nightly_reminder_job():
    """
    Se dispara a la hora de inicio configurada (default 21:00).
    Espera un tiempo aleatorio hasta el END (default 22:00) y manda el recordatorio.
    """
    window_seconds = (settings.reminder_hour_end - settings.reminder_hour_start) * 3600
    delay = random.randint(0, max(1, window_seconds - 60))
    minutes = delay // 60
    logger.info(f"Recordatorio nocturno: esperando {minutes} min antes de mandar")
    await asyncio.sleep(delay)

    try:
        today_total, today_count = await get_today_total()
        summary = await get_period_summary()

        if today_count == 0:
            text = (
                "🌙 *Recordatorio nocturno*\n\n"
                "Hoy no registré ningún gasto tuyo.\n"
                "¿Compraste algo que se te haya pasado anotar? "
                "Si no, ¡buen trabajo controlando! 💪\n\n"
                f"📊 _Periodo {summary['period_label']}: "
                f"${summary['expense_total']:,.2f} gastado_"
            )
        else:
            text = (
                f"🌙 *Recordatorio nocturno*\n\n"
                f"Hoy llevas *{today_count}* gasto"
                f"{'s' if today_count != 1 else ''} "
                f"por *${today_total:,.2f}*.\n"
                f"¿Te falta algo por registrar antes de cerrar el día?\n\n"
                f"📊 _Periodo {summary['period_label']}: "
                f"${summary['expense_total']:,.2f} gastado"
            )
            if summary["pct_used"] is not None:
                text += f" ({summary['pct_used']:.1f}% del ingreso)"
            text += "_"
        await send_message(settings.telegram_allowed_user_id, text)
        logger.info(f"Recordatorio enviado | hoy: {today_count} gastos, ${today_total:.2f}")
    except Exception as e:
        logger.exception(f"Error en recordatorio nocturno: {e}")


def start_scheduler():
    """Arranca el scheduler. Idempotente."""
    global scheduler
    if scheduler is not None:
        return
    tz = pytz.timezone(settings.timezone)
    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(
        nightly_reminder_job,
        trigger=CronTrigger(
            hour=settings.reminder_hour_start,
            minute=0,
            timezone=tz,
        ),
        id="nightly_reminder",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        f"Scheduler iniciado. Recordatorio: entre {settings.reminder_hour_start}:00 "
        f"y {settings.reminder_hour_end}:00 ({settings.timezone})"
    )


def stop_scheduler():
    global scheduler
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        scheduler = None
