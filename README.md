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
  source.py               Lectura (vib + metricas) + Source (el contrato/puerto)
  runner.py               crear_source() (factory por entorno) + cableado al motor
  sources/csv_source.py   adaptador CSV (funcional, lee magnitudes extra)
  sources/mqtt_source.py  adaptador MQTT (gateway que publica)
  sources/opcua_source.py adaptador OPC UA (PLC industrial, multi-variable)
  sample_readings.csv     datos de ejemplo (solo vibración)
  sample_readings_multi.csv  datos de ejemplo con varias magnitudes
```

## Multi-variable (varias magnitudes por máquina)

Una `Lectura` lleva la **vibración** (`vib`, el PIVOTE de detección) y, de forma
**opcional**, otras magnitudes en `metricas` (`{clave: float}`): temperatura,
presión, rpm, corriente… El motor acepta **cualquier magnitud numérica** que
mande el PLC (passthrough); el único campo reservado es `vib`. El vocabulario
canónico (`app/constants.py` → `METRICAS`) no limita lo que entra: solo aporta
unidades/labels a las magnitudes conocidas y alimenta los KPIs (añadir una
conocida = una línea).

- **La detección no cambia.** La probabilidad de fallo y la FSM siguen pivotando
  solo sobre `vib`. Las demás magnitudes son **telemetría aditiva**: se almacenan
  (`Maquina.metricas`, carry-forward del último valor por magnitud) y se exponen,
  pero no alteran las alertas. Son, además, la base para KPIs (OEE, energía…).
- **No rompe el frontend (aditivo).** Los campos nuevos del contrato son
  **opcionales**: `MaquinaDTO.metricas`, `AlertaDTO.metricas` y `LecturaDTO.m`
  (las magnitudes en cada punto del historial). En modo simulado por defecto van
  vacíos: el WebSocket emite **exactamente** el mismo payload que antes y por REST
  los campos llegan como `null` (el frontend los ignora hasta querer graficarlos).
  `vib`/`exp`/`v` siguen siendo el eje. Quedan documentados en `/docs`.
- **Adaptadores:** el CSV lee como métrica cualquier columna extra numérica
  (`sample_readings_multi.csv`); el MQTT toma cualquier clave numérica del payload
  (salvo `vib`/`ts`/`id`); el OPC UA **agrupa los nodos por máquina** y emite
  **una** `Lectura` multi-variable por máquina y ciclo (`vib` + el resto en
  `metricas`).
- **Demo en vivo:** `NEXIA_SIM_MULTIVAR=1` hace que el simulador genere magnitudes
  plausibles (apagado por defecto, para no tocar el payload en vivo).

```bash
# Pipeline real con varias magnitudes desde un CSV:
NEXIA_SOURCE=csv NEXIA_CSV_PATH=app/ingest/sample_readings_multi.csv uvicorn app.main:app --reload
# Simulador con métricas de demo:
NEXIA_SIM_MULTIVAR=1 uvicorn app.main:app --reload
```

`app/kpis.py` deja **listo el camino** para derivar OEE, eficiencia y energía a
partir de esas magnitudes (funciones puras; aún no se exponen en el contrato).

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

Cubren la `Lectura` multi-variable, el motor (filtrado/carry-forward de métricas,
e **invariante de que la FSM no cambia** con o sin magnitudes extra), la
retrocompatibilidad del contrato, los tres adaptadores y los KPIs.

## Estructura

```
app/
  main.py         FastAPI: rutas, WebSocket, elige simulación o ingesta (lifespan)
  contract.py     modelos de E/S (espejo de lib/api/contract.ts)
  constants.py    constantes del dominio + vocabulario de métricas (METRICAS)
  engine.py       FSM con histéresis + detección (espejo de lib/engine/fsm.ts)
  simulation.py   motor: estado vivo, tick (sim), procesar_lectura (real), comandos
  kpis.py         KPIs derivados (energía/eficiencia/OEE) — base, no en el contrato
  hub.py          gestor de conexiones WebSocket
  ingest/         módulo de ingesta (conectar fuentes reales)
```

## Próximos pasos (cuando crezca)

- Exponer KPIs en el contrato (p. ej. `MaquinaDTO.kpis`) reutilizando `app/kpis.py`.
- Detección multi-variable (que temperatura/corriente influyan en la probabilidad).
- Persistencia (Postgres/TimescaleDB) para historial y series.
- Autenticación (el contrato ya contempla `Authorization: Bearer`).
- Adaptador Modbus TCP (usar `opcua_source.py` / `mqtt_source.py` como plantilla).
