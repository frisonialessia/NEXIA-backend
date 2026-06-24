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
(`maquina_id`, `vib` en mm/s, `ts`) y los emite; el runner los mete al motor con
`engine.ingest()` y difunde por el WebSocket. El motor no sabe de dónde vino el
dato. Añadir Modbus/OPC UA/HTTP = escribir un `Source` nuevo y una rama en
`crear_source()`. La **autenticación** y el **mapeo de campos** están marcados
con `🔌` en cada adaptador (ver `app/ingest/sources/mqtt_source.py`).

```
app/ingest/
  source.py              Lectura + Source (el contrato/puerto)
  runner.py              crear_source() (factory por entorno) + cableado al motor
  sources/csv_source.py   adaptador CSV (funcional)
  sources/mqtt_source.py  adaptador MQTT (gateway que publica)
  sources/opcua_source.py adaptador OPC UA (PLC industrial)
  sample_readings.csv     datos de ejemplo
```

## Estructura

```
app/
  main.py         FastAPI: rutas, WebSocket, elige simulación o ingesta (lifespan)
  contract.py     modelos de E/S (espejo de lib/api/contract.ts)
  constants.py    constantes del dominio (espejo de lib/constants.ts)
  engine.py       FSM con histéresis + detección (espejo de lib/engine/fsm.ts)
  simulation.py   motor: estado vivo, tick (sim), procesar_lectura (real), comandos
  hub.py          gestor de conexiones WebSocket
  ingest/         módulo de ingesta (conectar fuentes reales)
```

## Próximos pasos (cuando crezca)

- Persistencia (Postgres/TimescaleDB) para historial y series.
- Autenticación (el contrato ya contempla `Authorization: Bearer`).
- Adaptadores Modbus TCP / OPC UA (usar `mqtt_source.py` como plantilla).
