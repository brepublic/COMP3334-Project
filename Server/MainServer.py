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


# Initialize offline message cleaning
@asynccontextmanager
async def cleanUp(app: FastAPI):
    print("Evoking expired message cleaner...")
    # Add cleaning offline message to background task loop
    task = asyncio.create_task(periodic_cleanup_task())
    # return control to FastAPI
    yield 
    task.cancel()
    print("Expired message cleaner off.")

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
    # Start the server
    uvicorn.run("MainServer:app", host="0.0.0.0", port=8000, reload=True)