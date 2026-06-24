# ──────────────────────────────────────────────────────────────────────────
# ADAPTADOR · MQTT  (esqueleto listo para conectar un gateway/PLC real)
# ──────────────────────────────────────────────────────────────────────────
# Patrón "el sensor empuja": un gateway industrial publica las lecturas de
# vibración a un broker MQTT; este adaptador está suscrito y, por cada mensaje,
# lo normaliza a `Lectura` y lo emite al motor.
#
#   sensor → gateway → (publica) BROKER MQTT → (suscrito) este Source → motor
#
# Hoy queda como ESQUELETO: el repo corre sin la dependencia. Para activarlo:
#   1) pip install paho-mqtt   (añádelo a requirements.txt)
#   2) NEXIA_SOURCE=mqtt  + las variables de entorno de abajo
#   3) revisa los dos bloques marcados con 🔌 (AUTENTICACIÓN y MAPEO DE CAMPOS)
#
# ⚙️  Para Modbus TCP / OPC UA (patrón "el backend pregunta"), la estructura es
#     la misma: en run() abres el cliente (pymodbus / asyncua), lees el registro
#     cada N segundos y emites `Lectura`. Copia este archivo como plantilla.
# ──────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import json
import os

from ..source import Lectura, Source


class MqttSource(Source):
    def __init__(self) -> None:
        super().__init__()
        # ── Configuración de conexión (por entorno; nada hardcodeado) ─────────
        self.host = os.getenv("MQTT_HOST", "localhost")
        self.port = int(os.getenv("MQTT_PORT", "1883"))
        self.topic = os.getenv("MQTT_TOPIC", "nexia/+/vibracion")  # '+' = comodín por máquina
        # 🔌 AUTENTICACIÓN — aquí se inyectan las credenciales del broker.
        #    Para TLS, añade ca_certs/certfile/keyfile y client.tls_set(...).
        self.username = os.getenv("MQTT_USER")
        self.password = os.getenv("MQTT_PASS")

    def _normalizar(self, topic: str, payload: bytes) -> Lectura | None:
        """🔌 MAPEO DE CAMPOS — traduce el mensaje del gateway a `Lectura`.
        Ajusta esto al formato EXACTO que publique tu gateway. Ejemplo asumido:
            topic:   nexia/<maquina_id>/vibracion
            payload: {"rms_mm_s": 4.2, "ts": 1719190000000}
        """
        try:
            data = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None  # payload inválido → se descarta (validación)

        # maquina_id desde el topic (o desde el payload, según tu convención):
        partes = topic.split("/")
        maquina_id = partes[1] if len(partes) > 1 else data.get("maquina_id", "")

        vib = data.get("rms_mm_s", data.get("vib"))
        if maquina_id == "" or vib is None:
            return None

        return Lectura(maquina_id=maquina_id, vib=float(vib), ts=data.get("ts"))

    async def run(self) -> None:
        # Import perezoso: el repo corre sin paho-mqtt instalado.
        try:
            import paho.mqtt.client as mqtt  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "MqttSource requiere 'paho-mqtt'. Instala: pip install paho-mqtt"
            ) from e

        loop = asyncio.get_running_loop()
        client = mqtt.Client()
        if self.username:
            client.username_pw_set(self.username, self.password)  # 🔌 AUTENTICACIÓN

        def on_connect(c, *_):
            c.subscribe(self.topic)

        def on_message(_c, _u, msg):
            lectura = self._normalizar(msg.topic, msg.payload)
            if lectura is not None:
                # El callback de paho corre en su hilo: reenvía al loop asyncio.
                asyncio.run_coroutine_threadsafe(self.emit(lectura), loop)

        client.on_connect = on_connect
        client.on_message = on_message
        client.connect(self.host, self.port, keepalive=60)
        client.loop_start()
        try:
            while True:
                await asyncio.sleep(3600)  # vive hasta que se cancele la tarea
        finally:
            client.loop_stop()
            client.disconnect()
