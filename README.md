# Contact Center Voice AI

Voice AI for contact centers. Real-time transcription with VAD, three-layer captions, and AI-assisted answers via DeepSeek.

## Architecture

### Frontend
- **Audio capture**: 48 kHz (or browser default) → downsample to 16 kHz mono
- **Chunking**: ~30 ms chunks via ScriptProcessor, Float32Array
- **WebSocket**: Sends raw PCM immediately; receives caption events
- **Display**: Three-layer captions (final / current / temp)
- **Device & model selection**: Auto, CPU, GPU; base.en, small.en, medium.en, turbo

### Backend
- **VAD**: RMS energy threshold 10, speech vs silence (tuned for system audio)
- **Buffering**: Finalize on 700 ms silence or 12 s max; preview every 300 ms (last 2.8 s)
- **Whisper**: Deduplication, prefix stabilization, hallucination filtering
- **WebSocket events**: `preview_caption`, `final_caption`, `clear`, `device_model_change`

## Structure

```
NPC_Dialogue/
├── backend/
│   ├── main.py           # API + WebSocket
│   ├── transcriber.py    # File transcription
│   ├── realtime_transcriber.py  # VAD, 3-layer logic
│   ├── deepseek_api.py
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── useLiveCaption.js
│   │   ├── App.css
│   │   └── main.jsx
│   └── package.json
└── README.md
```

## Setup

### Backend
```bash
cd backend
pip install -r requirements.txt
```
Create `.env` with `DEEPSEEK_API_KEY`. Install **ffmpeg** (e.g. `winget install Gyan.FFmpeg`).

### Frontend
```bash
cd frontend
npm install
```

## Run

**Development:**
```bash
# Terminal 1
cd backend && python main.py

# Terminal 2
cd frontend && npm run dev
```
Open http://localhost:5173 (Vite proxies `/api` and `/ws` to backend).

**Production:**
```bash
cd frontend && npm run build
cd ../backend && python main.py
```
Open http://localhost:8000.

## Troubleshooting

### No text from system sounds / screen share

1. **Check capture mode**: For screen share, you must enable "Share system audio" (or share a tab and ensure "Share tab audio" is checked). The frontend shows an error if no audio track is present.

2. **Whisper only transcribes speech**: It will not transcribe music, beeps, or UI sounds—only human speech (e.g. from YouTube videos).

3. **Enable debug logging**:
   ```bash
   DEBUG_LIVE=1 python main.py
   ```
   This logs chunk sizes, WebM decode success, and audio RMS so you can verify streaming and decoding.

4. **VAD threshold**: If system audio is quiet, the VAD may filter it. The default threshold is 10 (lowered for screen-share sensitivity).

## Features

- **Live captions** – VAD-based segmentation, 3-layer display
- **Mic / Share Screen** – Audio capture
- **Clear** – Resets captions, dialogue, answer; keeps User Context
- **Generate Answer** – DeepSeek uses context + dialogue
- **Device/Model** – Auto, CPU, GPU; Whisper model selection
