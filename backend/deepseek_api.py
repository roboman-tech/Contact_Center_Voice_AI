"""
DeepSeek API module for interview answer generation.
Reusable function for chat completions with error handling.
"""

import json
import os
import urllib.request
import urllib.error


DEFAULT_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT = 60
# Shorter answers = faster completion; still enough for contact-center replies
DEFAULT_MAX_TOKENS = 768
DEFAULT_TEMPERATURE = 0.45


def get_api_url() -> str:
    return (os.environ.get("DEEPSEEK_API_URL") or DEFAULT_API_URL).strip()


def get_api_key() -> str:
    """Get API key from environment (DEEPSEEK_API_KEY or DEEPSEEK_KEY)."""
    return (
        os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("DEEPSEEK_KEY")
        or ""
    ).strip()


def generate(
    prompt: str,
    system_prompt: str = None,
    api_key: str = None,
    model: str = None,
    timeout: int = None,
) -> str:
    """
    Send a prompt to DeepSeek and return the generated text.
    """
    api_key = api_key or get_api_key()
    if not api_key:
        return ""

    model = model or DEFAULT_MODEL
    timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

    messages = []
    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": prompt.strip()})

    body = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "temperature": DEFAULT_TEMPERATURE,
    }).encode("utf-8")

    req = urllib.request.Request(
        get_api_url(),
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        json.JSONDecodeError,
        TimeoutError,
        OSError,
    ) as e:
        return str(e) if isinstance(e, Exception) else ""

    choices = data.get("choices", [])
    if not choices:
        return ""

    content = choices[0].get("message", {}).get("content", "")
    return (content or "").strip()


def iter_generate_stream(
    prompt: str,
    system_prompt: str = None,
    api_key: str = None,
    model: str = None,
    timeout: int = None,
):
    """
    Stream text deltas from DeepSeek (OpenAI-compatible SSE).
    Yields each content fragment as it arrives.
    """
    api_key = api_key or get_api_key()
    if not api_key:
        return

    model = model or DEFAULT_MODEL
    timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

    messages = []
    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": prompt.strip()})

    body = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "temperature": DEFAULT_TEMPERATURE,
        "stream": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        get_api_url(),
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            while True:
                raw = resp.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if line == "data: [DONE]":
                    break
                if not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if payload == "[DONE]":
                    break
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                for choice in obj.get("choices", []) or []:
                    delta = choice.get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        yield piece
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
    ) as e:
        raise RuntimeError(str(e)) from e
