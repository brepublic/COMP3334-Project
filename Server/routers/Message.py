# routers/Messages.py

import uuid
from fastapi import APIRouter, Depends, HTTPException
from typing import List

# Import message
from Schema import (
    SendMessageRequest, SendMessageResponse, 
    OfflineMessageResponse, OfflineMessageItem, 
    AckMessagesRequest, StandardResponse
)
from Server_db import User, OfflineMessage, Friendship, UserBlock
from Dependency import get_db, get_current_user

router = APIRouter(tags=["Messages"])


@router.post("/messages/send", response_model=SendMessageResponse)
def send_message(
    request: SendMessageRequest,
    db = Depends(get_db),
    current_user_uuid: str = Depends(get_current_user)
):
    # Check if Friend exists
    receiver = db.query(User).filter(User.uuid == request.receiver_uuid).first()
    if not receiver:
        raise HTTPException(status_code=404, detail="收件人不存在")

    # Stealth Block User 
    relation = db.query(Friendship).filter(
        Friendship.user_uuid_1 == request.receiver_uuid,
        Friendship.user_uuid_2 == current_user_uuid
    ).first()

    blocked = db.query(UserBlock).filter(
        (
            (UserBlock.blocker_uuid == request.receiver_uuid)
            & (UserBlock.blocked_uuid == current_user_uuid)
        )
        | (
            (UserBlock.blocker_uuid == current_user_uuid)
            & (UserBlock.blocked_uuid == request.receiver_uuid)
        )
    ).first()

    if blocked or not relation or relation.status != "FRIEND":
        # If the sender is blocked by receiver, return a fake success message
        fake_message_id = str(uuid.uuid4())
        return SendMessageResponse(
            message_id=fake_message_id,
            status="UNRECEIVED" 
        )

    # If not blocked, put message in offline mailbox
    new_message = OfflineMessage(
        sender_uuid=current_user_uuid,
        receiver_uuid=request.receiver_uuid,
        ciphertext=request.ciphertext,
        expire_duration=request.expire_duration
    )
    db.add(new_message)
    db.flush()

    return SendMessageResponse(
        message_id=new_message.message_id,
        status="UNRECEIVED"
    )

@router.get("/messages/offline", response_model=OfflineMessageResponse)
def get_offline_messages(
    db = Depends(get_db),
    current_user_uuid: str = Depends(get_current_user)
):
    """Get all offline message for myself"""
    
    # get all offline message destinated to requester
    messages = db.query(OfflineMessage).filter(
        OfflineMessage.receiver_uuid == current_user_uuid
    ).order_by(OfflineMessage.created_at.asc(), OfflineMessage.message_id.asc()).all()

    # Return as specified in shcema
    msg_list = []
    for m in messages:
        msg_list.append(
            OfflineMessageItem(
                message_id=m.message_id,
                sender_uuid=m.sender_uuid,
                ciphertext=m.ciphertext,
                expire_duration=m.expire_duration,
                created_at=m.created_at
            )
        )

    return OfflineMessageResponse(messages=msg_list)

# Delete message from database if received by user
@router.post("/messages/ack", response_model=StandardResponse)
def acknowledge_messages(
    request: AckMessagesRequest,
    db = Depends(get_db),
    current_user_uuid: str = Depends(get_current_user)
):
    """Making sure the message is received, delete from database"""
    

    deleted_count = db.query(OfflineMessage).filter(
        OfflineMessage.receiver_uuid == current_user_uuid,
        OfflineMessage.message_id.in_(request.message_ids)
    ).delete(synchronize_session=False)

    db.commit()

    return StandardResponse(
        message=f"Deleted {deleted_count} message from offline mailbox"
    )
