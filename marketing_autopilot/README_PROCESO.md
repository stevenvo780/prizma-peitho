# Marketing Autopilot — Humanizar Systems

Pipeline de publicidad automatizada: genera imágenes de marca con IA, las evalúa con un crítico visual, genera copy con narrativa de marca, y publica en Facebook + Instagram.

> **Última ejecución:** 18 Feb 2026 — 8 posts en Facebook + 8 en Instagram (todos los productos).

---

## Inicio rápido

```bash
cd marketing_autopilot
source .venv/bin/activate
python3 run.py campana          # ← flujo completo interactivo
```

Eso es todo. El script guía paso a paso: configurar → generar → evaluar → revisar → publicar.

---

## Setup (solo la primera vez)

```bash
cd marketing_autopilot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Editar .env con las credenciales (ver sección Configuración abajo)
python3 run.py test             # verificar conexión con Meta
```

---

## Comandos

Todos los comandos se ejecutan desde `marketing_autopilot/`:

```bash
source .venv/bin/activate       # activar venv (una vez por terminal)
python3 run.py <comando>        # ejecutar
```

### `campana` — Pipeline completo interactivo ⭐

```bash
python3 run.py campana
```

Flujo guiado de 6 pasos con aprobación humana:

| Step | Qué hace | Interacción |
|------|----------|-------------|
| 1 | **Configurar** | Nombre, temática, productos, formatos, modelo IA |
| 2 | **Generar** | Crea las imágenes con Gemini |
| 3 | **Evaluar** | Crítico IA puntúa cada imagen (0-100) |
| 4 | **Revisar** | Tú apruebas/rechazas/eliminas cada imagen |
| 5 | **Publicar** | Sube a Facebook y/o Instagram |
| 6 | **Resumen** | Tabla final + metadata JSON |

En el paso 4 puedes abrir las imágenes, eliminar las malas, y regenerar las rechazadas antes de publicar.

### `generar` — Crear imágenes

```bash
# Un producto (4 formatos: feed, story, banner, promo)
python3 run.py generar --producto emw

# Todos los productos (8 × 4 = 32 imágenes)
python3 run.py generar --todos

# Campaña temática (agrupa imágenes bajo un nombre)
python3 run.py generar --campana "Marzo 2026" \
  --productos emw graf meravuelta \
  --tematica "Descuentos de apertura" \
  --formatos feed_1x1 story_9x16

# Prompt libre
python3 run.py generar --texto "Banner minimalista tech azul" --ratio 16:9

# Modelo rápido (menor calidad, más barato)
python3 run.py generar --producto graf --modelo gemini-2.5-flash-image

# Ver campañas existentes
python3 run.py generar --listar-campanas
```

**Formatos disponibles:**

| Formato | Ratio | Uso |
|---------|-------|-----|
| `feed_1x1` | 1:1 | Posts de feed FB/IG |
| `story_9x16` | 9:16 | Stories / Reels |
| `banner_16x9` | 16:9 | Portadas, covers |
| `promo_1x1` | 1:1 | Escena sin logo (fotorrealista) |
| `carousel_1x1` | 1:1 | Slide de carrusel |
| `tip_1x1` | 1:1 | Tip educativo |
| `stat_1x1` | 1:1 | Estadística destacada |
| `feature_9x16` | 9:16 | Feature showcase |
| `cta_story_9x16` | 9:16 | CTA agresivo |
| `testimonial_1x1` | 1:1 | Testimonio de cliente |

**Modelos IA:**

| Modelo | Velocidad | Calidad | Cuándo usar |
|--------|-----------|---------|-------------|
| `gemini-3-pro-image-preview` | Lento | Alta (4K, texto preciso) | **Default.** Campañas importantes |
| `gemini-2.5-flash-image` | Rápido | Media (1K) | Iteración rápida, rate limits |

**Salida:** `output/imagenes/<producto>/` o `output/campanas/<fecha>_<nombre>/`

### `evaluar` — Crítico visual IA

```bash
# Evaluar todas las imágenes
python3 run.py evaluar --todos

# Evaluar + regenerar las que fallen
python3 run.py evaluar --todos --regenerar

# Solo un producto
python3 run.py evaluar --producto graf --regenerar

# Umbral personalizado y más intentos
python3 run.py evaluar --todos --regenerar --umbral 80 --max-intentos 3
```

**Rúbrica (5 criterios × 20 pts = 100):**

| Criterio | Qué evalúa | Auto-rechazo si… |
|----------|------------|-------------------|
| Colores | ¿Paleta de marca correcta? ¿Contraste? | — |
| **Texto** ⚠️ | ¿Legible? ¿Sin duplicados ni gibberish? | Texto duplicado, corrupto, nombre mal escrito |
| Composición | ¿Profesional? ¿Equilibrada? | — |
| Logo | ¿Presente? ¿No alucinado? | — |
| Impacto | ¿Scroll-stopper? | — |
| **Marcas** ⛔ | ¿Logos de terceros? | Cualquier marca externa → rechazo inmediato |

- ≥ 70 → ✅ Aprobada
- < 70 → ❌ Rechazada (se mueve a `_rejected/`)

Reportes: `output/imagenes/reporte_calidad_<timestamp>.json`

### `publicar` — Post en Facebook

```bash
# Con copy IA + imagen generada
python3 run.py publicar --producto emw \
  --objetivo "Reactivar clientes dormidos" \
  --publico "Pymes colombianas con WhatsApp Business"

# Sin imagen (solo texto)
python3 run.py publicar --producto graf --sin-imagen

# Con modelo de imagen rápido
python3 run.py publicar --producto meravuelta \
  --modelo-imagen gemini-2.5-flash-image
```

Internamente: genera copy con Cerebro → genera imagen → sube a la Fan Page.

### `instagram` — Publicación masiva en IG

```bash
python3 run.py instagram
```

Publica todos los productos que tengan imagen `feed_1x1` en Instagram. Internamente levanta un servidor HTTP + ngrok para servir las imágenes (IG requiere URLs públicas).

**Requisitos:** `ngrok` instalado, cuenta IG vinculada a la Fan Page.

### `analytics` — Métricas

```bash
python3 run.py analytics --reporte          # Reporte completo Markdown
python3 run.py analytics --resumen          # Insights de la página
python3 run.py analytics --posts            # Métricas de posts
python3 run.py analytics --best-time        # Mejores horarios
python3 run.py analytics --dias 7           # Últimos 7 días
```

### `token` — Gestión de tokens Meta

```bash
python3 run.py token --validar              # ¿Token vigente?
python3 run.py token --refresh              # Renovar (short → long → page)
python3 run.py token --info                 # Debug info
```

Los tokens siguen este ciclo:

```
Token corto (~2h)  →  Token largo (~60 días)  →  Page Token (NO EXPIRA)
   Graph Explorer        token --refresh             token --refresh
```

**Si el token expira:**
1. [Graph Explorer](https://developers.facebook.com/tools/explorer/) → app "Humanizar" → generar User Token
2. Pegar en `META_ACCESS_TOKEN` del `.env`
3. `python3 run.py token --refresh`

### `scheduler` — Cola y calendario

```bash
python3 run.py scheduler --stats            # Estado de la cola
python3 run.py scheduler --pendientes       # Posts pendientes
python3 run.py scheduler --semana           # Generar calendario semanal
```

### `test` — Diagnóstico

```bash
python3 run.py test                         # Tests de conexión y dry-run
```

---

## Arquitectura

```
run.py ─── entry point único
  │
  ├── campana_interactiva.py ── pipeline step-by-step (orquesta todo)
  │
  ├── image_generator.py ────── Gemini 3 Pro → imágenes de marca
  │     └── 10 formatos (feed, story, banner, promo, carousel, tip, stat, feature, cta, testimonial)
  │
  ├── image_critic.py ──────── Gemini 2.5 Pro → evalúa + regenera
  │     └── rúbrica 5 criterios, auto-rechazo por texto/marcas
  │
  ├── cerebro.py ───────────── Gemini 2.0 Flash → copy + estrategia
  │     └── narrativa de marca como system prompt
  │
  ├── publisher.py ─────────── Graph API v24 → posts FB + IG
  │     └── subida directa (FB) + Content Publishing API (IG)
  │
  ├── scheduler.py ─────────── cola JSON, calendario, auto-publish
  ├── campaign_runner.py ───── orquestador de campañas por producto
  ├── analytics.py ─────────── insights FB/IG, mejores horarios
  ├── token_manager.py ─────── ciclo de vida de tokens Meta
  ├── publicar_instagram.py ── publicación masiva IG (ngrok)
  ├── tester.py ────────────── tests de conexión
  └── config.py ────────────── constantes, PRODUCTOS, logging, retry
```

| Módulo | Función | IA |
|--------|---------|-----|
| `config.py` | Fuente de verdad: productos, colores, paths, logging, retry | — |
| `cerebro.py` | Copy + estrategia con narrativa de marca | Gemini 2.0 Flash |
| `image_generator.py` | Imágenes con logos y screenshots de referencia | Gemini 3 Pro / 2.5 Flash |
| `image_critic.py` | Evalúa calidad, rechaza y regenera | Gemini 2.5 Pro |
| `publisher.py` | Posts orgánicos en Facebook e Instagram | — |
| `analytics.py` | Insights, engagement, mejores horarios | — |
| `token_manager.py` | Tokens Meta: short → long-lived → page | — |
| `scheduler.py` | Cola, calendario editorial, auto-publicación | — |

---

## Configuración `.env`

```bash
# IA
GOOGLE_API_KEY=...                # Gemini API (Google AI Studio)

# Meta (Facebook / Instagram)
META_APP_ID=...                   # App ID (Meta Developers)
META_APP_SECRET=...               # App Secret
META_ACCESS_TOKEN=...             # User token (se renueva)
META_AD_ACCOUNT_ID=act_...        # Cuenta publicitaria
META_PAGE_ID=...                  # Fan Page ID
META_INSTAGRAM_ID=...             # IG Business ID
META_LONG_LIVED_TOKEN=...         # (auto-generado)
META_PAGE_TOKEN=...               # (auto-generado, NO EXPIRA)
```

**Permisos Meta necesarios (9):**
`pages_manage_posts` · `pages_read_engagement` · `pages_show_list` · `instagram_basic` · `instagram_content_publish` · `instagram_manage_insights` · `business_management` · `ads_management` · `ads_read`

---

## Productos

| Producto | Key | URL | Precio | Línea |
|----------|-----|-----|--------|-------|
| EMW ⭐ | `emw` | emw.humanizar.cloud | $88.000 | Comercial |
| Graf ⭐ | `graf` | graf.com.co | $30.000/mes | Comercial |
| Mera Vuelta | `meravuelta` | meravuelta.com | $49.500/mes | Operación |
| Sinergia POS | `sinergia` | sinergia-pos.com | $10/mes | Operación |
| Agora | `agora` | agora.humanizar.cloud | $30.000/mes | Productividad |
| Terminal | `terminal` | terminal.humanizar-dev.cloud | $10/mes | Productividad |
| Fiar | `fiar` | fiar.humanizar.cloud | Próximamente | Facturación |
| Humanizar | `humanizar` | humanizar.co | — | Ecosistema |

---

## Estructura de salida

```
output/
├── imagenes/
│   ├── <producto>/               # imágenes aprobadas
│   ├── _rejected/<producto>/     # rechazadas por el crítico
│   └── reporte_calidad_*.json
├── campanas/
│   └── <fecha>_<nombre>/         # campañas con metadata
│       ├── <producto>/
│       ├── campana.json
│       └── campana_resultado.json
├── queue/
│   └── queue.json                # cola del scheduler
├── logs/
│   └── autopilot_*.log           # logs diarios
└── instagram_results.json
```

---

## Cheatsheet

```bash
# ── Flujo completo (recomendado) ──
python3 run.py campana

# ── Comandos individuales ──
python3 run.py generar --todos                          # 32 imágenes
python3 run.py generar --producto emw                   # solo EMW
python3 run.py generar --campana "Promo" --productos emw graf
python3 run.py evaluar --todos --regenerar              # evaluar + regenerar
python3 run.py publicar --producto graf --objetivo "Vender"
python3 run.py instagram                                # publicar todo en IG
python3 run.py analytics --reporte                      # métricas
python3 run.py token --refresh                          # renovar token
python3 run.py test                                     # diagnóstico

# ── Ayuda de cualquier comando ──
python3 run.py generar --help
python3 run.py evaluar --help
```

> **⚠️ Rate limits:** Gemini tiene ~15 RPM en plan gratuito. Si ves `429 RESOURCE_EXHAUSTED`, espera 60s.

---

## Historial

### 18 Feb 2026 — Lanzamiento Digital
- 32 imágenes generadas (8 productos × 4 formatos)
- 8 posts en Facebook + 8 en Instagram
- Página FB: Humanizar Systems (`1045986888587355`)
- Cuenta IG: @humanizar.systems (`17841446993293838`)
