"""
Contact Center Voice AI - Web API
Based on SpeechtoText project. Provides transcription + AI-generated answers.
"""

import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from pathlib import Path

from deepseek_api import generate as deepseek_generate
from transcriber import transcribe_audio

app = FastAPI(title="Contact Center Voice AI API", version="1.0.0")

# Serve frontend: prefer React build (dist), else legacy static
_frontend = Path(__file__).parent.parent / "frontend"
_dist = _frontend / "dist"
if _dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    user_context: str = ""
    dialogue: list[dict]  # [{"speaker": str, "text": str}, ...]
    question: Optional[str] = None


class GenerateResponse(BaseModel):
    answer: str
    error: Optional[str] = None


def _build_prompt(pre_given_context: str, dialogue: list[dict], question: str) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) for DeepSeek."""
    sys = (
        "You are an interview answering assistant. Use the pre-given context (resume, job description, etc.) "
        "and the dialogue history to generate clear, relevant answers. Be concise but complete."
    )
    lines = []
    for h in dialogue:
        s = h.get("speaker") or "Speaker"
        t = h.get("text") or ""
        lines.append(f"{s}: {t}")
    dialogue_text = "\n".join(lines) if lines else "(no dialogue yet)"
    user = f"Pre-given context (resume, job description, talking points):\n{pre_given_context or '(none)'}\n\n"
    user += f"Dialogue:\n{dialogue_text}\n\n"
    if question:
        user += f"Latest question/request:\n{question}\n\nGenerate a helpful answer:"
    else:
        user += "Based on the dialogue above, provide a brief summary or suggested response."
    return sys, user


@app.post("/api/transcribe")
async def api_transcribe(
    file: UploadFile = File(...),
    model: str = "small.en",
    device: str = "auto",
):
    """
    Transcribe uploaded audio file (WAV, WebM, MP3, etc.) to text.
    """
    if not file.filename:
        raise HTTPException(400, "No file provided")
    suffix = Path(file.filename).suffix or ".webm"
    if not suffix.startswith("."):
        suffix = "." + suffix
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        try:
            text = transcribe_audio(tmp_path, model_size=model, device=device)
            return {"text": text, "success": True}
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/generate", response_model=GenerateResponse)
async def api_generate(req: GenerateRequest):
    """
    Generate AI answer from user context + dialogue history.
    """
    sys_prompt, user_prompt = _build_prompt(
        req.user_context,
        req.dialogue,
        req.question or "",
    )
    try:
        answer = deepseek_generate(user_prompt, system_prompt=sys_prompt, timeout=60)
        if not answer:
            return GenerateResponse(
                answer="",
                error="No response from DeepSeek. Check DEEPSEEK_API_KEY and network.",
            )
        return GenerateResponse(answer=answer)
    except Exception as e:
        return GenerateResponse(answer="", error=str(e))


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    """Serve frontend index.html (React build or legacy)."""
    idx = (_dist / "index.html") if _dist.is_dir() else (_frontend / "index.html")
    if idx.is_file():
        return FileResponse(idx)
    return {"message": "Contact Center Voice AI API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
