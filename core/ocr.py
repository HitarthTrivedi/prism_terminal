"""Read the text in a picture -- a screenshot of a catalogue page, a photo
of a part with its code printed underneath.

A customer who cannot be bothered to type sends a picture: "SS Locker
(8 Comp)  KJP 3", cropped from a brochure. The code is IN the picture, so
until the picture is read the inquiry has no product and nothing to quote.

Backends, in the order tried:

  1. RapidOCR (rapidocr-onnxruntime) -- a pip package with the models
     inside it, about 30 MB with its runtime, no system install, the same
     on Windows, macOS and Linux. Reads the sample brochure crop in 0.2 s
     with the code at 0.79 confidence. This is the one a build ships.
  2. Apple's Vision framework (pyobjc) -- macOS only, already on the OS;
     used when RapidOCR is not importable in a source checkout.
  3. tesseract, if the binary happens to be on PATH.

Every backend answers the same shape: [(text, confidence)] per line, top
to bottom. None of them is an AI service: the picture never leaves the
machine, the same rule the measuring add-ons keep.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff")
TEXT_FILE = "image_text.txt"      # what the inquiry folder keeps, next to the picture

_rapid = None                     # the RapidOCR instance, built once: ~0.1 s + models


def is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_EXTS


def available() -> tuple[bool, str]:
    """Which backend will read pictures here, or why none will."""
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True, "RapidOCR"
    except Exception:                                   # noqa: BLE001
        pass
    if sys.platform == "darwin":
        try:
            import Vision  # noqa: F401
            return True, "macOS Vision"
        except Exception:                               # noqa: BLE001
            pass
    if shutil.which("tesseract"):
        return True, "tesseract"
    return False, ("reading text from pictures needs the rapidocr-onnxruntime "
                   "package:\n\n    pip install rapidocr-onnxruntime")


# ── backends ─────────────────────────────────────────────────────────────────

def _rapidocr(path: str) -> list[tuple[str, float]] | None:
    global _rapid
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:                                   # noqa: BLE001
        return None
    if _rapid is None:
        _rapid = RapidOCR()
    result, _elapsed = _rapid(path)
    out = []
    for entry in result or []:
        # (box, text, score) -- the box is four corners in pixels.
        box, text, score = entry[0], str(entry[1]).strip(), float(entry[2])
        if not text:
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        out.append(_Word(text, score, min(xs), min(ys), max(ys) - min(ys)))
    return _lines(out)


def _vision(path: str) -> list[tuple[str, float]] | None:
    if sys.platform != "darwin":
        return None
    try:
        import Quartz
        import Vision
        from Foundation import NSURL
    except Exception:                                   # noqa: BLE001
        return None
    src = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(path), None)
    if src is None:
        return None
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(1)                         # accurate, not fast
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
    ok, _err = handler.performRequests_error_([req], None)
    if not ok:
        return None
    out = []
    for obs in req.results() or []:
        cand = obs.topCandidates_(1)
        if not cand:
            continue
        text = str(cand[0].string()).strip()
        if not text:
            continue
        # Vision's box is normalised with y running bottom-up; flip it.
        b = obs.boundingBox()
        top = 1.0 - (b.origin.y + b.size.height)
        out.append(_Word(text, float(obs.confidence()), b.origin.x, top, b.size.height))
    return _lines(out)


def _tesseract(path: str) -> list[tuple[str, float]] | None:
    exe = shutil.which("tesseract")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, path, "stdout"], capture_output=True, text=True,
                           timeout=60)
    except Exception:                                   # noqa: BLE001
        return None
    if r.returncode != 0:
        return None
    return [(ln.strip(), 0.5) for ln in r.stdout.splitlines() if ln.strip()]


class _Word:
    """One recognised run of text with where it sits, whatever the backend."""
    __slots__ = ("text", "score", "x", "y", "h")

    def __init__(self, text: str, score: float, x: float, y: float, h: float):
        self.text, self.score, self.x, self.y, self.h = text, score, x, y, h


def _lines(words: list) -> list[tuple[str, float]]:
    """Group recognised runs into lines: two runs share a line when their
    vertical centres are within half a text height of each other. Within a
    line, left to right; lines top to bottom; a line's confidence is its
    lowest word's. Detectors split "SS Locker (8 Comp)   KJP 3" into three
    or four boxes and hand them back in no particular order -- this is
    what turns that back into the line a person would read."""
    rows: list[list[_Word]] = []
    for w in sorted(words, key=lambda w: (w.y + w.h / 2, w.x)):
        centre = w.y + w.h / 2
        for row in rows:
            ref = row[0]
            if abs((ref.y + ref.h / 2) - centre) <= max(ref.h, w.h) * 0.5:
                row.append(w)
                break
        else:
            rows.append([w])
    out = []
    for row in rows:
        row.sort(key=lambda w: w.x)
        out.append((" ".join(w.text for w in row), min(w.score for w in row)))
    return out


BACKENDS = (_rapidocr, _vision, _tesseract)


# ── the one call the rest of Prism makes ─────────────────────────────────────

def read(path: str) -> list[tuple[str, float]]:
    """Lines of text in the picture at `path`, top to bottom, each with the
    reader's confidence 0..1. [] when no backend can read it."""
    if not os.path.isfile(path):
        return []
    for backend in BACKENDS:
        try:
            lines = backend(path)
        except Exception:                               # noqa: BLE001
            lines = None
        if lines is not None:
            return lines
    return []


def text_of(path: str) -> str:
    return "\n".join(text for text, _ in read(path))


def read_files(paths: list[str]) -> str:
    """The text of every picture among `paths`, each under its file name --
    what an inquiry folder's image_text.txt holds, and what the code finder
    and the quotation window read."""
    blocks = []
    for p in paths or []:
        if not is_image(p):
            continue
        text = text_of(p)
        if text.strip():
            blocks.append(f"[{os.path.basename(p)}]\n{text}")
    return "\n\n".join(blocks)


def remember(folder: str, text: str) -> str:
    """Write the pictures' text beside them, so the quotation window and a
    later re-check read the same words the check read. Returns the path,
    or "" when there was nothing to write."""
    if not text.strip():
        return ""
    path = os.path.join(folder, TEXT_FILE)
    try:
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        return ""
    return path


def recall(folder: str) -> str:
    """What remember() wrote for this inquiry, or ""."""
    if not folder:
        return ""
    path = os.path.join(folder, TEXT_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""
