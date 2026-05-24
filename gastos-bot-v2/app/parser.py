"""
Parser de mensajes en español usando Claude API.
Extrae estructura de un texto natural tipo "café 50" o "uber 87.50 débito".

V2: agrega soporte para ingresos ("hoy me pagaron X") y consultas por
periodo financiero (25→24).
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from anthropic import AsyncAnthropic
import pytz
from app.config import settings

logger = logging.getLogger(__name__)

client = AsyncAnthropic(api_key=settings.anthropic_api_key)

CATEGORIAS = [
    "Comida", "Transporte", "Vivienda", "Salud", "Educación",
    "Entretenimiento", "Compras", "Suscripciones", "Personal", "Otros",
]

SUBCATEGORIAS = [
    "Restaurantes", "Súper", "Café/Bebidas", "Delivery",
    "Uber/Didi", "Gasolina", "Transporte público", "Mantenimiento auto",
    "Renta", "Servicios", "Internet",
    "Médico", "Medicamentos", "Gym", "Seguros",
    "UANL", "UVEG", "Libros", "Cursos",
    "Cine", "Salidas", "Streaming", "Hobbies",
    "Ropa", "Tecnología", "Hogar",
    "Software", "Apps",
    "Regalos", "Cuidado personal",
    "Otros",
]

METODOS_PAGO = ["Efectivo", "Tarjeta débito", "Tarjeta crédito", "SPEI", "Clip"]
TIPOS = ["Necesidad", "Deseo", "Inversión"]

TIPOS_INGRESO = ["Sueldo", "Vales", "Bono", "Freelance", "Reembolso", "Otro"]
QUINCENAS = ["Q1", "Q2", "Mensual", "N/A"]


SYSTEM_PROMPT = f"""Eres un parser de mensajes financieros personales en español mexicano. Tu trabajo es leer lo que el usuario escribe y devolver SIEMPRE un JSON válido con la estructura indicada.

El usuario te puede mandar:

**A) GASTOS** (type "expense"):
- "café 50" → es un gasto
- "Uber 87.50 débito" → es un gasto
- "Pagué 1,200 de gasolina con crédito en Pemex" → es un gasto
- "350 cena con Ana" → es un gasto
- "Recurrente Netflix 219" → gasto recurrente

**B) INGRESOS** (type "income"):
- "hoy me pagaron 14077" → ingreso de sueldo (Q1 si día <=15, Q2 si >15)
- "ingreso 5000 freelance" → ingreso freelance
- "vales 3566" → ingreso de vales
- "bono trimestral 8000" → ingreso de bono
- "me reembolsaron 500" → ingreso tipo reembolso

**C) CONSULTAS** (sin acción de registro):
- "¿cuánto llevo este mes?" → "query_total_month" (mes = periodo financiero 25→24)
- "qué he gastado hoy" / "cuánto llevo hoy" → "query_total_today"
- "cuánto he ingresado este mes" → "query_income_month"
- "resumen del mes" / "cómo voy este mes" → "query_period_summary"

**D) OTROS** (type "other"): saludos, preguntas no relacionadas, mensajes confusos.

---

CLASIFICACIÓN DE GASTOS:

**Categorías válidas (EXACTO):** {', '.join(CATEGORIAS)}

**Subcategorías válidas (EXACTO):** {', '.join(SUBCATEGORIAS)}

**Métodos de pago válidos:** {', '.join(METODOS_PAGO)}. Si no se menciona, usa null.

**Tipo de gasto** (Necesidad / Deseo / Inversión):
- Necesidad: súper básico, transporte para trabajar, vivienda, medicamentos, servicios.
- Deseo: restaurantes, café, entretenimiento, ropa no esencial, salidas, delivery.
- Inversión: gym, cursos, libros que aumentan habilidades, tecnología productiva, seguros.

**Recurrente**: true si incluye "recurrente", "mensual", "suscripción", o es servicio mensual conocido (Netflix, Spotify, gym, renta, internet).

**Descripción**: máximo 4 palabras.
**Comercio**: nombre del negocio si se menciona, si no null.
**Notas**: contexto extra ("con Ana", "junta de trabajo"), o null.
**fecha_relativa**: "hoy" (default), "ayer", o "anteayer".

---

CLASIFICACIÓN DE INGRESOS:

**Tipos válidos (EXACTO):** {', '.join(TIPOS_INGRESO)}

**Quincena**:
- "Q1" si fecha es del 1 al 15
- "Q2" si fecha es del 16 al fin de mes
- "Mensual" si no es quincenal (bonos, freelance)
- "N/A" si no aplica

**Origen**: pagador/origen si se menciona ("Clip", "cliente XYZ"), o null.
**Descripción**: corto. Ej: "Sueldo Q1 marzo", "Vales despensa", "Bono trimestral".

---

ESTRUCTURA EXACTA DE OUTPUT (responde SOLO el JSON, sin texto adicional, sin bloques de código):

{{
  "type": "expense" | "income" | "query_total_month" | "query_total_today" | "query_income_month" | "query_period_summary" | "other",
  "expense": {{
    "amount": <número>,
    "description": "<string>",
    "category": "<una de las válidas>",
    "subcategory": "<una de las válidas>",
    "payment_method": "<una de las válidas>" | null,
    "merchant": "<string>" | null,
    "type": "Necesidad" | "Deseo" | "Inversión",
    "recurring": <boolean>,
    "notes": "<string>" | null,
    "fecha_relativa": "hoy" | "ayer" | "anteayer"
  }} | null,
  "income": {{
    "amount": <número>,
    "description": "<string>",
    "income_type": "<uno de los válidos>",
    "quincena": "Q1" | "Q2" | "Mensual" | "N/A",
    "source": "<string>" | null,
    "notes": "<string>" | null,
    "fecha_relativa": "hoy" | "ayer" | "anteayer"
  }} | null,
  "response_for_other": "<string corto en español>" | null
}}

Reglas estrictas:
- Si type == "expense", income debe ser null.
- Si type == "income", expense debe ser null.
- Si type es una consulta o "other", ambos deben ser null.
- Si type == "other", incluye en "response_for_other" un mensaje breve.
"""


async def parse_message(text: str) -> dict:
    """
    Parsea el texto del usuario y devuelve dict estructurado.
    Si Claude falla o el JSON no es válido, devuelve un 'other' por seguridad.
    """
    raw = ""
    try:
        message = await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=800,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": text},
                {"role": "assistant", "content": "{"},
            ],
        )
        raw = "{" + message.content[0].text
        raw = raw.strip()
        parsed = json.loads(raw)
        return parsed
    except json.JSONDecodeError as e:
        logger.error(f"Parser JSON inválido: {e}. Raw: {raw[:300]}")
        return {
            "type": "other",
            "expense": None,
            "income": None,
            "response_for_other": "No entendí bien tu mensaje. Intenta `café 50`, `uber 87 débito`, o `hoy me pagaron 14000`.",
        }
    except Exception as e:
        logger.exception(f"Error en parser: {e}")
        return {
            "type": "other",
            "expense": None,
            "income": None,
            "response_for_other": "Hubo un error procesando tu mensaje. Inténtalo de nuevo.",
        }


def resolve_date(fecha_relativa: str) -> str:
    """Convierte 'hoy'/'ayer'/'anteayer' a fecha ISO YYYY-MM-DD en zona MX."""
    tz = pytz.timezone(settings.timezone)
    now = datetime.now(tz)
    offset_days = {"hoy": 0, "ayer": 1, "anteayer": 2}.get(fecha_relativa, 0)
    target = now - timedelta(days=offset_days)
    return target.strftime("%Y-%m-%d")
