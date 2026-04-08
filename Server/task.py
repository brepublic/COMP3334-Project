# tasks.py

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from SdbManager import ServerDBManager
from Server_db import OfflineMessage

db_manager = ServerDBManager()
logger = logging.getLogger(__name__)

def cleanup_expired_messages():
    """
    Delete Offline message that expires
    """
    with db_manager.get_session() as db:
        now = datetime.now(timezone.utc)
        # Get all offline messages
        all_messages = db.query(OfflineMessage).all()
        
        expired_ids = []
        for msg in all_messages:
            # Calculate expiration date
            expiration_time = msg.created_at + timedelta(seconds=msg.expire_duration)
            if now > expiration_time:
                expired_ids.append(msg.message_id)
        
        # Delete all expired messages
        if expired_ids:
            deleted_count = db.query(OfflineMessage).filter(
                OfflineMessage.message_id.in_(expired_ids)
            ).delete(synchronize_session=False)
            logger.info("Deleted %s expired offline messages.", deleted_count)


async def periodic_cleanup_task():
    """
    Async function that carries out execution every once a while
    """
    # Execution hiatus
    sleep_time = 3600 
    
    while True:
        await asyncio.sleep(sleep_time)
        
        # Get current main loop
        loop = asyncio.get_running_loop()
        # throw it in another thread to execute
        await loop.run_in_executor(None, cleanup_expired_messages)
