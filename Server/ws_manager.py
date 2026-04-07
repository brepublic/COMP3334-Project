# ws_manager.py
import logging
from fastapi import WebSocket
from typing import Dict


logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # 核心数据结构：记录所有在线用户的 UUID 和他们对应的长连接
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_uuid: str):
        """用户上线：接受连接并登记造册"""
        previous = self.active_connections.get(user_uuid)
        if previous is not None and previous is not websocket:
            try:
                await previous.close(code=1000)
            except Exception:
                pass
        await websocket.accept()
        self.active_connections[user_uuid] = websocket
        logger.info("WebSocket user connected: %s", user_uuid)

    def disconnect(self, user_uuid: str):
        """用户下线：从字典中移除"""
        if user_uuid in self.active_connections:
            del self.active_connections[user_uuid]
            logger.info("WebSocket user disconnected: %s", user_uuid)

    async def send_personal_message(self, message: dict, target_uuid: str) -> bool:
        """精准投递：尝试向特定用户发送消息"""
        if target_uuid in self.active_connections:
            target_ws = self.active_connections[target_uuid]
            try:
                await target_ws.send_json(message)
                return True # 发送成功
            except Exception as e:
                logger.warning("WebSocket send to %s failed: %s", target_uuid, e)
                self.disconnect(target_uuid)
                return False # 目标可能已断开
        return False # 目标不在线

# 实例化一个全局单例！全服务器共用这一个大管家
manager = ConnectionManager()
