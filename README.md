# NEXIA · Backend

API en **FastAPI** que implementa el contrato del frontend
(`lib/api/contract.ts`). Incluye una **planta virtual**: un motor que simula la
flota y publica al **mismo WebSocket** que publicaría un gateway real, para que
el frontend funcione "en vivo" desde hoy. El día que lleguen sensores físicos,
se reemplaza el motor por la ingesta real y el contrato no cambia.

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET`  | `/v1/fleet/snapshot` | Estado completo de la planta (REST) |
| `WS`   | `/v1/fleet/live` | Snapshot inicial + actualizaciones cada 2 s |
| `POST` | `/v1/alerts/{id}/label` | Etiqueta una alerta `{ "veredicto": "real" \| "falsa" \| "nc" }` |
| `POST` | `/v1/machines/{id}/repair` | Marca una máquina como reparada |
| `POST` | `/v1/machines` | Alta de máquina (cuerpo = semilla) |
| `PATCH`| `/v1/machines/{id}` | Edición parcial de máquina |
| `DELETE`| `/v1/machines/{id}` | Baja de máquina |

Los comandos mutan el estado y reemiten un `snapshot` por el WebSocket; el
frontend reconcilia automáticamente.

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
```

El frontend traerá el snapshot por REST y escuchará el WebSocket. Sin esa
variable, el frontend corre 100 % simulado por su cuenta.

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
(`maquina_id`, `vib` en mm/s, `ts` y `metricas` opcionales — ver multi-variable
abajo) y los emite; el runner los mete al motor con `engine.ingest()` y difunde
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
**opcional**, otras magnitudes: los campos nombrados `temp`, `pres`, `rpm`,
`caudal`, `corriente`, y/o un dict genérico `metricas` (`{clave: float}`) para el
resto del vocabulario (p. ej. `voltaje`). El vocabulario canónico vive en un solo
sitio, `app/constants.py` (`METRICAS` / `CAMPOS_TELEMETRIA`), con los **mismos
nombres cortos que el frontend**; añadir una magnitud es una línea.

- **La detección de fallo no cambia.** La probabilidad y la FSM siguen pivotando
  solo sobre `vib`. Las demás magnitudes son telemetría: se almacenan
  (`Maquina.metricas`, carry-forward del último valor por magnitud) y se exponen.
- **Dos vistas en el contrato (aditivas y opcionales):**
  - `MaquinaDTO.metricas` — dict genérico y extensible (cualquier magnitud).
  - `MaquinaDTO.telemetria` — `TelemetriaDTO` **tipado** (las 5 magnitudes que
    grafica el frontend: temp/pres/rpm/caudal/corriente). Solo se emite cuando las
    **5 están completas** (sus campos son floats no-nulos); si falta alguna → `null`.
  - `MaquinaDTO.kpis` — `KpisDTO` con energía/eficiencia/OEE derivados (ver abajo).
  - `AlertaDTO` gana `campo`/`valor`/`limite` (qué magnitud disparó y su límite).
  - `LecturaDTO.m` — las magnitudes en cada punto del historial.
- **No rompe el frontend.** Todo lo anterior es opcional; `vib`/`exp`/`v` y el
  núcleo de las alertas no cambian. Con `NEXIA_SIM_MULTIVAR=0` el payload en vivo
  es **idéntico** al de antes de multi-variable. Todo queda documentado en `/docs`.
- **Adaptadores:** el CSV lee como métrica cualquier columna extra del vocabulario
  (`sample_readings_multi.csv`); el MQTT toma las claves extra del payload JSON; el
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

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

Cubren la `Lectura` multi-variable, el motor (filtrado/carry-forward, telemetría
**solo-si-completa**, e **invariante de que la FSM no cambia** con o sin magnitudes
extra), las **reglas de temperatura/presión** (edge-trigger), la retrocompatibilidad
del contrato, los tres adaptadores y los KPIs.

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
  ingest/         módulo de ingesta (conectar fuentes reales)
```

## Próximos pasos (cuando crezca)

- Detección multi-variable (que temperatura/corriente influyan en la probabilidad,
  no solo como reglas de umbral independientes).
- OEE completo: disponibilidad (paradas) y calidad (scrap) con datos reales, en vez
  de los placeholders actuales.
- **FASE 2:** persistencia (Postgres/Supabase), login `Authorization: Bearer` y
  multi-tenant (filtrar por organización en REST y WebSocket).
- **FASE 3:** empaquetar `app/ingest/` como agente edge (Docker) dentro de la planta.
- Adaptador Modbus TCP (usar `opcua_source.py` / `mqtt_source.py` como plantilla).
