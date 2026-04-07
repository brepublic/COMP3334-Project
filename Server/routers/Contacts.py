# routers/Contacts.py

from fastapi import APIRouter, Depends, HTTPException, status
from typing import List

# Import schema and my own modules
from Schema import (
    FriendRequestPayload, StandardResponse, BlockUserRequest, 
    FriendRequestAction, PendingRequestInfo, FriendInfo, 
    FriendListResponse, ContactKeysResponse, DeviceKeyInfo
)
from Server_db import User, Friendship, FriendRequest, Device
from Dependency import get_db, get_current_user

router = APIRouter(tags=["Contacts"])

@router.post("/friends/request", response_model=StandardResponse)
def send_friend_request(
    payload: FriendRequestPayload, 
    db = Depends(get_db),
    current_user_uuid: str = Depends(get_current_user) # validates user token
):
    """Send friend request through email"""
    
    # Don't add yourself
    target_email = payload.target_email
    sender = db.query(User).filter(User.uuid == current_user_uuid).first()
    if sender.email == target_email:
        raise HTTPException(status_code=400, detail="Can't add yourself as Friend.")

    # Don't add nobody
    target_user = db.query(User).filter(User.email == target_email).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Doesn't not found user.")

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

    return StandardResponse(message=f"Successfully send friend request to {target_user.user_name}!")


# Accept Friend request
@router.get("/friends/pending", response_model=List[PendingRequestInfo])
def get_pending_requests(
    db = Depends(get_db),
    current_user_uuid: str = Depends(get_current_user)
):
    """Get Pending friend request"""
    
    # Get the friend list of request
    requests = db.query(FriendRequest).filter(
        FriendRequest.receiver_uuid == current_user_uuid,
        FriendRequest.status == "PENDING"
    ).all()

    response_list = []
    for req in requests:
        # Grab user name of the friend list
        sender = db.query(User).filter(User.uuid == req.sender_uuid).first()
        response_list.append(
            PendingRequestInfo(
                request_id=req.request_id,
                sender_uuid=req.sender_uuid,
                sender_name=sender.user_name if sender else "Unkown"
            )
        )
    return response_list


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
    
    friendships = db.query(Friendship).filter(
        ((Friendship.user_uuid_1 == current_user_uuid) & (Friendship.user_uuid_2 == request.target_uuid)) |
        ((Friendship.user_uuid_1 == request.target_uuid) & (Friendship.user_uuid_2 == current_user_uuid))
    ).all()

    if not friendships:
        raise HTTPException(status_code=404, detail="You are not friend, cannot block")

    # Update Block information
    for f in friendships:
        f.status = "BLOCKED"
        f.blocked_by = current_user_uuid

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
    
    device_infos = [
        DeviceKeyInfo(device_id=d.device_id, device_public_key=d.device_public_key)
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