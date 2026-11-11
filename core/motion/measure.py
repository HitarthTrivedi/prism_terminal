"""
Prism Motion Graphics — measuring a scene in the real runtime
──────────────────────────────────────────────────────────────
core.motion.inspect estimates where a node will be from its spec: a text's
width as characters × font size × 0.55, nothing about the camera. That is
the right first check (no browser, instant) and the wrong last one: the
study of 11 Nov 2026 (finding M4) found a phone number the estimate put at
80..1119 px that Chromium laid out at −763..928, and a "push" shot that
zooms 1.3× moves every edge the estimate never looked at.

This lays the scene out in the runtime that will render it, seeks its
settled frame, and reads each text/image node's box in VIEWPORT
coordinates — the stage already carries the camera, so off-frame and
platform-band faults come out exact with no arithmetic of our own. It is
the same move core.reel_web.inspect makes for Studio.

inspect_all() is what the storyboard stage hands core.motion.generate
.build_spec as its `check`: the estimate's faults, with its off-frame and
safe-area guesses replaced by measured ones whenever a browser is here.
Without a browser it is the estimate alone, as before.
"""
from __future__ import annotations

import json
import os
import pathlib
from typing import Any

from . import inspect as _inspect
from .camera import safe_area

# Fault wording is shared with inspect.py on purpose: generate._REPAIR_MOVES
# keys on "runs off the edge" and "platform's own UI" to tell the model what
# to change on the second round.
_REPLACES = ("runs off the edge", "platform's own UI", "bottom band")

_MEASURE_JS = """
(ids) => {
  const want = new Set(ids);
  const eff = (el) => {
    let o = 1;
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden') return 0;
      o *= parseFloat(cs.opacity || '1');
    }
    return o;
  };
  const out = {};
  for (const host of document.querySelectorAll('[data-motion-id]')) {
    const id = host.dataset.motionId;
    if (!want.has(id)) continue;
    const box = host.firstElementChild;
    if (!box) continue;
    const r = box.getBoundingClientRect();
    out[id] = {l: r.left, t: r.top, r: r.right, b: r.bottom, o: eff(box)};
  }
  return out;
}
"""


def _measurable(scenes: list[dict]) -> dict[str, str]:
    """{node id: type} for every text/image node, including the children
    of depth layers, panels and groups — the same walk inspect makes."""
    found: dict[str, str] = {}

    def visit(node: dict) -> None:
        kind = str(node.get("type", ""))
        if kind in ("text", "image") and node.get("id"):
            found[str(node["id"])] = kind
        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                visit(child)

    for sc in scenes:
        for node in sc.get("nodes", []) or []:
            if isinstance(node, dict):
                visit(node)
    return found


def inspect_rendered(spec: dict[str, Any], at: float = 0.75) -> list[str] | None:
    """Faults read off the browser's own layout at `at` of each scene's
    length. None when there is no browser to ask — the caller keeps the
    estimate — and [] when everything measured sits inside the frame and
    the platform's safe area."""
    from .render import _playwright_available
    if not _playwright_available():
        return None
    from .resolver import resolve_motion_spec
    from .schema import validate_motion_spec
    resolved = resolve_motion_spec(validate_motion_spec(spec))
    project = resolved["project"]
    width, height = int(project["width"]), int(project["height"])
    fps = int(project.get("fps", 30) or 30)
    kinds = _measurable(resolved.get("scenes", []))
    if not kinds:
        return []
    zone = safe_area(width, height)

    from playwright.sync_api import sync_playwright
    from .. import browser as _browser
    index = pathlib.Path(os.path.dirname(__file__), "runtime", "index.html")
    faults: list[str] = []
    with sync_playwright() as pw:
        chromium = _browser.launch_chromium(
            pw, args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
        try:
            page = chromium.new_page(viewport={"width": width, "height": height})
            page.goto(index.as_uri(), wait_until="domcontentloaded")
            page.wait_for_function("typeof window.__loadSpec === 'function'", timeout=15_000)
            page.evaluate("spec => window.__loadSpec(spec)", resolved)
            try:
                page.wait_for_function("document.fonts.ready.then(() => true)", timeout=8000)
            except Exception:  # noqa: BLE001
                pass
            for sc in resolved.get("scenes", []):
                start = float(sc.get("start", 0.0) or 0.0)
                dur = float(sc.get("duration", 0.0) or 0.0)
                moment = start + dur * at
                page.evaluate(f"window.__seek({int(round(moment * fps))})")
                boxes = page.evaluate(_MEASURE_JS, list(kinds))
                for nid, m in boxes.items():
                    if m["o"] < 0.05 or m["r"] - m["l"] <= 0:
                        continue  # not on screen at this moment
                    kind = kinds[nid]
                    where = (f'{m["l"]:.0f},{m["t"]:.0f} to {m["r"]:.0f},{m["b"]:.0f} '
                             f"at {moment:.1f}s, measured in the browser with the camera applied")
                    if m["l"] < 0 or m["t"] < 0 or m["r"] > width or m["b"] > height:
                        faults.append(
                            f'node "{nid}" ({kind}) runs off the edge of the {width}x{height} '
                            f"frame as drawn — its box is {where}; pull it inside, and "
                            "check its anchor against its position")
                    elif zone.get("vertical") and m["t"] < zone["top"]:
                        faults.append(
                            f'node "{nid}" ({kind}) sits inside the top {zone["top"]}px of the '
                            f"frame where the platform's own UI covers it — its box is {where}; "
                            f'keep text and logos below y={zone["top"]}')
                    elif zone.get("vertical") and m["b"] > zone["bottom"]:
                        faults.append(
                            f'node "{nid}" ({kind}) reaches into the bottom band of the frame '
                            f"where the platform's own UI (captions and buttons) covers it — "
                            f'its box is {where}; keep text and logos above y={zone["bottom"]}')
        finally:
            chromium.close()
    return faults


def inspect_all(spec: dict[str, Any]) -> list[str]:
    """The estimate's faults with the geometry ones measured for real when
    a browser is here. Same signature as inspect.inspect, so build_spec's
    `check` takes it unchanged."""
    estimated = _inspect.inspect(spec)
    try:
        measured = inspect_rendered(spec)
    except Exception:  # noqa: BLE001 — a browser hiccup must not fail the scene; keep the estimate
        measured = None
    if measured is None:
        return estimated
    kept = [f for f in estimated if not any(key in f for key in _REPLACES)]
    return kept + measured
