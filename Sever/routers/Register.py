# routers/Register

import pyotp
from fastapi import HTTPException, Depends, APIRouter, Request
from argon2 import PasswordHasher
from limitor import limiter

from Schema import RegisterRequest, RegisterResponse
from Server_db import User
from Dependency import get_db


#Init FastAPI Router for future integration
router = APIRouter(tags=["Register"])
ph = PasswordHasher() # 

@router.post("/register", response_model=RegisterResponse)
@limiter.limit("3/day")
def register_user(request: RegisterRequest, db=Depends(get_db)):
    """New user register -> hash pw -> generate OTP -> store in db"""
    existing_user = db.query(User).filter(User.email == request.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    # hash
    hashed_password = ph.hash(request.password)

    # generate OTP
    otp_secret = pyotp.random_base32()

    # Create new entry
    new_user = User(
        email=request.email,
        user_name=request.user_name,
        password_hash=hashed_password,
        otp_secret=otp_secret  
    )
    
    # Store in db
    db.add(new_user)
    db.flush()
    
    return RegisterResponse(
        message="Registered Succeed",
        user_uuid=new_user.uuid,
        otp_secret=otp_secret
    )