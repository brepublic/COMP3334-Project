# routers/ChatWS.py

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query, HTTPException
from jwt.exceptions import InvalidTokenError
from datetime import datetime, timezone

# 引入我们的组件
from config import settings
from ws_manager import manager
from Server_db import OfflineMessage, Friendship
from Dependency import get_db, authenticate_token

router = APIRouter(tags=["WebSocket"])

# ==========================================
# WS 专属看门大爷：从 URL Parameter 中验票
# ==========================================
async def get_ws_current_user(token: str = Query(...)):
    """从 ws://.../?token=xxx 中提取并验证 JWT"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_uuid: str = payload.get("sub")
        if user_uuid is None:
            return None
        return user_uuid
    except InvalidTokenError:
        return None

# ==========================================
# 核心大动脉：长连接接入点
# ==========================================
@router.websocket("/ws/chat")
async def websocket_endpoint(
    websocket: WebSocket, 
    user_uuid: str = Depends(get_ws_current_user),
    db = Depends(get_db)
):
    # 1. 验证失败直接踢掉断开
    if not user_uuid:
        await websocket.close(code=1008) # 1008: Policy Violation (未授权)
        return
    try:
        authenticate_token(websocket.query_params.get("token", ""), db)
    except HTTPException:
        await websocket.close(code=1008)
        return

    # 2. 验证成功，登记上线
    await manager.connect(websocket, user_uuid)

    try:
        # 3. 开启死循环，永远监听这个长连接发来的消息
        while True:
            # 阻塞等待客户端发来的 JSON 数据
            data = await websocket.receive_json()
            
            # 假设客户端发来的格式是: {"receiver_uuid": "...", "ciphertext": "...", "expire_duration": 86400}
            receiver_uuid = data.get("receiver_uuid")
            ciphertext = data.get("ciphertext")

            if not receiver_uuid or not ciphertext:
                continue # 格式不对，忽略

            # 🚨 触发黑洞拦截机制 (Stealth Block)
            relation = db.query(Friendship).filter(
                Friendship.user_uuid_1 == receiver_uuid,
                Friendship.user_uuid_2 == user_uuid
            ).first()

            if not relation or (relation.status == "BLOCKED" and relation.blocked_by == receiver_uuid):
                # 被拉黑了，直接假装没看见，也不往下传
                continue 

            # 4. 尝试实时投递给 Bob
            forward_payload = {
                "type": "NEW_MESSAGE",
                "sender_uuid": user_uuid,
                "ciphertext": ciphertext,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            is_online = await manager.send_personal_message(forward_payload, receiver_uuid)

            # 5. 如果 Bob 不在线，必须存入离线数据库保底！
            if not is_online:
                new_offline_msg = OfflineMessage(
                    sender_uuid=user_uuid,
                    receiver_uuid=receiver_uuid,
                    ciphertext=ciphertext,
                    expire_duration=data.get("expire_duration", 86400)
                )
                db.add(new_offline_msg)
                db.commit() # 落盘

    except WebSocketDisconnect:
        # 6. 如果客户端断网、杀后台，捕获异常并让管家把他从字典里删掉
        manager.disconnect(user_uuid)