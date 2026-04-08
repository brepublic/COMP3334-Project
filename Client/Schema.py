from pydantic import BaseModel, EmailStr, Field
from typing import List, Literal, Optional
from datetime import datetime

#-----------------------------------Authentication Module------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    user_name: str = Field(..., min_length=2, max_length=30)
    password: str = Field(..., min_length=8)

class RegisterResponse(BaseModel):
    message: str
    user_uuid: str
    otp_secret: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    otp_code: str = Field(..., min_length=6, max_length=6) 
    device_hash: str = Field(..., min_length=8, max_length=128)
    device_public_key: str = Field(..., min_length=32, max_length=512)

class LoginResponse(BaseModel):
    message: str
    user_uuid: str
    user_name: str
    access_token: str
    token_type: str = "bearer"


#-------------------------------------Key Management Module-----------------------------------
class DeviceKeyInfo(BaseModel):
    device_id: str
    device_public_key: str

class ContactKeysResponse(BaseModel):
    contact_uuid: str
    active_devices: List[DeviceKeyInfo]


#-------------------------------------Contact Module-----------------------------------------
class FriendRequestPayload(BaseModel):
    target_email: EmailStr

class FriendRequestAction(BaseModel):
    request_id: str
    # Force the response to be one of the two string
    action: Literal["ACCEPT", "REJECT"] 

class PendingRequestInfo(BaseModel):
    request_id: str
    direction: Literal["incoming", "outgoing"]
    counterparty_uuid: str
    counterparty_name: str
    email: Optional[EmailStr] = None

class FriendInfo(BaseModel):
    uuid: str
    user_name: str
    email: Optional[EmailStr] = None
    status: Literal["FRIEND", "BLOCKED"] 
    blocked_by: Optional[str] = None

class FriendListResponse(BaseModel):
    friends: List[FriendInfo]

class BlockUserRequest(BaseModel):
    target_uuid: str


#-------------------------------Offline Message and Self Destroy Module-------------------------

class SendMessageRequest(BaseModel):
    receiver_uuid: str
    ciphertext: str = Field(..., min_length=2, max_length=65536)
    expire_duration: int = Field(default=86400, ge=1, le=604800, description="Default TTL is 24 hours")

class SendMessageResponse(BaseModel):
    message_id: str
    status: Literal["DELIVERED", "UNRECEIVED"]


class OfflineMessageItem(BaseModel):
    message_id: str
    sender_uuid: str
    ciphertext: str
    expire_duration: int
    created_at: datetime

class OfflineMessageResponse(BaseModel):
    messages: List[OfflineMessageItem]


class AckMessagesRequest(BaseModel):
    message_ids: List[str]
    
class StandardResponse(BaseModel):
    """An universal Response type... Maybe useful"""
    message: str
