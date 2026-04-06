# routers/Login.py

import pyotp
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends, Request
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from limitor import limiter

# self defined modules
from Schema import LoginRequest, LoginResponse
from Server_db import User, Device
from Dependency import get_db

router = APIRouter(tags=["Login"])

ph = PasswordHasher()

# # Jwt setting.. maybe I should create a .env file?
# SECRET_KEY = "90e72a5fa897b18cda428b2939c3c3a0068ca04ab283936846317f146b3c5dbe"
# ALGORITHM = "HS256"
# ACCESS_TOKEN_EXPIRE_DAYS = 7 

from config import settings


def create_access_token(data: dict, expires_delta: timedelta):
    # create a dictionary of encoding data
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    # add expiration date to data
    to_encode.update({"exp": expire})
    
    # Sign it with server secrete key
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
def login_user(request: Request, payload: LoginRequest, db=Depends(get_db)):
    """User login -> validate password -> validate OTP -> Sign device -> Sign JWT"""
    
    # find user first
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Email or password is wrong.")

    # validate password
    try:
        ph.verify(user.password_hash, payload.password)
    except VerifyMismatchError:
        raise HTTPException(status_code=401, detail="Email or password is wrong")

    # Validate OTP
    totp = pyotp.TOTP(user.otp_secret)
    if not totp.verify(payload.otp_code):
        raise HTTPException(status_code=401, detail="Incorret OTP or time out")

    
    # Delete the previous devices. Supports only single device login.
    db.query(Device).filter(Device.user_uuid == user.uuid).delete()
    # Create the entry for the new device.
    new_device = Device(
        user_uuid=user.uuid,
        device_hash=payload.device_hash,
        device_public_key=payload.device_public_key
    )
    db.add(new_device)

    # Sign JWT
    access_token_expires = timedelta(days=settings.ACCESS_TOKEN_EXPIRE_DAYS)
    access_token = create_access_token(
        data={"sub": user.uuid}, 
        expires_delta=access_token_expires
    )

    # Return to Client
    return LoginResponse(
        message="Login Succeed!",
        user_uuid=user.uuid,
        access_token=access_token,
        token_type="bearer"
    )
