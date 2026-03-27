import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { motion } from "framer-motion";
import {
  Mic,
  Square,
  Trash2,
  Sparkles,
  Loader2,
  Volume2,
  FileText,
  MessageSquare,
  Monitor,
} from "lucide-react";
import { useLiveCaption } from "./useLiveCaption";
import "./App.css";

const API_BASE = "";

const HALLUCINATION_PHRASES = [
  "thanks for watching",
  "thank you for watching",
  "you for watching",
  "for watching",
  "subscribe",
  "like and subscribe",
  "that's all",
  "bye",
  "goodbye",
];

function isHallucination(text) {
  const raw = (text || "").trim();
  if (!raw) return true;
  if (/^(.)\1{4,}$/.test(raw.replace(/\s/g, ""))) return true;
  const t = raw.toLowerCase().replace(/\s+/g, " ").replace(/[.!?,]+$/g, "");
  return HALLUCINATION_PHRASES.some((p) => t === p || t.endsWith(" " + p));
}

function detectLatestQuestion(history) {
  const markers = [
    "?",
    "tell me",
    "what",
    "how",
    "why",
    "can you",
    "could you",
    "would you",
    "describe",
    "explain",
  ];
  for (let i = history.length - 1; i >= 0; i--) {
    const t = (history[i]?.text || "").trim().toLowerCase();
    if (!t) continue;
    if (t.endsWith("?") || markers.some((m) => t.startsWith(m))) {
      return history[i].text;
    }
  }
  for (let i = history.length - 1; i >= 0; i--) {
    const t = (history[i]?.text || "").trim();
    if (t) return t;
  }
  return "";
}

export default function App() {
  const [isRecording, setIsRecording] = useState(false);
  const [status, setStatus] = useState("Ready");
  const [dialogue, setDialogue] = useState([]);
  const [finalLayer, setFinalLayer] = useState("");
  const [currentLayer, setCurrentLayer] = useState("");
  const [tempLayer, setTempLayer] = useState("");
  const [liveSpeaker, setLiveSpeaker] = useState("You");
  const [context, setContext] = useState("");
  const [answer, setAnswer] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [model, setModel] = useState("small.en");
  const [device, setDevice] = useState("auto");
  const isRecordingRef = useRef(false);
  const dialogueEndRef = useRef(null);

  useEffect(() => {
    dialogueEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [dialogue, finalLayer, currentLayer, tempLayer]);

  const onPreviewCaption = useCallback((finalText, currentText, tempText) => {
    const f = isHallucination(finalText) ? "" : (finalText || "");
    const c = isHallucination(currentText) ? "" : (currentText || "");
    const t = isHallucination(tempText) ? "" : (tempText || "");
    setFinalLayer(f);
    setCurrentLayer(c);
    setTempLayer(t);
    if (f || c || t) setLiveSpeaker("You");
  }, []);

  const onFinalCaption = useCallback((text, speaker) => {
    const trimmed = (text || "").trim();
    if (trimmed && !isHallucination(trimmed)) {
      setDialogue((d) => {
        if (d.length > 0 && d[d.length - 1]?.text === trimmed) return d;
        const spk = speaker || "You";
        if (d.length > 0) {
          const last = d[d.length - 1];
          const sameSpeaker = last.speaker === spk;
          if (sameSpeaker) {
            return [...d.slice(0, -1), { ...last, text: last.text + " " + trimmed }];
          }
        }
        return [...d, { speaker: spk, text: trimmed }];
      });
    }
    setFinalLayer("");
    setCurrentLayer("");
    setTempLayer("");
    setLiveSpeaker(speaker || "You");
  }, []);

  const onGeneratedAnswer = useCallback((ans) => {
    setAnswer(ans || "");
  }, []);

  const onClearAck = useCallback(() => {
    setStatus("Listening…");
    setTimeout(() => setStatus(isRecordingRef.current ? "Live caption • Recording…" : "Ready"), 800);
  }, []);

  const { start, stop, sendClear, sendDeviceModelChange } = useLiveCaption({
    onPreviewCaption,
    onFinalCaption,
    onGeneratedAnswer,
    onError: (msg) => setStatus("Error: " + msg),
    onClearAck,
    device,
    model,
  });

  const startRecording = useCallback(async () => {
    setStatus("Connecting…");
    const ok = await start("mic");
    if (ok !== false) {
      setIsRecording(true);
      isRecordingRef.current = true;
      setStatus("Live caption • Recording…");
    }
  }, [start]);

  const startScreenCapture = useCallback(async () => {
    setStatus("Share screen, then connecting…");
    const ok = await start("screen");
    if (ok !== false) {
      setIsRecording(true);
      isRecordingRef.current = true;
      setStatus("Live caption • Recording…");
    }
  }, [start]);

  const stopRecording = useCallback(() => {
    stop();
    setIsRecording(false);
    isRecordingRef.current = false;
    setStatus("Ready");
    setFinalLayer("");
    setCurrentLayer("");
    setTempLayer("");
    setLiveSpeaker("You");
  }, [stop]);

  const clearAll = useCallback(() => {
    setDialogue([]);
    setFinalLayer("");
    setCurrentLayer("");
    setTempLayer("");
    setAnswer("");
    setStatus("Listening…");
    sendClear();
    setTimeout(() => setStatus(isRecordingRef.current ? "Live caption • Recording…" : "Ready"), 1000);
  }, [sendClear]);

  const generateAnswer = useCallback(async () => {
    const snapshot = { dialogue: [...dialogue], context };
    const question = detectLatestQuestion(snapshot.dialogue);
    setIsGenerating(true);
    setAnswer("");

    try {
      const res = await fetch(`${API_BASE}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_context: snapshot.context,
          dialogue: snapshot.dialogue,
          question: question || null,
        }),
      });
      const data = await res.json();
      setAnswer(data.error || data.answer || "No response.");
      if (!isRecordingRef.current) {
        setStatus(data.error ? "Error" : "Answer generated");
      }
    } catch (err) {
      setAnswer("Error: " + err.message);
      if (!isRecordingRef.current) {
        setStatus("Error");
      }
    } finally {
      setIsGenerating(false);
    }
  }, [context, dialogue]);

  const handleDeviceChange = useCallback(
    (e) => {
      const d = e.target.value;
      setDevice(d);
      if (isRecording) {
        sendDeviceModelChange(d, model);
      }
    },
    [model, isRecording, sendDeviceModelChange]
  );

  const handleModelChange = useCallback(
    (e) => {
      const m = e.target.value;
      setModel(m);
      if (isRecording) {
        sendDeviceModelChange(device, m);
      }
    },
    [device, isRecording, sendDeviceModelChange]
  );

  const hasContent =
    dialogue.length > 0 || finalLayer || currentLayer || tempLayer;

  const dialogueJoined = useMemo(
    () => dialogue.map((item) => item.text).join(" "),
    [dialogue]
  );

  return (
    <div className="app">
      <header className="header">
        <motion.h1
          className="title"
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
        >
          Contact Center Voice AI
        </motion.h1>
        <StatusIndicator status={status} isRecording={isRecording} />
      </header>

      <motion.div
        className="toolbar"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.1 }}
      >
        <div className="toolbar-actions">
          {!isRecording ? (
            <>
              <motion.button
                className="btn btn-record"
                onClick={startRecording}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
              >
                <Mic size={18} />
                Mic
              </motion.button>
              <motion.button
                className="btn btn-screen"
                onClick={startScreenCapture}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
              >
                <Monitor size={18} />
                Share Screen
              </motion.button>
            </>
          ) : (
            <motion.button
              className="btn btn-stop"
              onClick={stopRecording}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
            >
              <Square size={16} fill="currentColor" />
              Stop
            </motion.button>
          )}
          <select
            className="model-select"
            value={device}
            onChange={handleDeviceChange}
            title="Device"
          >
            <option value="auto">Device: Auto</option>
            <option value="cpu">Device: CPU</option>
            <option value="cuda">Device: GPU</option>
          </select>
          <select
            className="model-select"
            value={model}
            onChange={handleModelChange}
            title="Model"
          >
            <option value="base.en">base.en</option>
            <option value="small.en">small.en</option>
            <option value="medium.en">medium.en</option>
            <option value="turbo">turbo</option>
          </select>
          <motion.button
            className="btn btn-ghost"
            onClick={clearAll}
            title="Clear chat history (dialogue). Generate Answer will use only new chat + pre-given context."
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
          >
            <Trash2 size={16} />
            Clear
          </motion.button>
        </div>
      </motion.div>

      <main className="content content-layout">
        <div className="content-left">
          <Panel
            icon={<MessageSquare size={18} />}
            title="Live Caption / Dialogue"
            className="panel-dialogue"
          >
            {!hasContent ? (
              <div className="placeholder">
                <Volume2 size={32} strokeWidth={1.5} />
                <p>
                  <strong>Live captions</strong> – 3-layer display (final / current / temp)
                </p>
                <p className="hint">
                  <strong>Mic</strong> – your voice · <strong>Share Screen</strong> – tab/screen audio
                </p>
              </div>
            ) : (
              <div className="captions-container captions-scroll">
                <div className="dialogue-single">
                  <span className="speaker">{liveSpeaker}</span>
                  <div className="dialogue-text" ref={dialogueEndRef}>
                    {dialogueJoined}
                    {dialogue.length > 0 && (currentLayer || tempLayer) ? " " : ""}
                    <span className="caption-current">{currentLayer}</span>
                    {currentLayer && tempLayer ? " " : ""}
                    <span className="caption-temp">{tempLayer}</span>
                  </div>
                </div>
              </div>
            )}
          </Panel>

          <Panel
            icon={<FileText size={18} />}
            title="User Context"
            hint="talking points…"
          >
            <textarea
              className="context-input"
              value={context}
              onChange={(e) => setContext(e.target.value)}
              placeholder="Paste your context here…"
              rows={5}
            />
          </Panel>
        </div>

        <div className="content-right">
          <motion.button
            className="btn btn-generate"
            onClick={generateAnswer}
            disabled={isGenerating}
            whileHover={!isGenerating ? { scale: 1.02 } : {}}
            whileTap={!isGenerating ? { scale: 0.98 } : {}}
          >
            {isGenerating ? (
              <>
                <Loader2 size={20} className="spin" />
                Generating…
              </>
            ) : (
              <>
                <Sparkles size={20} />
                Generate Answer
              </>
            )}
          </motion.button>

          <Panel
            icon={<Sparkles size={18} />}
            title="Generated Answer"
            className="panel-answer"
          >
            {!answer && !isGenerating ? (
              <div className="placeholder">
                <p>
                  Click <strong>Generate Answer</strong> for AI-assisted response.
                </p>
                <p className="hint">Based on dialogue and context.</p>
              </div>
            ) : (
              <motion.div
                className="answer-content"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                key={answer}
              >
                {answer}
              </motion.div>
            )}
          </Panel>
        </div>
      </main>

      <footer className="footer">
        <span>Ready • Ctrl+C to copy</span>
      </footer>
    </div>
  );
}

function StatusIndicator({ status, isRecording }) {
  return (
    <div className={`status ${isRecording ? "recording" : ""}`}>
      <motion.span
        className="status-dot"
        animate={
          isRecording ? { scale: [1, 1.2, 1], opacity: [1, 0.7, 1] } : {}
        }
        transition={{ duration: 1.2, repeat: isRecording ? Infinity : 0 }}
      />
      <span className="status-text">{status}</span>
    </div>
  );
}

function Panel({ icon, title, hint, children, className = "" }) {
  return (
    <motion.section
      className={`panel ${className}`}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <div className="panel-header">
        <span className="panel-icon">{icon}</span>
        <h2 className="panel-title">{title}</h2>
      </div>
      {hint && <p className="panel-hint">{hint}</p>}
      <div className="panel-body">{children}</div>
    </motion.section>
  );
}
