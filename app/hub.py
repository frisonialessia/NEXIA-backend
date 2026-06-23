# ──────────────────────────────────────────────────────────────────────────
# HUB DE WEBSOCKETS
# Mantiene las conexiones vivas y difunde mensajes a todas. Tolera desconexiones
# silenciosas: si un envío falla, descarta esa conexión.
# ──────────────────────────────────────────────────────────────────────────

from fastapi import WebSocket


class ConnectionHub:
    def __init__(self) -> None:
        self._conns: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._conns.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._conns.discard(ws)

    async def broadcast(self, mensaje: dict) -> None:
        muertas = []
        for ws in list(self._conns):
            try:
                await ws.send_json(mensaje)
            except Exception:
                muertas.append(ws)
        for ws in muertas:
            self._conns.discard(ws)

    @property
    def count(self) -> int:
        return len(self._conns)
