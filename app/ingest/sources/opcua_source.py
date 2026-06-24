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

from ..source import Lectura, Source

# ── 🔌 MAPEO DE NODOS ───────────────────────────────────────────────────────
# Qué nodo OPC UA corresponde a qué máquina (y qué magnitud mide). Edítalo aquí,
# o pásalo por la variable de entorno OPCUA_NODES como JSON con esta misma forma.
# Hoy el motor consume 'vib' (vibración mm/s); cuando ampliemos a multi-variable
# (temp, presion, rpm, corriente…) bastará con añadir entradas con otro 'campo'.
NODOS_POR_DEFECTO = [
    {"node": "ns=2;i=1001", "maquina": "Bomba de agua cruda", "campo": "vib"},
    {"node": "ns=2;i=1002", "maquina": "Compresor de aire #2", "campo": "vib"},
]

# Reconexión con backoff (s) si el servidor del PLC se cae.
_BACKOFF_S = [2, 5, 10, 30]


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
        for n in self.nodos:
            # Hoy solo se consume la vibración; el resto se ignora hasta que el
            # motor sea multi-variable.
            if n.get("campo", "vib") != "vib":
                continue
            try:
                valor = await client.get_node(n["node"]).read_value()
                await self.emit(Lectura(maquina_id=n["maquina"], vib=float(valor)))
            except Exception:
                # Un nodo ilegible no debe tumbar la lectura de los demás.
                continue

    async def stop(self) -> None:
        self._corriendo = False
