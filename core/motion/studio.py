"""
Prism Motion Graphics — the Studio editing surface
───────────────────────────────────────────────────
The Motion counterpart of core.reel_edit: the finished spec opens in the
browser with an edit layer — scenes and continuity threads in the left
rail, pose / material / shot / handoff controls in the inspector, camera
and handoff marks on the timeline, a safe-area overlay, and start /
midpoint / settled / exit review points for every shot.

The one rule this module exists to keep: **preview and export cannot
differ.** An edit is a small record applied to the scene-local spec
BEFORE validation and resolution (`apply_edits`), and both the editor's
preview (`/preview` on the local server) and `render()` go through that
same function. The page never styles a node by hand.

Records (everything from the browser is sanitised by `clean_edits`):

    {"scene": i, "node": "<id>", "dx", "dy", "scale", "rotation",
     "opacity", "hidden", "text", "material": {blur, transmission,
     border_light, inner_shadow, specular}}
    {"scene": i, "root": true, "seconds", "shot": {intent, target, zoom},
     "handoff_easing": "<easing>"}

Stdlib only apart from the sibling motion modules; no browser.
"""
from __future__ import annotations

import copy
import json
import os
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import camera as _camera
from . import beats as _beats
from . import continuity as _continuity
from .resolver import resolve_motion_spec
from .schema import _valid_easing, validate_motion_spec

EDITS_KEY = "_motion_edits"
_RUNTIME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime")
_MATERIAL_KEYS = ("blur", "transmission", "border_light", "inner_shadow", "specular")


# ── sanitising what the browser sends ────────────────────────────────────────

def _num(value: Any, default: float, lo: float, hi: float, digits: int = 2) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out:  # NaN
        return default
    return round(max(lo, min(hi, out)), digits)


def _clean_node_edit(raw: dict) -> Optional[dict]:
    node_id = str(raw.get("node", ""))[:80]
    if not node_id:
        return None
    out: Dict[str, Any] = {"scene": int(raw["scene"]), "node": node_id}
    dx = _num(raw.get("dx"), 0.0, -4000, 4000)
    dy = _num(raw.get("dy"), 0.0, -4000, 4000)
    scale = _num(raw.get("scale"), 1.0, 0.05, 20, 3)
    rotation = _num(raw.get("rotation"), 0.0, -360, 360, 1)
    if dx:
        out["dx"] = dx
    if dy:
        out["dy"] = dy
    if scale != 1.0:
        out["scale"] = scale
    if rotation:
        out["rotation"] = rotation
    if raw.get("opacity") is not None:
        out["opacity"] = _num(raw.get("opacity"), 1.0, 0.0, 1.0)
    if raw.get("hidden"):
        out["hidden"] = True
    if isinstance(raw.get("text"), str):
        out["text"] = raw["text"][:400]
    material = raw.get("material")
    if isinstance(material, dict):
        kept = {}
        for key in _MATERIAL_KEYS:
            if material.get(key) is not None:
                hi = 40.0 if key == "blur" else 1.0
                kept[key] = _num(material.get(key), 0.0, 0.0, hi, 3)
        if kept:
            out["material"] = kept
    return out if len(out) > 2 else None


def _clean_scene_edit(raw: dict) -> Optional[dict]:
    out: Dict[str, Any] = {"scene": int(raw["scene"]), "root": True}
    if raw.get("seconds") is not None:
        out["seconds"] = _num(raw.get("seconds"), 3.0, 0.5, 30.0, 2)
    shot = _camera.normalize_shot(raw.get("shot"))
    if shot:
        out["shot"] = shot
    easing = raw.get("handoff_easing")
    if isinstance(easing, str) and _valid_easing(easing):
        out["handoff_easing"] = easing.strip()
    return out if len(out) > 2 else None


def clean_edits(raw: Any) -> List[dict]:
    """The browser's records, bounded and typed; junk and no-op records are
    dropped rather than raised — the page is user input."""
    if not isinstance(raw, list):
        return []
    out: List[dict] = []
    seen: set = set()
    for item in raw[:400]:
        if not isinstance(item, dict):
            continue
        try:
            int(item.get("scene"))
        except (TypeError, ValueError):
            continue
        if int(item["scene"]) < 0:
            continue
        cleaned = _clean_scene_edit(item) if item.get("root") else _clean_node_edit(item)
        if not cleaned:
            continue
        key = (cleaned["scene"], cleaned.get("node", "/root"))
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


# ── applying edits to the spec ───────────────────────────────────────────────

def _find_node(scene: dict, node_id: str) -> Optional[dict]:
    def visit(node: dict) -> Optional[dict]:
        if str(node.get("id", "")) == node_id:
            return node
        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                hit = visit(child)
                if hit is not None:
                    return hit
        return None

    for node in scene.get("nodes", []) or []:
        if isinstance(node, dict):
            hit = visit(node)
            if hit is not None:
                return hit
    return None


def apply_edits(spec: dict, edits: Any) -> dict:
    """A deep copy of the scene-local spec with the edits folded in — the
    spec render() validates, resolves and films. Idempotent by shape: the
    copy carries no `_motion_edits` of its own, so a saved, already-applied
    spec is not edited twice."""
    out = copy.deepcopy(spec)
    out.pop(EDITS_KEY, None)
    records = clean_edits(edits)
    if not records:
        return out
    scenes = [s for s in out.get("scenes", []) or [] if isinstance(s, dict)]
    timing_changed = False
    for rec in records:
        idx = rec["scene"]
        if idx >= len(scenes):
            continue
        scene = scenes[idx]
        if rec.get("root"):
            if "seconds" in rec:
                scene["duration"] = rec["seconds"]
                timing_changed = True
            if "shot" in rec:
                scene["shot"] = dict(rec["shot"])
            if "handoff_easing" in rec:
                scene["handoff_easing"] = rec["handoff_easing"]
            continue
        node = _find_node(scene, rec["node"])
        if node is None:
            continue
        pos = node.get("position") or [0, 0]
        try:
            x, y = float(pos[0]), float(pos[1])
        except (TypeError, ValueError, IndexError):
            x, y = 0.0, 0.0
        node["position"] = [round(x + rec.get("dx", 0.0), 2), round(y + rec.get("dy", 0.0), 2)]
        if "scale" in rec:
            sc = node.get("scale") or [1, 1]
            try:
                sx, sy = float(sc[0]), float(sc[1])
            except (TypeError, ValueError, IndexError):
                sx, sy = 1.0, 1.0
            node["scale"] = [round(sx * rec["scale"], 4), round(sy * rec["scale"], 4)]
        if "rotation" in rec:
            try:
                node["rotation"] = round(float(node.get("rotation", 0) or 0) + rec["rotation"], 2)
            except (TypeError, ValueError):
                node["rotation"] = rec["rotation"]
        if "opacity" in rec:
            node["opacity"] = rec["opacity"]
        if rec.get("hidden"):
            node["visible"] = False
        if "text" in rec and node.get("type") == "text":
            node["content"] = rec["text"]
        if "material" in rec and node.get("type") == "glass_panel":
            node.update(rec["material"])
    if timing_changed:
        project = out.setdefault("project", {})
        project["duration"] = round(sum(float(s.get("duration", 0) or 0) for s in scenes), 3)
    out["_motion_edits_applied"] = len(records)
    return out


def resolved_for(spec: dict, edits: Any) -> dict:
    """Edits applied, validated, resolved — exactly what render() films."""
    return resolve_motion_spec(validate_motion_spec(apply_edits(spec, edits)))


def review_points(scene: dict) -> Dict[str, float]:
    """Start, midpoint, settled and exit times of one resolved scene — the
    four states every shot must pass visual review at."""
    start = float(scene.get("start", 0) or 0)
    dur = max(0.1, float(scene.get("duration", 0) or 0))
    return {
        "start": round(start + min(0.05, dur * 0.1), 3),
        "mid": round(start + dur * 0.5, 3),
        "settled": round(start + dur * 0.8, 3),
        "exit": round(start + dur - min(0.05, dur * 0.1), 3),
    }


def preview_payload(spec: dict, edits: Any) -> dict:
    resolved = resolved_for(spec, edits)
    compiled = resolved.get("_continuity_compiled") or {}
    grid = _beats.timing_grid(resolved)
    return {
        "resolved": resolved,
        "review": [review_points(s) for s in resolved.get("scenes", [])],
        "errors": [e["message"] for e in compiled.get("errors", [])],
        "warnings": [w["message"] for w in compiled.get("warnings", [])],
        "beats": {"bpm": grid["bpm"], "offset": grid["offset"], "source": grid["source"],
                  "beats": grid["beats"], "bars": grid["bars"], "markers": grid["markers"]},
    }


# ── the editor page ──────────────────────────────────────────────────────────

def _runtime_asset(name: str) -> str:
    with open(os.path.join(_RUNTIME, name), encoding="utf-8") as fh:
        return fh.read()


def editable_html(spec: dict, edits: Any = None) -> str:
    """The runtime page (the same index.html the renderer films) with the
    studio layer on top. Scripts stay relative (`gsap.min.js`, …) — serve()
    answers them from the runtime folder."""
    project = (spec.get("project") or {})
    safe = _camera.safe_area(int(project.get("width", 1080) or 1080),
                             int(project.get("height", 1920) or 1920))
    edits = clean_edits(edits if edits is not None else spec.get(EDITS_KEY))
    source = validate_motion_spec(apply_edits(spec, []))
    payload = preview_payload(spec, edits)
    inject = (
        "<script>window.__MOTION_SOURCE__=" + json.dumps(source)
        + ";window.__MOTION_PREVIEW__=" + json.dumps(payload)
        + ";window.__MOTION_EDITS__=" + json.dumps(edits)
        + ";window.__MOTION_SAFE__=" + json.dumps(safe)
        + ";window.__MOTION_EASINGS__=" + json.dumps(_EASING_MENU)
        + ";window.__MOTION_SHOTS__=" + json.dumps(list(_camera.SHOT_INTENTS))
        + ";</script><style>" + _runtime_asset("studio.css") + "</style>"
        + "<script>" + _runtime_asset("studio.js") + "</script>"
    )
    html = _runtime_asset("index.html")
    return html.replace("</body>", inject + "</body>", 1)


_EASING_MENU = ["power2.inOut", "power3.inOut", "sine.inOut", "power2.out",
                "power3.out", "expo.inOut", "circ.inOut", "none"]


# ── follow-up prompting, scoped to the selection ─────────────────────────────

def _pose_line(scene_no: int, node: dict) -> str:
    return (f'scene {scene_no} node "{node.get("id", "")}" settles at position '
            f'{list(node.get("position") or [0, 0])}, scale '
            f'{list(node.get("scale") or [1, 1])}')


def followup_prompt(change: str, context: dict, spec: dict) -> str:
    """One scene's worth of context plus the requested change — not the
    whole spec. The reply is the corrected scene in the same shape
    build_spec() asks for, so apply_followup() can parse it."""
    scenes = [s for s in spec.get("scenes", []) or [] if isinstance(s, dict)]
    try:
        idx = max(0, min(len(scenes) - 1, int(context.get("scene_index", 0) or 0)))
    except (TypeError, ValueError):
        idx = 0
    scene = scenes[idx] if scenes else {}
    node_id = str(context.get("node_id", "") or "")
    key = str(context.get("continuity_key", "") or "")
    node = _find_node(scene, node_id) if node_id else None
    if node is not None and not key:
        key = str(node.get("continuity_key", "") or "")

    selection = f"scene {idx + 1} of {len(scenes)}"
    if scene.get("id"):
        selection += f' ("{scene["id"]}")'
    if node is not None:
        selection += f', node "{node_id}" ({node.get("type", "node")})'
    if key:
        selection += f', continuity_key "{key}"'

    thread: List[str] = []
    if key:
        for n, other in enumerate(scenes, 1):
            if n - 1 == idx:
                continue
            for cand in _walk(other):
                if cand.get("continuity_key") == key:
                    thread.append(_pose_line(n, cand))
    scene_json = json.dumps({k: v for k, v in scene.items()
                             if k in ("id", "duration", "shot", "transition_in", "nodes")},
                            ensure_ascii=False)
    return (
        f"CHANGE REQUESTED IN PRISM STUDIO: {change.strip()}\n\n"
        f"SELECTION: {selection}.\n\n"
        f"THE SCENE AS IT IS NOW (scene {idx + 1}):\n```json\n{scene_json}\n```\n\n"
        + (("THE SAME SUBJECT ELSEWHERE — keep its pose within reach of these "
            "so the cuts still morph:\n" + "\n".join(f"- {t}" for t in thread) + "\n\n")
           if thread else "")
        + f"Rewrite ONLY scene {idx + 1}. Keep every node the change does not "
        "involve exactly as it is, with the same ids. Keep the "
        '"continuity_key" on the carried subject. Reply with ONLY the JSON '
        'object {"shot": {...}, "nodes": [...]} for this one scene, in a '
        "```json fenced block, nothing before or after it."
    )


def _walk(scene: dict):
    stack = [n for n in scene.get("nodes", []) or [] if isinstance(n, dict)]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(c for c in node.get("children", []) or [] if isinstance(c, dict))


def apply_followup(spec: dict, scene_index: int, reply: str) -> Tuple[Optional[dict], str]:
    """The model's one-scene reply folded into a copy of the spec.

    Returns (new_spec, note); new_spec is None when the reply carried no
    usable scene. Hand edits on the replaced scene are dropped (they
    targeted nodes that may no longer exist); edits on other scenes stay.
    """
    from .generate import parse_scene
    from . import inspect as _inspect

    scene = parse_scene(reply or "")
    if scene is None:
        return None, "the reply carried no scene JSON — the motion graphic is unchanged"
    out = copy.deepcopy(spec)
    scenes = [s for s in out.get("scenes", []) or [] if isinstance(s, dict)]
    if not (0 <= scene_index < len(scenes)):
        return None, "the selected scene no longer exists"
    old = scenes[scene_index]
    scene["id"] = old.get("id", f"scene_{scene_index}")
    scene["duration"] = old.get("duration", 3.0)
    for key in ("transition_in", "handoff_easing"):
        if key in old and key not in scene:
            scene[key] = old[key]
    scenes[scene_index] = scene
    out["scenes"] = scenes
    out[EDITS_KEY] = [e for e in clean_edits(out.get(EDITS_KEY))
                      if e["scene"] != scene_index]
    if not out[EDITS_KEY]:
        del out[EDITS_KEY]
    notes = [f"scene {scene_index + 1} rewritten — {len(scene.get('nodes', []))} node(s)"]
    try:
        checked = validate_motion_spec(copy.deepcopy(out))
        faults = _inspect.inspect({"project": checked.get("project", {}),
                                   "scenes": [checked["scenes"][scene_index]]})
        rep = _continuity.report(checked)
    except Exception as e:                                # noqa: BLE001
        return None, f"the rewritten scene does not validate ({e})"
    if faults:
        notes.append(f"{len(faults)} layout problem(s): " + "; ".join(faults[:3]))
    if rep["errors"]:
        notes.append("continuity broken: " + "; ".join(e["message"] for e in rep["errors"][:2]))
    return out, ". ".join(notes)


# ── the local server the editor page talks to ────────────────────────────────

def serve(spec: dict, on_save: Optional[Callable[[list], None]] = None,
          on_render: Optional[Callable[[list], None]] = None,
          on_refine: Optional[Callable[[str, dict], None]] = None
          ) -> Tuple[str, Callable[[], None]]:
    """Serve the editor on 127.0.0.1 and hand edits back through callbacks.

    Same contract as core.reel_edit.serve(): `on_save(edits)` for Save
    and autosave, `on_render(edits)` for Render, `on_refine(change,
    context)` for the prompt row — all on the server's thread. `/preview`
    is answered here without a callback: the page posts its edits and gets
    back the resolved spec it should play.
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    html = editable_html(spec).encode("utf-8")
    base_spec = copy.deepcopy(spec)
    runtime_root = os.path.realpath(_RUNTIME)
    content_types = {".js": "application/javascript", ".css": "text/css",
                     ".html": "text/html; charset=utf-8"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, html, "text/html; charset=utf-8")
                return
            rel = self.path.split("?", 1)[0].lstrip("/")
            target = os.path.realpath(os.path.join(runtime_root, rel))
            ext = os.path.splitext(target)[1]
            if (not target.startswith(runtime_root + os.sep) or ext not in content_types
                    or not os.path.isfile(target) or os.path.basename(target) == "index.html"):
                self.send_response(404)
                self.end_headers()
                return
            with open(target, "rb") as fh:
                self._send(200, fh.read(), content_types[ext])

        def _same_origin(self) -> bool:
            origin = self.headers.get("Origin", "")
            return not origin or origin.startswith("http://127.0.0.1:")

        def _body(self, cap: int = 2_000_000) -> dict:
            try:
                length = min(int(self.headers.get("Content-Length") or 0), cap)
                data = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, OSError):
                data = {}
            return data if isinstance(data, dict) else {}

        def do_POST(self):
            if not self._same_origin():
                self.send_response(403)
                self.end_headers()
                return
            if self.path == "/refine":
                self._refine()
                return
            if self.path == "/preview":
                data = self._body()
                try:
                    payload = preview_payload(base_spec, data.get("edits"))
                    self._send(200, json.dumps(payload).encode())
                except Exception as e:                    # noqa: BLE001
                    self._send(400, json.dumps({"error": str(e)[:400]}).encode())
                return
            callback = {"/save": on_save, "/autosave": on_save, "/render": on_render}
            if self.path not in callback:
                self.send_response(404)
                self.end_headers()
                return
            data = self._body()
            if "edits" not in data:
                self.send_response(400)
                self.end_headers()
                return
            edits = clean_edits(data.get("edits"))
            self._send(200, json.dumps({"ok": True, "edits": len(edits)}).encode())
            fn = callback[self.path]
            if fn is not None:
                try:
                    fn(edits)
                except Exception:                         # noqa: BLE001
                    pass

        def _refine(self):
            data = self._body(16_000)
            change = str(data.get("change", "")).strip()[:2000]
            context = data.get("context") if isinstance(data.get("context"), dict) else {}
            try:
                scene_index = max(0, int(context.get("scene_index", 0) or 0))
            except (TypeError, ValueError):
                scene_index = 0
            clean_context = {
                "scene_index": scene_index,
                "scene_id": str(context.get("scene_id", ""))[:64],
                "node_id": str(context.get("node_id", ""))[:80],
                "continuity_key": str(context.get("continuity_key", ""))[:80],
                "label": str(context.get("label", ""))[:160],
            }
            ok = bool(change and on_refine)
            self._send(200 if ok else 400, json.dumps({"ok": ok}).encode())
            if ok:
                try:
                    on_refine(change, clean_context)
                except Exception:                         # noqa: BLE001
                    pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True,
                              name="prism-motion-studio")
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"

    def stop():
        try:
            server.shutdown()
            server.server_close()
        except Exception:                                 # noqa: BLE001
            pass

    return url, stop
