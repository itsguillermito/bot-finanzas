#Gastos Bot

Bot de Telegram que registra gastos en Notion usando lenguaje natural.
Se escribe `café 50` y Claude lo parsea a `{Comida / Café/Bebidas / $50 / Necesidad}` y lo guarda en una base de datos de Notion. El bot recuerda cada noche entre 9 y 10 pm si hace falta registrar algo y envía un mensaje a modo de recordatorio.

```
[Telegram] → [FastAPI webhook] → [Claude API: parsea texto] → [Notion API]
                                          ↓
                              [Scheduler: recordatorio nocturno]
```

---

##Prerrequisitos

Se necesita crear cuentas / credenciales en 4 servicios. Toma como 30 min en total.

### 1. Bot de Telegram

1. Abrir Telegram, buscar **@BotFather**, escribir `/newbot`.
2. Seguir las instrucciones (nombre y username del bot).
3. Guardar el **token** que se da. Se ve así: `7812345678:AAH...`
4. En Telegram, buscar **@userinfobot** y escribirle algo. Devolverá el **user_id** (entero, ej. `123456789`). Hay que guardarlo.

### 2. API Key de Anthropic

1. Entrar a [console.anthropic.com](https://console.anthropic.com/), crear cuenta.
2. Settings → API Keys → Create Key.
3. Guardar la key (empieza con `sk-ant-...`).

> El parser usa Claude Haiku 4.5, costo Aprox de $0.001 por mensaje. Con 100 gastos/mes son ~$0.10 USD. No muy costoso, pero hay que medirlo.

### 3. Integración de Notion

1. Ir a [notion.so/profile/integrations](https://www.notion.so/profile/integrations).
2. **+ New integration** → Internal integration → ponerle un nombre como "Gastos Bot".
3. Asociar con nuestro workspace y guardar. Copiar el **Internal Integration Secret** (empieza con `secret_` o `ntn_`).
4. **IMPORTANTE**: Hay que compartit la base de datos `[Nombre de nuestra base de datos` con la integración:
   - Abrir la base en Notion.
   - Click en los `···` arriba a la derecha → "Connections" → buscar nuestra integración y agrégalar.

### 4. Cuenta en Railway

1. Entrar a [railway.app](https://railway.app/), y registrarse con GitHub.
2. Son como $5 USD/mes de crédito gratis.

## Deploy en Railway

### Paso 1: Subir el código a GitHub

```bash
cd gastos-bot
git init
git add .
git commit -m "Initial commit"
gh repo create gastos-bot --private --source=. --push
```

### Paso 2: Conectar Railway al repo

1. En Railway → **New Project** → **Deploy from GitHub repo** → seleccionar `[Nombre del repo]`.
2. Railway detecta Python y empieza a buildear.

### Paso 3: Variables de entorno

En Railway → nombre del servicio → **Variables**, agregar las variables:

```
Variables de ejemplo:
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

1. Railway → nombre del servicio → **Settings** → **Networking** → **Generate Domain**.
2. Da algo tipo `https://gastos-bot-production.up.railway.app`.
3. Agregar esa URL como variable en `PUBLIC_URL` en Railway.
4. Railway re-deployea automáticamente.

### Paso 5: Registrar el webhook con Telegram

Una vez la app esté corriendo (hay que revisar logs hasta ver "App arrancada"):

```bash
curl -X POST "https://NOMBRE_DE_LA_URLL.up.railway.app/admin/set-webhook" \
  -H "Authorization: Bearer <TELEGRAM_WEBHOOK_SECRET>"
```

Se deberia de ver `{"ok": true}`.

### Paso 6: Probar

En Telegram, hay que buscar el bot por su username, y mandarle `/start`. Debería responder con el mensaje de bienvenida. Luego probar con `café 50`.

---

## Troubleshooting

**El bot no responde**
- Revisar logs en Railway → tu servicio → Deployments → View Logs.
- Verifica que el webhook esté registrado: `curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo`

**Notion devuelve 404**
- ¿Le diste acceso a la integración a la base? (paso 4 de prerrequisitos).
- Verificar que `NOTION_DATABASE_ID` esté correcto.

**El parser equivoca categorías**
- Editar `app/parser.py` y mejorar el SYSTEM_PROMPT con más ejemplos de vocabulario.

**No me llega el recordatorio nocturno**
- Verificar que la variable `TIMEZONE=America/Mexico_City` esté bien.
- En los logs buscar "Scheduler iniciado". Deberia aparecer al arrancar.
