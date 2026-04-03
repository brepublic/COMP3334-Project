# limiter.py
from slowapi import Limiter
from slowapi.util import get_remote_address

# Initialize global limiter, limit and track connection based on remote address
limiter = Limiter(key_func=get_remote_address)