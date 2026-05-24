# 💸 Gastos Bot

Bot de Telegram que registra tus gastos en Notion usando lenguaje natural.
Tú escribes `café 50` y Claude lo parsea a `{Comida / Café/Bebidas / $50 / Necesidad}` y lo guarda en tu base de datos de Notion. Te recuerda cada noche entre 9 y 10 pm si te falta registrar algo.

```
[Telegram] → [FastAPI webhook] → [Claude API: parsea texto] → [Notion API]
                                          ↓
                              [Scheduler: recordatorio nocturno]
```

---

## 📋 Prerrequisitos

Necesitas crear cuentas / credenciales en 4 servicios. Toma como 30 min en total.

### 1. Bot de Telegram

1. Abre Telegram, busca **@BotFather**, escribe `/newbot`.
2. Sigue las instrucciones (nombre y username del bot).
3. Guarda el **token** que te da. Se ve así: `7812345678:AAH...`
4. En Telegram, busca **@userinfobot** y escríbele algo. Te devuelve tu **user_id** (entero, ej. `123456789`). Guárdalo.

### 2. API Key de Anthropic

1. Entra a [console.anthropic.com](https://console.anthropic.com/), crea cuenta.
2. Settings → API Keys → Create Key.
3. Guarda la key (empieza con `sk-ant-...`).

> El parser usa Claude Haiku 4.5, costo ~$0.001 por mensaje. Con 100 gastos/mes son ~$0.10 USD. Negligible.

### 3. Integración de Notion

1. Ve a [notion.so/profile/integrations](https://www.notion.so/profile/integrations).
2. **+ New integration** → Internal integration → ponle un nombre como "Gastos Bot".
3. Asocia con tu workspace y guarda. Copia el **Internal Integration Secret** (empieza con `secret_` o `ntn_`).
4. **IMPORTANTE**: Comparte la base de datos `💸 Gastos Personales` con tu integración:
   - Abre la base en Notion.
   - Click en los `···` arriba a la derecha → "Connections" → busca tu integración y agrégala.

El **ID de la base** ya está en el `.env.example`: `62f666f3858347739f7e48964466a2e1`. Es la que ya te creé.

### 4. Cuenta en Railway

1. Entra a [railway.app](https://railway.app/), regístrate con GitHub.
2. Te dan $5 USD/mes de crédito gratis (sobra para esto).

---

## 🚀 Deploy en Railway

### Paso 1: Subir el código a GitHub

```bash
cd gastos-bot
git init
git add .
git commit -m "Initial commit"
gh repo create gastos-bot --private --source=. --push
# O manual: crea repo en github.com y haz push
```

### Paso 2: Conectar Railway al repo

1. En Railway → **New Project** → **Deploy from GitHub repo** → selecciona `gastos-bot`.
2. Railway detecta Python y empieza a buildear.

### Paso 3: Variables de entorno

En Railway → tu servicio → **Variables**, agrega todo lo del `.env.example`:

```
TELEGRAM_BOT_TOKEN=7812345678:AAH...
TELEGRAM_ALLOWED_USER_ID=123456789
TELEGRAM_WEBHOOK_SECRET=<corre `openssl rand -hex 32` y pega aquí>
ANTHROPIC_API_KEY=sk-ant-...
NOTION_API_KEY=secret_...
NOTION_DATABASE_ID=62f666f3858347739f7e48964466a2e1
TIMEZONE=America/Mexico_City
REMINDER_HOUR_START=21
REMINDER_HOUR_END=22
```

### Paso 4: Generar el dominio público

1. Railway → tu servicio → **Settings** → **Networking** → **Generate Domain**.
2. Te da algo tipo `https://gastos-bot-production.up.railway.app`.
3. Agrega esa URL como variable `PUBLIC_URL` en Railway.
4. Railway re-deployea automáticamente.

### Paso 5: Registrar el webhook con Telegram

Una vez la app esté corriendo (revisa logs hasta ver "App arrancada ✓"):

```bash
curl -X POST "https://TU-URL.up.railway.app/admin/set-webhook" \
  -H "Authorization: Bearer <TELEGRAM_WEBHOOK_SECRET>"
```

Deberías ver `{"ok": true}`.

### Paso 6: Probar

En Telegram, busca tu bot por su username, mándale `/start`. Debería responderte el mensaje de bienvenida. Luego prueba con `café 50`.

---

## 🧪 Probar localmente (opcional, para desarrollo)

```bash
cd gastos-bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edita .env con tus credenciales
uvicorn app.main:app --reload
```

Para que Telegram pueda llegar a tu localhost, usa **ngrok** o **cloudflared**:

```bash
ngrok http 8000
# Toma la URL HTTPS que te da y úsala como PUBLIC_URL
```

---

## 📁 Estructura del proyecto

```
gastos-bot/
├── README.md              # Esta guía
├── requirements.txt       # Dependencias Python
├── .env.example           # Plantilla de variables
├── .gitignore
├── Procfile               # Comando de start para Railway
├── runtime.txt            # Versión Python
└── app/
    ├── __init__.py
    ├── main.py            # FastAPI app + endpoints
    ├── config.py          # Carga env vars
    ├── parser.py          # Parser con Claude API
    ├── notion_client.py   # Wrapper de Notion
    ├── telegram_client.py # Wrapper de Telegram
    └── scheduler.py       # Recordatorio nocturno
```

---

## 🐛 Troubleshooting

**El bot no responde**
- Revisa logs en Railway → tu servicio → Deployments → View Logs.
- Verifica que el webhook esté registrado: `curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo`

**Notion devuelve 404**
- ¿Le diste acceso a la integración a la base? (paso 4 de prerrequisitos).
- Verifica que `NOTION_DATABASE_ID` esté correcto.

**El parser equivoca categorías**
- Edita `app/parser.py` y mejora el SYSTEM_PROMPT con más ejemplos de tu vocabulario.

**No me llega el recordatorio nocturno**
- Verifica que la variable `TIMEZONE=America/Mexico_City` esté bien.
- En los logs busca "Scheduler iniciado". Debe aparecer al arrancar.

---

## 🔧 Ideas para extender después

- **Presupuesto por categoría**: agregar segunda DB en Notion (`Presupuestos`) y alertar al 80% consumido.
- **Reportes semanales** automáticos los domingos por la noche con tendencia vs semana pasada.
- **Reconocimiento de tickets** mandando foto: usa la vista vision de Claude para extraer datos del ticket.
- **Categorización aprendida**: si corriges una categoría ("no era Comida, era Personal"), el bot lo aprende vía un fine-tune-prompt con historial.
- **Dashboard ejecutivo** en Notion con métricas tipo Looker (gasto promedio diario, % deseo vs necesidad por mes, top 5 comercios).
