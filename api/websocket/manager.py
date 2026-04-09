"""
api/websocket/manager.py - WebSocket connection manager with heartbeat

Features:
  - Channel-based connection tracking
  - Periodic ping/pong heartbeat (detects stale connections)
  - Automatic cleanup of disconnected clients
  - Connection count per channel
"""

import json
import time
import asyncio
import logging
from typing import Dict, Set
from fastapi import WebSocket
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30  # seconds between pings
HEARTBEAT_TIMEOUT = 10   # seconds to wait for pong response


class ConnectionManager:
    """Manage WebSocket connections by channel with heartbeat support."""

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self._last_pong: Dict[int, float] = {}  # ws id → last pong timestamp
        self._heartbeat_task = None

    async def connect(self, websocket: WebSocket, channel: str):
        """Accept and register new WebSocket connection."""
        await websocket.accept()
        if channel not in self.active_connections:
            self.active_connections[channel] = set()
        self.active_connections[channel].add(websocket)
        self._last_pong[id(websocket)] = time.monotonic()
        logger.info(f"WebSocket connected to '{channel}' (total: {len(self.active_connections[channel])})")

        # Start heartbeat if not running
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def disconnect(self, websocket: WebSocket, channel: str):
        """Remove WebSocket connection."""
        if channel in self.active_connections:
            self.active_connections[channel].discard(websocket)
            logger.info(f"WebSocket disconnected from '{channel}' (total: {len(self.active_connections[channel])})")
        self._last_pong.pop(id(websocket), None)

    async def broadcast(self, message: dict, channel: str):
        """Broadcast message to all connections in a channel."""
        if channel not in self.active_connections:
            return

        disconnected = set()
        for connection in self.active_connections[channel]:
            try:
                if connection.client_state == WebSocketState.CONNECTED:
                    await connection.send_json(message)
                else:
                    disconnected.add(connection)
            except Exception:
                disconnected.add(connection)

        for connection in disconnected:
            await self.disconnect(connection, channel)

    def get_connection_count(self, channel: str) -> int:
        """Get number of active connections in a channel."""
        return len(self.active_connections.get(channel, set()))

    def get_total_connections(self) -> int:
        """Get total connections across all channels."""
        return sum(len(conns) for conns in self.active_connections.values())

    async def _heartbeat_loop(self):
        """Periodic heartbeat: send ping, cleanup stale connections."""
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)

                if self.get_total_connections() == 0:
                    continue

                stale = []
                now = time.monotonic()

                for channel, connections in list(self.active_connections.items()):
                    for ws in list(connections):
                        try:
                            if ws.client_state != WebSocketState.CONNECTED:
                                stale.append((ws, channel))
                                continue

                            # Send ping
                            await ws.send_json({"type": "ping", "ts": int(time.time())})
                            self._last_pong[id(ws)] = now

                        except Exception:
                            stale.append((ws, channel))

                # Cleanup stale connections
                for ws, channel in stale:
                    await self.disconnect(ws, channel)

                if stale:
                    logger.info(f"Heartbeat: cleaned {len(stale)} stale connection(s)")

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.debug(f"Heartbeat error: {e}")
                await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def close_all(self):
        """Close all connections gracefully (called on shutdown)."""
        for channel, connections in list(self.active_connections.items()):
            for ws in list(connections):
                try:
                    if ws.client_state == WebSocketState.CONNECTED:
                        await ws.close(code=1001, reason="Server shutting down")
                except Exception:
                    pass
            connections.clear()

        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()

        logger.info("All WebSocket connections closed")
