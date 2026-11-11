"""
Prism Motion Graphics — a second pair of eyes on the finished frames
─────────────────────────────────────────────────────────────────────
The geometry checks (core.motion.measure) know where every box is and cannot
tell whether the frame is any good: a headline that fits but is lost in a sea
of empty page, a card with nothing in it, a phone number bigger than the brand
name. A small vision model can, for a fraction of a cent a frame — measured
11 Nov 2026: Claude Haiku 5.5 at $0.0004 a frame found the clipped text, the
run-off phone number and the dead areas in a model-written film that the
estimate-based checker had passed.

Opt-in. It sends rendered frames of the client's own film to a third-party
model, so it runs only when config `motion_critic` is true and an OpenRouter
key is set — the same explicit choice the BOQ add-on asks for before it sends
a drawing. It reports; it does not repair (repair needs the writer again).

    settled_frames(spec)              -> [(scene_index, png_bytes)]
    critique(frames, cfg)             -> {"defects": [...], "cost": dollars}
    faults(defects, min_severity=2)   -> sentences for a repair prompt
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
from io import BytesIO
from typing import Any

MODEL = "anthropic/claude-haiku-5.5"
MAX_FRAMES = 12            # a cap, not a target: one settled frame per scene
FRAME_WIDTH = 540          # what the model sees; enough to read, cheap to send

_RUBRIC = (
    "These are frames from an AI-generated motion graphic, one per scene, in order. "
    "List every defect a motion designer would reject. Look for: text cut off by a frame "
    "edge; text overlapping other text; text too small to read on a phone; a big empty "
    "area with nothing to look at; weak hierarchy (the most important line is not the most "
    "prominent); an empty card or panel; a number or phone line that outweighs the brand; "
    "a photo or logo covered by text. Do not praise. Each defect names its scene "
    "(1-based), what it is, where, and a severity from 1 (minor) to 3 (reject).")

_SCHEMA = {"type": "json_schema", "json_schema": {"name": "defects", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["defects"],
    "properties": {"defects": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["scene", "type", "where", "severity"],
        "properties": {"scene": {"type": "integer"}, "type": {"type": "string"},
                       "where": {"type": "string"}, "severity": {"type": "integer"}}}}}}}}


def enabled(cfg: dict | None) -> bool:
    cfg = cfg or {}
    return bool(cfg.get("motion_critic")) and bool((cfg.get("openrouter_api_key") or "").strip())


def settled_frames(spec: dict[str, Any], at: float = 0.8) -> list[tuple[int, bytes]]:
    """One PNG per scene, taken `at` of the way through it, camera applied — the
    way the viewer sees it — at FRAME_WIDTH wide. [] when there is no browser."""
    from .render import _playwright_available
    if not _playwright_available():
        return []
    from .resolver import resolve_motion_spec
    from .schema import validate_motion_spec
    resolved = resolve_motion_spec(validate_motion_spec(spec))
    project = resolved["project"]
    width, height = int(project["width"]), int(project["height"])
    fps = int(project.get("fps", 30) or 30)
    scale = min(1.0, FRAME_WIDTH / width)
    from playwright.sync_api import sync_playwright
    from .. import browser as _browser
    index = pathlib.Path(os.path.dirname(__file__), "runtime", "index.html")
    out: list[tuple[int, bytes]] = []
    with sync_playwright() as pw:
        chromium = _browser.launch_chromium(
            pw, args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
        try:
            page = chromium.new_page(viewport={"width": width, "height": height}, device_scale_factor=scale)
            page.goto(index.as_uri(), wait_until="domcontentloaded")
            page.wait_for_function("typeof window.__loadSpec === 'function'", timeout=15_000)
            page.evaluate("s => window.__loadSpec(s)", resolved)
            try:
                page.wait_for_function("document.fonts.ready.then(() => true)", timeout=8000)
            except Exception:  # noqa: BLE001
                pass
            for si, sc in enumerate(resolved.get("scenes", [])[:MAX_FRAMES]):
                moment = float(sc.get("start", 0.0) or 0.0) + float(sc.get("duration", 0.0) or 0.0) * at
                page.evaluate(f"window.__seek({int(round(moment * fps))})")
                out.append((si, page.screenshot(type="png")))
        finally:
            chromium.close()
    return out


def parse(text: str) -> list[dict[str, Any]]:
    """Defects out of a model reply; [] for anything that is not the schema."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        start, end = (text or "").find("{"), (text or "").rfind("}")
        if start < 0 or end <= start:
            return []
        try:
            data = json.loads(text[start:end + 1])
        except ValueError:
            return []
    out = []
    for d in (data.get("defects") if isinstance(data, dict) else None) or []:
        if isinstance(d, dict) and d.get("type"):
            try:
                sev = max(1, min(3, int(d.get("severity", 1))))
                scene = int(d.get("scene", 0))
            except (TypeError, ValueError):
                continue
            out.append({"scene": scene, "type": str(d["type"])[:120], "where": str(d.get("where", ""))[:160],
                        "severity": sev})
    return out


def critique(frames: list[tuple[int, bytes]], cfg: dict | None, model: str = MODEL,
             max_cost: float = 0.10) -> dict[str, Any]:
    """Ask the model about `frames`. Returns {"defects": [...], "cost": dollars,
    "skipped": reason|None}. Never raises on a provider error: a critic that
    cannot answer must not cost the film."""
    from .. import openrouter as _or
    if not enabled(cfg):
        return {"defects": [], "cost": 0.0, "skipped": "the critic is off (config motion_critic) or no OpenRouter key"}
    if not frames:
        return {"defects": [], "cost": 0.0, "skipped": "no frames to look at"}
    attachments = [{"kind": "image", "mime": "image/png", "b64": base64.b64encode(png).decode("ascii"),
                    "name": f"scene_{si + 1}.png"} for si, png in frames[:MAX_FRAMES]]
    usage: dict[str, Any] = {}
    try:
        text = _or.openrouter_chat((cfg or {})["openrouter_api_key"].strip(), model, _RUBRIC,
                                   attachments=attachments, temperature=0.2, timeout=120, max_tokens=1500,
                                   extra={"response_format": _SCHEMA}, usage_sink=usage)
    except Exception as e:  # noqa: BLE001
        return {"defects": [], "cost": float(usage.get("cost") or 0.0), "skipped": f"the critic could not answer ({e})"}
    cost = float(usage.get("cost") or 0.0)
    if cost > max_cost:
        return {"defects": parse(text), "cost": cost, "skipped": f"cost ${cost:.3f} was over the ${max_cost:.2f} cap"}
    return {"defects": parse(text), "cost": cost, "skipped": None}


def faults(defects: list[dict[str, Any]], min_severity: int = 2) -> list[str]:
    """Sentences for a repair prompt or a warning, worst first."""
    keep = [d for d in defects if d["severity"] >= min_severity]
    keep.sort(key=lambda d: (-d["severity"], d["scene"]))
    return [f"Scene {d['scene']}: {d['type']} — {d['where']}".rstrip(" —") for d in keep]
