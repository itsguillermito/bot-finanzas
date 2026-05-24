"""
Scheduler con APScheduler para recordatorio nocturno entre 21:00 y 22:00 hora MX.

Estrategia: corremos un cron diario a 21:00 que calcula un delay aleatorio
entre 0 y 60 minutos antes de mandar el recordatorio. Así el horario varía
día a día y se siente menos robótico.
"""
import asyncio
import logging
import random
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from app.config import settings
from app.telegram_client import send_message
from app.notion_client import get_today_total

logger = logging.getLogger(__name__)

scheduler: AsyncIOScheduler | None = None


async def nightly_reminder_job():
    """
    Se dispara a la hora de inicio configurada (default 21:00).
    Espera un tiempo aleatorio hasta el END (default 22:00) y manda el recordatorio.
    """
    window_seconds = (settings.reminder_hour_end - settings.reminder_hour_start) * 3600
    delay = random.randint(0, max(1, window_seconds - 60))  # 1 min buffer
    minutes = delay // 60
    logger.info(f"Recordatorio nocturno: esperando {minutes} min antes de mandar")
    await asyncio.sleep(delay)

    try:
        total, count = await get_today_total()
        if count == 0:
            text = (
                "🌙 *Recordatorio nocturno*\n\n"
                "No he registrado ningún gasto tuyo hoy.\n"
                "¿Compraste algo que se te haya pasado anotar? "
                "Si no, ¡buen trabajo controlando! 💪"
            )
        else:
            text = (
                f"🌙 *Recordatorio nocturno*\n\n"
                f"Hoy llevas *{count}* gasto{'s' if count != 1 else ''} "
                f"por un total de *${total:,.2f}*.\n"
                f"¿Te falta algo por registrar antes de cerrar el día?"
            )
        await send_message(settings.telegram_allowed_user_id, text)
        logger.info(f"Recordatorio enviado | hoy: {count} gastos, ${total:.2f}")
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
