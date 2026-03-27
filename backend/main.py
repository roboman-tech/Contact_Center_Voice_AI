"""
Contact Center Voice AI - Web API
Full spec: VAD, 3-layer captions, DeepSeek, device/model selection.
"""

import asyncio
import json
import logging
import os
import queue
import shutil
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

# Ensure ffmpeg is findable
def _ensure_ffmpeg():
    if shutil.which("ffmpeg"):
        return True
    for p in [
        Path("C:/ffmpeg/bin"),
        Path("C:/Program Files/ffmpeg/bin"),
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "ffmpeg/bin",
    ]:
        if p.exists() and (p / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")).exists():
            os.environ["PATH"] = str(p.resolve()) + os.pathsep + os.environ.get("PATH", "")
            return True
    try:
        winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
        if winget.exists():
            for exe in winget.rglob("ffmpeg.exe"):
                os.environ["PATH"] = str(exe.parent.resolve()) + os.pathsep + os.environ.get("PATH", "")
                return True
    except Exception:
        pass
    return False

_ensure_ffmpeg()
if not shutil.which("ffmpeg"):
    print("WARNING: ffmpeg not found. Install: winget install Gyan.FFmpeg", file=sys.stderr)

from fastapi import FastAPI, File, UploadFile, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

from deepseek_api import generate as deepseek_generate
from transcriber import transcribe_audio
from realtime_transcriber import WebRealtimeTranscriber

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Contact Center Voice AI API", version="2.0.0")

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
    dialogue: list[dict]
    question: Optional[str] = None


class GenerateResponse(BaseModel):
    answer: str
    error: Optional[str] = None


def _build_prompt(pre_given_context: str, dialogue: list[dict], question: str) -> tuple[str, str]:
    sys = (
        "You are an interview answering assistant. Use the pre-given context and "
        "dialogue history (chat since last clear) to generate clear, relevant answers. Be concise but complete."
    )
    lines = [f"{h.get('speaker', 'Speaker')}: {h.get('text', '')}" for h in dialogue]
    dialogue_text = "\n".join(lines) if lines else "(no chat yet – history was cleared)"
    user = f"Pre-given context:\n{pre_given_context or '(none)'}\n\nChat history (since last clear):\n{dialogue_text}\n\n"
    if question:
        user += f"Latest question/request:\n{question}\n\nGenerate a helpful answer:"
    elif lines:
        user += "Provide only a brief answer or suggested response for the latest question or request in the chat."
    else:
        user += "Provide only a brief answer based on the pre-given context alone."
    return sys, user


@app.post("/api/transcribe")
async def api_transcribe(
    file: UploadFile = File(...),
    model: str = "small.en",
    device: str = "auto",
):
    suffix = Path(file.filename or "").suffix or ".webm"
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        try:
            text = transcribe_audio(tmp_path, model_size=model, device=device)
            return {"text": text, "success": True}
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    except Exception as e:
        logger.exception("Transcription failed")
        err = str(e)
        if "ffmpeg" in err.lower():
            err = "ffmpeg not found. Install: winget install Gyan.FFmpeg"
        raise HTTPException(500, err)


@app.post("/api/generate", response_model=GenerateResponse)
async def api_generate(req: GenerateRequest):
    sys_prompt, user_prompt = _build_prompt(
        req.user_context, req.dialogue, req.question or "",
    )
    try:
        answer = deepseek_generate(user_prompt, system_prompt=sys_prompt, timeout=60)
        return GenerateResponse(answer=answer or "", error=None if answer else "No response from DeepSeek.")
    except Exception as e:
        return GenerateResponse(answer="", error=str(e))


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.websocket("/ws/live")
async def websocket_live(ws: WebSocket):
    """Full spec: PCM audio, VAD, 3-layer captions, clear, device_model_change."""
    await ws.accept()
    logger.info("WebSocket /ws/live connected")
    model = "small.en"
    device = "auto"
    transcriber = None
    transcript_queue: queue.Queue = queue.Queue()
    run_sender = True

    acc_current = []
    acc_temp = [""]

    def on_caption(text: str, caption_type: str):
        transcript_queue.put((caption_type, text or ""))

    async def sender_loop():
        while run_sender:
            await asyncio.sleep(0.02)
            while True:
                try:
                    caption_type, text = transcript_queue.get_nowait()
                    if caption_type == "final":
                        await ws.send_json({
                            "event": "final_caption",
                            "final": text,
                            "speaker": "You",
                        })
                        acc_current.clear()
                        acc_temp[0] = ""
                    elif caption_type == "clear_segment":
                        acc_current.clear()
                        acc_temp[0] = ""
                        await ws.send_json({
                            "event": "preview_caption",
                            "final": "",
                            "current": "",
                            "temp": "",
                        })
                    elif caption_type == "current_real":
                        if text:
                            acc_current.append(text)
                        await ws.send_json({
                            "event": "preview_caption",
                            "final": "",
                            "current": " ".join(acc_current).strip(),
                            "temp": acc_temp[0],
                        })
                    elif caption_type == "temp":
                        acc_temp[0] = text
                        await ws.send_json({
                            "event": "preview_caption",
                            "final": "",
                            "current": " ".join(acc_current).strip(),
                            "temp": acc_temp[0],
                        })
                except q.Empty:
                    break
                except (WebSocketDisconnect, RuntimeError):
                    return

    sender_task = None

    try:
        try:
            cfg = await asyncio.wait_for(ws.receive(), timeout=3.0)
            if "text" in cfg:
                j = __import__("json").loads(cfg["text"])
                if j.get("event") == "init":
                    model = j.get("model", model)
                    device = j.get("device", device)
        except (asyncio.TimeoutError, Exception):
            pass

        transcriber = WebRealtimeTranscriber(on_caption, model_size=model, device=device)
        transcriber.start()
        sender_task = asyncio.create_task(sender_loop())

        while True:
            msg = await ws.receive()

            if "text" in msg:
                try:
                    j = __import__("json").loads(msg["text"])
                    ev = j.get("event")
                    if ev == "stop":
                        break
                    if ev == "clear":
                        if transcriber:
                            transcriber.reset()
                        while not transcript_queue.empty():
                            try:
                                transcript_queue.get_nowait()
                            except Exception:
                                break
                        try:
                            await ws.send_json({
                                "event": "preview_caption",
                                "final": "",
                                "current": "",
                                "temp": "",
                            })
                            await ws.send_json({"event": "clear_ack"})
                        except Exception:
                            pass
                        continue
                    if ev == "device_model_change":
                        new_model = j.get("model", model)
                        new_device = j.get("device", device)
                        if transcriber:
                            transcriber.stop()
                        model, device = new_model, new_device
                        transcriber = WebRealtimeTranscriber(on_caption, model_size=model, device=device)
                        transcriber.start()
                        continue
                    if ev == "init":
                        model = j.get("model", model)
                        device = j.get("device", device)
                        continue
                except Exception:
                    pass
                continue

            if "bytes" in msg and msg["bytes"]:
                data = msg["bytes"]
                if os.environ.get("DEBUG_LIVE", "").lower() in ("1", "true", "yes"):
                    logger.info("Live audio chunk: %d bytes", len(data))
                if len(data) < 100:
                    continue
                try:
                    transcriber.process_audio_chunk(data)
                except FileNotFoundError:
                    try:
                        await ws.send_json({
                            "event": "error",
                            "message": "ffmpeg not found. Install: winget install Gyan.FFmpeg",
                        })
                    except Exception:
                        pass
                except Exception as e:
                    logger.exception("Live transcribe error")
                    try:
                        await ws.send_json({
                            "event": "error",
                            "message": str(e),
                        })
                    except Exception:
                        pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("WebSocket error")
    finally:
        run_sender = False
        if transcriber:
            transcriber.stop()
        if sender_task:
            sender_task.cancel()
            try:
                await sender_task
            except asyncio.CancelledError:
                pass
        try:
            await ws.close()
        except Exception:
            pass


@app.get("/")
async def root():
    idx = (_dist / "index.html") if _dist.is_dir() else (_frontend / "index.html")
    if idx.is_file():
        return FileResponse(idx)
    return {"message": "Contact Center Voice AI API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
