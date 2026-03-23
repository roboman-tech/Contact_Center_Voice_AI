import { useState, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Mic,
  Square,
  Trash2,
  Sparkles,
  Loader2,
  Volume2,
  FileText,
  MessageSquare,
} from "lucide-react";
import "./App.css";

const API_BASE = "";

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
  const [context, setContext] = useState("");
  const [answer, setAnswer] = useState(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [model, setModel] = useState("small.en");

  const mediaRecorderRef = useRef(null);
  const streamRef = useRef(null);

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      const chunks = [];

      recorder.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        if (chunks.length > 0) {
          setStatus("Transcribing...");
          const blob = new Blob(chunks, { type: "audio/webm" });
          const formData = new FormData();
          formData.append("file", blob, "recording.webm");

          try {
            const res = await fetch(
              `${API_BASE}/api/transcribe?model=${encodeURIComponent(model)}`,
              { method: "POST", body: formData }
            );
            if (!res.ok) throw new Error(await res.text() || res.statusText);
            const data = await res.json();
            const text = (data.text || "").trim();
            if (text) {
              setDialogue((d) => [...d, { speaker: "You", text }]);
            }
          } catch (err) {
            setStatus("Error: " + err.message);
            return;
          }
        }
        setStatus("Ready");
      };

      recorder.start();
      mediaRecorderRef.current = recorder;
      setIsRecording(true);
      setStatus("Recording...");
    } catch (err) {
      setStatus("Mic error: " + err.message);
    }
  }, [model]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current?.state === "recording") {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  }, []);

  const clearAll = useCallback(() => {
    setDialogue([]);
    setAnswer(null);
    setStatus("Cleared");
    setTimeout(() => setStatus("Ready"), 1500);
  }, []);

  const generateAnswer = useCallback(async () => {
    const question = detectLatestQuestion(dialogue);
    setIsGenerating(true);
    setAnswer(null);

    try {
      const res = await fetch(`${API_BASE}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_context: context,
          dialogue,
          question: question || null,
        }),
      });
      const data = await res.json();
      setAnswer(data.error || data.answer || "No response.");
      setStatus(data.error ? "Error" : "Answer generated");
    } catch (err) {
      setAnswer("Error: " + err.message);
      setStatus("Error");
    } finally {
      setIsGenerating(false);
    }
  }, [context, dialogue]);

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
            <motion.button
              className="btn btn-record"
              onClick={startRecording}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
            >
              <Mic size={18} />
              Start Recording
            </motion.button>
          ) : (
            <motion.button
              className="btn btn-stop"
              onClick={stopRecording}
              initial={{ scale: 0.9 }}
              animate={{ scale: 1 }}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
            >
              <Square size={16} fill="currentColor" />
              Stop
            </motion.button>
          )}
          <select
            className="model-select"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          >
            <option value="base.en">base.en</option>
            <option value="small.en">small.en</option>
            <option value="medium.en">medium.en</option>
            <option value="turbo">turbo</option>
          </select>
          <motion.button
            className="btn btn-ghost"
            onClick={clearAll}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
          >
            <Trash2 size={16} />
            Clear
          </motion.button>
        </div>
      </motion.div>

      <main className="content">
        <Panel
          icon={<MessageSquare size={18} />}
          title="Live Caption / Dialogue"
          className="panel-dialogue"
        >
          {dialogue.length === 0 ? (
            <div className="placeholder">
              <Volume2 size={32} strokeWidth={1.5} />
              <p>Click <strong>Start Recording</strong> to capture audio.</p>
              <p className="hint">Speak, then click Stop to transcribe.</p>
            </div>
          ) : (
            <div className="dialogue-list">
              <AnimatePresence mode="popLayout">
                {dialogue.map((item, i) => (
                  <motion.div
                    key={i}
                    className="dialogue-item"
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, x: -20 }}
                    transition={{ duration: 0.25 }}
                  >
                    <span className="speaker">{item.speaker}</span>
                    <span className="text">{item.text}</span>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          )}
        </Panel>

        <Panel
          icon={<FileText size={18} />}
          title="User Context"
          hint="Resume, job description, talking points..."
        >
          <textarea
            className="context-input"
            value={context}
            onChange={(e) => setContext(e.target.value)}
            placeholder="Paste your context here..."
            rows={5}
          />
        </Panel>

        <motion.div
          className="generate-row"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.2 }}
        >
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
                Generating...
              </>
            ) : (
              <>
                <Sparkles size={20} />
                Generate Answer
              </>
            )}
          </motion.button>
        </motion.div>

        <Panel
          icon={<Sparkles size={18} />}
          title="Generated Answer"
          className="panel-answer"
        >
          {!answer && !isGenerating ? (
            <div className="placeholder">
              <p>Click <strong>Generate Answer</strong> to get AI-assisted response.</p>
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
          isRecording
            ? { scale: [1, 1.2, 1], opacity: [1, 0.7, 1] }
            : {}
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
