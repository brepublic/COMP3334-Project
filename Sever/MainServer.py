from fastapi import FastAPI
# Import FastAPI functions form routers
from routers import Register, Login

#initialize main program
app = FastAPI(title="E2EE Chat Server API", version="1.0.0")

# Integrate FastAPI functions 
app.include_router(Register.router, prefix="/api/v1")
app.include_router(Login.router, prefix="/api/v1")

@app.get("/")
def main():
    return {"status": "Server is running smoothly!"}
