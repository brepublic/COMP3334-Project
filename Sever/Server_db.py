import uuid
from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone

Base = declarative_base()

def generate_uuid():
    return str(uuid.uuid4())

#----------------------------------------User-----------------------------------------------
class User(Base):
    
    __tablename__ = 'users'

    uuid = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, nullable=False)
    user_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)

    # Set foreign Keys
    devices = relationship("Device", back_populates="user", cascade="all, delete-orphan")
    
    sent_requests = relationship("FriendRequest", foreign_keys="[FriendRequest.sender_uuid]", back_populates="sender")
    received_requests = relationship("FriendRequest", foreign_keys="[FriendRequest.receiver_uuid]", back_populates="receiver")
    
    sent_offline_messages = relationship("OfflineMessage", foreign_keys="[OfflineMessage.sender_uuid]", back_populates="sender")
    received_offline_messages = relationship("OfflineMessage", foreign_keys="[OfflineMessage.receiver_uuid]", back_populates="receiver")


#----------------------------------------Device----------------------------------
class Device(Base):
    __tablename__ = 'devices'

    device_id = Column(String, primary_key=True, default=generate_uuid)
    user_uuid = Column(String, ForeignKey('users.uuid'), nullable=False)
    device_hash = Column(String, nullable=False)
    device_public_key = Column(String, nullable=False)

    user = relationship("User", back_populates="devices")


#--------------------------------------Friend-------------------------------------
class Friendship(Base):
    __tablename__ = 'friendships'

    relation_id = Column(String, primary_key=True, default=generate_uuid)
    user_uuid_1 = Column(String, ForeignKey('users.uuid'), nullable=False)
    user_uuid_2 = Column(String, ForeignKey('users.uuid'), nullable=False)
    status = Column(String, nullable=False) 
    blocked_by = Column(String, nullable=True) #only store the initiator's UUID, or BOTH
    __table_args__ = (UniqueConstraint('user_uuid_1', 'user_uuid_2', name='_user1_user2_uc'),)

#------------------------------------Friend Request---------------------------------
class FriendRequest(Base):
    __tablename__ = 'friend_requests'

    request_id = Column(String, primary_key=True, default=generate_uuid)
    sender_uuid = Column(String, ForeignKey('users.uuid'), nullable=False)
    receiver_uuid = Column(String, ForeignKey('users.uuid'), nullable=False)
    status = Column(String, nullable=False) 
    # Make friend Request auto-expire after 3 days.
    # expire_duration = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


    sender = relationship("User", foreign_keys=[sender_uuid], back_populates="sent_requests")
    receiver = relationship("User", foreign_keys=[receiver_uuid], back_populates="received_requests")

#——-----------------------------------------Offline Message-----------------------------
class OfflineMessage(Base):
    __tablename__ = 'offline_messages'

    message_id = Column(String, primary_key=True, default=generate_uuid)
    sender_uuid = Column(String, ForeignKey('users.uuid'), nullable=False)
    receiver_uuid = Column(String, ForeignKey('users.uuid'), nullable=False)
    ciphertext = Column(String, nullable=False) 
    expire_duration = Column(Integer, nullable=False) 

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    sender = relationship("User", foreign_keys=[sender_uuid], back_populates="sent_offline_messages")
    receiver = relationship("User", foreign_keys=[receiver_uuid], back_populates="received_offline_messages")