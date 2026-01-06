"""Static file routes"""
import os
import mimetypes
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.responses import FileResponse as StarletteFileResponse

router = APIRouter(tags=["static"])


@router.get("/")
async def serve_frontend():
    """Serve the main HTML page"""
    return FileResponse("static/index.html")


@router.get("/static/{file_path:path}")
async def serve_static(file_path: str):
    """Serve static files with no-cache headers"""
    full_path = f"static/{file_path}"
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    mime_type, _ = mimetypes.guess_type(full_path)
    return StarletteFileResponse(
        full_path,
        media_type=mime_type,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

