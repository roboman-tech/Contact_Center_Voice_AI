/** Browsers block http/ws from https pages (mixed content). */

export function isHttpsPage() {
  return typeof window !== "undefined" && window.location.protocol === "https:";
}

export function isInsecureBackendUrl(url) {
  const s = (url || "").trim();
  return s.startsWith("http://") || s.startsWith("ws://");
}

/**
 * HTTPS production pages: rewrite http:// → https:// when env used http by mistake
 * (nginx often serves TLS on 443 while Vercel env still says http://).
 */
export function upgradeInsecureApiBaseToHttps(raw) {
  const s = (raw || "").trim();
  if (!s || !import.meta.env.PROD || typeof window === "undefined") return s;
  if (window.location.protocol !== "https:") return s;
  if (s.startsWith("http://")) {
    return `https://${s.slice(7)}`;
  }
  return s;
}

/** Explicit VITE_WS_URL: ws:// → wss:// on HTTPS production pages. */
export function upgradeInsecureWsUrlToWss(raw) {
  const s = (raw || "").trim();
  if (!s || !import.meta.env.PROD || typeof window === "undefined") return s;
  if (window.location.protocol !== "https:") return s;
  if (s.startsWith("ws://")) {
    return `wss://${s.slice(5)}`;
  }
  return s;
}

export function mixedContentBackendMessage() {
  return (
    "This page is HTTPS: use https:// and wss:// for your backend. In Vercel set " +
    "VITE_API_BASE=https://voiceai.culturemind.org (not http://). If you use VITE_WS_URL, " +
    "it must start with wss://. Save env, then Redeploy (without cache)."
  );
}
