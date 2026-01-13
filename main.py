"""Entry point for the application - imports from app.main"""
import os
import app.main as app_main

# Expose ASGI app at module level (used by `uvicorn main:app`)
app = app_main.app

if __name__ == "__main__":
    import uvicorn
    reload = os.getenv("UVICORN_RELOAD", "true").lower() in ("1", "true", "yes", "y", "on")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=reload)
