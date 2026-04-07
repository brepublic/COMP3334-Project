from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt.exceptions import InvalidTokenError
from datetime import datetime, timezone
from hashlib import sha256

# Import customer modules
from config import settings
from SdbManager import ServerDBManager
from Server_db import RevokedToken, User


db_manager = ServerDBManager()

def get_db():
    """Get a database session for read and write"""
    with db_manager.get_session() as session:
        yield session


# I really understand this bearer function eiter. It seems like it this requirement is not satisfied, request will todo tokenUrl to request for a token.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/login")

def _ensure_utc(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return None


def authenticate_token(token: str, db):
    """Validate JWT expiry/signature + server-side revocation state."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid Token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(
            token, 
            settings.JWT_SECRET_KEY, 
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        user_uuid: str = payload.get("sub")
        token_jti: str = payload.get("jti")
        token_iat = _ensure_utc(payload.get("iat"))
        
        if user_uuid is None or token_jti is None or token_iat is None:
            raise credentials_exception

    except InvalidTokenError:
        raise credentials_exception

    user = db.query(User).filter(User.uuid == user_uuid).first()
    if not user:
        raise credentials_exception

    revoked = db.query(RevokedToken).filter(RevokedToken.token_jti == token_jti).first()
    if revoked:
        raise credentials_exception

    cutoff = _ensure_utc(user.token_invalid_before)
    if cutoff and token_iat <= cutoff:
        raise credentials_exception

    token_hash = sha256(token.encode("utf-8")).hexdigest()
    revoked_by_hash = db.query(RevokedToken).filter(RevokedToken.token_hash == token_hash).first()
    if revoked_by_hash:
        raise credentials_exception

    return user_uuid


def get_current_user(token: str = Depends(oauth2_scheme), db=Depends(get_db)):
    """Validates the token in HTTP request and returns corresponding user."""
    return authenticate_token(token, db)