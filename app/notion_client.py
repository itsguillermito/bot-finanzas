"""
Wrapper de Notion API para nuestra DB de gastos.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from notion_client import AsyncClient
import pytz
from app.config import settings

logger = logging.getLogger(__name__)

notion = AsyncClient(auth=settings.notion_api_key)


def _today_mx() -> datetime:
    return datetime.now(pytz.timezone(settings.timezone))


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
    """Crea una página (= un gasto) en la base de datos de Notion."""
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


async def get_total(start_date_iso: str, end_date_iso: Optional[str] = None) -> tuple[float, int]:
    """
    Devuelve (suma_montos, cantidad_gastos) en el rango de fechas (inclusivos).
    Si end_date es None, sólo busca para start_date.
    """
    filter_obj = {
        "and": [
            {"property": "Fecha", "date": {"on_or_after": start_date_iso}},
        ]
    }
    if end_date_iso:
        filter_obj["and"].append(
            {"property": "Fecha", "date": {"on_or_before": end_date_iso}}
        )
    else:
        filter_obj["and"].append(
            {"property": "Fecha", "date": {"on_or_before": start_date_iso}}
        )

    total = 0.0
    count = 0
    cursor = None
    while True:
        kwargs = {
            "database_id": settings.notion_database_id,
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


async def get_month_total() -> tuple[float, int]:
    """Total y cantidad de gastos del mes actual (zona MX)."""
    now = _today_mx()
    start = now.replace(day=1).strftime("%Y-%m-%d")
    # último día del mes
    next_month = (now.replace(day=28) + timedelta(days=4)).replace(day=1)
    last_day = (next_month - timedelta(days=1)).strftime("%Y-%m-%d")
    return await get_total(start, last_day)


async def get_today_total() -> tuple[float, int]:
    """Total y cantidad de gastos de hoy."""
    today = _today_mx().strftime("%Y-%m-%d")
    return await get_total(today)
