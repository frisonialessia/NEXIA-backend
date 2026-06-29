# NEXIA · Backend

API en **FastAPI** que implementa el contrato del frontend
(`lib/api/contract.ts`). Incluye una **planta virtual**: un motor que simula la
flota y publica al **mismo WebSocket** que publicaría un gateway real, para que
el frontend funcione "en vivo" desde hoy. El día que lleguen sensores físicos,
se reemplaza el motor por la ingesta real y el contrato no cambia.

## Endpoints

| Método | Ruta | Descripción | Permiso |
|--------|------|-------------|---------|
| `POST` | `/v1/auth/login` | `{ email, password }` → `{ token, usuario }` | público |
| `GET`  | `/v1/auth/me` | Usuario del token Bearer | token |
| `GET`  | `/v1/org/permisos` | Matriz de permisos de la organización | token |
| `PUT`  | `/v1/org/permisos` | Editar la matriz (cuerpo `{ permisos }`) | `usuarios` |
| `GET`  | `/v1/fleet/snapshot` | Estado completo de la planta (REST) | token |
| `WS`   | `/v1/fleet/live?token=` | Snapshot inicial + actualizaciones cada 2 s | token |
| `POST` | `/v1/alerts/{id}/label` | Etiqueta una alerta `{ "veredicto": "real" \| "falsa" \| "nc" }` | `auditar` |
| `POST` | `/v1/machines/{id}/repair` | Marca una máquina como reparada | `mantenimiento` |
| `POST` | `/v1/machines` | Alta de máquina (cuerpo = semilla) | `activos` |
| `PATCH`| `/v1/machines/{id}` | Edición parcial de máquina | `activos` |
| `DELETE`| `/v1/machines/{id}` | Baja de máquina | `activos` |

Los comandos mutan el estado y reemiten un `snapshot` por el WebSocket; el
frontend reconcilia automáticamente. Con `NEXIA_AUTH=1` se exige
`Authorization: Bearer <token>` (y `?token=` en el WS) y cada comando requiere su
permiso (ver **Auth y multi-tenant**). Con auth desactivada (default) todo queda
abierto sobre una organización por defecto.

Docs interactivas (OpenAPI) en `/docs`.

## Arranque local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- REST: http://localhost:8000/v1/fleet/snapshot
- WebSocket: ws://localhost:8000/v1/fleet/live
- Docs: http://localhost:8000/docs

## Conectar el frontend

En el repo del frontend, crea `.env.local`:

```
NEXT_PUBLIC_API_URL=http://localhost:8000
# Login real contra el backend (FASE 2). Requiere arrancar el backend con
# NEXIA_AUTH=1. Sin esta variable, el frontend usa su login local.
NEXT_PUBLIC_AUTH=remote
```

El frontend traerá el snapshot por REST y escuchará el WebSocket. Sin
`NEXT_PUBLIC_API_URL`, el frontend corre 100 % simulado por su cuenta.

## Despliegue

Cualquier host de Python sirve. Opciones incluidas:

- **Render:** `render.yaml` (deploy desde el repo).
- **Docker:** `docker build -t nexia-backend . && docker run -p 8000:8000 nexia-backend`
- **Railway / Fly / Heroku:** usan el `Procfile`.

Recuerda fijar `NEXIA_CORS_ORIGINS` a tu dominio de Vercel en producción.

## Módulo de ingesta (conectar máquinas reales)

El "enchufe" para datos reales, desacoplado del motor (patrón puerto/adaptador).
La fuente de datos se elige por `NEXIA_SOURCE` **sin tocar el motor ni la UI**:

| `NEXIA_SOURCE` | Qué hace |
|---|---|
| `sim` (def.) | Simulador interno (sin hardware). |
| `csv` | Reproduce `app/ingest/sample_readings.csv`. Prueba todo el pipeline. |
| `mqtt` | Escucha un broker MQTT real (gateway que publica). |
| `opcua` | Lee un **PLC / gateway industrial** por OPC UA. |

Conectores reales (MQTT/OPC UA) requieren `pip install -r requirements-ingest.txt`.
El `🔌 MAPEO` de nodos/campos y la `🔌 AUTENTICACIÓN` están marcados en cada adaptador.

Probar el pipeline con datos "reales" desde un CSV:

```bash
NEXIA_SOURCE=csv uvicorn app.main:app --reload
```

**Cómo encaja:** cualquier fuente normaliza sus datos a una `Lectura`
(`maquina_id`, `vib` en mm/s, `ts` y telemetría opcional `temp/pres/rpm/caudal/
corriente` — ver multi-variable abajo) y los emite; el runner los mete al motor
con `engine.ingest()` y difunde
por el WebSocket. El motor no sabe de dónde vino el dato. Añadir Modbus/OPC UA/HTTP
= escribir un `Source` nuevo y una rama en `crear_source()`. La **autenticación**
y el **mapeo de campos** están marcados con `🔌` en cada adaptador (ver
`app/ingest/sources/mqtt_source.py`).

```
app/ingest/
  source.py               Lectura (vib + telemetría) + Source (el contrato/puerto)
  runner.py               crear_source() (factory por entorno) + cableado al motor
  sources/csv_source.py   adaptador CSV (funcional, lee magnitudes extra)
  sources/mqtt_source.py  adaptador MQTT (gateway que publica)
  sources/opcua_source.py adaptador OPC UA (PLC industrial, multi-variable)
  sample_readings.csv     datos de ejemplo (solo vibración)
  sample_readings_multi.csv  datos de ejemplo con varias magnitudes
```

## Multi-variable (varias magnitudes por máquina)

Una `Lectura` lleva la **vibración** (`vib`, el PIVOTE de detección) y, de forma
**opcional**, las 5 magnitudes de telemetría: `temp`, `pres`, `rpm`, `caudal`,
`corriente`. El vocabulario canónico vive en un solo sitio, `app/constants.py`
(`METRICAS` / `CAMPOS_TELEMETRIA`), con los **mismos nombres cortos que el
frontend**; añadir una magnitud es una línea.

- **La detección de fallo no cambia.** La probabilidad y la FSM siguen pivotando
  solo sobre `vib`. La telemetría se almacena (`Maquina.telemetria`, carry-forward
  del último valor por magnitud) y se expone, pero no toca las alertas de vibración.
- **En el contrato (aditivo y opcional):**
  - `MaquinaDTO.telemetria` — `TelemetriaDTO` **tipado** (las 5 magnitudes que
    grafica el frontend: temp/pres/rpm/caudal/corriente). Solo se emite cuando las
    **5 están completas** (sus campos son floats no-nulos); si falta alguna → `null`
    (carry-forward la va completando).
  - `MaquinaDTO.kpis` — `KpisDTO` con energía/eficiencia/OEE derivados (ver abajo).
  - `AlertaDTO` gana `campo`/`valor`/`limite` (qué magnitud disparó y su límite).
- **No rompe el frontend.** Todo lo anterior es opcional; `vib`/`exp`/`v`, el
  historial `{t,v,exp}` y el núcleo de las alertas no cambian. Con
  `NEXIA_SIM_MULTIVAR=0` el payload en vivo es **idéntico** al de antes de
  multi-variable. Todo queda documentado en `/docs`.
- **Adaptadores:** el CSV lee como telemetría las columnas del vocabulario
  (`sample_readings_multi.csv`); el MQTT toma esas claves del payload JSON; el
  OPC UA **agrupa los nodos por máquina** (cada nodo mapea un `campo`) y emite
  **una** `Lectura` multi-variable por máquina y ciclo (`vib` + el resto).

### Reglas multi-variable (alertas que no son de vibración)

Además de la FSM de vibración, hay reglas por umbral **edge-triggered** (una alerta
al cruzar el umbral; se rearma al volver al rango), configurables en
`app/constants.py`:

- **Sobretemperatura:** `temp > UMBRAL_TEMP` (80 °C).
- **Presión fuera de rango:** `pres < PRES_MIN` (1 bar) o `pres > PRES_MAX` (10 bar).

Cada una emite una `AlertaDTO` normal (mismo formato que la de vibración) con
`campo` = `"temperatura"` | `"presion"` y su `valor`/`limite`.

### KPIs (base de OEE / eficiencia / energía)

`app/kpis.py` deriva, con la telemetría disponible, un `MaquinaDTO.kpis`:
`energiaKw` (de `corriente` × voltaje), `eficiencia` (`caudal` / nominal) y un `oee`
base (rendimiento real por caudal; disponibilidad y calidad son placeholders
documentados hasta tener datos de parada/scrap). Solo aparece lo calculable con los
datos presentes; es una capa aparte que **no toca la FSM**.

### Demo

```bash
# Pipeline real con varias magnitudes desde un CSV:
NEXIA_SOURCE=csv NEXIA_CSV_PATH=app/ingest/sample_readings_multi.csv uvicorn app.main:app --reload
# El simulador genera telemetría por defecto; para apagarla (payload "clásico"):
NEXIA_SIM_MULTIVAR=0 uvicorn app.main:app --reload
```

## Auth y multi-tenant (FASE 2)

Login propio con **JWT Bearer** y aislamiento por **organización**. Se activa con
`NEXIA_AUTH=1` (desactivado por defecto → modo demo abierto, idéntico a FASE 1).
Sin dependencias nativas: el JWT (HS256) y el hash de contraseña (PBKDF2) usan
solo la stdlib.

**Login** (contrato que consume el frontend):

```
POST /v1/auth/login   { "email": "...", "password": "..." }
→ { "token": "<jwt>", "usuario": { "nombre", "email", "rol", "color"? } }
```

Las llamadas autenticadas mandan `Authorization: Bearer <token>`; el WebSocket
recibe el token por query param: `/v1/fleet/live?token=<jwt>`.

**Roles:** `admin · jefe · tecnico · operador · lectura`. Cada organización tiene
su **matriz de 11 permisos** (sembrada con defaults, editable por el admin vía
`PUT /v1/org/permisos`). Permisos que gobiernan endpoints del backend:

| Permiso | Roles (default) | Gobierna |
|---|---|---|
| `auditar` | admin, jefe, tecnico, operador | etiquetar alertas |
| `mantenimiento` | admin, jefe, tecnico | reparar máquina |
| `activos` | admin, tecnico | alta/edición/baja de máquinas |

Los demás (`produccion, plantas, facturacion, conexiones, usuarios, ajustesPlanta,
exportar, tendencia`) gobiernan vistas del frontend; el backend los sirve en
`GET /v1/org/permisos` para que la UI se adapte.

**Multi-tenant:** cada organización tiene su propio motor de planta y su flota; un
usuario solo ve y opera la suya. El token lleva la organización y el backend
enruta snapshot/comandos/WS a su *tenant*.

**Persistencia (opcional, $0):** por defecto el estado vive en memoria (orgs/
usuarios sembrados; 2 orgs de demo). Activando `NEXIA_SQLITE_PATH` (o
`NEXIA_PERSIST=1`) el estado de cada organización se guarda en un fichero **SQLite
local** y sobrevive reinicios — sin servicios ni coste. Es **aditivo**: con el flag
apagado el comportamiento y el contrato son idénticos (ver `app/persistence.py`).

**Usuarios de demo** (contraseña `demo1234`):

| Organización | Email | Rol |
|---|---|---|
| Planta Norte | alessia@planta.com | admin |
| Planta Norte | carlos@planta.com | jefe |
| Planta Norte | roberto@planta.com | tecnico |
| Planta Norte | luis@planta.com | operador |
| Planta Norte | audit@planta.com | lectura |
| Aguas del Valle | admin@aguasdelvalle.com | admin |
| Aguas del Valle | tecnico@aguasdelvalle.com | tecnico |

Config: `NEXIA_AUTH`, `NEXIA_JWT_SECRET`, `NEXIA_JWT_TTL_H` (ver `.env.example`).

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

Cubren la `Lectura` multi-variable, el motor (filtrado/carry-forward, telemetría
**solo-si-completa**, e **invariante de que la FSM no cambia** con o sin magnitudes
extra), las **reglas de temperatura/presión** (edge-trigger), la retrocompatibilidad
del contrato, los tres adaptadores y los KPIs. Y para FASE 2: login/tokens, hash de
contraseña, la **matriz de roles**, el **aislamiento multi-tenant** y los endpoints
de auth (Bearer requerido, permisos por comando, WS con `?token`).

## Estructura

```
app/
  main.py         FastAPI: rutas, WebSocket, elige simulación o ingesta (lifespan)
  contract.py     modelos de E/S (espejo de lib/api/contract.ts)
  constants.py    constantes del dominio + vocabulario de métricas (METRICAS)
  engine.py       FSM con histéresis + detección (espejo de lib/engine/fsm.ts)
  simulation.py   motor: estado vivo, tick (sim), procesar_lectura (real), comandos
  kpis.py         KPIs derivados (energía/eficiencia/OEE), expuestos en MaquinaDTO.kpis
  hub.py          gestor de conexiones WebSocket
  tenancy.py      multi-tenant: un motor + hub + lock por organización
  persistence.py  persistencia local SQLite opcional ($0, aditiva, off por defecto)
  auth/           login JWT (stdlib), matriz de roles, semilla de orgs/usuarios
  ingest/         módulo de ingesta (conectar fuentes reales)
```

## Próximos pasos (cuando crezca)

- Detección multi-variable (que temperatura/corriente influyan en la probabilidad,
  no solo como reglas de umbral independientes).
- OEE completo: disponibilidad (paradas) y calidad (scrap) con datos reales, en vez
  de los placeholders actuales.
- **FASE 2a (hecho):** login `Authorization: Bearer` + multi-tenant + endurecido
  de JWT (fail-fast sin secreto en prod), aislamiento en REST y WebSocket.
- **Persistencia local (hecho, opcional, $0):** SQLite local activable por entorno
  (`NEXIA_SQLITE_PATH`), aditiva y desactivada por defecto. Sobrevive reinicios sin
  coste ni servicios.
- **Más adelante (si se necesita escala):** mover la persistencia a Postgres
  gestionado y ROI real calculado desde las etiquetas persistidas.
- **FASE 3:** empaquetar `app/ingest/` como agente edge (Docker) dentro de la planta.
- Adaptador Modbus TCP (usar `opcua_source.py` / `mqtt_source.py` como plantilla).
