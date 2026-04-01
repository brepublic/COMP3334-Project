import uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, String, Integer, ForeignKey, Boolean, DateTime
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

def generate_uuid():
    return str(uuid.uuid4())

#--------------------------Local Identity--------------------------------------------
class LocalIdentity(Base):
    __tablename__ = 'local_identity'
    
    uuid = Column(String, primary_key=True, default=generate_uuid)
    public_key = Column(String, nullable=False)
    private_key = Column(String, nullable=False)


#---------------------------Conversation---------------------------------------------
class Conversation(Base):
    __tablename__ = 'conversations'

    contact_uuid = Column(String, primary_key=True)
    contact_name = Column(String, nullable=False)
    unread_threads = Column(Integer, default=0)

    # Delete related device is the contact is deleted
    devices = relationship("ContactDevice", back_populates="conversation", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

#------------------------------Contact devices related to contact--------------------
class ContactDevice(Base):
    __tablename__ = 'contact_devices'

    contact_device_id = Column(String, primary_key=True, default=generate_uuid)
    contact_uuid = Column(String, ForeignKey('conversations.contact_uuid'), nullable=False)
    public_key = Column(String, nullable=False)
    is_verified = Column(Boolean, default=False)

    conversation = relationship("Conversation", back_populates="devices")

#--------------------------------Message--------------------------------------------
class Message(Base):
    __tablename__ = 'messages'

    message_id = Column(String, primary_key=True, default=generate_uuid)
    conversation_id = Column(String, ForeignKey('conversations.contact_uuid'), nullable=False)
    sender_id = Column(String, nullable=False)
    receiver_id = Column(String, nullable=False)
    
    content_plaintext = Column(String, nullable=False)
    
    expire_duration = Column(Integer, nullable=False)
    receive_at = Column(DateTime, default=lambda: datetime.now(timezone.utc)) 

    conversation = relationship("Conversation", back_populates="messages")
