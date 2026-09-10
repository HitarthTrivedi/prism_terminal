"""
Prism Motion Graphics — the promotion gate
───────────────────────────────────────────
The acceptance criteria in docs/INSPO_BENCHMARK_ROADMAP.md, run as code
against one spec on one machine, and the "same prompt everywhere" check:
one brand and tagline through the authored cinematic lab, the Motion
runtime and the Studio page.

`evaluate()` writes `promotion.json` and `promotion.md` into a folder —
every criterion with pass / fail / manual, its evidence, and the platform
it ran on. A criterion no program can judge (does removing one effect
collapse the composition?) is reported as *manual* with the review sheet
as its evidence, never silently passed. Promotion is per platform: the
report says which one it proves, and nothing else.

No git, no network, no licence check anywhere in this package — that is
one of the criteria, and `static_faults()` reads the sources to prove it.
"""
from __future__ import annotations

import json
import os
import platform
import re
import sys
import time
from typing import Any, Callable, Dict, List, Optional

from . import camera as _camera
from . import continuity as _continuity
from . import review as _review
from .studio import EDITS_KEY, resolved_for

# (key, group, text) — the wording mirrors the roadmap's acceptance list.
CRITERIA = [
    ("cold_reset", "visual", "No cold scene reset in the first-to-last continuity thread."),
    ("handoff_bridge", "visual", "Every handoff has a visible subject or energy bridge."),
    ("layout", "visual", "No unintended overlap, clipping, off-frame text or broken image."),
    ("glass_contrast", "visual", "Glass panels preserve edge definition and text contrast at 100% playback."),
    ("hold", "visual", "Typography remains readable for the intended hold duration."),
    ("hierarchy", "visual", "Effects support hierarchy; removing any one effect should not collapse the composition."),
    ("camera_continuous", "motion", "Camera and hero subject have continuous curves across cuts."),
    ("no_pop", "motion", "Handoffs are smooth at 60 FPS with no one-frame pop, jump or opacity flash."),
    ("review_states", "motion", "Start, midpoint, settled and exit previews all pass visual review."),
    ("resolves", "motion", "The final scene resolves the same subject introduced in the opening."),
    ("preview_export", "technical", "Preview and exported MP4 match at golden frames within the configured pixel tolerance."),
    ("probe", "technical", "The file probe confirms requested dimensions, FPS, duration and codec."),
    ("local_only", "technical", "Rendering works with local assets and with no licensed-server dependency."),
    ("editable_on_failure", "technical", "A failed render leaves an editable JSON project and actionable diagnostics."),
    ("no_git", "technical", "No automatic git commit or push is part of generation."),
]

_HERE = os.path.dirname(os.path.abspath(__file__))


def platform_tag() -> Dict[str, str]:
    return {"os": sys.platform, "release": platform.release(),
            "python": platform.python_version(), "machine": platform.machine()}


# ── static proofs ────────────────────────────────────────────────────────────

_FORBIDDEN = {
    # Executable forms only — a "git" argument to a subprocess/os call or a
    # shell string — so the criterion's own wording above does not match.
    "no_git": re.compile(r"""(\[|\(|,)\s*["']git["']|subprocess[^\n]*\bgit\b|os\.system\([^\n]*\bgit\b"""),
    "local_only": re.compile(r"^\s*(from|import)\s+.*\b(licensing|requests|urllib|http\.client|socket)\b", re.M),
}


def static_faults() -> Dict[str, List[str]]:
    """Which files in core/motion mention git, or import the network or the
    licence layer. The local HTTP server the Studio uses is a stdlib
    loopback server, imported inside serve() and not a network client."""
    out: Dict[str, List[str]] = {"no_git": [], "local_only": []}
    for name in sorted(os.listdir(_HERE)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(_HERE, name), encoding="utf-8") as fh:
            source = fh.read()
        for key, rx in _FORBIDDEN.items():
            for m in rx.finditer(source):
                line = source.count("\n", 0, m.start()) + 1
                text = source.splitlines()[line - 1].strip()
                if text.startswith("#") or '"""' in text:
                    continue
                out[key].append(f"{name}:{line}: {text[:80]}")
    return out


# ── the checklist ────────────────────────────────────────────────────────────

def _thread_resolves(resolved: Dict[str, Any]) -> Optional[str]:
    rep = _continuity.report(resolved)
    scenes = resolved.get("scenes", []) or []
    if len(scenes) < 2:
        return None
    opening = {k for k, items in rep["threads"].items() if items and items[0]["scene_index"] == 0}
    closing = {k for k, items in rep["threads"].items()
               if items and items[-1]["scene_index"] == len(scenes) - 1}
    if not opening:
        return "no continuity_key is introduced in the opening scene"
    if not opening & closing:
        return f"the opening subject ({', '.join(sorted(opening))}) does not return in the final scene"
    return None


def evaluate(spec: Dict[str, Any], out_dir: str, mp4: Optional[str] = None,
             on_progress: Optional[Callable[[int, int], None]] = None,
             preview_check: bool = True) -> Dict[str, Any]:
    """Run every criterion against `spec`; render unless `mp4` is given.
    Returns the report (also written as promotion.json / promotion.md)."""
    os.makedirs(out_dir, exist_ok=True)
    started = time.time()
    results: Dict[str, Dict[str, Any]] = {}

    def mark(key: str, status: str, evidence: str) -> None:
        results[key] = {"status": status, "evidence": evidence}

    # The editable project is written BEFORE anything can fail — that is
    # the "failed render leaves an editable JSON" guarantee, proven by
    # doing it, not by asserting it.
    project_path = os.path.join(out_dir, "promotion_spec.json")
    with open(project_path, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, indent=2, ensure_ascii=False)

    resolved = resolved_for(spec, spec.get(EDITS_KEY))
    compiled = resolved.get("_continuity_compiled") or {}
    errors = [e["message"] for e in compiled.get("errors", [])]
    notes = errors + [w["message"] for w in compiled.get("warnings", [])]
    cold = [e for e in notes if "cold reset" in e or "hard cut" in e]
    mark("cold_reset", "fail" if cold else "pass",
         "; ".join(cold) if cold else f"{len(compiled.get('threads', {}))} thread(s), no cold reset")
    scenes = resolved.get("scenes", []) or []
    keyed_cuts = sum(1 for i in range(1, len(scenes))
                     if scenes[i].get("transition_in") == _continuity.MORPH_TRANSITION)
    unbridged = [e for e in errors if "cannot be handed" in e]
    mark("handoff_bridge", "fail" if unbridged or (len(scenes) > 1 and not compiled.get("bridges"))
         else "pass", "; ".join(unbridged) if unbridged
         else f"{len(compiled.get('bridges', []))} bridge(s) on {keyed_cuts} morph cut(s)")
    tracks = (resolved.get("camera") or {}).get("tracks") or []
    cam_ok = bool(tracks) and _camera.is_continuous(tracks)
    mark("camera_continuous", "pass" if cam_ok and not unbridged else "fail",
         f"{len(tracks)} camera track(s), continuous={cam_ok}; hero bridged={not unbridged}")
    why = _thread_resolves(resolved)
    mark("resolves", "fail" if why else "pass", why or "the opening subject closes the piece")

    static = static_faults()
    mark("no_git", "fail" if static["no_git"] else "pass",
         "; ".join(static["no_git"]) or "core/motion never names git")
    mark("local_only", "fail" if static["local_only"] else "pass",
         "; ".join(static["local_only"]) or "core/motion imports no network or licence layer; assets are inlined data: URIs")

    # The film and its review.
    try:
        report = _review.review_sheet(spec, out_dir, mp4=mp4, on_progress=on_progress)
    except Exception as e:                                # noqa: BLE001
        diag = os.path.join(out_dir, "promotion_diagnostics.txt")
        with open(diag, "w", encoding="utf-8") as fh:
            fh.write(f"render failed: {e}\n")
        mark("editable_on_failure", "pass", f"render failed and left {project_path} + {diag}")
        for key in ("layout", "glass_contrast", "hold", "no_pop", "review_states",
                    "preview_export", "probe"):
            mark(key, "fail", f"no film to judge: {e}")
        mark("hierarchy", "manual", "no film to judge")
        return _finish(results, out_dir, started, None)

    mark("editable_on_failure", "pass",
         f"{project_path} written before the render; review.json carries every diagnostic")
    faults = report["faults"]
    layout = [f for f in faults if any(w in f for w in ("overlap", "outside", "off the edge", "platform"))]
    mark("layout", "fail" if layout else "pass", "; ".join(layout) or "no overlap, off-frame or safe-area fault")
    contrast = [f for f in faults if "contrast" in f]
    measured = not any("contrast not measured" in w for w in report["warnings"])
    mark("glass_contrast", "fail" if contrast else ("pass" if measured else "manual"),
         "; ".join(contrast) or ("every settled headline measures at least "
                                 f"{_review.MIN_CONTRAST_RATIO:g}:1 on the frame"
                                 if measured else "contrast could not be measured (no browser)"))
    hold = [f for f in faults if "holds for" in f]
    mark("hold", "fail" if hold else "pass", "; ".join(hold) or "every text holds long enough to be read")
    pops = [f for f in faults if "pops" in f]
    mark("no_pop", "fail" if pops else "pass",
         "; ".join(pops) or f"no one-frame pop at any of {max(0, len(scenes) - 1)} cut(s)")
    probe = [f for f in faults if f.startswith("export:")]
    mark("probe", "fail" if probe else "pass", "; ".join(probe) or json.dumps(report["project"]))
    mark("review_states", "manual", f"sheet: {report['sheet']} ({len(report['frames'])} frames)")
    mark("hierarchy", "manual", f"judge on the sheet: {report['sheet']}")

    if preview_check:
        times = [fr["time"] for fr in report["frames"] if fr["label"] in ("settled", "50%")]
        try:
            diffs = _review.preview_matches_export(resolved, report["mp4"], times)
            mark("preview_export", "fail" if diffs else "pass",
                 "; ".join(diffs) or f"{len(times)} golden frame(s) within {_review.PREVIEW_TOLERANCE:g}")
        except Exception as e:                            # noqa: BLE001
            mark("preview_export", "manual", f"could not compare ({e})")
    else:
        mark("preview_export", "manual", "preview check skipped")
    return _finish(results, out_dir, started, report)


def _finish(results: Dict[str, Dict[str, Any]], out_dir: str, started: float,
            review: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    for key, group, text in CRITERIA:
        got = results.get(key, {"status": "manual", "evidence": "not evaluated"})
        rows.append({"key": key, "group": group, "criterion": text, **got})
    failed = [r for r in rows if r["status"] == "fail"]
    manual = [r for r in rows if r["status"] == "manual"]
    report = {
        "platform": platform_tag(),
        "promoted": not failed,
        "failed": [r["key"] for r in failed],
        "manual": [r["key"] for r in manual],
        "criteria": rows,
        "seconds": round(time.time() - started, 1),
        "review": {k: review[k] for k in ("mp4", "sheet")} if review else None,
    }
    with open(os.path.join(out_dir, "promotion.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "promotion.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown(report))
    return report


def markdown(report: Dict[str, Any]) -> str:
    p = report["platform"]
    lines = [f"# Promotion gate — {p['os']} ({p['machine']}, Python {p['python']})", "",
             ("**Promoted on this platform.**" if report["promoted"]
              else f"**Not promoted:** {len(report['failed'])} criterion(s) failed."),
             ""]
    if report["manual"]:
        lines.append(f"{len(report['manual'])} criterion(s) need a human: "
                     + ", ".join(report["manual"]) + ".")
        lines.append("")
    for group in ("visual", "motion", "technical"):
        lines.append(f"## {group.title()}")
        lines.append("")
        for row in report["criteria"]:
            if row["group"] != group:
                continue
            flag = {"pass": "PASS", "fail": "FAIL", "manual": "MANUAL"}[row["status"]]
            lines.append(f"- [{flag}] {row['criterion']}")
            lines.append(f"  - {row['evidence']}")
        lines.append("")
    lines.append("Promotion is per platform. Run this gate on Linux, Windows and macOS; "
                 "promote only when every platform's report reads PASS on every "
                 "automated criterion and a reviewer has signed the manual ones off "
                 "against the review sheet.")
    return "\n".join(lines) + "\n"


# ── the same prompt everywhere ───────────────────────────────────────────────

def same_prompt_everywhere(brand: str, tagline: str, out_dir: str,
                           on_progress: Optional[Callable[[int, int], None]] = None,
                           preview_check: bool = True) -> Dict[str, Any]:
    """One brand and tagline through the authored lab (settled and
    transition previews), the Motion runtime (the materials fixture,
    rendered and gated) and the Studio page (served, mounted content)."""
    from .fixtures import materials_fixture
    from . import studio as _studio

    os.makedirs(out_dir, exist_ok=True)
    out: Dict[str, Any] = {"brand": brand, "tagline": tagline}

    lab_dir = os.path.join(out_dir, "lab")
    try:
        from core.cinematic import CinematicTheme, build_demo_spec, render_previews, \
            render_transition_previews
        lab_spec = build_demo_spec(CinematicTheme(brand=brand, tagline=tagline), fps=30)
        stills = render_previews(lab_spec, lab_dir)
        cuts = render_transition_previews(lab_spec, lab_dir)
        out["lab"] = {"ok": bool(stills) and bool(cuts), "stills": stills, "handoffs": cuts}
    except Exception as e:                                # noqa: BLE001
        out["lab"] = {"ok": False, "error": str(e)}

    spec = materials_fixture(1080, 1920, 60, brand=brand, tagline=tagline)
    out["motion"] = evaluate(spec, os.path.join(out_dir, "motion"),
                             on_progress=on_progress, preview_check=preview_check)

    page = _studio.editable_html(spec)
    out["studio"] = {"ok": brand in page and "Prism <i>Motion Studio</i>" in page
                     and '"threads"' in page,
                     "bytes": len(page)}
    with open(os.path.join(out_dir, "same_prompt.json"), "w", encoding="utf-8") as fh:
        json.dump({k: (v if k != "motion" else {"promoted": v["promoted"], "failed": v["failed"]})
                   for k, v in out.items()}, fh, indent=2)
    return out
