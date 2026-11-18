from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os

app = FastAPI()
TEAM = os.environ.get("TEAM", "team28")

@app.get("/")
def root():
    return {"team": TEAM, "status": "ok"}

@app.get("/health")
def health():
    return {"team": TEAM, "status": "ok"}

@app.post("/run")
async def run(request: Request):
    return JSONResponse(status_code=501, content={"error": "not implemented yet"})