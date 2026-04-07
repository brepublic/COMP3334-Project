# routers/Contacts.py

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Literal

# Import schema and my own modules
from Schema import (
    FriendRequestPayload, StandardResponse, BlockUserRequest, 
    FriendRequestAction, PendingRequestInfo, FriendInfo, 
    FriendListResponse, ContactKeysResponse, DeviceKeyInfo
)
from Server_db import User, Friendship, FriendRequest, Device, FriendRequestRateLimit, UserBlock
from Dependency import get_db, get_current_user

router = APIRouter(tags=["Contacts"])


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _block_exists(db, blocker_uuid: str, blocked_uuid: str) -> bool:
    return (
        db.query(UserBlock)
        .filter(
            UserBlock.blocker_uuid == blocker_uuid,
            UserBlock.blocked_uuid == blocked_uuid,
        )
        .first()
        is not None
    )


def _pending_info_for(db, request_row: FriendRequest, direction: Literal["incoming", "outgoing"]) -> PendingRequestInfo:
    if direction == "incoming":
        counterparty_uuid = request_row.sender_uuid
    else:
        counterparty_uuid = request_row.receiver_uuid
    counterparty = db.query(User).filter(User.uuid == counterparty_uuid).first()
    return PendingRequestInfo(
        request_id=request_row.request_id,
        direction=direction,
        counterparty_uuid=counterparty_uuid,
        counterparty_name=counterparty.user_name if counterparty else "Unknown",
    )

@router.post("/friends/request", response_model=StandardResponse)
def send_friend_request(
    payload: FriendRequestPayload, 
    db = Depends(get_db),
    current_user_uuid: str = Depends(get_current_user) # validates user token
):
    """Send friend request through email"""
    
    now = datetime.now(timezone.utc)
    rate_limit = db.query(FriendRequestRateLimit).filter(
        FriendRequestRateLimit.sender_uuid == current_user_uuid
    ).first()
    blocked_until = _ensure_utc(rate_limit.blocked_until) if rate_limit else None
    if blocked_until and blocked_until > now:
        remaining_seconds = int((blocked_until - now).total_seconds())
        raise HTTPException(
            status_code=429,
            detail=f"Too many friend requests. Retry in about {remaining_seconds} seconds.",
        )

    # Don't add yourself
    target_email = payload.target_email
    sender = db.query(User).filter(User.uuid == current_user_uuid).first()
    if sender.email == target_email:
        raise HTTPException(status_code=400, detail="Can't add yourself as Friend.")

    # Don't add nobody
    target_user = db.query(User).filter(User.email == target_email).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Doesn't not found user.")

    if _block_exists(db, target_user.uuid, current_user_uuid) or _block_exists(db, current_user_uuid, target_user.uuid):
        return StandardResponse(message="Friend request ignored.")

    # Check for duplicate
    existing_friend = db.query(Friendship).filter(
        ((Friendship.user_uuid_1 == current_user_uuid) & (Friendship.user_uuid_2 == target_user.uuid)) |
        ((Friendship.user_uuid_1 == target_user.uuid) & (Friendship.user_uuid_2 == current_user_uuid))
    ).first()
    
    if existing_friend:
        raise HTTPException(status_code=400, detail="You are alread friends.")

    # Check for duplicate friend requests
    existing_request = db.query(FriendRequest).filter(
        FriendRequest.sender_uuid == current_user_uuid,
        FriendRequest.receiver_uuid == target_user.uuid,
        FriendRequest.status == "PENDING"
    ).first()
    
    if existing_request:
        raise HTTPException(status_code=400, detail="You have already sent a friend request")


    # Generate the actual friend request
    new_request = FriendRequest(
        sender_uuid=current_user_uuid,
        receiver_uuid=target_user.uuid,
        status="PENDING"
    )
    db.add(new_request)
    db.flush()

    one_minute_ago = now - timedelta(minutes=1)
    sent_in_last_minute = db.query(FriendRequest).filter(
        FriendRequest.sender_uuid == current_user_uuid,
        FriendRequest.created_at >= one_minute_ago,
    ).count()
    if sent_in_last_minute >= 10:
        blocked_until = now + timedelta(minutes=30)
        if not rate_limit:
            rate_limit = FriendRequestRateLimit(sender_uuid=current_user_uuid)
            db.add(rate_limit)
        rate_limit.blocked_until = blocked_until
        rate_limit.updated_at = now

    return StandardResponse(message=f"Successfully send friend request to {target_user.user_name}!")


# Accept Friend request
@router.get("/friends/pending", response_model=List[PendingRequestInfo])
def get_pending_requests(
    direction: Literal["incoming", "outgoing"] = Query(default="incoming"),
    db = Depends(get_db),
    current_user_uuid: str = Depends(get_current_user)
):
    """Get Pending friend request"""
    if direction == "incoming":
        requests = db.query(FriendRequest).filter(
            FriendRequest.receiver_uuid == current_user_uuid,
            FriendRequest.status == "PENDING"
        ).all()
    else:
        requests = db.query(FriendRequest).filter(
            FriendRequest.sender_uuid == current_user_uuid,
            FriendRequest.status == "PENDING"
        ).all()

    return [_pending_info_for(db, req, direction) for req in requests]


# Respond to friend request
@router.post("/friends/action", response_model=StandardResponse)
def respond_to_friend_request(
    payload: FriendRequestAction,
    db = Depends(get_db),
    current_user_uuid: str = Depends(get_current_user)
):
    """Accept or Reject Friend Request"""
    
    # Verify if the request exists
    req = db.query(FriendRequest).filter(
        FriendRequest.request_id == payload.request_id,
        FriendRequest.receiver_uuid == current_user_uuid, 
        FriendRequest.status == "PENDING"
    ).first()

    if not req:
        raise HTTPException(status_code=404, detail="Request doesn't exist or handled")

    # Update request status
    req.status = payload.action

    # 3. If accepted, create friend entries
    if payload.action == "ACCEPT":
        friendship_1 = Friendship(user_uuid_1=current_user_uuid, user_uuid_2=req.sender_uuid, status="FRIEND")
        friendship_2 = Friendship(user_uuid_1=req.sender_uuid, user_uuid_2=current_user_uuid, status="FRIEND")
        db.add_all([friendship_1, friendship_2])
        message = "Friend Accepted"
    else:
        message = "Friend Rejected"

    return StandardResponse(message=message)


# Get my friend list
@router.get("/friends", response_model=FriendListResponse)
def get_my_friends(
    db = Depends(get_db),
    current_user_uuid: str = Depends(get_current_user)
):
    """Get all of my friends"""
    
    friendships = db.query(Friendship).filter(
        Friendship.user_uuid_1 == current_user_uuid
    ).all()

    friend_list = []
    for f in friendships:
        friend_user = db.query(User).filter(User.uuid == f.user_uuid_2).first()
        if friend_user:
            friend_list.append(
                FriendInfo(
                    uuid=friend_user.uuid,
                    user_name=friend_user.user_name,
                    email=friend_user.email,
                    status=f.status,
                    blocked_by=f.blocked_by
                )
            )
            
    return FriendListResponse(friends=friend_list)


@router.post("/friends/block", response_model=StandardResponse)
def block_user(
    request: BlockUserRequest,
    db = Depends(get_db),
    current_user_uuid: str = Depends(get_current_user)
):
    
    if request.target_uuid == current_user_uuid:
        raise HTTPException(status_code=400, detail="Cannot block yourself.")

    target_user = db.query(User).filter(User.uuid == request.target_uuid).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found.")

    existing_block = db.query(UserBlock).filter(
        UserBlock.blocker_uuid == current_user_uuid,
        UserBlock.blocked_uuid == request.target_uuid,
    ).first()
    if not existing_block:
        db.add(UserBlock(blocker_uuid=current_user_uuid, blocked_uuid=request.target_uuid))

    friendships = db.query(Friendship).filter(
        ((Friendship.user_uuid_1 == current_user_uuid) & (Friendship.user_uuid_2 == request.target_uuid)) |
        ((Friendship.user_uuid_1 == request.target_uuid) & (Friendship.user_uuid_2 == current_user_uuid))
    ).all()

    # Update Block information
    for f in friendships:
        f.status = "BLOCKED"
        f.blocked_by = current_user_uuid

    db.query(FriendRequest).filter(
        ((FriendRequest.sender_uuid == current_user_uuid) & (FriendRequest.receiver_uuid == request.target_uuid))
        | ((FriendRequest.sender_uuid == request.target_uuid) & (FriendRequest.receiver_uuid == current_user_uuid))
    ).delete(synchronize_session=False)

    return StandardResponse(message="Blocked User")

@router.get("/friends/{contact_uuid}/keys", response_model=ContactKeysResponse)
def get_contact_keys(
    contact_uuid: str,
    db = Depends(get_db),
    current_user_uuid: str = Depends(get_current_user)
):
    """Fetch public keys of a contact"""
    # 1. Verify if they are friends
    friendship = db.query(Friendship).filter(
        (Friendship.user_uuid_1 == current_user_uuid) & 
        (Friendship.user_uuid_2 == contact_uuid) &
        (Friendship.status == "FRIEND")
    ).first()

    if not friendship:
        raise HTTPException(status_code=403, detail="You are not friends with this user or they blocked you.")
    
    # 2. Fetch active devices and their keys
    devices = db.query(Device).filter(Device.user_uuid == contact_uuid).all()
    
    # Client uses login "device_hash" as local_device_id, so expose hash as routing id.
    device_infos = [
        DeviceKeyInfo(device_id=d.device_hash, device_public_key=d.device_public_key)
        for d in devices
    ]
    
    return ContactKeysResponse(
        contact_uuid=contact_uuid,
        active_devices=device_infos
    )

# Revoke friend request
@router.delete("/friends/request/{request_id}", response_model=StandardResponse)
def cancel_friend_request(
    request_id: str,
    db = Depends(get_db),
    current_user_uuid: str = Depends(get_current_user)
):
    """Cancle friend request sent"""
    
    # Find pending friend request of request id
    req = db.query(FriendRequest).filter(
        FriendRequest.request_id == request_id,
        FriendRequest.sender_uuid == current_user_uuid,
        FriendRequest.status == "PENDING"
    ).first()

    if not req:
        raise HTTPException(status_code=404, detail="Error, request not found.")

    db.delete(req)

    return StandardResponse(message="Friend request revoked.")


@router.delete("/friends/{friend_uuid}", response_model=StandardResponse)
def remove_friend(
    friend_uuid: str,
    db=Depends(get_db),
    current_user_uuid: str = Depends(get_current_user),
):
    links = db.query(Friendship).filter(
        ((Friendship.user_uuid_1 == current_user_uuid) & (Friendship.user_uuid_2 == friend_uuid))
        | ((Friendship.user_uuid_1 == friend_uuid) & (Friendship.user_uuid_2 == current_user_uuid))
    ).all()
    if not links:
        raise HTTPException(status_code=404, detail="Friend relation not found.")

    for link in links:
        db.delete(link)
    return StandardResponse(message="Friend removed.")
