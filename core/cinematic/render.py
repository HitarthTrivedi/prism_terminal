"""Preview, render and soundtrack helpers for the isolated cinematic lab."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from .. import reel_web


def duration(spec: dict) -> float:
    _plan, frames = reel_web._plan(spec, int(spec.get("fps", 30)))
    return frames / int(spec.get("fps", 30))


def render_previews(spec: dict, folder: str | os.PathLike, at: float = .62) -> list[str]:
    """Render one reviewed frame per shot after entrances have settled."""
    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    plan, _frames = reel_web._plan(spec, int(spec.get("fps", 30)))
    fps = int(spec.get("fps", 30))
    paths = []
    for index, shot in enumerate(plan, 1):
        frame = round((shot["start"] + shot["dur"] * at) * fps / 1000)
        path = target / f"shot-{index}.png"
        reel_web.still(spec, frame, str(path))
        paths.append(str(path))
    return paths


def render_transition_previews(spec: dict, folder: str | os.PathLike,
                               spread: float = .30) -> list[str]:
    """Capture before/middle/after frames for every scene handoff."""
    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    fps = int(spec.get("fps", 30))
    plan, total = reel_web._plan(spec, fps)
    samples = (("before", -spread), ("middle", 0.0), ("after", spread))
    paths = []
    for boundary, shot in enumerate(plan[1:], 1):
        # A scene starts at the beginning of its overlap.  The visual cut's
        # midpoint is half an in-window later, when both roots contribute
        # equally—not at ``start`` itself.
        seconds = (shot["start"] + shot["inLen"] / 2) / 1000
        for label, offset in samples:
            frame = max(0, min(total - 1, round((seconds + offset) * fps)))
            path = target / f"cut-{boundary}-{label}.png"
            reel_web.still(spec, frame, str(path))
            paths.append(str(path))
    return paths


def _soundtrack(path: str, seconds: float, transitions: list[float]) -> str:
    """Create a restrained procedural review track using bundled FFmpeg.

    It is intentionally a temp score: ambient air, a low tonal floor, and
    short cues at shot changes. It proves timing/audio plumbing without
    pretending to replace licensed music or final sound design.
    """
    ffmpeg = reel_web.ffmpeg_path()
    cmd = [ffmpeg, "-y", "-loglevel", "error",
           "-f", "lavfi", "-i",
           f"anoisesrc=color=pink:amplitude=0.018:duration={seconds:.3f}:sample_rate=48000",
           "-f", "lavfi", "-i", f"sine=frequency=55:duration={seconds:.3f}:sample_rate=48000"]
    filters = ["[0:a]lowpass=f=950,highpass=f=70,volume=1.15[air]",
               "[1:a]volume=0.18,afade=t=in:st=0:d=1.2,"
               f"afade=t=out:st={max(0, seconds - 1.4):.3f}:d=1.4[floor]"]
    mix = ["[air]", "[floor]"]
    for i, start in enumerate(transitions):
        delay = max(0, round(start * 1000))
        cmd += ["-f", "lavfi", "-i", "sine=frequency=520:duration=0.38:sample_rate=48000"]
        label = f"cue{i}"
        filters.append(
            f"[{i + 2}:a]volume=0.24,afade=t=out:st=0.02:d=0.36,"
            f"adelay={delay}|{delay}[{label}]")
        mix.append(f"[{label}]")
    filters.append("".join(mix) + f"amix=inputs={len(mix)}:normalize=0,"
                   "volume=7.5,alimiter=limit=0.82,afade=t=out:st="
                   f"{max(0, seconds - .7):.3f}:d=0.7[out]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "[out]",
            "-c:a", "aac", "-b:a", "192k", "-t", f"{seconds:.3f}", path]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return path


def render(spec: dict, out_path: str | os.PathLike, *, with_audio: bool = True,
           on_progress=None) -> str:
    """Render a cinematic test MP4, optionally with the procedural score."""
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    project_seconds = duration(spec)
    plan, _frames = reel_web._plan(spec, int(spec.get("fps", 30)))
    transitions = [shot["start"] / 1000 for shot in plan[1:]]
    if not with_audio:
        return reel_web.render(spec, str(output), on_progress=on_progress,
                               capture_quality=98, crf=16)

    with tempfile.TemporaryDirectory(prefix="prism-cinematic-", dir=str(output.parent)) as temp:
        silent = os.path.join(temp, "picture.mp4")
        score = os.path.join(temp, "score.m4a")
        reel_web.render(spec, silent, on_progress=on_progress,
                        capture_quality=98, crf=16)
        _soundtrack(score, project_seconds, transitions)
        cmd = [reel_web.ffmpeg_path(), "-y", "-loglevel", "error",
               "-i", silent, "-i", score, "-map", "0:v:0", "-map", "1:a:0",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
               "-movflags", "+faststart", "-shortest", str(output)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return str(output)


def save_project(spec: dict, path: str | os.PathLike) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return str(target)
