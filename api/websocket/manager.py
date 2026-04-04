"""
api/websocket/manager.py - WebSocket connection manager
"""

import json
import logging
from typing import Dict, List, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class ConnectionManager:
    """Manage WebSocket connections by channel"""

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, channel: str):
        """Accept and register new WebSocket connection"""
        await websocket.accept()
        if channel not in self.active_connections:
            self.active_connections[channel] = set()
        self.active_connections[channel].add(websocket)
        logger.info(f"WebSocket connected to channel '{channel}' - Total: {len(self.active_connections[channel])}")

    async def disconnect(self, websocket: WebSocket, channel: str):
        """Remove WebSocket connection"""
        if channel in self.active_connections:
            self.active_connections[channel].discard(websocket)
            logger.info(f"WebSocket disconnected from channel '{channel}' - Total: {len(self.active_connections[channel])}")

    async def broadcast(self, message: dict, channel: str):
        """Broadcast message to all connections in a channel"""
        if channel not in self.active_connections:
            return

        disconnected = set()
        for connection in self.active_connections[channel]:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending message: {e}")
                disconnected.add(connection)

        # Clean up disconnected connections
        for connection in disconnected:
            await self.disconnect(connection, channel)

    def get_connection_count(self, channel: str) -> int:
        """Get number of active connections in a channel"""
        return len(self.active_connections.get(channel, set()))

