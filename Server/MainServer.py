import logging
import ssl
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from limitor import limiter
# Import FastAPI functions form routers
from routers import Register, Login, Contacts, Message, ChatWS
from task import periodic_cleanup_task
from config import settings


logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.WARNING))
logger = logging.getLogger(__name__)


def require_tls_configuration(*, allow_insecure_override: bool | None = None) -> tuple[str | None, str | None]:
    ssl_certfile = settings.TLS_CERT_FILE
    ssl_keyfile = settings.TLS_KEY_FILE

    if bool(ssl_certfile) != bool(ssl_keyfile):
        raise RuntimeError("TLS_CERT_FILE and TLS_KEY_FILE must either both be set or both be unset.")

    if ssl_certfile and ssl_keyfile:
        if not ssl_certfile.is_file():
            raise RuntimeError(f"TLS certificate file does not exist: {ssl_certfile}")
        if not ssl_keyfile.is_file():
            raise RuntimeError(f"TLS key file does not exist: {ssl_keyfile}")
        return str(ssl_certfile), str(ssl_keyfile)

    if allow_insecure_override is None:
        allow_insecure_override = settings.ALLOW_INSECURE_TEST_MODE
    if allow_insecure_override:
        return None, None

    raise RuntimeError(
        "TLS_CERT_FILE and TLS_KEY_FILE must be set to start the server. "
        "Tests may opt in via ALLOW_INSECURE_TEST_MODE=true."
    )


# Initialize offline message cleaning
@asynccontextmanager
async def cleanUp(app: FastAPI):
    require_tls_configuration()
    logger.info("Starting expired message cleaner.")
    # Add cleaning offline message to background task loop
    task = asyncio.create_task(periodic_cleanup_task())
    # return control to FastAPI
    yield 
    task.cancel()
    logger.info("Expired message cleaner stopped.")

# initialize main program
# This defines the FastAPI setting, as well as the automatically generated file
app = FastAPI(
    title="E2EE Chat Server API", 
    version="1.0.0",
    description="API for Secure Instant Messaging with End-to-End Encryption",
    lifespan=cleanUp
)

# initialize connection limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows connection from any source 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Integrate FastAPI functions 
app.include_router(Register.router, prefix="/api/v1")
app.include_router(Login.router, prefix="/api/v1")
app.include_router(Contacts.router, prefix="/api/v1")
app.include_router(Message.router, prefix="/api/v1")
app.include_router(ChatWS.router)

# Crash checker
@app.get("/", tags=["Health Check"])
def main():
    return {
        "status": "Server is running smoothly!",
        "version": "1.0.0",
        "docs_url": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    ssl_certfile, ssl_keyfile = require_tls_configuration()

    uvicorn.run(
        "MainServer:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=settings.SERVER_RELOAD,
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
        ssl_version=ssl.PROTOCOL_TLS_SERVER if ssl_certfile and ssl_keyfile else None,
    )
