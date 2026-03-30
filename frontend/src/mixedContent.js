/** Browsers block http/ws from https pages (mixed content). */

export function isHttpsPage() {
  return typeof window !== "undefined" && window.location.protocol === "https:";
}

export function isInsecureBackendUrl(url) {
  const s = (url || "").trim();
  return s.startsWith("http://") || s.startsWith("ws://");
}

export function mixedContentBackendMessage() {
  return (
    "This page is HTTPS; the API must use HTTPS and WSS. Put TLS in front of uvicorn (nginx, Caddy, Cloudflare Tunnel, etc.), " +
    "then set VITE_API_BASE=https://your-domain (no http://) in Vercel and redeploy."
  );
}
