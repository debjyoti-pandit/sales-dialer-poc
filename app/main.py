"""Main FastAPI application"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import campaign_routes, voice_routes, static_routes
from app.websocket.routes import websocket_endpoint

app = FastAPI(title="Sales Dialer POC")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(campaign_routes.router)
app.include_router(voice_routes.router)
app.include_router(static_routes.router)

# WebSocket endpoint
app.websocket("/ws/{agent_name}")(websocket_endpoint)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

