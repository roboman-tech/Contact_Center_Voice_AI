"""
Web-friendly transcription: accepts audio file path, returns text via Whisper.
"""

import os
from pathlib import Path

_whisper_model = None
_model_device = None


def _load_whisper(model_size: str = "small.en", device: str = "auto"):
    global _whisper_model, _model_device
    if _whisper_model is not None:
        return _whisper_model

    import torch
    import whisper

    if device == "auto":
        dev = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        dev = "cuda" if device == "gpu" and torch.cuda.is_available() else "cpu"

    _whisper_model = whisper.load_model(model_size, device=dev)
    _model_device = dev
    return _whisper_model


def transcribe_audio(
    audio_path: str,
    model_size: str = "small.en",
    device: str = "auto",
    language: str = "en",
) -> str:
    """
    Transcribe audio file to text using Whisper.
    Supports WAV, WebM, MP3, etc. (Whisper uses ffmpeg internally).
    """
    if not os.path.isfile(audio_path):
        return ""

    model = _load_whisper(model_size, device)
    import torch

    with torch.inference_mode():
        result = model.transcribe(
            audio_path,
            language=language,
            task="transcribe",
            fp16=(_model_device == "cuda"),
            verbose=False,
            temperature=0.0,
            beam_size=5,
        )

    return (result.get("text") or "").strip()
