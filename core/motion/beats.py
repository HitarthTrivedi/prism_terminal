"""
Prism Motion Graphics — beat markers and the timing grid
─────────────────────────────────────────────────────────
Camera, subject motion, text and cuts share one rhythm in the reference
film. This module gives a piece that rhythm explicitly: a tempo (either
the production track's own, from the spec's `audio` block, or one chosen
so the cuts already land on beats), the beat and bar times across the
whole timeline, and a marker list of every cut, bridge, camera move and
text entrance with how far each sits from its nearest beat.

Nothing here writes music. A temporary score never enters the design
contract; production music and voice are attached as files in
`spec["audio"]` and muxed at export (render.py), and only their tempo and
offset are used to lay the grid.

Stdlib only.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Optional, Sequence

BPM_MIN, BPM_MAX = 40.0, 240.0
_SEARCH_LO, _SEARCH_HI, _SEARCH_PREFERRED = 80, 140, 110
# A marker within this many seconds of a beat counts as on it (two frames
# at 60 fps — the tolerance below which a cut and a downbeat read as one).
ON_BEAT_TOLERANCE = 0.034


def _num(value: Any, default: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(out) or math.isinf(out):
        return default
    return out


def _drift(time: float, bpm: float, offset: float) -> float:
    """Signed seconds from `time` to its nearest beat."""
    period = 60.0 / bpm
    phase = (time - offset) / period
    return (phase - round(phase)) * period


def choose_bpm(cuts: Sequence[float], lo: int = _SEARCH_LO, hi: int = _SEARCH_HI,
               offset: float = 0.0) -> float:
    """The whole-number tempo (lo..hi) at which the cuts sit closest to
    beats; ties go to the tempo nearest 110. With no cuts, 110."""
    times = [t for t in (_num(c, -1.0) for c in cuts) if t > 0]
    if not times:
        return float(_SEARCH_PREFERRED)
    best, best_err = float(_SEARCH_PREFERRED), None
    for bpm in range(lo, hi + 1):
        err = sum(_drift(t, bpm, offset) ** 2 for t in times)
        if best_err is None or err < best_err - 1e-9 or (
                abs(err - best_err) <= 1e-9
                and abs(bpm - _SEARCH_PREFERRED) < abs(best - _SEARCH_PREFERRED)):
            best, best_err = float(bpm), err
    return best


def _cut_times(resolved: Dict[str, Any]) -> List[float]:
    scenes = [s for s in resolved.get("scenes", []) or [] if isinstance(s, dict)]
    return [_num(s.get("start"), 0.0) for s in scenes[1:]]


def timing_grid(resolved: Dict[str, Any], bpm: Optional[float] = None,
                offset: Optional[float] = None) -> Dict[str, Any]:
    """Beats, bars and markers for a RESOLVED spec (global times).

    Tempo comes from, in order: the `bpm` argument, the spec's `audio`
    block, or `choose_bpm()` over the cuts. Returns::

        {"bpm", "offset", "source", "beats": [t, ...], "bars": [t, ...],
         "markers": [{"time", "kind", "scene", "label", "drift",
                      "on_beat"}, ...],
         "on_beat": <count>, "off_beat": <count>}
    """
    scenes = [s for s in resolved.get("scenes", []) or [] if isinstance(s, dict)]
    project = resolved.get("project") or {}
    duration = _num(project.get("duration"), 0.0)
    if scenes:
        last = scenes[-1]
        duration = max(duration, _num(last.get("start"), 0.0) + _num(last.get("duration"), 0.0))
    audio = resolved.get("audio") if isinstance(resolved.get("audio"), dict) else {}
    source = "argument"
    if bpm is None:
        if audio.get("bpm"):
            bpm, source = _num(audio.get("bpm"), 0.0), "audio"
        else:
            source = "cuts"
    if offset is None:
        offset = _num(audio.get("offset"), 0.0)
    cuts = _cut_times(resolved)
    if not bpm or bpm < BPM_MIN or bpm > BPM_MAX:
        bpm, source = choose_bpm(cuts, offset=offset), "cuts"
    period = 60.0 / bpm
    beats: List[float] = []
    t = offset
    while t < 0:
        t += period
    while t <= duration + 1e-6 and len(beats) < 4000:
        beats.append(round(t, 3))
        t += period
    bars = [b for i, b in enumerate(beats) if i % 4 == 0]

    markers: List[Dict[str, Any]] = []

    def mark(time: float, kind: str, scene: int, label: str) -> None:
        drift = _drift(time, bpm, offset)
        markers.append({"time": round(time, 3), "kind": kind, "scene": scene,
                        "label": label, "drift": round(drift, 3),
                        "on_beat": abs(drift) <= ON_BEAT_TOLERANCE})

    for i, scene in enumerate(scenes):
        start = _num(scene.get("start"), 0.0)
        if i > 0:
            mark(start, "cut", i, f"cut into scene {i + 1}"
                 + (f" ({scene['transition_in']})" if scene.get("transition_in") else ""))
        for node in _walk(scene):
            anim = node.get("animation")
            enter = anim.get("enter") if isinstance(anim, dict) else None
            if node.get("type") == "text" and isinstance(enter, dict) and not enter.get("_bridge"):
                mark(_num(enter.get("time"), start), "enter", i,
                     f'text "{node.get("id", "")}" enters')
    for bridge in (resolved.get("_continuity_compiled") or {}).get("bridges", []) or []:
        mark(_num(bridge.get("start"), 0.0), "bridge", int(bridge.get("scene_index", 0)),
             f'"{bridge.get("key", "")}" morph begins')
    for track in ((resolved.get("camera") or {}).get("tracks") or []):
        if isinstance(track, dict) and track.get("_shot") and track["_shot"] != "open":
            scene_no = next((i for i, s in enumerate(scenes)
                             if abs(_num(s.get("start"), 0.0) - _num(track.get("time"), 0.0)) < 0.01), 0)
            mark(_num(track.get("time"), 0.0), "camera", scene_no, f"camera {track['_shot']}")
    markers.sort(key=lambda m: (m["time"], m["kind"]))
    return {
        "bpm": round(bpm, 2), "offset": round(offset, 3), "source": source,
        "beats": beats, "bars": bars, "markers": markers,
        "on_beat": sum(1 for m in markers if m["on_beat"]),
        "off_beat": sum(1 for m in markers if not m["on_beat"]),
    }


def _walk(scene: Dict[str, Any]):
    stack = [n for n in scene.get("nodes", []) or [] if isinstance(n, dict)]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(c for c in node.get("children", []) or [] if isinstance(c, dict))


def snap_scene_lengths(spec: Dict[str, Any], bpm: float, offset: float = 0.0,
                       beats_per_scene_min: int = 2) -> Dict[str, Any]:
    """A copy of a SCENE-LOCAL spec whose scene lengths are whole beats, so
    every cut lands on the grid. Opt-in: an editing aid, never applied by
    the pipeline on its own."""
    out = copy.deepcopy(spec)
    bpm = max(BPM_MIN, min(BPM_MAX, _num(bpm, 110.0)))
    period = 60.0 / bpm
    scenes = [s for s in out.get("scenes", []) or [] if isinstance(s, dict)]
    cursor = offset
    for scene in scenes:
        want = _num(scene.get("duration"), 0.0)
        beats = max(beats_per_scene_min, int(round(want / period)))
        # keep the END on a beat even if the start drifted from a prior edit
        end = cursor + beats * period
        end = offset + round((end - offset) / period) * period
        scene["duration"] = round(max(period, end - cursor), 3)
        cursor = end
    if scenes:
        out.setdefault("project", {})["duration"] = round(
            sum(_num(s.get("duration"), 0.0) for s in scenes), 3)
    return out
