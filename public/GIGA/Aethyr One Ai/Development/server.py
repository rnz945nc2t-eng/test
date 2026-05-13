from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
import sys
import os

# Import the Io engine
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from io_engine import IoFrankensteinEngine, perform_web_search

app = FastAPI(title="Io Frankenstein Engine API")
engine = IoFrankensteinEngine()

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "dist")

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str
    sources_count: int

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        prompt = request.message
        # 1. Fetch data from internet (REAL)
        sources = perform_web_search(prompt)

        # 2. Patch results using HST logic
        synthesis = engine.patch(prompt, sources)

        return ChatResponse(
            response=synthesis,
            sources_count=len(sources)
        )
    except Exception as e:
        print(f"[!] Error in chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "healthy", "engine": "Io v2 Sacred"}

# Serve static files from the React build
if os.path.exists(DIST_DIR):
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="static")

    @app.get("/{full_path:path}")
    async def serve_react_app(full_path: str):
        return FileResponse(os.path.join(DIST_DIR, "index.html"))
else:
    @app.get("/")
    async def root():
        return {"message": "Io Backend Online. Frontend build not detected."}

if __name__ == "__main__":
    # Ensure dependencies are available for the subprocess
    uvicorn.run(app, host="0.0.0.0", port=8000)
