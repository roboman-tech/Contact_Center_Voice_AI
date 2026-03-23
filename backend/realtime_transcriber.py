"""
Web adaptation of SpeechtoText RealtimeTranscriber.
VAD-based segmentation: finalize on silence, not fixed time.
Three-layer captions: current_real (stable), temp (preview), final (complete sentence).
"""

from __future__ import annotations

import io
import os
import re
import shutil
import logging

_DEBUG = os.environ.get("DEBUG_LIVE", "").lower() in ("1", "true", "yes")
import queue
import threading
import numpy as np

SAMPLE_RATE_WHISPER = 16000
CHUNK_MS = 30
# VAD: absolute RMS (int16/32768). Silence ~0.001, speech ~0.02-0.1. 82/82=noise passed as speech.
VAD_ENERGY_THRESHOLD = 0.012
MIN_RMS_FOR_WHISPER = 0.008
SPEECH_PADDING_MS = 700
MIN_SPEECH_MS = 200
MAX_SPEECH_MS = 12000
PREVIEW_INTERVAL_MS = 300
PREVIEW_WINDOW_MS = 2800
MAX_IDLE_BUFFER_MS = 4000


def _norm(w: str) -> str:
    return w.lower().rstrip(".,?!;:\"'")


def _stable_prefix_len(prev_words: list[str], curr_words: list[str]) -> int:
    n = 0
    for i in range(min(len(prev_words), len(curr_words))):
        if _norm(prev_words[i]) != _norm(curr_words[i]):
            break
        n += 1
    return n


def _strip_overlap(committed: list[str], new: list[str]) -> list[str]:
    for k in range(min(len(committed), len(new)), 0, -1):
        if all(_norm(c) == _norm(n) for c, n in zip(committed[-k:], new[:k])):
            return new[k:]
    return new


def _remove_growing_prefixes(text: str) -> str:
    parts = re.split(r'[.?!]\s+', text)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) < 2:
        return text
    result = []
    for p in parts:
        p_norm = _norm(p)
        while result and p_norm and _norm(result[-1]) and p_norm.startswith(_norm(result[-1])) and p_norm != _norm(result[-1]):
            result.pop()
        result.append(p)
    return ". ".join(result) if result else text


def _deduplicate_words(text: str) -> str:
    words = text.split()
    if len(words) < 2:
        return text
    out = [words[0]]
    for w in words[1:]:
        if _norm(w) != _norm(out[-1]):
            out.append(w)
    n = len(out)
    for k in range(1, n // 2 + 1):
        if out[:k] == out[k : 2 * k]:
            return " ".join(out[:k])
    for phrase_len in range(min(5, n // 2), 1, -1):
        i = 0
        while i <= len(out) - 2 * phrase_len:
            if all(_norm(out[i + j]) == _norm(out[i + phrase_len + j]) for j in range(phrase_len)):
                out = out[: i + phrase_len] + out[i + 2 * phrase_len :]
                n = len(out)
                i = max(0, i - phrase_len)
            else:
                i += 1
    return _remove_growing_prefixes(" ".join(out))


# Known Whisper hallucinations (often on silence/noise) — suppress from output
_HALLUCINATION_PHRASES = frozenset({
    "thanks for watching", "thank you for watching", "you for watching", "for watching",
    "subscribe", "please subscribe", "like and subscribe",
    "that's all", "that's all for now", "bye", "goodbye",
})


def _normalize(t: str) -> str:
    """Normalize for comparison: lowercase, collapse spaces, strip punctuation."""
    return re.sub(r"\s+", " ", t.strip().lower().rstrip(".!?"))


def _is_repetitive_hallucination(text: str) -> bool:
    """Detect Whisper repetitive hallucinations: SSS..., Mmm..., etc."""
    t = text.strip()
    if len(t) < 5:
        return False
    if re.search(r"(.)\1{4,}", t):
        return True
    stripped = re.sub(r"\s+", "", t)
    if len(stripped) >= 5 and len(set(stripped.lower())) <= 1:
        return True
    return False


def _is_hallucination(text: str) -> bool:
    """True if text is entirely a hallucination phrase or repetitive junk."""
    t = _normalize(text)
    if not t:
        return True
    if _is_repetitive_hallucination(text):
        return True
    if t in _HALLUCINATION_PHRASES:
        return True
    for phrase in _HALLUCINATION_PHRASES:
        if t == phrase:
            return True
    return False


def _strip_hallucination(text: str) -> str:
    """Remove hallucination phrases and repetitive junk from end; return empty if entirely hallucination."""
    t = text.strip()
    if not t:
        return ""
    if _is_hallucination(t):
        return ""
    t = re.sub(r"(.)\1{3,}\s*$", "", t).strip()
    if not t or _is_hallucination(t):
        return ""
    norm = _normalize(t)
    for phrase in sorted(_HALLUCINATION_PHRASES, key=len, reverse=True):
        if norm == phrase or norm.endswith(" " + phrase):
            pattern = re.compile(re.escape(phrase) + r"[.!?\s,]*$", re.IGNORECASE)
            out = pattern.sub("", t).rstrip(" .,!?")
            return "" if _is_hallucination(out) or not out else out
    return t


def _rms_normalized(audio: np.ndarray) -> float:
    """RMS on normalized float [-1,1] scale."""
    if len(audio) < 2:
        return 0.0
    f = audio.astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(f * f)))


_vad_log_ct = [0]


def _is_speech_energy(audio: np.ndarray, threshold: float = VAD_ENERGY_THRESHOLD) -> bool:
    """VAD: use absolute RMS (int16->float/32768). Peak-norm wrongly treats noise as speech."""
    if len(audio) < 2:
        return False
    f = audio.astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(f * f)))
    is_speech = rms > threshold
    if _DEBUG:
        _vad_log_ct[0] += 1
        if _vad_log_ct[0] % 50 == 1:
            logging.info("VAD RMS=%.4f speech=%s", rms, is_speech)
    return is_speech


def _float32_to_int16(audio_float: np.ndarray) -> np.ndarray:
    """Convert float32 [-1,1] to int16 for VAD compatibility."""
    return (np.clip(audio_float, -1.0, 1.0) * 32767).astype(np.int16)


def _pcm_float32_from_bytes(data: bytes) -> np.ndarray | None:
    """Parse raw Float32 PCM bytes to numpy int16 (for VAD)."""
    if len(data) < 100:
        return None
    try:
        arr = np.frombuffer(data, dtype=np.float32)
        return _float32_to_int16(arr)
    except Exception:
        return None


def _webm_to_pcm(webm_bytes: bytes) -> np.ndarray | None:
    """Decode WebM/Matroska bytes (audio or video) to 16kHz mono int16 PCM.
    Uses ffmpeg with explicit -ar 16000 -ac 1 for reliable Opus 48kHz->16kHz conversion."""
    import subprocess
    import tempfile
    try:
        ff = shutil.which("ffmpeg")
        if ff:
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
                f.write(webm_bytes)
                tmp = f.name
            try:
                out = subprocess.run(
                    [
                        ff, "-y", "-i", tmp,
                        "-vn", "-ar", str(SAMPLE_RATE_WHISPER), "-ac", "1",
                        "-f", "s16le", "-"
                    ],
                    capture_output=True,
                    timeout=5,
                )
                if out.returncode == 0 and len(out.stdout) >= 2:
                    samples = np.frombuffer(out.stdout, dtype=np.int16)
                    if _DEBUG and len(samples) > 0:
                        rms = _rms_normalized(samples)
                        logging.info(
                            "WebM(ffmpeg): %d bytes -> %d samples (%.2fs), RMS=%.4f",
                            len(webm_bytes), len(samples), len(samples) / SAMPLE_RATE_WHISPER, rms,
                        )
                    return samples
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
    except Exception as e:
        if _DEBUG:
            logging.warning("ffmpeg WebM decode failed: %s", e)
    try:
        from pydub import AudioSegment
        buf = io.BytesIO(webm_bytes)
        try:
            seg = AudioSegment.from_file(buf, format="webm")
        except Exception:
            buf.seek(0)
            seg = AudioSegment.from_file(buf, format="matroska")
        seg = seg.set_frame_rate(SAMPLE_RATE_WHISPER).set_channels(1)
        samples = np.array(seg.get_array_of_samples(), dtype=np.int16)
        if _DEBUG and len(samples) > 0:
            rms = _rms_normalized(samples)
            logging.info("WebM(pydub): %d bytes -> %d samples, RMS=%.4f", len(webm_bytes), len(samples), rms)
        return samples
    except Exception as e:
        if _DEBUG:
            logging.warning("WebM decode failed: %s (len=%d)", e, len(webm_bytes))
        return None


def _run_whisper(audio: np.ndarray, model, sr: int = SAMPLE_RATE_WHISPER) -> str:
    import contextlib
    import io
    import torch
    audio_float = audio.astype(np.float32) / 32768.0
    peak = float(np.max(np.abs(audio_float)))
    if 0 < peak < 0.02:
        gain = min(5.0, 0.1 / peak)
        audio_float = audio_float * gain
    use_fp16 = next(model.parameters()).device.type == "cuda"
    opts = dict(
        language="en",
        task="transcribe",
        fp16=use_fp16,
        verbose=None,
        temperature=0.0,
        beam_size=5,
    )
    with contextlib.redirect_stdout(io.StringIO()), torch.inference_mode():
        try:
            result = model.transcribe(
                audio_float,
                no_speech_threshold=0.3,
                condition_on_previous_text=False,
                **opts,
            )
        except TypeError:
            result = model.transcribe(audio_float, **opts)
    return (result.get("text") or "").strip()


class WebRealtimeTranscriber:
    """
    VAD + stable-word transcription for web audio.
    Callback receives: (text, caption_type) where caption_type in
    ("current_real", "temp", "final", "clear_segment").
    """

    def __init__(self, text_callback, model_size: str = "small.en", device: str = "auto"):
        self.text_callback = text_callback
        self.model_size = model_size
        self._device_pref = (device or "auto").lower()
        self._model = None
        self._work_queue: queue.Queue = queue.Queue(maxsize=64)
        self._prev_partial = ""
        self._committed_real_words: list[str] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._transcribe_thread = None
        self._buffer: list[np.ndarray] = []
        self._buffer_duration_ms = 0
        self._speech_started = False
        self._padding_counter = 0
        self._chunks_since_preview = 0
        self._last_final_text = ""

    def reset(self):
        """Reset segment state (for clear)."""
        with self._lock:
            self._prev_partial = ""
            self._committed_real_words = []
        self._buffer.clear()
        self._buffer_duration_ms = 0
        self._speech_started = False
        self._padding_counter = 0
        self._chunks_since_preview = 0

    def _load_model(self):
        import torch
        import whisper
        cuda_avail = torch.cuda.is_available()
        if self._device_pref in ("cuda", "gpu") and cuda_avail:
            self._device = "cuda"
        elif self._device_pref in ("cuda", "gpu"):
            self._device = "cpu"
        else:
            self._device = "cuda" if cuda_avail else "cpu"
        self._model = whisper.load_model(self.model_size, device=self._device)

    def process_audio_pcm(self, pcm_bytes: bytes) -> bool:
        """Process raw Float32 PCM bytes (16kHz mono). Run VAD, enqueue segments."""
        pcm = _pcm_float32_from_bytes(pcm_bytes)
        return self._process_pcm_array(pcm) if pcm is not None else True

    def process_audio_chunk(self, webm_bytes: bytes) -> bool:
        """Decode WebM, run VAD, enqueue segments. Maintains state across chunks."""
        pcm = _webm_to_pcm(webm_bytes)
        if pcm is None:
            logging.warning("WebM decode failed, %d bytes", len(webm_bytes))
            return True
        if _DEBUG:
            rms = _rms_normalized(pcm)
            logging.info("WebM decoded: %d bytes -> %d samples, RMS=%.4f", len(webm_bytes), len(pcm), rms)
        return self._process_pcm_array(pcm)

    def _process_pcm_array(self, pcm: np.ndarray) -> bool:
        if pcm is None or len(pcm) < SAMPLE_RATE_WHISPER * 0.1:
            return True
        speech_count = 0

        num_samples_per_chunk = int(SAMPLE_RATE_WHISPER * CHUNK_MS / 1000)
        padding_chunks = int(SPEECH_PADDING_MS / CHUNK_MS)
        min_speech_chunks = int(MIN_SPEECH_MS / CHUNK_MS)
        max_speech_chunks = int(MAX_SPEECH_MS / CHUNK_MS)
        preview_interval_chunks = max(1, int(PREVIEW_INTERVAL_MS / CHUNK_MS))

        buffer = self._buffer
        buffer_duration_ms = self._buffer_duration_ms
        speech_started = self._speech_started
        padding_counter = self._padding_counter
        chunks_since_preview = self._chunks_since_preview

        offset = 0
        while offset + num_samples_per_chunk <= len(pcm):
            chunk = pcm[offset : offset + num_samples_per_chunk]
            offset += num_samples_per_chunk

            is_speech = _is_speech_energy(chunk)
            if is_speech:
                speech_count += 1

            if is_speech:
                buffer.append(chunk.copy())
                buffer_duration_ms += CHUNK_MS
                speech_started = True
                padding_counter = 0
                chunks_since_preview += 1

                if chunks_since_preview >= preview_interval_chunks and len(buffer) >= min_speech_chunks:
                    audio = np.concatenate(buffer)
                    if len(audio) >= SAMPLE_RATE_WHISPER * 0.2:
                        n = int(PREVIEW_WINDOW_MS / 1000 * SAMPLE_RATE_WHISPER)
                        if len(audio) > n:
                            audio = audio[-n:]
                        try:
                            self._work_queue.put_nowait((audio.copy(), False))
                            if _DEBUG:
                                logging.info("Queue preview qsize=%d", self._work_queue.qsize())
                        except queue.Full:
                            pass
                    chunks_since_preview = 0

                if buffer_duration_ms >= MAX_SPEECH_MS:
                    audio = np.concatenate(buffer)
                    try:
                        self._work_queue.put_nowait((audio.copy(), True))
                        if _DEBUG:
                            logging.info("Queue final (max) qsize=%d", self._work_queue.qsize())
                    except queue.Full:
                        pass
                    buffer.clear()
                    buffer_duration_ms = 0
                    speech_started = False
                    chunks_since_preview = 0

            elif speech_started:
                buffer.append(chunk.copy())
                buffer_duration_ms += CHUNK_MS
                padding_counter += 1

                if padding_counter >= padding_chunks:
                    if buffer_duration_ms >= MIN_SPEECH_MS:
                        audio = np.concatenate(buffer)
                        try:
                            self._work_queue.put_nowait((audio.copy(), True))
                            if _DEBUG:
                                logging.info("Queue final (silence) qsize=%d", self._work_queue.qsize())
                        except queue.Full:
                            pass
                    buffer.clear()
                    buffer_duration_ms = 0
                    speech_started = False
                    chunks_since_preview = 0
                elif buffer_duration_ms >= max_speech_chunks * CHUNK_MS:
                    audio = np.concatenate(buffer)
                    try:
                        self._work_queue.put_nowait((audio.copy(), True))
                    except queue.Full:
                        pass
                    buffer.clear()
                    buffer_duration_ms = 0
                    speech_started = False
                    chunks_since_preview = 0

            else:
                buffer.append(chunk.copy())
                buffer_duration_ms += CHUNK_MS
                while buffer_duration_ms > MAX_IDLE_BUFFER_MS and len(buffer) > 1:
                    buffer.pop(0)
                    buffer_duration_ms -= CHUNK_MS

        self._buffer = buffer
        self._buffer_duration_ms = buffer_duration_ms
        self._speech_started = speech_started
        self._padding_counter = padding_counter
        self._chunks_since_preview = chunks_since_preview
        if _DEBUG and speech_count > 0:
            logging.info("VAD: %d speech chunks, qsize=%d", speech_count, self._work_queue.qsize())
        return True

    def _transcribe_loop(self):
        while not self._stop.is_set():
            try:
                item = self._work_queue.get(timeout=0.15)
            except queue.Empty:
                continue
            if item is None:
                break
            audio, finalize = item
            if len(audio) < SAMPLE_RATE_WHISPER * 0.1:
                continue
            rms = _rms_normalized(audio)
            if rms < MIN_RMS_FOR_WHISPER:
                if _DEBUG:
                    logging.info("Skip low RMS %.4f < %.4f", rms, MIN_RMS_FOR_WHISPER)
                if finalize and self.text_callback:
                    with self._lock:
                        self._prev_partial = ""
                        self._committed_real_words = []
                    self.text_callback("", "clear_segment")
                continue
            if _DEBUG:
                logging.info("Transcribing %.2fs, RMS=%.4f, finalize=%s", len(audio)/SAMPLE_RATE_WHISPER, rms, finalize)
            try:
                text = _run_whisper(audio, self._model)
            except Exception:
                continue
            text = _deduplicate_words(text)
            if _DEBUG and text:
                logging.info("Whisper out: %r", text)
            if finalize:
                with self._lock:
                    self._prev_partial = ""
                    self._committed_real_words = []
                if text:
                    norm = text.strip().lower()
                    if _is_hallucination(text) or norm == self._last_final_text.strip().lower():
                        text = ""
                    else:
                        self._last_final_text = text
                if text and self.text_callback:
                    self.text_callback(text, "final")
                if self.text_callback:
                    self.text_callback("", "clear_segment")
            else:
                curr = text.split()
                prev = self._prev_partial.split()
                stable_len = _stable_prefix_len(prev, curr)
                delta_text = ""
                temp_text = ""
                with self._lock:
                    n = len(self._committed_real_words)
                    if stable_len > n:
                        new_stable = _strip_overlap(self._committed_real_words, curr[n:stable_len])
                        if new_stable:
                            delta_text = _deduplicate_words(" ".join(new_stable))
                            self._committed_real_words = curr[:stable_len]
                    temp_tail = curr[len(self._committed_real_words):]
                    temp_text = _deduplicate_words(" ".join(temp_tail).strip()) if temp_tail else ""
                    self._prev_partial = text
                delta_text = _strip_hallucination(delta_text)
                temp_text = _strip_hallucination(temp_text)
                if delta_text and self.text_callback:
                    self.text_callback(delta_text, "current_real")
                if self.text_callback:
                    self.text_callback(temp_text, "temp")

    def start(self):
        if self._model is None:
            self._load_model()
        self._transcribe_thread = threading.Thread(target=self._transcribe_loop, daemon=True)
        self._transcribe_thread.start()

    def stop(self):
        self._stop.set()
        self._work_queue.put(None)
        if self._transcribe_thread and self._transcribe_thread.is_alive():
            self._transcribe_thread.join(timeout=5.0)
