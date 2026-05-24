"""
Parser de mensajes en español usando Claude API.
Extrae estructura de un texto natural tipo "café 50" o "uber 87.50 débito".
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

# Categorías y opciones válidas (deben coincidir EXACTO con Notion)
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


SYSTEM_PROMPT = f"""Eres un parser de mensajes de gastos personales en español mexicano. Tu trabajo es leer lo que el usuario escribe y devolver SIEMPRE un JSON válido con la estructura indicada.

El usuario te va a mandar cosas como:
- "café 50" → es un gasto
- "Uber 87.50 débito" → es un gasto
- "Pagué 1,200 de gasolina con crédito en Pemex" → es un gasto
- "350 cena con Ana" → es un gasto
- "Recurrente Netflix 219" → es un gasto recurrente
- "¿cuánto llevo este mes?" → es una consulta de total
- "qué he gastado hoy" → es una consulta de total del día
- "hola" o cualquier cosa no relacionada → es "other"

REGLAS DE CLASIFICACIÓN:

**type** debe ser uno de: "expense", "query_total_month", "query_total_today", "other".

**Categorías válidas (usa EXACTO uno de estos):**
{', '.join(CATEGORIAS)}

**Subcategorías válidas (usa EXACTO uno de estos):**
{', '.join(SUBCATEGORIAS)}

**Métodos de pago válidos:**
{', '.join(METODOS_PAGO)}. Si no se menciona, usa null.

**Tipo de gasto** (Necesidad / Deseo / Inversión):
- Necesidad: comida básica (súper), transporte para trabajar, vivienda, medicamentos, servicios básicos.
- Deseo: restaurantes, café, entretenimiento, ropa no esencial, salidas, delivery.
- Inversión: gym, cursos, libros que aumentan habilidades, tecnología productiva, seguros.

**Recurrente**: true si el mensaje incluye palabras como "recurrente", "mensual", "suscripción", o si es claramente un servicio mensual conocido (Netflix, Spotify, gym mensual, renta, internet).

**Descripción**: corto, máximo 4 palabras. Ej: "Café Starbucks", "Uber al trabajo", "Súper Walmart".

**Comercio**: nombre del negocio si se menciona, si no null. Ej: "Oxxo", "Pemex", "Starbucks", "Walmart".

**Notas**: cualquier contexto extra ("con Ana", "junta de trabajo", etc), o null.

**fecha_relativa**: "hoy" (default), "ayer", o "anteayer" si se menciona explícitamente. Si no, "hoy".

ESTRUCTURA EXACTA DE OUTPUT (no agregues nada más):

{{
  "type": "expense" | "query_total_month" | "query_total_today" | "other",
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
  "response_for_other": "<string corto en español>" | null
}}

Si type != "expense", expense debe ser null.
Si type == "other", incluye en "response_for_other" un mensaje breve y amistoso explicando qué puedes hacer.

Responde SOLO el JSON, sin explicaciones, sin bloques de código, sin nada más.
"""


async def parse_message(text: str) -> dict:
    """
    Parsea el texto del usuario y devuelve dict estructurado.
    Si Claude falla o el JSON no es válido, devuelve un 'other' por seguridad.
    """
    try:
        message = await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": text},
                {"role": "assistant", "content": "{"},  # Prefill JSON
            ],
        )
        raw = "{" + message.content[0].text
        # En caso de que Claude haya cerrado con texto extra después del JSON
        raw = raw.strip()
        parsed = json.loads(raw)
        return parsed
    except json.JSONDecodeError as e:
        logger.error(f"Parser JSON inválido: {e}. Raw: {raw[:300]}")
        return {
            "type": "other",
            "expense": None,
            "response_for_other": "No entendí bien tu mensaje. Intenta algo como `café 50` o `uber 87 débito`.",
        }
    except Exception as e:
        logger.exception(f"Error en parser: {e}")
        return {
            "type": "other",
            "expense": None,
            "response_for_other": "Hubo un error procesando tu mensaje. Inténtalo de nuevo.",
        }


def resolve_date(fecha_relativa: str) -> str:
    """Convierte 'hoy'/'ayer'/'anteayer' a fecha ISO YYYY-MM-DD en zona MX."""
    tz = pytz.timezone(settings.timezone)
    now = datetime.now(tz)
    offset_days = {"hoy": 0, "ayer": 1, "anteayer": 2}.get(fecha_relativa, 0)
    target = now - timedelta(days=offset_days)
    return target.strftime("%Y-%m-%d")
