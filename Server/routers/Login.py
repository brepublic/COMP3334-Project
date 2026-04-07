# routers/Login.py

import pyotp
import jwt
from datetime import datetime, timedelta, timezone
import uuid
from hashlib import sha256
from fastapi import APIRouter, HTTPException, Depends, Request
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from limitor import limiter

# self defined modules
from Schema import LoginRequest, LoginResponse, StandardResponse
from Server_db import User, Device, RevokedToken
from Dependency import get_db, get_current_user, oauth2_scheme

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
    issued_at = datetime.now(timezone.utc)
    expire = issued_at + expires_delta
    # add expiration date to data
    to_encode.update({"iat": issued_at, "exp": expire, "jti": str(uuid.uuid4())})
    
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


@router.post("/logout", response_model=StandardResponse)
def logout_user(
    token: str = Depends(oauth2_scheme),
    current_user_uuid: str = Depends(get_current_user),
    db=Depends(get_db),
):
    """Revoke current access token immediately."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid Token")

    token_jti = payload.get("jti")
    token_exp = payload.get("exp")
    if not token_jti or not token_exp:
        raise HTTPException(status_code=401, detail="Invalid Token")

    expires_at = datetime.fromtimestamp(token_exp, tz=timezone.utc)
    token_hash = sha256(token.encode("utf-8")).hexdigest()
    exists = db.query(RevokedToken).filter(RevokedToken.token_jti == token_jti).first()
    if not exists:
        db.add(
            RevokedToken(
                user_uuid=current_user_uuid,
                token_jti=token_jti,
                token_hash=token_hash,
                expires_at=expires_at,
            )
        )
    return {"message": "Logged out. Token revoked."}


@router.post("/logout-all", response_model=StandardResponse)
def logout_all_sessions(
    current_user_uuid: str = Depends(get_current_user),
    db=Depends(get_db),
):
    """Invalidate all tokens issued before now for current user."""
    user = db.query(User).filter(User.uuid == current_user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.token_invalid_before = datetime.now(timezone.utc)
    return {"message": "All previous sessions invalidated."}
