from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt.exceptions import InvalidTokenError

# Import customer modules
from config import settings
from SdbManager import ServerDBManager


db_manager = ServerDBManager()

def get_db():
    """Get a database session for read and write"""
    with db_manager.get_session() as session:
        yield session


# I really understand this bearer function eiter. It seems like it this requirement is not satisfied, request will todo tokenUrl to request for a token.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/login")

def get_current_user(token: str = Depends(oauth2_scheme)):
    """Validates the token in HTTP request and returns corresponding user"""
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
        
        if user_uuid is None:
            raise credentials_exception
            
    except InvalidTokenError:
        raise credentials_exception
        
    return user_uuid