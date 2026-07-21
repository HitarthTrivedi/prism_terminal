"""
Prism — persistent configuration
────────────────────────────────
Everything the user sets during onboarding lives in ~/.prism/config.json so it
survives across runs and is independent of the current working directory.
Once written, Prism never asks for these again (unless the user edits them).
"""
import os
import json

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".prism")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
RUNS_DIR = os.path.join(CONFIG_DIR, "runs")

DEFAULT = {
    "api_key": "",        # Groq key (gsk_...)
    "profile": "",        # free-text "what do you do" — steers routing
    "agents": {},         # {category: agent_name} — only categories the user enabled
    "chrome_version": "", # pinned Chrome major version; "" = auto-detect
    "onboarded": False,
    "model": "llama-3.3-70b-versatile",
}


def load() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {**DEFAULT, **data}
        except Exception:
            pass
    return dict(DEFAULT)


def save(cfg: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    try:
        os.chmod(CONFIG_PATH, 0o600)  # key is sensitive — owner-only
    except OSError:
        pass


def is_configured(cfg: dict) -> bool:
    return bool(cfg.get("api_key")) and bool(cfg.get("onboarded"))


def active_agents(cfg: dict) -> dict:
    """Categories the user actually assigned an agent to."""
    return {k: v for k, v in (cfg.get("agents") or {}).items() if v}


def save_run(record: dict) -> str:
    """Persist one query's routing + responses to ~/.prism/runs/<ts>.json."""
    import time
    os.makedirs(RUNS_DIR, exist_ok=True)
    path = os.path.join(RUNS_DIR, f"run_{int(time.time())}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    return path
