from uuid import uuid4

from fastapi import FastAPI, HTTPException
from app.desktop_sessions import recover_sessions
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="PHANTOM VPN API",
    description="Private VPN management platform",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Development only
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ServerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    location: str = Field(min_length=2, max_length=100)
    endpoint: str = Field(min_length=3, max_length=255)


servers = []
devices = []


@app.get("/")
def root():
    return {
        "name": "PHANTOM VPN",
        "status": "online",
        "message": "Backend is running",
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/api/dashboard")
def dashboard():
    return {
        "server_count": len(servers),
        "device_count": len(devices),
        "network_status": "Development mode",
        "connection_status": "Not connected",
    }


@app.get("/api/servers")
def get_servers():
    return {"servers": servers}


@app.post("/api/servers", status_code=201)
def create_server(server: ServerCreate):
    new_server = {
        "id": str(uuid4()),
        "name": server.name,
        "location": server.location,
        "endpoint": server.endpoint,
        "status": "Registered - not verified",
    }

    servers.append(new_server)
    return new_server


@app.delete("/api/servers/{server_id}")
def delete_server(server_id: str):
    for index, server in enumerate(servers):
        if server["id"] == server_id:
            deleted = servers.pop(index)
            return {"message": "Server removed", "server": deleted}

    raise HTTPException(status_code=404, detail="Server not found")


@app.get("/api/devices")
def get_devices():
    return {"devices": devices}

from app.auth import router as auth_router
app.include_router(auth_router)

from app.desktop_gateway import router as desktop_router
app.include_router(desktop_router)
app.mount("/desktop/ui", StaticFiles(directory="/usr/share/novnc", html=True), name="novnc")

from app.access_management import router as access_router
app.include_router(access_router)

@app.on_event("startup")
async def restore_desktop_sessions():
    await recover_sessions()

