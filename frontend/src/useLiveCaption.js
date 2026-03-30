/**
 * Real-time live caption: MediaRecorder sends WebM chunks via WebSocket.
 * Backend handles both WebM and raw PCM.
 */

import { useCallback, useRef } from "react";

const CHUNK_MS = 2500;

const devLog = (...args) => {
  if (import.meta.env.DEV) console.log(...args);
};

function getWsUrl() {
  const explicit = import.meta.env.VITE_WS_URL;
  if (explicit) return explicit;
  const apiBase = import.meta.env.VITE_API_BASE;
  if (apiBase) {
    try {
      const u = new URL(apiBase);
      const wsProto = u.protocol === "https:" ? "wss:" : "ws:";
      return `${wsProto}//${u.host}/ws/live`;
    } catch {
      /* fall through */
    }
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/live`;
}

export function useLiveCaption({
  onPreviewCaption,
  onFinalCaption,
  onGeneratedAnswer,
  onError,
  onClearAck,
  device,
  model,
}) {
  const wsRef = useRef(null);
  const streamRef = useRef(null);
  const recorderRef = useRef(null);
  const chunkTimerRef = useRef(null);
  const isLiveRef = useRef(false);
  const onPreviewRef = useRef(onPreviewCaption);
  const onFinalRef = useRef(onFinalCaption);
  const onAnswerRef = useRef(onGeneratedAnswer);
  const onErrorRef = useRef(onError);
  const onClearAckRef = useRef(onClearAck);
  onPreviewRef.current = onPreviewCaption;
  onFinalRef.current = onFinalCaption;
  onAnswerRef.current = onGeneratedAnswer;
  onErrorRef.current = onError;
  onClearAckRef.current = onClearAck;

  const stop = useCallback(() => {
    isLiveRef.current = false;
    if (chunkTimerRef.current) {
      clearTimeout(chunkTimerRef.current);
      chunkTimerRef.current = null;
    }
    if (recorderRef.current?.state === "recording") {
      recorderRef.current.stop();
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (wsRef.current) {
      try {
        wsRef.current.send(JSON.stringify({ event: "stop" }));
        wsRef.current.close();
      } catch (_) {}
      wsRef.current = null;
    }
  }, []);

  const start = useCallback(
    async (source) => {
      const isMic = source === "mic";
      let stream;
      try {
        if (isMic) {
          stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } else {
          stream = await navigator.mediaDevices.getDisplayMedia({
            video: true,
            audio: true,
          });
          if (stream.getAudioTracks().length === 0) {
            stream.getTracks().forEach((t) => t.stop());
            onError?.("No audio. Check 'Share system audio' or share a tab with sound.");
            return false;
          }
        }
      } catch (err) {
        if (err?.name === "NotAllowedError") {
          onError?.(isMic ? "Mic permission denied." : "Screen share cancelled.");
        } else {
          onError?.(err?.message || "Failed to get media.");
        }
        return false;
      }

      streamRef.current = stream;

      const ws = new WebSocket(getWsUrl());
      wsRef.current = ws;

      ws.onmessage = (e) => {
        if (typeof e.data === "string") {
          devLog("[LiveCaption] msg:", e.data.slice(0, 80));
          try {
            const msg = JSON.parse(e.data);
            const ev = msg.event;
            if (ev === "preview_caption") {
              onPreviewRef.current?.(msg.final ?? "", msg.current ?? "", msg.temp ?? "");
            } else if (ev === "final_caption") {
              onFinalRef.current?.(msg.final ?? "", msg.speaker ?? "Speaker");
            } else if (ev === "generated_answer") {
              onAnswerRef.current?.(msg.answer ?? "");
            } else if (ev === "clear_ack") {
              onClearAckRef.current?.();
            } else if (ev === "error") {
              onErrorRef.current?.(msg.message ?? "Error");
            }
          } catch (_) {}
        }
      };

      ws.onerror = () => onError?.("WebSocket error");

      try {
        await new Promise((resolve, reject) => {
          ws.onopen = () => {
            devLog("[LiveCaption] WebSocket connected");
            ws.send(
              JSON.stringify({
                event: "init",
                device: device || "auto",
                model: model || "small.en",
              })
            );
            resolve();
          };
          ws.onerror = () => reject(new Error("WebSocket failed"));
          ws.onclose = () => reject(new Error("WebSocket closed"));
        });
      } catch (e) {
        onError?.(e?.message || "WebSocket failed");
        stream.getTracks().forEach((t) => t.stop());
        ws.close();
        return false;
      }

      const startChunkedRecorder = () => {
        if (!isLiveRef.current || !streamRef.current) return;
        const recorder = new MediaRecorder(streamRef.current);
        recorderRef.current = recorder;
        const chunks = [];

        recorder.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data);
        recorder.onerror = () => onError?.("Recording error");
        recorder.onstop = () => {
          if (chunks.length > 0 && wsRef.current?.readyState === WebSocket.OPEN) {
            const blob = new Blob(chunks, {
              type: isMic ? "audio/webm" : "video/webm",
            });
            blob.arrayBuffer().then((buf) => {
              if (wsRef.current?.readyState === WebSocket.OPEN && buf.byteLength >= 100) {
                devLog("[LiveCaption] sending audio", buf.byteLength, "bytes");
                wsRef.current.send(buf);
              } else if (import.meta.env.DEV) {
                console.warn("[LiveCaption] skip send:", buf.byteLength, "bytes, open=", wsRef.current?.readyState === WebSocket.OPEN);
              }
            });
          }
          if (isLiveRef.current && streamRef.current) {
            startChunkedRecorder();
          }
        };

        recorder.start(500);
        chunkTimerRef.current = setTimeout(() => {
          chunkTimerRef.current = null;
          if (recorder.state === "recording") recorder.stop();
        }, CHUNK_MS);
      };

      isLiveRef.current = true;
      startChunkedRecorder();

      if (stream.getVideoTracks().length > 0) {
        stream.getVideoTracks()[0].addEventListener("ended", stop);
      }
      return true;
    },
    [device, model, onError, stop]
  );

  const sendClear = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ event: "clear" }));
    }
  }, []);

  const sendDeviceModelChange = useCallback((dev, mod) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({ event: "device_model_change", device: dev, model: mod })
      );
    }
  }, []);

  return { start, stop, sendClear, sendDeviceModelChange };
}
