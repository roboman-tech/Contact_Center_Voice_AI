# Contact Center Voice AI

Voice AI for contact centers. Record your voice, get real-time transcription, paste context (resume, job description), and generate AI-assisted answers via DeepSeek.

## Structure

```
Contact_Center_Voice_AI/
├── backend/          # FastAPI server
│   ├── main.py       # API + static serving
│   ├── transcriber.py
│   ├── deepseek_api.py
│   └── requirements.txt
├── frontend/         # React + Vite
│   ├── src/
│   │   ├── App.jsx
│   │   ├── App.css
│   │   └── main.jsx
│   ├── index.html
│   └── package.json
└── README.md
```

## Setup

### 1. Backend

```bash
cd Contact_Center_Voice_AI/backend
pip install -r requirements.txt
```

Create `.env` from `.env.example` and add your DeepSeek API key:

```
DEEPSEEK_API_KEY=sk-...
```

**Note:** Whisper requires ffmpeg. Install it if needed (e.g. `winget install ffmpeg` on Windows).

### 2. Frontend (React)

```bash
cd Contact_Center_Voice_AI/frontend
npm install
```

### 3. Run

**Development** (two terminals):

```bash
# Terminal 1 - Backend
cd backend && python main.py

# Terminal 2 - React dev server (proxies /api to backend)
cd frontend && npm run dev
```

Open **http://localhost:5173** for the React app.

**Production** (single server):

```bash
cd frontend && npm run build
cd ../backend && python main.py
```

Open **http://localhost:8000**.

## Features

- **Record** – Start/stop microphone recording
- **Transcribe** – Audio sent to backend, transcribed with Whisper
- **Dialogue** – Captions appear in the dialogue panel
- **Context** – Paste resume, job description, talking points
- **Generate Answer** – DeepSeek generates answers from context + dialogue

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/transcribe` | Upload audio file, get transcription |
| POST | `/api/generate` | Generate AI answer (context + dialogue) |
| GET | `/api/health` | Health check |
