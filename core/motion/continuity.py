"""
Prism Motion Graphics — continuity compiler
────────────────────────────────────────────
Turns the ``continuity_key`` contract (schema.py normalises it, generate.py
asks the model for it) into something the renderer can actually play.

The model is asked to keep one visual subject alive across every cut. It
frequently disobeys: the subject re-enters from the centre, fades to
nothing before the cut, or is simply forgotten for a scene. Rather than
trusting the reply, this module reads each subject's last authored pose in
one scene and its first authored pose in the next, and synthesises a
matched *bridge*: the outgoing instance travels to the incoming pose while
the incoming instance travels from the outgoing pose, over the same window
with the same easing, so at every frame both instances sit at the same
place. With the scene containers crossfading (the ``morph`` transition in
runtime/transitions.js) the two instances read as one object transforming.

What cannot be repaired is reported as a fault with a repair instruction a
model can act on, and render.py refuses to render a spec whose errors are
unresolved — a broken handoff should fail before a minute of frames is
encoded, not after.

Pure Python, no browser: pose, timing and scene order all exist in the
spec before a single frame is drawn (same argument inspect.py makes).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .schema import _valid_easing

# The transition compiled onto any cut that carries a bridged subject. The
# other named transitions (push/zoom/...) move or scale the whole scene
# container, which would drag the bridged subject off its matched path.
MORPH_TRANSITION = "morph"

# The profile whose scenes are expected to carry the spine in every shot.
CINEMATIC_PROFILE = "cinematic_glass"

# Handoff limits. A bridge faster than this reads as a pop, not a move —
# the value is canvas-relative (diagonals per second) so 9:16 and 16:9
# projects get the same judgement. Scale is judged as a ratio.
MAX_BRIDGE_SPEED_DIAGONALS_PER_S = 1.6
MAX_BRIDGE_SCALE_RATIO = 6.0
MIN_BRIDGE_SECONDS = 0.08

BRIDGE_EASING = "power2.inOut"


def handoff_overlap(prev_duration: float, this_duration: float) -> float:
    """How long two adjacent scenes coexist around their cut.

    One source of truth for resolver.py (which stamps the visibility
    windows) and this compiler (which must know the bridge length before
    the resolver runs, so build_spec() can report faults during
    generation). Mirrors core.reel_web._plan(): half a second at most, and
    never more than a third of either neighbour so a short scene is not
    swallowed by its own transition.
    """
    try:
        prev_d = float(prev_duration or 0.0)
        this_d = float(this_duration or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(0.5, prev_d / 3.0, this_d / 3.0))


def bridge_window(cut_at: float, overlap: float) -> Tuple[float, float]:
    """The absolute [start, end] a bridge plays over — the same window
    resolver.py gives the two scenes' visibility (transitionInStart ..
    transitionOutEnd), so both subject instances are on screen for all of
    it."""
    return (round(cut_at - overlap, 3), round(cut_at + overlap * 0.4, 3))


# ── Pose reading ─────────────────────────────────────────────────────────────

def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(out) or math.isinf(out):
        return default
    return out


def _pair(value: Any, default: Tuple[float, float]) -> Tuple[float, float]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (_num(value[0], default[0]), _num(value[1], default[1]))
    return default


def _layout_centre(layout: Any) -> Optional[Tuple[float, float]]:
    """Where a particle_field layout puts its tiles, as one point."""
    if not isinstance(layout, dict):
        return None
    kind = layout.get("kind")
    if kind == "box" or kind == "scatter":
        box = layout.get("box")
        if isinstance(box, (list, tuple)) and len(box) == 4:
            return ((_num(box[0]) + _num(box[2])) / 2, (_num(box[1]) + _num(box[3])) / 2)
    if kind == "band":
        return ((_num(layout.get("x0"), 0) + _num(layout.get("x1"), 1080)) / 2, _num(layout.get("y")))
    if kind == "column":
        return (_num(layout.get("x")), (_num(layout.get("y0"), 0) + _num(layout.get("y1"), 1920)) / 2)
    if kind == "points":
        pts = [p for p in (layout.get("points") or []) if isinstance(p, (list, tuple)) and len(p) == 2]
        if pts:
            return (sum(_num(p[0]) for p in pts) / len(pts), sum(_num(p[1]) for p in pts) / len(pts))
    if kind == "ring":
        c = layout.get("center") or layout.get("centre")
        if isinstance(c, (list, tuple)) and len(c) == 2:
            return (_num(c[0]), _num(c[1]))
    return None


def _pose(node: Dict[str, Any], parent_pos: Tuple[float, float],
          at_start: bool = False) -> Dict[str, float]:
    """A node's settled, authored pose in scene (world) space. A
    particle_field sits at [0, 0] and lays its tiles out elsewhere, so its
    pose is the centre of a layout — the last one when the field hands
    off (`at_start` False), the FIRST one when it is handed to: a field
    that arrives as a band and streams away as a column must be bridged
    to the band, or the whole field slides in from the column's centre
    (the composed reel's second scene, 11 Sep 2026)."""
    x, y = _pair(node.get("position"), (0.0, 0.0))
    if node.get("type") == "particle_field":
        phases = [ph for ph in (node.get("phases") or []) if isinstance(ph, dict)]
        for phase in (phases if at_start else reversed(phases)):
            centre = _layout_centre(phase.get("layout"))
            if centre is not None:
                x, y = x + centre[0], y + centre[1]
                break
    sx, sy = _pair(node.get("scale"), (1.0, 1.0))
    return {
        "x": parent_pos[0] + x,
        "y": parent_pos[1] + y,
        "scale_x": sx,
        "scale_y": sy,
        "rotation": _num(node.get("rotation"), 0.0),
        "opacity": _num(node.get("opacity"), 1.0),
    }


def _keyed_nodes(scene: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """{continuity_key: [instance, ...]} for one scene. More than one
    instance per key in a scene is itself a fault (see report())."""
    found: Dict[str, List[Dict[str, Any]]] = {}

    def visit(node: Dict[str, Any], parent_pos: Tuple[float, float]) -> None:
        pos = _pair(node.get("position"), (0.0, 0.0))
        world = (parent_pos[0] + pos[0], parent_pos[1] + pos[1])
        key = node.get("continuity_key")
        if isinstance(key, str) and key:
            found.setdefault(key, []).append({
                "node": node,
                "id": str(node.get("id", "")),
                "pose": _pose(node, parent_pos),
                "pose_in": _pose(node, parent_pos, at_start=True),
            })
        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                visit(child, world)

    for node in scene.get("nodes", []) or []:
        if isinstance(node, dict):
            visit(node, (0.0, 0.0))
    return found


# ── Analysis ─────────────────────────────────────────────────────────────────

def _scene_label(index: int, scene: Dict[str, Any]) -> str:
    sid = scene.get("id")
    return f"scene {index + 1}" + (f' ("{sid}")' if sid else "")


def _plan_bridge(out_inst: Dict[str, Any], in_inst: Dict[str, Any],
                 start: float, end: float,
                 diagonal: float) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """The delta one subject must travel across a cut, or why it cannot."""
    a, b = out_inst["pose"], in_inst.get("pose_in", in_inst["pose"])
    seconds = end - start
    if seconds < MIN_BRIDGE_SECONDS:
        return None, "the cut is too short to bridge"
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    distance = math.hypot(dx, dy)
    speed = distance / seconds / max(1.0, diagonal)
    if speed > MAX_BRIDGE_SPEED_DIAGONALS_PER_S:
        return None, (f"it would have to travel {distance:.0f}px in "
                      f"{seconds:.2f}s, which reads as a jump — move the "
                      "incoming pose closer to the outgoing one, or give the "
                      "neighbouring scenes more time")
    for axis in ("scale_x", "scale_y"):
        lo, hi = sorted((abs(a[axis]), abs(b[axis])))
        if lo <= 1e-6 or hi / lo > MAX_BRIDGE_SCALE_RATIO:
            return None, (f"its scale changes from {a[axis]:g} to {b[axis]:g} "
                          "across the cut — more than a bridge can carry; "
                          "bring the two scales closer")
    if a["opacity"] <= 0.05:
        return None, ("its outgoing instance settles at opacity "
                      f"{a['opacity']:g}, so there is nothing visible to hand "
                      "off — leave it visible until the cut")
    if b["opacity"] <= 0.05:
        return None, ("its incoming instance settles at opacity "
                      f"{b['opacity']:g}, so nothing visible receives the "
                      "handoff — let it settle visible")
    return {
        "dx": round(dx, 3), "dy": round(dy, 3),
        "dscale_x": round(b["scale_x"] - a["scale_x"], 4),
        "dscale_y": round(b["scale_y"] - a["scale_y"], 4),
        "drotation": round(b["rotation"] - a["rotation"], 3),
        "start": start, "end": end,
    }, None


def report(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Analyse a validated, scene-local spec (times counted from each
    scene's own start — the shape build_spec() assembles and
    validate_motion_spec() returns) without changing it.

    Returns {"threads", "bridges", "errors", "warnings"}:
      threads   {key: [{"scene", "scene_index", "node", "pose"}, ...]}
      bridges   one planned bridge per adjacent keyed pair that can be
                matched — what compile() will write onto the nodes
      errors    {"scene_index", "key", "message"} — a handoff that cannot
                be rendered faithfully; render.py refuses these
      warnings  same shape — the spine contract is bent but the piece
                still renders (only raised for the cinematic profile)
    """
    scenes = [s for s in spec.get("scenes", []) or [] if isinstance(s, dict)]
    project = spec.get("project") or {}
    diagonal = math.hypot(_num(project.get("width"), 1080.0),
                          _num(project.get("height"), 1920.0))
    cinematic = spec.get("_motion_profile") == CINEMATIC_PROFILE

    per_scene = [_keyed_nodes(s) for s in scenes]
    threads: Dict[str, List[Dict[str, Any]]] = {}
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    bridges: List[Dict[str, Any]] = []

    for idx, (scene, keyed) in enumerate(zip(scenes, per_scene)):
        for key, instances in keyed.items():
            if len(instances) > 1:
                ids = ", ".join(f'"{i["id"]}"' for i in instances)
                errors.append({
                    "scene_index": idx, "key": key,
                    "message": (f'{_scene_label(idx, scene)} gives continuity_key '
                                f'"{key}" to {len(instances)} nodes ({ids}) — a '
                                "subject can only be one node per scene; keep the "
                                "key on the hero and drop it from the others")})
            inst = instances[0]
            threads.setdefault(key, []).append({
                "scene": str(scene.get("id", "")), "scene_index": idx,
                "node": inst["id"], "pose": inst["pose"],
                "type": str(inst["node"].get("type", "")),
            })

    # Thread gaps: a subject that vanishes for a scene and then returns.
    # A gap is not a broken render — the subject leaves and comes back
    # through ordinary transitions — so it is a warning the repair pass
    # and Studio surface, never a refusal (a finished twenty-minute plan
    # was once thrown away over one missing key).
    for key, items in threads.items():
        seen = [it["scene_index"] for it in items]
        for a, b in zip(seen, seen[1:]):
            if b - a > 1:
                missing = ", ".join(_scene_label(i, scenes[i]) for i in range(a + 1, b))
                warnings.append({
                    "scene_index": a + 1, "key": key,
                    "message": (f'continuity_key "{key}" is carried by '
                                f"{_scene_label(a, scenes[a])} and returns in "
                                f"{_scene_label(b, scenes[b])} but is missing from "
                                f"{missing} — that is a cold reset; give {missing} "
                                "a node with the same key so the subject never "
                                "leaves the screen")})

    # Adjacent pairs that share a key: plan the bridge or explain why not.
    for idx in range(1, len(scenes)):
        prev_scene, this_scene = scenes[idx - 1], scenes[idx]
        overlap = handoff_overlap(prev_scene.get("duration"), this_scene.get("duration"))
        shared = [k for k in per_scene[idx - 1] if k in per_scene[idx]]
        if not shared:
            continue
        if overlap <= 0.02:
            errors.append({
                "scene_index": idx, "key": shared[0],
                "message": (f"{_scene_label(idx, this_scene)} carries "
                            + ", ".join(f'"{k}"' for k in shared)
                            + f" from {_scene_label(idx - 1, prev_scene)} but one of "
                            "the two scenes is too short to overlap — the handoff "
                            "would be a hard cut; give both scenes at least 0.5s")})
            continue
        start, end = bridge_window(0.0, overlap)  # relative to the cut
        for key in shared:
            out_inst = per_scene[idx - 1][key][0]
            in_inst = per_scene[idx][key][0]
            plan, why = _plan_bridge(out_inst, in_inst, start, end, diagonal)
            if plan is None:
                errors.append({
                    "scene_index": idx, "key": key,
                    "message": (f'continuity_key "{key}" cannot be handed from '
                                f'node "{out_inst["id"]}" in {_scene_label(idx - 1, prev_scene)} '
                                f'to node "{in_inst["id"]}" in {_scene_label(idx, this_scene)}: '
                                f"{why}")})
                continue
            plan.update({
                "key": key, "scene_index": idx,
                "out_scene": str(prev_scene.get("id", "")), "out_node": out_inst["id"],
                "in_scene": str(this_scene.get("id", "")), "in_node": in_inst["id"],
            })
            bridges.append(plan)

    # Text the CAMERA clips: the inspector checks authored boxes against the
    # frame, but a shot that parks the camera off-centre moves the frame.
    # Read the compiled camera at each scene's settled time and refuse a
    # text node whose box falls outside what the camera shows.
    errors.extend(_camera_clip_faults(spec, scenes))

    if cinematic and scenes:
        # A spine has to TRANSFORM. The same node type at the same pose for
        # three scenes running is a logo on a slide deck, not a subject
        # changing state (the Alphakore run carried its mark that way for
        # seven scenes). Reported once per thread, at the third scene.
        for key, items in threads.items():
            run = 1
            for a, b in zip(items, items[1:]):
                pa, pb = a["pose"], b["pose"]
                same = (b["scene_index"] == a["scene_index"] + 1 and a["type"] == b["type"]
                        and abs(pa["x"] - pb["x"]) < 8 and abs(pa["y"] - pb["y"]) < 8
                        and abs(pa["scale_x"] - pb["scale_x"]) < 0.05)
                run = run + 1 if same else 1
                if run == 3:
                    warnings.append({
                        "scene_index": b["scene_index"], "key": key,
                        "message": (f'continuity_key "{key}" is the same {a["type"]} at the '
                                    f"same pose in scenes {b['scene_index'] - 1} to "
                                    f"{b['scene_index'] + 1} — the subject never changes "
                                    "state; a spine transforms from beat to beat (gathers, "
                                    "streams, converges, opens, resolves), it does not sit")})
                    break
        for idx, (scene, keyed) in enumerate(zip(scenes, per_scene)):
            if not keyed:
                warnings.append({
                    "scene_index": idx, "key": "",
                    "message": (f"{_scene_label(idx, scene)} has no node with a "
                                'continuity_key — the visual spine is dropped '
                                "here; give the subject that carries this shot the "
                                "key it had before")})
        opening = per_scene[0]
        closing = per_scene[-1]
        if len(scenes) > 1 and opening:
            for key in opening:
                if key not in closing:
                    warnings.append({
                        "scene_index": len(scenes) - 1, "key": key,
                        "message": (f'continuity_key "{key}" opens the piece but '
                                    f"the final {_scene_label(len(scenes) - 1, scenes[-1])} "
                                    "does not resolve it — end on the same subject "
                                    "becoming the logo, answer or call to action")})

    return {"threads": threads, "bridges": bridges,
            "errors": errors, "warnings": warnings}


def _camera_clip_faults(spec: Dict[str, Any], scenes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from . import camera as _camera
    from .inspect import _node_bounds
    project = spec.get("project") or {}
    width = int(_num(project.get("width"), 1080)); height = int(_num(project.get("height"), 1920))
    if not any(isinstance(s.get("shot"), dict) for s in scenes):
        return []
    # scene starts are scene-local here (build_spec's shape); lay them out
    cursor, laid = 0.0, []
    for s in scenes:
        laid.append(dict(s, start=cursor)); cursor += _num(s.get("duration"), 0.0)
    world = {}
    for s in laid:
        def visit(node, parent=(0.0, 0.0)):
            pos = _pair(node.get("position"), (0.0, 0.0))
            here = (parent[0] + pos[0], parent[1] + pos[1])
            if node.get("id") and not node.get("_no_position"):
                cx, cy = _camera.node_centre(node)
                world[str(node["id"])] = (parent[0] + cx, parent[1] + cy)
            for c in node.get("children") or []:
                if isinstance(c, dict):
                    visit(c, here)
        for n in s.get("nodes") or []:
            if isinstance(n, dict):
                visit(n)
    tracks = _camera.compile_tracks(laid, width, height, world) or []
    out: List[Dict[str, Any]] = []
    for idx, s in enumerate(laid):
        settled = s["start"] + _num(s.get("duration"), 0.0) * 0.8
        view = _camera.visible_rect(_camera.state_at(tracks, settled, width, height), width, height)
        def check(node, parent=(0.0, 0.0), gone=False):
            pos = _pair(node.get("position"), (0.0, 0.0))
            here = (parent[0] + pos[0], parent[1] + pos[1])
            # a node whose exit is over before the shot settles has left the
            # frame on purpose (the composed reel's bubbles, still leaving
            # across a cut): the settled camera cannot clip what is gone
            anim = node.get("animation") if isinstance(node.get("animation"), dict) else {}
            ex = anim.get("exit") if isinstance(anim.get("exit"), dict) else None
            if ex and _num(ex.get("time"), 1e9) + _num(ex.get("duration"), 0.0) <= _num(s.get("duration"), 0.0) * 0.8:
                gone = True
            if not gone and node.get("type") == "text" and str(node.get("content") or "").strip():
                shifted = dict(node, position=list(here))
                b = _node_bounds(shifted, width, height)
                if b:
                    left, top, right, bottom = b
                    ix = max(0.0, min(right, view[2]) - max(left, view[0]))
                    iy = max(0.0, min(bottom, view[3]) - max(top, view[1]))
                    area = max(1.0, (right - left) * (bottom - top))
                    # a card cut by the frame edge is the reference's own
                    # grammar; text is clipped when most of it is out of view
                    if ix * iy / area < 0.6:
                        out.append({"scene_index": idx, "key": "",
                                    "message": (f'{_scene_label(idx, s)}: the camera shows x {view[0]:.0f}-{view[2]:.0f}, '
                                                f'y {view[1]:.0f}-{view[3]:.0f} once its shot settles, and text node '
                                                f'"{node.get("id")}" ({left:.0f},{top:.0f} to {right:.0f},{bottom:.0f}) '
                                                "falls outside it — move the text into view, or give the shot a "
                                                "target the text sits under")})
            for c in node.get("children") or []:
                if isinstance(c, dict):
                    check(c, here, gone)
        for n in s.get("nodes") or []:
            if isinstance(n, dict):
                check(n)
    return out


def faults(spec: Dict[str, Any]) -> List[str]:
    """The error messages only, as plain strings — the shape inspect() uses
    and build_spec()'s repair loop sends back to the model."""
    return [e["message"] for e in report(spec)["errors"]]


# ── Compilation ──────────────────────────────────────────────────────────────

def _tween(channel: str, frm: float, to: float,
           easing: str = BRIDGE_EASING) -> Dict[str, Any]:
    return {"channel": channel, "from": frm, "to": to, "easing": easing}


def bridge_easing(scene: Dict[str, Any]) -> str:
    """The easing both instances of a bridged subject share across the
    cut INTO `scene` — the scene's own `handoff_easing` (Studio's handoff
    control) when it names a valid GSAP ease, else the default."""
    easing = scene.get("handoff_easing")
    return easing.strip() if isinstance(easing, str) and _valid_easing(easing) else BRIDGE_EASING


def _find_node(scene: Dict[str, Any], node_id: str) -> Optional[Dict[str, Any]]:
    def visit(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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


def _block(time: float, duration: float, tweens: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"time": round(time, 3), "duration": round(duration, 3),
            "tweens": tweens, "_bridge": True}


def compile(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Write every plannable bridge onto its two subject instances, in
    place, and record what was done.

    Must run AFTER resolver.py has laid the scenes out on the global
    timeline (each scene's `start` is final) and BEFORE it stamps
    transitions: a cut carrying a bridge gets `transition_in = "morph"`
    here, and the resolver's transition step honours it.

    Tween values follow runtime.js's convention: x/y/scale/rotation tweens
    are DELTAS from the node's own resting value, opacity is absolute. The
    outgoing instance's exit is replaced (an authored exit that fades the
    subject out before the cut is exactly the cold reset being repaired)
    and so is the incoming instance's enter. Both instances keep their own
    opacity; the crossfade between them is the morph transition's job, so
    the subject's brightness stays constant while it moves.
    """
    result = report(spec)
    scenes = [s for s in spec.get("scenes", []) or [] if isinstance(s, dict)]
    for plan in result["bridges"]:
        idx = plan["scene_index"]
        prev_scene, this_scene = scenes[idx - 1], scenes[idx]
        cut_at = _num(this_scene.get("start"), 0.0)
        start = cut_at + plan["start"]
        end = cut_at + plan["end"]
        duration = end - start
        plan["start"], plan["end"] = round(start, 3), round(end, 3)

        out_node = _find_node(prev_scene, plan["out_node"])
        in_node = _find_node(this_scene, plan["in_node"])
        if out_node is None or in_node is None:
            continue

        moves = [
            ("x", plan["dx"]), ("y", plan["dy"]),
            ("scaleX", plan["dscale_x"]), ("scaleY", plan["dscale_y"]),
            ("rotation", plan["drotation"]),
        ]
        easing = bridge_easing(this_scene)
        out_tweens = [_tween(ch, 0.0, d, easing) for ch, d in moves if abs(d) > 1e-6]
        in_tweens = [_tween(ch, -d, 0.0, easing) for ch, d in moves if abs(d) > 1e-6]
        if not out_tweens:
            # Same pose on both sides: still pin both instances so an
            # authored enter/exit cannot fade or fling the subject during
            # the cut. A zero-length x tween is a legal, inert pin.
            out_tweens = [_tween("x", 0.0, 0.0, easing)]
            in_tweens = [_tween("x", 0.0, 0.0, easing)]
        plan["easing"] = easing

        out_anim = out_node.setdefault("animation", {})
        if not isinstance(out_anim, dict):
            out_anim = out_node["animation"] = {}
        in_anim = in_node.setdefault("animation", {})
        if not isinstance(in_anim, dict):
            in_anim = in_node["animation"] = {}
        out_anim["exit"] = _block(start, duration, out_tweens)
        in_anim["enter"] = _block(start, duration, in_tweens)
        this_scene["transition_in"] = MORPH_TRANSITION

    return result
