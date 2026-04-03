# ws_manager.py
from fastapi import WebSocket
from typing import Dict

class ConnectionManager:
    def __init__(self):
        # 核心数据结构：记录所有在线用户的 UUID 和他们对应的长连接
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_uuid: str):
        """用户上线：接受连接并登记造册"""
        await websocket.accept()
        self.active_connections[user_uuid] = websocket
        print(f"[WS] 用户 {user_uuid} 已上线，当前在线人数: {len(self.active_connections)}")

    def disconnect(self, user_uuid: str):
        """用户下线：从字典中移除"""
        if user_uuid in self.active_connections:
            del self.active_connections[user_uuid]
            print(f"[WS] 用户 {user_uuid} 已下线")

    async def send_personal_message(self, message: dict, target_uuid: str) -> bool:
        """精准投递：尝试向特定用户发送消息"""
        if target_uuid in self.active_connections:
            target_ws = self.active_connections[target_uuid]
            try:
                await target_ws.send_json(message)
                return True # 发送成功
            except Exception as e:
                print(f"[WS] 发送给 {target_uuid} 失败: {e}，将其从在线列表移除")
                self.disconnect(target_uuid)
                return False # 目标可能已断开
        return False # 目标不在线

# 实例化一个全局单例！全服务器共用这一个大管家
manager = ConnectionManager()