# ──────────────────────────────────────────────────────────────────────────
# ADAPTADOR · OPC UA  (PLC / gateway industrial — patrón "el backend pregunta")
# ──────────────────────────────────────────────────────────────────────────
# OPC UA es el estándar industrial moderno. Un PLC expone sus variables como
# "nodos" con una dirección (NodeId), p. ej. ns=2;i=1001 ó ns=3;s=Pump1.Vib.
# Este adaptador se conecta al servidor OPC UA del PLC, lee los nodos
# configurados cada N segundos, y emite una `Lectura` por cada uno.
#
#   PLC (servidor OPC UA)  ◀── lee cada Ns ──  este Source  ──▶  motor
#
# Para activarlo:
#   1) pip install asyncua            (o: pip install -r requirements-ingest.txt)
#   2) NEXIA_SOURCE=opcua  + las variables OPCUA_* (ver abajo y .env.example)
#   3) revisa los dos bloques 🔌 (AUTENTICACIÓN y MAPEO DE NODOS)
#
# 🧪 PROBAR SIN PLC FÍSICO: apunta OPCUA_URL a un servidor OPC UA de demo
#    público (Eclipse Milo, Prosys, Unified Automation) y mapea uno de sus nodos.
#
# ⚙️  Modbus TCP es análogo: en run() abres pymodbus, lees holding registers y
#    emites `Lectura`. Copia este archivo como plantilla.
# ──────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import json
import os

from ...constants import CLAVES_METRICAS, METRICA_PIVOTE
from ..source import Lectura, Source

# ── 🔌 MAPEO DE NODOS ───────────────────────────────────────────────────────
# Qué nodo OPC UA corresponde a qué máquina y qué magnitud ('campo') mide.
# Edítalo aquí, o pásalo por la variable de entorno OPCUA_NODES como JSON con
# esta misma forma. 'campo' usa el vocabulario canónico (app/constants.py):
# 'vib' es el PIVOTE de detección; el resto (temperatura, presion, rpm,
# corriente, voltaje, caudal) son telemetría multi-variable.
#
# Por cada ciclo se leen TODOS los nodos, se AGRUPAN por máquina y se emite UNA
# `Lectura` multi-variable por máquina (vib + el resto en `metricas`). Así un
# mismo PLC alimenta varias magnitudes de un activo en una sola lectura.
NODOS_POR_DEFECTO = [
    {"node": "ns=2;i=1001", "maquina": "Bomba de agua cruda", "campo": "vib"},
    {"node": "ns=2;i=1002", "maquina": "Bomba de agua cruda", "campo": "temperatura"},
    {"node": "ns=2;i=1003", "maquina": "Bomba de agua cruda", "campo": "rpm"},
    {"node": "ns=2;i=1004", "maquina": "Bomba de agua cruda", "campo": "corriente"},
    {"node": "ns=2;i=2001", "maquina": "Compresor de aire #2", "campo": "vib"},
]

# Reconexión con backoff (s) si el servidor del PLC se cae.
_BACKOFF_S = [2, 5, 10, 30]


def agrupar_por_maquina(nodos: list[dict]) -> dict[str, list[dict]]:
    """Agrupa la lista de nodos por máquina, preservando el orden de aparición.
    Función PURA (sin E/S), por eso es trivial de testear sin un servidor OPC UA."""
    grupos: dict[str, list[dict]] = {}
    for n in nodos:
        grupos.setdefault(n["maquina"], []).append(n)
    return grupos


class OpcUaSource(Source):
    def __init__(self) -> None:
        super().__init__()
        # ── Conexión (por entorno; nada hardcodeado) ──────────────────────────
        self.url = os.getenv("OPCUA_URL", "opc.tcp://localhost:4840")
        self.intervalo_s = float(os.getenv("OPCUA_INTERVALO_S", "2"))
        # 🔌 AUTENTICACIÓN — usuario/clave del PLC. Para certificados, usa
        #    client.set_security_string(...) dentro de run().
        self.user = os.getenv("OPCUA_USER")
        self.password = os.getenv("OPCUA_PASS")
        # Mapeo de nodos: por entorno (JSON) o el de arriba.
        raw = os.getenv("OPCUA_NODES")
        self.nodos = json.loads(raw) if raw else NODOS_POR_DEFECTO
        # Agrupados por máquina una sola vez: cada ciclo emite una Lectura
        # multi-variable por máquina (no una por nodo).
        self._grupos = agrupar_por_maquina(self.nodos)
        self._corriendo = False

    async def run(self) -> None:
        # Import perezoso: el repo corre sin asyncua instalado.
        try:
            from asyncua import Client  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "OpcUaSource requiere 'asyncua'. Instala: pip install asyncua"
            ) from e

        self._corriendo = True
        intento = 0
        while self._corriendo:
            try:
                client = Client(url=self.url)
                if self.user:  # 🔌 AUTENTICACIÓN
                    client.set_user(self.user)
                    if self.password:
                        client.set_password(self.password)
                async with client:
                    intento = 0  # conexión OK → resetea el backoff
                    while self._corriendo:
                        await self._leer_todos(client)
                        await asyncio.sleep(self.intervalo_s)
            except asyncio.CancelledError:
                raise
            except Exception:
                # PLC inaccesible / caída: reconecta con backoff.
                espera = _BACKOFF_S[min(intento, len(_BACKOFF_S) - 1)]
                intento += 1
                await asyncio.sleep(espera)

    async def _leer_todos(self, client) -> None:
        """Lee todos los nodos de cada máquina y emite UNA Lectura multi-variable
        por máquina: vibración (pivote) + el resto de magnitudes en `metricas`."""
        for maquina, nodos in self._grupos.items():
            valores: dict[str, float] = {}
            for n in nodos:
                campo = n.get("campo", METRICA_PIVOTE)
                if campo not in CLAVES_METRICAS:
                    continue  # magnitud fuera del vocabulario → se ignora
                try:
                    valor = await client.get_node(n["node"]).read_value()
                    valores[campo] = float(valor)
                except Exception:
                    # Un nodo ilegible no debe tumbar el resto: se omite ESA
                    # magnitud, no la máquina entera.
                    continue
            vib = valores.pop(METRICA_PIVOTE, None)
            if vib is None:
                # Sin vibración este ciclo: el motor pivota sobre vib, así que no
                # se emite (la telemetría sin pivote es trabajo futuro).
                continue
            await self.emit(Lectura(maquina_id=maquina, vib=vib, metricas=valores))

    async def stop(self) -> None:
        self._corriendo = False
