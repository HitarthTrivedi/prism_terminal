"""
Prism — OpenRouter API calls ("Prism Agent", BOQ-CHANGES-TODO.md item 30)
───────────────────────────────────────────────────────────────────────
The BOQ add-on's write-up stage has always run by driving a real tool in a
browser (Claude, ChatGPT, Grok, ...). Item 30b adds a second path: a plain
API call through OpenRouter, for the two agents BOQ now also offers,
"Prism Agent Claude" and "Prism Agent Deep" (addons/boq/agents.py).

Mirrors router.py's own groq_chat() on purpose — same retry-on-429/5xx
shape, same rule that a failure raises with the server's own words rather
than a paraphrase, so the two API paths behave the same way to whatever
reads their exceptions.
"""
from __future__ import annotations

import json
import time

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_RETRY_STATUS = (429, 500, 502, 503, 504)


def _content_blocks(prompt: str, attachments: list[dict] | None) -> str | list[dict]:
    """A plain string when there is nothing to show the model (the common
    case, and every call before item 32) — or OpenRouter's own multimodal
    content-array shape once there's a rendered drawing to go with the
    text. Each item in `attachments` is cad_render.prepare_for_ai()'s own
    shape: {"kind": "image"|"pdf", "mime", "b64", "name"}.

    Image -> an `image_url` block with a data: URI, OpenAI's (and so
    OpenRouter's) documented shape for a vision model. PDF -> a `file`
    block with `file_data`, OpenRouter's own documented shape for a real
    document a compatible model (Claude) reads natively, not a picture of
    it. NOT verified against a live call yet — built from OpenRouter's
    published API shape, the same honesty this file already asks of
    everything it has not run for real (BOQ-CHANGES-TODO.md item 32's own
    "still open" note)."""
    if not attachments:
        return prompt
    blocks: list[dict] = [{"type": "text", "text": prompt}]
    for att in attachments:
        uri = f"data:{att['mime']};base64,{att['b64']}"
        if att["kind"] == "pdf":
            blocks.append({"type": "file",
                           "file": {"filename": att.get("name", "drawing.pdf"),
                                    "file_data": uri}})
        else:
            blocks.append({"type": "image_url", "image_url": {"url": uri}})
    return blocks


def openrouter_chat(api_key: str, model: str, prompt: str, *,
                     attachments: list[dict] | None = None,
                     temperature: float = 0.3, timeout: int = 180,
                     retries: int = 1) -> str:
    """One OpenRouter completion. `model` is an OpenRouter model id, e.g.
    "anthropic/claude-sonnet-5.5" — addons/boq/agents.py owns the mapping
    from a Prism Agent's display name to the model id actually sent here.

    `attachments`: rendered drawings from addons/boq/cad_render.py's own
    prepare_for_ai(), to actually show the model (item 32) — never the
    raw DXF/DWG bytes, and only ever sent after the SAME consent gate
    (addons/boq/dialog.py's _drawing_consent()) a browser agent's own
    drawing upload already goes through; nothing here decides whether a
    drawing may be sent at all."""
    if not api_key:
        raise RuntimeError(
            "No OpenRouter key set. Add one in Settings → AI tools.")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # OpenRouter's own docs ask for these on every call — identifies
        # the app in OpenRouter's own dashboards; a request with neither
        # still works, just shows up as anonymous there.
        "HTTP-Referer": "https://prism.app",
        "X-Title": "Prism",
    }
    content = _content_blocks(prompt, attachments)
    last = ""
    for attempt in range(retries + 1):
        try:
            resp = requests.post(OPENROUTER_URL, headers=headers, json={
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "temperature": temperature,
            }, timeout=timeout)
        except requests.RequestException as e:
            raise RuntimeError(
                f"Couldn't reach OpenRouter — check your internet connection. "
                f"({e})") from e

        try:
            body = resp.json()
        except ValueError:
            body = {}

        if resp.status_code == 200 and body.get("choices"):
            return body["choices"][0]["message"]["content"]

        if resp.status_code in _RETRY_STATUS and attempt < retries:
            delay = 5
            try:
                delay = min(int(float(resp.headers.get("retry-after", 5))), 20)
            except (TypeError, ValueError):
                pass
            time.sleep(delay)
            continue

        if resp.status_code == 429:
            raise RuntimeError(
                "OpenRouter is rate-limiting your key. Wait a minute and "
                "try again, or raise your limits at openrouter.ai.")
        if resp.status_code == 401:
            raise RuntimeError(
                "OpenRouter rejected your API key. Re-enter it in "
                "Settings → AI tools.")
        err = None
        if isinstance(body, dict):
            err = (body.get("error") or {}).get("message")
        last = err or f"HTTP {resp.status_code}: {json.dumps(body)[:300]}"
        raise RuntimeError(f"OpenRouter API error ({last})")

    raise RuntimeError(f"OpenRouter did not answer. ({last})")


def verify_key(api_key: str, model: str = "") -> str:
    """Check an OpenRouter key against OpenRouter. Returns "" if it works,
    else why not — mirrors router.verify_key's own shape (same reasoning:
    ask this the moment the key is entered, not on the first real task)."""
    api_key = (api_key or "").strip()
    if not api_key:
        return "No key entered."
    if not api_key.startswith("sk-or-"):
        return ("An OpenRouter key starts with 'sk-or-' — this doesn't "
                "look like one.")
    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"}, timeout=20)
    except Exception as e:                                  # noqa: BLE001
        return (f"Couldn't reach OpenRouter to check the key ({e}).\nIf "
                "you're behind a proxy or offline, the key may still be fine.")
    if resp.status_code == 401:
        return ("OpenRouter rejected this key. Make a new one at "
                "openrouter.ai/keys and paste it again — copying it twice "
                "by accident is the usual cause.")
    if resp.status_code == 429:
        return ("The key is valid, but OpenRouter is rate-limiting it "
                "right now. Writing may be slow until that clears.")
    if resp.status_code != 200:
        return (f"OpenRouter answered HTTP {resp.status_code} — the key "
                "may not be usable.")
    if model:
        try:
            ids = {m.get("id") for m in resp.json().get("data", [])}
            if ids and model not in ids:
                return (f"The key works, but '{model}' isn't on OpenRouter's "
                        "current model list.")
        except Exception:                                   # noqa: BLE001
            pass
    return ""
