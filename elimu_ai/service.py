from fastapi import FastAPI
from pydantic import BaseModel

from elimu_ai.agent import run_agent

app = FastAPI()


class ChatRequest(BaseModel):
    message: str
    history: list = []


@app.get("/")
def root():
    return {
        "status": "running",
        "service": "Elimu AI"
    }


@app.post("/chat")
def chat(req: ChatRequest):

    answer = run_agent(
        question=req.message,
        history=req.history
    )

    return {
        "success": True,
        "answer": answer
    }
