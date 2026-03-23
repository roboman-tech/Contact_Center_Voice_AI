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
        "max_tokens": 2048,
        "temperature": 0.7,
    }).encode("utf-8")

    req = urllib.request.Request(
        DEFAULT_API_URL,
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
