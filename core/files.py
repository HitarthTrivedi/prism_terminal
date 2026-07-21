"""
Prism — file attachments (any type)
───────────────────────────────────
Users can attach ANY file to a task. Prism does two things with each one:

  1. Extracts text when possible (txt/md/code/csv/json/pdf/docx/…) and injects
     it into the routing brain + every agent's context, so even tools without an
     upload box still "see" the content.
  2. Uploads the real file to each tool's web UI (via its <input type="file">),
     so images, audio, video, zips, datasets, etc. reach agents that accept them.

Text extraction for PDF/DOCX uses optional deps (pypdf, python-docx). If they're
missing, the file is still attached and uploaded — only inline text is skipped.
"""
from __future__ import annotations
import os
import mimetypes

# How much extracted text to inline per file (keeps prompts sane).
MAX_TEXT_CHARS = 12000

# Extensions we treat as directly-readable UTF-8 text even when mimetypes is unsure.
_TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json", ".jsonl",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".xml", ".html", ".htm",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cpp", ".cc", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala", ".sh", ".bash",
    ".zsh", ".sql", ".r", ".m", ".lua", ".pl", ".dart", ".vue", ".svelte", ".css",
    ".scss", ".less", ".tex", ".bib", ".srt", ".vtt",
}


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}GB"


def _classify(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    mime, _ = mimetypes.guess_type(path)
    if ext in _TEXT_EXTS:
        return "text"
    if mime:
        if mime.startswith("image/"):
            return "image"
        if mime.startswith("audio/"):
            return "audio"
        if mime.startswith("video/"):
            return "video"
        if mime.startswith("text/"):
            return "text"
        if mime in ("application/json", "application/xml",
                    "application/x-yaml", "application/javascript"):
            return "text"
    if ext == ".pdf":
        return "pdf"
    if ext in (".docx",):
        return "docx"
    return "binary"


def _extract_text(path: str, kind: str) -> str | None:
    try:
        if kind == "text":
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read(MAX_TEXT_CHARS + 1)
        if kind == "pdf":
            try:
                from pypdf import PdfReader
            except Exception:
                try:
                    from PyPDF2 import PdfReader  # older name
                except Exception:
                    return None
            reader = PdfReader(path)
            out = []
            for page in reader.pages:
                out.append(page.extract_text() or "")
                if sum(len(x) for x in out) > MAX_TEXT_CHARS:
                    break
            return "\n".join(out) or None
        if kind == "docx":
            try:
                import docx  # python-docx
            except Exception:
                return None
            d = docx.Document(path)
            return "\n".join(p.text for p in d.paragraphs) or None
        # Last resort: sniff whether an unknown binary is actually decodable text.
        with open(path, "rb") as f:
            head = f.read(4096)
        if b"\x00" not in head:
            try:
                text = head.decode("utf-8")
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read(MAX_TEXT_CHARS + 1)
            except Exception:
                return None
    except Exception:
        return None
    return None


# Folder attach cap — ChatGPT (the file-analysis stage) takes at most 20
# files per message, so stay comfortably under it.
MAX_DIR_FILES = 15


def attach_dir(path: str) -> list[dict]:
    """Attachment records for every plain file directly inside a folder
    (hidden files skipped, capped at MAX_DIR_FILES)."""
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(path):
        raise NotADirectoryError(path)
    out = []
    for name in sorted(os.listdir(path)):
        fp = os.path.join(path, name)
        if name.startswith(".") or not os.path.isfile(fp):
            continue
        try:
            out.append(attach(fp))
        except Exception:
            continue
        if len(out) >= MAX_DIR_FILES:
            break
    return out


def attach(path: str) -> dict:
    """Build an attachment record for any file. Raises if it doesn't exist."""
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if os.path.isdir(path):
        raise IsADirectoryError(path)
    kind = _classify(path)
    text = _extract_text(path, kind)
    truncated = bool(text and len(text) > MAX_TEXT_CHARS)
    if truncated:
        text = text[:MAX_TEXT_CHARS]
    return {
        "path": path,
        "name": os.path.basename(path),
        "size": os.path.getsize(path),
        "mime": mimetypes.guess_type(path)[0] or "application/octet-stream",
        "kind": kind,
        "text": text,
        "truncated": truncated,
    }


def describe(att: dict) -> str:
    tag = "📄 text" if att["text"] else f"📎 {att['kind']}"
    return f"{att['name']}  [dim]({_human_size(att['size'])} · {tag})[/dim]"


def context_block(attachments: list[dict]) -> str:
    """Text injected into agent prompts so tools see file contents inline."""
    if not attachments:
        return ""
    parts = ["📎 The user attached the following file(s). Use them as primary source material:\n"]
    for att in attachments:
        header = f"── {att['name']} ({_human_size(att['size'])}, {att['kind']})"
        if att["text"]:
            trunc = "  [content truncated]" if att.get("truncated") else ""
            parts.append(f"{header}{trunc}\n{att['text']}\n")
        else:
            parts.append(f"{header}\n(binary file — uploaded directly to the tool; contents not inlined)\n")
    parts.append("── end of attachments ──\n")
    return "\n".join(parts) + "\n"


def routing_note(attachments: list[dict]) -> str:
    """A short note for the routing brain (full contents are given to agents)."""
    if not attachments:
        return ""
    names = ", ".join(a["name"] for a in attachments)
    kinds = ", ".join(sorted({a["kind"] for a in attachments}))
    return (
        f"\nThe user attached {len(attachments)} file(s): {names} (types: {kinds}). "
        "Their contents are provided to each agent as context and the raw files are "
        "uploaded to each tool. Write prompts that explicitly use these files.\n"
    )


def upload_paths(attachments: list[dict]) -> list[str]:
    return [a["path"] for a in attachments]
