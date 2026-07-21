"""
Prism — browser automation
───────────────────────────
Drives the user's logged-in Chrome (via undetected-chromedriver) through each
needed pipeline stage: opens the tool, types the prompt(s), waits, scrapes the
response, and passes it forward as context to the next stage.

Ported from the original prism_new.py, generalised to N categories and decoupled
from Google Drive. Selenium/uc are imported lazily so the REPL and dry-runs work
even on machines where they aren't installed yet.
"""
from __future__ import annotations
import os
import time
import shutil
import tempfile
import subprocess
import platform
import webbrowser
from . import agents as A
from . import ui

# Common Chrome binary locations across platforms.
_CHROME_BINARIES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",   # macOS
    "/usr/bin/google-chrome",                                         # Linux
    "/usr/bin/google-chrome-stable",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",         # Windows
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

# Cap on how much of the previous stage's output is forwarded. The tail is
# kept (not the head) because that's where the HANDOFF summary lives.
_MAX_FORWARD_CHARS = 8000


def _bmp_safe(text: str) -> str:
    """ChromeDriver's send_keys only accepts Basic-Multilingual-Plane characters
    (<= U+FFFF). Drop anything above it (emoji, etc.) so typing never crashes
    with 'ChromeDriver only supports characters in the BMP'."""
    return "".join(ch for ch in text if ord(ch) <= 0xFFFF)


def parse_chrome_version(raw) -> int | None:
    """Accept '147', '147.0.7727.139', 147 → 147. Blank/invalid → None."""
    if raw in (None, ""):
        return None
    try:
        return int(str(raw).strip().split(".")[0])
    except (ValueError, IndexError):
        return None


def detect_chrome_version() -> int | None:
    """Return the installed Chrome major version, or None if it can't be found."""
    for path in _CHROME_BINARIES:
        if not os.path.exists(path):
            continue
        try:
            out = subprocess.check_output([path, "--version"], text=True)
            # e.g. "Google Chrome 147.0.7727.139"
            return int(out.strip().split()[2].split(".")[0])
        except Exception:
            continue
    return None


def _setup_chrome_driver(version_main=None):
    """Clone the user's real Chrome profile into a temp dir so their logins are
    available, then launch undetected-chromedriver against it."""
    import undetected_chromedriver as uc

    system=platform.system()
    if system=="Linux":
        src=os.path.expanduser("~/.config/google-chrome")
    elif system=="Windows":
        src = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data")
    elif system=="Darwin":
        src = os.path.expanduser("~/Library/Application Support/Google/Chrome")
    else:
        ui.err("prism yet doesnt support your OS")
        raise RuntimeError(f"Unsupported operating system: {system}")

    tmp = os.path.join(tempfile.gettempdir(), "uc_chrome_prism_terminal")
    if os.path.exists(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)

    src_default = os.path.join(src, "Default")
    if os.path.exists(src_default):
        shutil.copytree(
            src_default, os.path.join(tmp, "Default"), dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("Singleton*", "*.lock"),
        )
    local_state = os.path.join(src, "Local State")
    if os.path.exists(local_state):
        shutil.copy2(local_state, os.path.join(tmp, "Local State"))

    opts = uc.ChromeOptions()
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--disable-blink-features=AutomationControlled")

    # Drop any cached wrong-architecture chromedriver (x86 on Apple Silicon).
    uc_cache = os.path.expanduser("~/Library/Application Support/undetected_chromedriver")
    if os.path.exists(uc_cache):
        for f in [x for x in os.listdir(uc_cache) if "chromedriver" in x.lower()]:
            fp = os.path.join(uc_cache, f)
            try:
                r = subprocess.run(["file", fp], capture_output=True, text=True)
                if "x86" in r.stdout and "arm" not in r.stdout.lower():
                    os.remove(fp)
            except Exception:
                pass

    # Match the driver to Chrome: use the user's pinned version if provided,
    # otherwise auto-detect the installed one.
    if version_main is None:
        version_main = detect_chrome_version()
    if version_main:
        ui.info(f"   🌐  targeting Chrome v{version_main}")

    return uc.Chrome(options=opts, user_data_dir=tmp, version_main=version_main)


def _needed_stages(routing: dict, agents: dict):
    """Yield (stage, agent_name, questions) for every stage that should run."""
    for stage in A.PIPELINE_ORDER:
        data = routing.get(stage)
        if not data or not data.get("needed", False):
            continue
        questions = [q for q in data.get("questions", []) if q and q.strip()]
        if not questions:
            continue
        if stage == "summary":
            name = A.summary_agent_name(agents)
        else:
            name = agents.get(stage)
        if not name:
            continue
        yield stage, name, questions


def _upload_files(driver, agent_cfg, attachments):
    """Push any attached files into the tool's <input type='file'>, if present."""
    if not attachments:
        return
    from selenium.webdriver.common.by import By
    from . import files as F

    sel = agent_cfg.get("upload_selector", "input[type='file']")
    inputs = driver.find_elements(By.CSS_SELECTOR, sel)
    if not inputs:
        return
    paths = F.upload_paths(attachments)
    target = inputs[0]
    uploaded = 0
    try:
        # Most multi-file inputs accept newline-separated paths in one send_keys.
        target.send_keys("\n".join(paths))
        uploaded = len(paths)
        ui.info(f"   📎  uploaded {uploaded} file(s)")
    except Exception:
        # Fall back to one-at-a-time (input may be replaced between sends).
        for p in paths:
            try:
                for inp in driver.find_elements(By.CSS_SELECTOR, sel):
                    inp.send_keys(p)
                    uploaded += 1
                    break
            except Exception:
                pass
        if uploaded:
            ui.info(f"   📎  uploaded {uploaded} file(s)")
    if not uploaded:
        return   # nothing reached the page — no ingest to wait for
    # Big files / multiple files take a while to ingest — submitting before the
    # upload finishes silently drops the attachment. Wait a size-scaled floor,
    # then keep waiting while the page still shows an upload spinner/progress
    # bar, up to a size-scaled cap.
    total_mb = sum(a.get("size", 0) for a in attachments) / 1e6
    floor = min(15 + int(total_mb * 4), 120)          # 6.5 MB → ~41s
    cap = max(45, min(300, 30 + int(total_mb * 20)))  # 6.5 MB → 160s
    start = time.time()
    time.sleep(min(floor, cap))
    while time.time() - start < cap:
        try:
            busy = driver.execute_script(
                """
                const sels = "[role='progressbar'], progress, .animate-spin, [aria-busy='true']";
                return Array.from(document.querySelectorAll(sels))
                            .some(el => el.offsetParent !== null);
                """)
        except Exception:
            busy = False
        if not busy:
            break
        time.sleep(2)
    ui.info(f"   📎  upload settled after {int(time.time() - start)}s")


def _fast_type(driver, element, text: str) -> bool:
    """Insert the whole prompt at once via JavaScript instead of per-character
    send_keys (which crawls at ~20 chars/sec over the WebDriver wire — minutes
    for a long context). Handles <textarea>/<input> through the native value
    setter (so React/Vue notice the change) and contenteditable editors through
    execCommand('insertText'), which fires real input events.
    Returns False if the text didn't land, so the caller can fall back."""
    try:
        element.click()
    except Exception:
        pass
    try:
        return bool(driver.execute_script(
            """
            const el = arguments[0], text = arguments[1];
            el.focus();
            if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
                const proto = el.tagName === 'TEXTAREA'
                    ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, text);
                el.dispatchEvent(new Event('input',  {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                return el.value === text;
            }
            document.execCommand('selectAll', false, null);
            const ok = document.execCommand('insertText', false, text);
            return ok && (el.innerText || el.textContent || '').trim().length > 0;
            """,
            element, text,
        ))
    except Exception:
        return False


def _harvest_images(driver, agent_cfg, stage: str) -> list[dict]:
    """A generated image can't travel in a text handoff. Pull every real image
    out of the response area — fetched through the page's own session so
    auth-gated CDN links work — and return attachment records that later
    stages can re-upload. Falls back to screenshotting the rendered element."""
    import base64
    from selenium.webdriver.common.by import By

    sel = agent_cfg.get("response_selector", "")
    try:
        imgs = driver.find_elements(By.CSS_SELECTOR, f"{sel} img" if sel else "img")
    except Exception:
        return []

    out, seen = [], set()
    try:
        driver.set_script_timeout(20)
    except Exception:
        pass
    for img in imgs:
        try:
            src = img.get_attribute("src") or ""
            w = driver.execute_script("return arguments[0].naturalWidth || 0", img)
            h = driver.execute_script("return arguments[0].naturalHeight || 0", img)
        except Exception:
            continue
        # Icons, avatars and citation thumbnails are small — real generated
        # images aren't.
        if not src or src in seen or w < 256 or h < 256:
            continue
        seen.add(src)
        raw, mime = None, "image/png"
        try:
            data = driver.execute_async_script(
                """
                const src = arguments[0], done = arguments[arguments.length - 1];
                fetch(src, {credentials: 'include'})
                    .then(r => r.blob())
                    .then(b => { const fr = new FileReader();
                                 fr.onloadend = () => done(fr.result);
                                 fr.readAsDataURL(b); })
                    .catch(() => done(null));
                """, src)
            if data and data.startswith("data:"):
                header, b64 = data.split(",", 1)
                raw = base64.b64decode(b64)
                mime = header[5:].split(";")[0] or "image/png"
        except Exception:
            raw = None
        if not raw:
            try:
                raw = img.screenshot_as_png   # rendered pixels — always works
            except Exception:
                continue
        if not mime.startswith("image/"):
            continue
        ext = {"image/png": ".png", "image/jpeg": ".jpg",
               "image/webp": ".webp", "image/gif": ".gif"}.get(mime, ".png")
        path = os.path.join(tempfile.gettempdir(),
                            f"prism_{stage}_img{len(out) + 1}{ext}")
        with open(path, "wb") as f:
            f.write(raw)
        out.append({"path": path, "name": os.path.basename(path), "size": len(raw),
                    "mime": mime, "kind": "image", "text": None, "truncated": False})
        if len(out) >= 4:
            break
    return out


def _smart_wait(driver, agent_cfg, cap: int, poll: int = 5,
                stable_for: int = 15, min_wait: int = 20) -> int:
    """Wait for the agent to finish generating — but no longer than needed.
    Polls the response selector and returns once the total response text has
    stopped growing for `stable_for` seconds (after having grown at least
    once). `cap` is the hard maximum (the old fixed sleep), so a selector
    that never matches degrades to the previous behaviour, not a hang."""
    from selenium.webdriver.common.by import By
    sel = agent_cfg.get("response_selector", "")
    start = time.time()
    baseline = last_len = None
    last_change = start
    grown = False
    while time.time() - start < cap:
        time.sleep(poll)
        try:
            total = sum(len(el.text) for el in
                        driver.find_elements(By.CSS_SELECTOR, sel))
        except Exception:
            continue
        if baseline is None:
            # First reading — whatever is already on the page (our own typed
            # prompt, old chat turns) doesn't count as generation.
            baseline = last_len = total
            continue
        if total != last_len:
            grown = grown or total > baseline
            last_len = total
            last_change = time.time()
        elif (grown and time.time() - start >= min_wait
              and time.time() - last_change >= stable_for):
            break
    return int(time.time() - start)


def _click_by_text(driver, texts: list[str], timeout: int = 10) -> bool:
    """Best-effort: click the first visible, clickable element whose text
    matches one of `texts` (case-insensitive, substring). NotebookLM's UI
    doesn't expose stable ids/classes the way ChatGPT/Claude do, so matching
    on visible button/label TEXT is the more durable anchor here. Returns
    False (never raises) if nothing matched within `timeout`."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    parts = []
    for t in texts:
        tl = t.lower()
        parts.append(
            "//*[self::button or self::a or self::span or self::div or self::li]"
            "[contains(translate(normalize-space(.), "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
            f"'{tl}')]"
        )
    xpath = " | ".join(parts)
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, xpath)))
        el.click()
        return True
    except Exception:
        return False


def _run_notebooklm(driver, agent_cfg: dict, stage: str, prompt: str) -> list[str]:
    """NotebookLM is not a chat box — it's a 'sources' notebook. This drives
    its multi-step UI as best-effort automation:
      1. start a fresh notebook (so this run's source doesn't mix with old ones)
      2. add a "Copied text" source and paste the engineered prompt/context —
         NotebookLM's only free-text input surface
      3. wait for that source to finish processing
      4. MEDIA stage → open Studio and trigger the Video Overview generator
         (a real, multi-minute async render — this only REQUESTS it and
         returns; the finished video appears in the notebook afterwards)
         any other stage → ask the actual question in NotebookLM's chat and
         scrape its answer

    UNVERIFIED against a live session — Google's Material UI class names
    churn often and this environment has no live browser to test against, so
    every step is wrapped to fail soft with a clear message instead of
    hanging or crashing the whole pipeline run. Expect to need real-world
    iteration on the exact button/label text if Google changes the UI."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    try:
        # 1) Fresh notebook.
        _click_by_text(driver, ["create new", "new notebook", "+ new"], timeout=15)
        time.sleep(3)

        # 2) Add a "Copied text" source with the engineered prompt as its content.
        if not _click_by_text(driver, ["copied text", "paste text"], timeout=15):
            return ["NotebookLM: couldn't find the 'Add source → Copied text' "
                    "option — the UI may have changed. Check the open tab; the "
                    "notebook may still be usable manually from here."]
        time.sleep(1)
        try:
            box = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "textarea")))
        except Exception:
            return ["NotebookLM: the paste-text box never appeared — check "
                    "the open tab and add the source manually if needed."]
        if not _fast_type(driver, box, prompt):
            box.send_keys(prompt)
        time.sleep(1)
        _click_by_text(driver, ["insert", "add source", "add"], timeout=10)

        # 3) Wait for the source to finish processing (spinner-based, capped).
        start = time.time()
        while time.time() - start < 90:
            try:
                busy = driver.execute_script(
                    "return !!document.querySelector("
                    "\"[role='progressbar'], .animate-spin, [aria-busy='true']\");")
            except Exception:
                busy = False
            if not busy:
                break
            time.sleep(3)

        if stage == "media":
            # 4a) Request the Video Overview — this is a long async render;
            # we trigger it and move on rather than blocking the whole
            # pipeline for the many minutes it can take.
            _click_by_text(driver, ["studio"], timeout=10)
            time.sleep(1)
            got = _click_by_text(
                driver, ["video overview", "generate video overview"], timeout=10)
            if not got:
                return ["NotebookLM: the source was added, but the Studio → "
                        "Video Overview button couldn't be found automatically "
                        "— open the tab and click Generate manually."]
            return ["NotebookLM Video Overview requested. Generation takes "
                    "several minutes — check the notebook tab afterwards for "
                    "the finished video."]

        # 4b) Any other stage: ask the actual question in NotebookLM's chat.
        try:
            chat = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "textarea, div[contenteditable='true']")))
        except Exception:
            return ["NotebookLM: the source was added, but no chat box was "
                    "found to ask the question — check the open tab."]
        if not _fast_type(driver, chat, prompt):
            chat.send_keys(prompt)
        chat.send_keys(Keys.ENTER)
        time.sleep(agent_cfg.get("wait_time", 45))
        texts = [e.text.strip() for e in driver.find_elements(
            By.CSS_SELECTOR, ".prose, .markdown, [role='article']") if e.text.strip()]
        texts = [t for t in texts if len(t) > 50]
        return texts or ["NotebookLM answered, but no response text could be "
                          "scraped automatically — check the open tab."]
    except Exception as e:
        return [f"NotebookLM automation stopped early at an unverified UI "
                f"step ({e}). Check the open tab — your source/prompt may "
                f"still be usable manually from here."]


def run(routing: dict, cfg: dict, attachments=None, on_event=None,
        query: str = "", chatgpt_analysis: bool = True):
    """Execute the pipeline. Returns (responses, links).

    attachments: list of records from core.files.attach() — uploaded to each
                 tool and their extracted text prepended to the first prompt.
    query: the user's original task — gives the file-analysis stage its focus.
    chatgpt_analysis: when attachments exist, prepend a ChatGPT stage that
                 analyses the files first (skipped if the pipeline already
                 starts with ChatGPT, or when the caller routes its own
                 analysis, e.g. /email).
    on_event(kind, payload) is an optional callback for live UI updates.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from . import files as F

    attachments = attachments or []
    attach_ctx = F.context_block(attachments)

    def emit(kind, payload):
        if on_event:
            on_event(kind, payload)

    agents = {k: v for k, v in (cfg.get("agents") or {}).items() if v}
    stages = list(_needed_stages(routing, agents))
    if not stages:
        ui.warn("Router marked every stage as not-needed — nothing to run.")
        return {}, {}

    # ChatGPT is Prism's dedicated file analyst: whenever attachments ride
    # along, it reads them FIRST and hands a precise brief to the pipeline —
    # its file/vision handling is the most reliable of the web tools. If this
    # stage fails, `prior` stays empty and the next stage gets the raw files
    # re-supplied, so the run degrades gracefully to the old behaviour.
    if attachments and chatgpt_analysis and stages[0][1] != "ChatGPT":
        names = ", ".join(a["name"] for a in attachments)
        goal = f" for this task: {query}" if query.strip() else " for the user's task"
        q = (f"Your ONLY task is: analyse the attached file(s) ({names}) thoroughly — "
             "their content, structure, key facts, numbers, data and style — and "
             "produce a short, precise brief of everything the next AI needs to "
             f"use these files{goal}. Do NOT perform the task itself.")
        stages.insert(0, ("analysis", "ChatGPT", [q]))
        ui.info("📎  attachments present — ChatGPT will analyse the files first")

    driver = _setup_chrome_driver(parse_chrome_version(cfg.get("chrome_version")))
    all_responses: dict[str, list[str]] = {}
    all_links: dict[str, str] = {}
    pipeline_files: list[dict] = []   # images GENERATED by earlier stages
    first_tab = True

    try:
        for stage_idx, (stage, agent_name, questions) in enumerate(stages):
            agent_cfg = A.resolve_agent(stage, agent_name)
            if not agent_cfg:
                ui.warn(f"No registry entry for {agent_name} — skipping {stage}.")
                continue

            emit("stage_start", {"stage": stage, "agent": agent_name})
            ui.rule(f"{stage.upper()}  ·  {agent_name}", style=A.CATEGORIES.get(stage, {}).get("color", "pink"))

            try:
                if not first_tab:
                    driver.execute_script("window.open('');")
                    time.sleep(1)
                    driver.switch_to.window(driver.window_handles[-1])
                first_tab = False
                driver.get(agent_cfg["url"])
                time.sleep(agent_cfg.get("page_wait", 4))

                # Only NON-EMPTY prior outputs count — a failed scrape must not
                # inject an empty "[STAGE]" block downstream.
                prior = [(s, t) for s, t in all_responses.items()
                         if t and any(x.strip() for x in t)]

                # Attachments are analysed ONCE, by the first stage, which hands
                # its findings forward. Later stages build on those findings and
                # do NOT get the raw file again — with two exceptions:
                #   • nothing usable came back from earlier stages (a scrape
                #     failed), so the stage would otherwise be blind;
                #   • PRODUCER stages — the agents that actually make the
                #     deliverable (image, reel, app, deck). Text handoffs dilute
                #     a document's exact copy and can't carry images/video at
                #     all, so the maker gets the user's original files too.
                producer = stage in ("visual", "media", "development", "presentation")
                include_attachment = bool(attachments) and (
                    stage_idx == 0 or not prior or producer)
                # Producers also receive files GENERATED by earlier stages
                # (e.g. the logo the visual stage just made) — those can't
                # travel in a text handoff at all.
                send_files = (attachments if include_attachment else []) + \
                             (pipeline_files if producer else [])
                if send_files:
                    _upload_files(driver, agent_cfg, send_files)

                # Relay hand-off: forward ONLY the most recent stage's output.
                # Every agent is instructed (below) to fold the key findings of
                # everything before it into its own answer, so the latest output
                # already carries the whole chain — re-sending every older stage
                # would only bloat and slow down the prompt.
                context = attach_ctx if include_attachment else ""
                if producer and pipeline_files:
                    names = ", ".join(f["name"] for f in pipeline_files)
                    context += (
                        f"An earlier pipeline stage GENERATED these image file(s), "
                        f"uploaded to this chat: {names}. Use them as assets in "
                        "what you produce — do not recreate them from scratch.\n\n"
                    )
                if prior:
                    prev_stage, prev_texts = prior[-1]
                    prev_text = "\n\n".join(t for t in prev_texts if t.strip())
                    if len(prev_text) > _MAX_FORWARD_CHARS:
                        prev_text = prev_text[-_MAX_FORWARD_CHARS:]
                    context += (
                        f"Context from the previous pipeline stage ({prev_stage.upper()}) — "
                        "it already includes the distilled findings of every stage "
                        "before it. Build directly on this brief:\n\n"
                        f"{prev_text}\n\n"
                        "Now continue the pipeline and complete the following:\n\n"
                    )

                if stage_idx + 1 < len(stages):
                    nxt_stage, nxt_agent, _ = stages[stage_idx + 1]
                    rules = [
                        "Perform ONLY the task above — nothing more. Do not build, "
                        "design or produce anything that was not explicitly asked of you.",
                    ]
                    if prior:
                        rules.append(
                            "First analyse the context above from the previous stage and "
                            "extract its most important findings in a short, precise form — "
                            "they must survive into your handoff."
                        )
                    rules.append(
                        f"Your output will be passed directly to {nxt_agent} (the "
                        f"'{nxt_stage}' stage of this pipeline), and {nxt_agent} will see "
                        f"ONLY your answer — nothing from earlier stages. End with a "
                        f"section titled 'HANDOFF FOR {nxt_agent.upper()}' containing a "
                        f"short, precise summary of every key finding, decision and "
                        f"constraint so far (earlier stages' AND your own) that "
                        f"{nxt_agent} needs to do its job."
                    )
                    rules.append(
                        "Your reader is another AI, not a human — never end with a "
                        "follow-up question or an offer of options. The handoff "
                        "section must be the LAST thing in your answer."
                    )
                    handoff = "\n\nSTRICT PIPELINE RULES:\n" + "\n".join(
                        f"{i}. {r}" for i, r in enumerate(rules, 1))
                else:
                    handoff = (
                        "\n\nSTRICT PIPELINE RULES:\n"
                        "You are the FINAL stage. The context above is your complete "
                        "brief — everything important from earlier stages is already "
                        "distilled into it. Perform ONLY the task above and deliver the "
                        "polished final result. Do not add any handoff or summary "
                        "section, and do not ask any follow-up questions."
                    )

                if agent_name == "NotebookLM":
                    # NotebookLM is not a chat box — it's a "sources" notebook
                    # (add a source, then either ask about it or generate a
                    # Video/Audio Overview). Best-effort automation driven by
                    # visible button TEXT rather than CSS classes, since
                    # Google's Material UI class names churn too often to
                    # hard-code reliably — see _run_notebooklm()'s docstring.
                    nb_prompt = _bmp_safe((context + "\n\n".join(questions) + handoff))
                    stage_responses = _run_notebooklm(driver, agent_cfg, stage, nb_prompt)
                else:
                    for idx, prompt in enumerate(questions, 1):
                        try:
                            ui.info(f"   → prompt {idx}/{len(questions)}: {prompt[:80]}…")
                            textarea = WebDriverWait(driver, agent_cfg.get("input_wait", 15)).until(
                                EC.presence_of_element_located(
                                    (By.CSS_SELECTOR, agent_cfg["textarea_selector"]))
                            )
                            try:
                                textarea.clear()
                            except Exception:
                                pass

                            full_prompt = ((context + prompt) if (idx == 1 and context) else prompt) + handoff
                            full_prompt = _bmp_safe(full_prompt)  # strip emoji ChromeDriver can't type
                            if not _fast_type(driver, textarea, full_prompt):
                                # JS insertion didn't take on this site — fall back
                                # to per-keystroke typing (slow but universal).
                                lines = full_prompt.split("\n")
                                for i, line in enumerate(lines):
                                    if line:
                                        textarea.send_keys(line)
                                    if i < len(lines) - 1:
                                        textarea.send_keys(Keys.SHIFT, Keys.ENTER)
                            time.sleep(1)

                            # Submit — try the button, fall back to Enter.
                            submitted = False
                            sel = agent_cfg.get("submit_selector", "")
                            if sel:
                                try:
                                    btn = WebDriverWait(driver, 5).until(
                                        EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
                                    btn.click()
                                    submitted = True
                                except Exception:
                                    pass
                            if not submitted:
                                textarea.send_keys(Keys.ENTER)

                            if idx < len(questions):
                                # Let this answer finish before sending the next prompt.
                                _smart_wait(driver, agent_cfg, 120)
                        except Exception as e:
                            ui.err(f"   prompt error: {e}")

                    wait = agent_cfg.get("wait_time", 60)
                    ui.info(f"   ⏳  waiting up to {wait}s for {agent_name} to finish…")
                    emit("waiting", {"stage": stage, "seconds": wait})
                    took = _smart_wait(driver, agent_cfg, wait)
                    ui.info(f"   ✓  response settled after {took}s")

                    elements = driver.find_elements(By.CSS_SELECTOR, agent_cfg.get("response_selector", ""))
                    texts = []
                    for el in elements:
                        try:
                            t = el.text.strip()
                        except Exception:
                            continue
                        if len(t) > 50 and t not in texts:
                            texts.append(t)
                    # Response selectors often match a container AND pieces inside it
                    # (sections, citation chips…). Keep only the fullest captures:
                    # drop any text that is contained inside another element's text.
                    texts = [t for t in texts if not any(t != u and t in u for u in texts)]
                    if not texts:
                        stage_responses = []
                    elif len(questions) == 1:
                        # One prompt → one answer: the biggest surviving capture IS it.
                        stage_responses = [max(texts, key=len)]
                    else:
                        stage_responses = texts[-len(questions):]
                if stage_responses:
                    ui.info(f"   📥  captured {sum(len(t) for t in stage_responses)} chars")

                all_links[stage] = driver.current_url
                all_responses[stage] = stage_responses

                # Image-making stages: pull the generated images off the page so
                # later stages can actually use them (text handoffs can't).
                if stage in ("visual", "media") and stage_idx + 1 < len(stages):
                    made = _harvest_images(driver, agent_cfg, stage)
                    if made:
                        pipeline_files = (pipeline_files + made)[-6:]
                        ui.info(f"   🖼️   harvested {len(made)} generated image(s) "
                                "for the next stages")

                if stage_responses:
                    ui.ok(f"captured {len(stage_responses)} response(s)")
                    emit("stage_done", {"stage": stage, "count": len(stage_responses),
                                        "snippet": stage_responses[0][:200],
                                        "texts": stage_responses, "url": driver.current_url})
                else:
                    ui.warn("no response scraped, but link saved")
                    emit("stage_done", {"stage": stage, "count": 0, "texts": [],
                                        "url": driver.current_url})
                ui.info(f"   🔗  {driver.current_url}")

            except Exception as ex:
                ui.err(f"stage {stage} failed: {ex}")
                emit("stage_error", {"stage": stage, "error": str(ex)})
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    return all_responses, all_links


def open_login_tabs(urls: list[str]):
    """Open each tool's URL in Chrome so the user can sign in before a real run."""
    first = True
    for url in urls:
        for chrome in _CHROME_BINARIES:
            if os.path.exists(chrome):
                subprocess.Popen([chrome, url])
                break
        else:
            webbrowser.open(url)
        # Chrome may be cold-starting on the first URL — give its singleton
        # lock time to settle so the remaining tabs join the same instance
        # instead of racing it and getting dropped.
        time.sleep(2.5 if first else 0.4)
        first = False

