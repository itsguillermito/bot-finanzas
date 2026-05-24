"""
Wrapper de Notion API para la DB de gastos e ingresos.

V2: agrega soporte para periodo financiero (25→24), DB de ingresos,
y consultas combinadas (gastos vs ingresos del periodo).
"""
import logging
from datetime import datetime, timedelta, date
from typing import Optional
from notion_client import AsyncClient
import pytz
from app.config import settings

logger = logging.getLogger(__name__)

notion = AsyncClient(auth=settings.notion_api_key)

# Día de corte del periodo financiero: 25 (le pagan a Guille el 25)
PERIOD_CUTOFF_DAY = 25


def _today_mx() -> datetime:
    return datetime.now(pytz.timezone(settings.timezone))


def get_financial_period(reference: Optional[date] = None) -> tuple[date, date, str]:
    """
    Devuelve (inicio, fin, label) del periodo financiero al que pertenece la fecha.

    El periodo va del día 25 de un mes al día 24 del mes siguiente.
    Ej: 25/mar → 24/abr es el periodo "2026-03".

    Si reference es None, usa hoy en zona MX.
    """
    if reference is None:
        reference = _today_mx().date()

    if reference.day >= PERIOD_CUTOFF_DAY:
        # Estamos en la primera mitad del periodo (después del corte)
        start = reference.replace(day=PERIOD_CUTOFF_DAY)
        # Fin: día 24 del mes siguiente
        if reference.month == 12:
            end = date(reference.year + 1, 1, 24)
        else:
            end = date(reference.year, reference.month + 1, 24)
    else:
        # Estamos en la segunda mitad del periodo (antes del próximo corte)
        if reference.month == 1:
            start = date(reference.year - 1, 12, PERIOD_CUTOFF_DAY)
        else:
            start = date(reference.year, reference.month - 1, PERIOD_CUTOFF_DAY)
        end = reference.replace(day=24)

    label = start.strftime("%Y-%m")
    return start, end, label


def format_period_human(start: date, end: date) -> str:
    """Formato humano del periodo: '25 mar - 24 abr'."""
    meses = [
        "ene", "feb", "mar", "abr", "may", "jun",
        "jul", "ago", "sep", "oct", "nov", "dic",
    ]
    s = f"{start.day} {meses[start.month - 1]}"
    e = f"{end.day} {meses[end.month - 1]}"
    return f"{s} – {e}"


# ============================================================
# GASTOS
# ============================================================

async def create_expense(
    *,
    amount: float,
    description: str,
    category: str,
    subcategory: str,
    fecha_iso: str,
    payment_method: Optional[str] = None,
    merchant: Optional[str] = None,
    tipo: str = "Necesidad",
    recurring: bool = False,
    notes: Optional[str] = None,
    original_message: str = "",
) -> dict:
    """Crea un gasto en la DB de Gastos."""
    properties = {
        "Descripción": {"title": [{"text": {"content": description[:200]}}]},
        "Monto": {"number": amount},
        "Fecha": {"date": {"start": fecha_iso}},
        "Categoría": {"select": {"name": category}},
        "Subcategoría": {"select": {"name": subcategory}},
        "Tipo": {"select": {"name": tipo}},
        "Recurrente": {"checkbox": recurring},
        "Mensaje original": {
            "rich_text": [{"text": {"content": original_message[:2000]}}]
        },
    }
    if payment_method:
        properties["Método de pago"] = {"select": {"name": payment_method}}
    if merchant:
        properties["Comercio"] = {"rich_text": [{"text": {"content": merchant[:200]}}]}
    if notes:
        properties["Notas"] = {"rich_text": [{"text": {"content": notes[:500]}}]}

    page = await notion.pages.create(
        parent={"database_id": settings.notion_database_id},
        properties=properties,
    )
    logger.info(f"Notion: gasto creado id={page['id']} monto={amount} desc={description}")
    return page


async def _sum_db_in_range(
    database_id: str,
    start_date_iso: str,
    end_date_iso: str,
) -> tuple[float, int]:
    """Suma montos de una DB filtrando por rango de fechas (inclusivos)."""
    filter_obj = {
        "and": [
            {"property": "Fecha", "date": {"on_or_after": start_date_iso}},
            {"property": "Fecha", "date": {"on_or_before": end_date_iso}},
        ]
    }
    total = 0.0
    count = 0
    cursor = None
    while True:
        kwargs = {
            "database_id": database_id,
            "filter": filter_obj,
            "page_size": 100,
        }
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = await notion.databases.query(**kwargs)
        for page in resp["results"]:
            monto = page["properties"]["Monto"]["number"]
            if monto is not None:
                total += monto
                count += 1
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return total, count


async def get_expense_total_period() -> tuple[float, int, date, date]:
    """Suma de gastos del periodo financiero actual. Devuelve (total, count, start, end)."""
    start, end, _ = get_financial_period()
    total, count = await _sum_db_in_range(
        settings.notion_database_id,
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
    )
    return total, count, start, end


async def get_today_total() -> tuple[float, int]:
    """Suma de gastos de hoy."""
    today = _today_mx().strftime("%Y-%m-%d")
    return await _sum_db_in_range(settings.notion_database_id, today, today)


# ============================================================
# INGRESOS
# ============================================================

async def create_income(
    *,
    amount: float,
    description: str,
    income_type: str,
    quincena: str = "N/A",
    fecha_iso: str,
    source: Optional[str] = None,
    notes: Optional[str] = None,
    original_message: str = "",
) -> dict:
    """Crea un ingreso en la DB de Ingresos."""
    if not settings.notion_income_database_id:
        raise RuntimeError("NOTION_INCOME_DATABASE_ID no configurado")

    properties = {
        "Descripción": {"title": [{"text": {"content": description[:200]}}]},
        "Monto": {"number": amount},
        "Fecha": {"date": {"start": fecha_iso}},
        "Tipo": {"select": {"name": income_type}},
        "Quincena": {"select": {"name": quincena}},
        "Mensaje original": {
            "rich_text": [{"text": {"content": original_message[:2000]}}]
        },
    }
    if source:
        properties["Origen"] = {"rich_text": [{"text": {"content": source[:200]}}]}
    if notes:
        properties["Notas"] = {"rich_text": [{"text": {"content": notes[:500]}}]}

    page = await notion.pages.create(
        parent={"database_id": settings.notion_income_database_id},
        properties=properties,
    )
    logger.info(f"Notion: ingreso creado id={page['id']} monto={amount} desc={description}")
    return page


async def get_income_total_period() -> tuple[float, int, date, date]:
    """Suma de ingresos del periodo financiero actual."""
    if not settings.notion_income_database_id:
        return 0.0, 0, *get_financial_period()[:2]
    start, end, _ = get_financial_period()
    total, count = await _sum_db_in_range(
        settings.notion_income_database_id,
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
    )
    return total, count, start, end


# ============================================================
# RESUMEN COMBINADO
# ============================================================

async def get_period_summary() -> dict:
    """
    Devuelve resumen del periodo financiero actual:
    {
        "period_label": "25 mar – 24 abr",
        "expense_total": float,
        "expense_count": int,
        "income_total": float,
        "income_count": int,
        "balance": float (income - expense),
        "pct_used": float (expense / income * 100, o None si no hay ingreso),
        "start": date,
        "end": date
    }
    """
    expense_total, expense_count, start, end = await get_expense_total_period()
    income_total, income_count, _, _ = await get_income_total_period()
    balance = income_total - expense_total
    pct_used = (expense_total / income_total * 100) if income_total > 0 else None
    return {
        "period_label": format_period_human(start, end),
        "expense_total": expense_total,
        "expense_count": expense_count,
        "income_total": income_total,
        "income_count": income_count,
        "balance": balance,
        "pct_used": pct_used,
        "start": start,
        "end": end,
    }
