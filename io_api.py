
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import time
from io_ai_core import IoAICore

app = FastAPI(title="Io AI API", description="API for Io v2 Sacred Intelligence")

# Initialize the core
io_core = IoAICore()

class GenerateRequest(BaseModel):
    prompt: str
    max_tokens: Optional[int] = 50
    temperature: Optional[float] = 0.8

class GenerateResponse(BaseModel):
    text: str
    generation_time: float
    model: str

@app.get("/status")
async def get_status():
    return io_core.get_status()

@app.post("/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest):
    start_time = time.time()
    try:
        generated_text = io_core.generate(
            prompt=request.prompt,
            max_tokens=request.max_tokens,
            temperature=request.temperature
        )
        end_time = time.time()

        return GenerateResponse(
            text=generated_text,
            generation_time=end_time - start_time,
            model="Io v2 Sacred"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
