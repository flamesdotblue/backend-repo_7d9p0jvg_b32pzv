import os
import json
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import User, Guardian, Trackpoint, Incident, Areaalert

app = FastAPI(title="SafeShe API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"name": "SafeShe API", "status": "ok"}


@app.get("/health")
async def health():
    # Verify DB connection
    status = {"backend": "ok", "database": "disconnected"}
    try:
        if db is not None:
            db.list_collection_names()
            status["database"] = "ok"
    except Exception as e:
        status["database"] = f"error: {str(e)[:80]}"
    return status


@app.get("/schema")
async def get_schema():
    """Expose schema names for tooling/viewers"""
    return {
        "models": [
            {"name": "user"},
            {"name": "guardian"},
            {"name": "trackpoint"},
            {"name": "incident"},
            {"name": "areaalert"},
        ]
    }


# -------------------- Auth (mock OAuth stubs) --------------------
class MockAuthRequest(BaseModel):
    provider: str
    token: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    photo_url: Optional[str] = None


@app.get("/auth/providers")
async def auth_providers():
    return {"providers": ["google", "microsoft", "apple", "mock"]}


@app.post("/auth/mock-login")
async def mock_login(payload: MockAuthRequest):
    provider = payload.provider.lower()
    if provider not in {"google", "microsoft", "apple", "mock"}:
        raise HTTPException(status_code=400, detail="Unsupported provider")

    user_doc = User(
        name=payload.name or "SafeShe User",
        email=payload.email or f"user-{provider}@safeshe.app",
        provider=provider,
        provider_id=payload.token or "mock-token",
        photo_url=payload.photo_url,
    )
    user_id = create_document("user", user_doc)
    return {"user_id": user_id, "provider": provider}


# -------------------- Guardians --------------------
@app.post("/guardians")
async def add_guardian(guardian: Guardian):
    gid = create_document("guardian", guardian)
    return {"guardian_id": gid}


@app.get("/guardians")
async def list_guardians(user_id: str = Query(...)):
    items = get_documents("guardian", {"user_id": user_id})
    for x in items:
        x["_id"] = str(x["_id"])  # make JSON serializable
    return {"items": items}


# -------------------- Location Tracking --------------------
@app.post("/location/update")
async def location_update(point: Trackpoint):
    data = point.model_dump()
    data["server_ts"] = datetime.now(timezone.utc)
    new_id = create_document("trackpoint", data)
    # also notify live sockets (best-effort)
    await ws_broadcast(point.user_id, {"type": "track", "data": {
        **{k: v for k, v in point.model_dump().items() if v is not None},
        "_id": new_id,
        "server_ts": data["server_ts"].isoformat(),
    }})
    return {"trackpoint_id": new_id}


@app.get("/location/last")
async def location_last(user_id: str = Query(...)):
    items = get_documents("trackpoint", {"user_id": user_id}, limit=50)
    # Sort by created_at desc if present
    items.sort(key=lambda x: x.get("created_at", datetime.min), reverse=True)
    latest = items[0] if items else None
    if latest:
        latest["_id"] = str(latest["_id"])  # serialize
    return {"latest": latest}


# -------------------- Incidents --------------------
@app.post("/incidents")
async def create_incident(inc: Incident):
    iid = create_document("incident", inc)
    return {"incident_id": iid}


@app.get("/incidents")
async def list_incidents(user_id: Optional[str] = None, limit: int = 50):
    filt = {"user_id": user_id} if user_id else {}
    items = get_documents("incident", filt, limit=limit)
    for x in items:
        x["_id"] = str(x["_id"])  # serialize
    # newest first
    items.sort(key=lambda x: x.get("created_at", datetime.min), reverse=True)
    return {"items": items}


# -------------------- Area Alerts (demo) --------------------
@app.get("/alerts/nearby")
async def nearby_alerts(lat: float = Query(...), lng: float = Query(...)):
    # For demo, return a couple of sample alerts around the given point
    sample = [
        {
            "title": "Well-lit route",
            "message": "Preferred street with active shops",
            "lat": lat + 0.001,
            "lng": lng + 0.001,
            "radius_m": 150,
            "level": "info",
        },
        {
            "title": "Avoid underpass at night",
            "message": "Reports of harassment after 9pm",
            "lat": lat - 0.0015,
            "lng": lng - 0.0008,
            "radius_m": 200,
            "level": "caution",
        },
    ]
    return {"items": sample}


# -------------------- WebSocket live tracking --------------------
class ConnectionManager:
    def __init__(self):
        self.active: dict[str, list[WebSocket]] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active.setdefault(user_id, []).append(websocket)

    def disconnect(self, user_id: str, websocket: WebSocket):
        conns = self.active.get(user_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns and user_id in self.active:
            self.active.pop(user_id, None)

    async def broadcast(self, user_id: str, message: dict):
        conns = self.active.get(user_id, [])
        stale = []
        for ws in conns:
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(user_id, ws)


manager = ConnectionManager()


async def ws_broadcast(user_id: str, message: dict):
    await manager.broadcast(user_id, message)


@app.websocket("/ws/track/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await manager.connect(user_id, websocket)
    try:
        # On connect, send last known point if any
        try:
            items = get_documents("trackpoint", {"user_id": user_id}, limit=1)
            items.sort(key=lambda x: x.get("created_at", datetime.min), reverse=True)
            if items:
                latest = items[0]
                latest["_id"] = str(latest["_id"])  # serialize
                await websocket.send_text(json.dumps({"type": "last", "data": latest}, default=str))
        except Exception:
            pass

        while True:
            # Clients may ping or send messages to keep alive
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
