#!/usr/bin/env python3
"""
Prism — terminal
────────────────
One prompt → many specialist AIs, in sequence. A modern, Claude-Code-style REPL
that replaces the old Google-Drive watcher. Type a task; Groq splits it across
the agents you chose; Prism drives your logged-in Chrome to run each one and
hands the output forward.

    python3 prism.py            # interactive REPL
    python3 prism.py "task…"    # run one task and exit
    python3 prism.py --dry "…"  # show the routing plan only
    python3 prism.py --config   # re-run setup
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import config as C          # noqa: E402
from core import ui                   # noqa: E402
from core import router               # noqa: E402
from core import agents as A          # noqa: E402
from core import onboarding           # noqa: E402


# ── query execution ───────────────────────────────────────────────────────────

def run_query(cfg: dict, query: str, dry: bool, attachments: list | None = None,
              confirm: bool = True) -> None:
    if not query.strip():
        ui.warn("Empty task — nothing to route.")
        return
    attachments = attachments or []
    ui.rule("Routing", "teal")
    if attachments:
        ui.info(f"📎  {len(attachments)} file(s) attached to this task.")
    ui.info("🧠  asking Groq to split your task…")
    try:
        routing = router.route(query, cfg, attachments)
    except Exception as e:
        ui.err(str(e))
        return

    ui.routing_plan(routing, C.active_agents(cfg))
    _show_prompt_upgrade(query, routing, C.active_agents(cfg))
    if attachments:
        ui.info("📎  plus an ANALYSIS stage first (not shown above): ChatGPT reads "
                "the attached file(s) and briefs the pipeline.")

    if dry:
        ui.info("\nDry run — no browser opened. This is exactly what would execute.")
        C.save_run({"query": query, "dry": True, "routing": routing,
                    "attachments": [a["name"] for a in attachments]})
        return

    run_agents = _apply_named_tools(routing, C.active_agents(cfg))
    run_agents = _offer_agent_alternatives(routing, run_agents)

    # confirm before touching the browser (skipped for remote prompts — the
    # sender isn't at the keyboard to answer)
    if confirm:
        from core.onboarding import _ask_confirm
        _flush_stdin_noise()
        if not _ask_confirm("\nRun this plan against your logged-in browser now?", default=True):
            ui.info("Cancelled. (Tip: prefix with '/dry ' to preview without running.)")
            return

    try:
        from core import automation
    except Exception as e:
        ui.err(f"Automation deps not available ({e}). Install requirements.txt.")
        return

    cfg_for_run = cfg
    if run_agents != C.active_agents(cfg):
        cfg_for_run = dict(cfg)
        cfg_for_run["agents"] = run_agents

    try:
        responses, links = automation.run(routing, cfg_for_run, attachments=attachments, query=query)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        # Driver setup (Chrome missing, driver download, unsupported OS) can
        # raise before the per-stage error handling — never kill the REPL.
        ui.err(f"run failed before completing: {e}")
        return

    ui.rule("Results", "pink")
    if links:
        for stage, url in links.items():
            resp = responses.get(stage) or []
            ui.say(f"[bold]{stage.upper()}[/bold]  →  {url}")
            if resp:
                ui.info(f"   {resp[0][:280]}…")
    else:
        ui.warn("No agent produced output. Are you logged in to each tool in Chrome?")

    path = C.save_run({"query": query, "routing": routing,
                       "responses": responses, "links": links,
                       "attachments": [a["name"] for a in attachments]})
    ui.ok(f"Run saved → {path}")


def _esc(text: str) -> str:
    """Escape rich markup in untrusted text (LLM output, transcripts, paths) —
    a stray '[anything]' would otherwise crash the styled display."""
    try:
        from rich.markup import escape
        return escape(text)
    except Exception:
        return text


def _show_prompt_upgrade(query: str, routing: dict, agents: dict):
    """Show the full transformation chain — raw words → task brief → the
    engineered prompt each AI actually receives — so the difference between
    what the user gave and what Prism built from it is always visible."""
    from core import agents as A
    stages = [(s, d) for s in A.PIPELINE_ORDER
              for d in [routing.get(s)]
              if d and d.get("needed") and d.get("questions")]
    if not stages:
        return
    parts = [f'[bold]1 · You said:[/bold]  [dim]"{_esc(query.strip())}"[/dim]\n']
    brief = (routing.get("_brief") or "").strip()
    if brief:
        parts.append(f"[bold]2 · Prism expanded it into this task brief:[/bold]\n{_esc(brief)}\n")
    step = 3 if brief else 2
    parts.append(f"[bold]{step} · …and engineered each AI's prompt from it:[/bold]\n")
    for stage, data in stages:
        agent = agents.get(stage) or A.summary_agent_name(agents) or ""
        for q in data["questions"]:
            parts.append(f"[bold]{stage.upper()}[/bold] [dim]({_esc(agent)}) gets:[/dim]\n{_esc(q)}\n")
    ui.panel("\n".join(parts).strip(), title="your words → engineered prompts", style="teal")


def _apply_named_tools(routing: dict, agents: dict) -> dict:
    """The user can directly ORDER a specific tool ("using NotebookLM…",
    "notebook lm video generation") — router.detect_named_tools() catches
    this deterministically, no LLM judgement call needed. Force it in for any
    stage that's actually running this task; no guessing, no picker, just a
    one-line notice. Returns the agent mapping to use for THIS run — the
    user's saved defaults (/agents) are never touched."""
    named = routing.get("_named_tools") or {}
    if not named:
        return agents
    run_agents = dict(agents)
    for stage, tool in named.items():
        data = routing.get(stage) or {}
        if not (data.get("needed") and data.get("questions")):
            continue   # this stage isn't even running this task
        if run_agents.get(stage) == tool:
            continue   # already the default — nothing to announce
        run_agents[stage] = tool
        ui.info(f"🗣️  you asked for [bold]{_esc(tool)}[/bold] — using it for "
                f"{stage.upper()} this run.")
    return run_agents


def _offer_agent_alternatives(routing: dict, agents: dict) -> dict:
    """Only for stages where the router found a clearly better-suited tool:
    show that category's FULL tool list as a numbered table — your current
    pick marked ●, the router's suggestion starred ★ — and let you switch to
    ANY of them, or skip (Enter). Stages with no suggestion stay silent, no
    prompt at all. The user's saved defaults (/agents) are never touched —
    this only affects the run about to execute."""
    seen = {}
    for s in routing.get("_suggestions") or []:
        stage = s.get("stage")
        if stage and s.get("suggested"):
            seen[stage] = s   # last one wins if the router somehow doubled up
    if not seen:
        return agents
    run_agents = dict(agents)
    for stage, s in seen.items():
        current, suggested, reason = s["current"], s["suggested"], s.get("reason", "")
        if run_agents.get(stage) != current:
            continue   # default already differs from what this suggestion assumed — skip
        names = A.CATEGORIES.get(stage, {}).get("agents", [])
        if not names:
            continue
        ui.agent_pick_table(stage, current, suggested)
        ui.info(f"   why {_esc(suggested)}: {_esc(reason)}")
        ans = _prompt(f"   keep {current}? [Enter]  or type a # to switch (this task only) ").strip()
        if not ans:
            continue
        if ans.isdigit() and 1 <= int(ans) <= len(names):
            pick = names[int(ans) - 1]
            if pick != current:
                run_agents[stage] = pick
                ui.ok(f"   {stage} → {pick} for this run.")
        else:
            ui.warn("   not a valid number — keeping your default.")
    return run_agents


# ── slash commands ────────────────────────────────────────────────────────────

HELP = """
[bold]Commands[/bold]
  [teal]/help[/teal]        show this help
  [teal]/status[/teal]      current profile, key & agents
  [teal]/catalog[/teal]     the full tool catalogue
  [teal]/agents[/teal]      re-pick one agent per category
  [teal]/profile[/teal]     change what-you-do
  [teal]/key[/teal]         change your Groq API key
  [teal]/chrome[/teal]      set/edit your pinned Chrome version (or auto-detect)
  [teal]/login[/teal]       re-open your tools in Chrome to sign in
  [teal]/config[/teal]      re-run the whole setup wizard
  [teal]/attach <path…>[/teal]  attach file(s) of any type to your next task
  [teal]/find <description>[/teal]  locate & attach a file described in plain words
                ("the brochure in the prism folder of python program in documents")
  [teal]/files[/teal]       list currently attached files
  [teal]/detach[/teal]      clear all attached files
  [teal]/runs[/teal]        list saved runs
  [teal]/dry <task>[/teal]  preview routing without opening a browser
  [teal]/remote[/teal]      host a local website that sends prompts to this terminal
  [teal]/remote <code>[/teal]  pair a 4-digit code & listen (local bridge or relay)
  [teal]/remote url <link>[/teal]  set a hosted relay → pair with anyone over the internet
  [teal]/remote stop[/teal] shut the local bridge down
  [teal]/email setup[/teal]  configure your sending account (SMTP, one time)
  [teal]/email <goal>[/teal]  draft an email from attached files & send it — recipients
                from an attached CSV and/or addresses written in the prompt
  [teal]/exit[/teal]        quit

Anything else you type is treated as a task and routed to your agents.
Attached files ride along with your next task (and stay until you /detach).
"""


def cmd_status(cfg):
    ui.status_header(cfg, C.active_agents(cfg))
    premium = cfg.get("premium") or []
    if premium:
        ui.info(f"⭐  premium plans: {', '.join(premium)} (routed the bulk of the work)")


def cmd_agents(cfg):
    cfg["agents"] = onboarding.collect_agents(cfg.get("agents", {}))
    cfg["premium"] = onboarding.collect_premium(cfg["agents"], cfg.get("premium"))
    C.save(cfg)
    ui.ok("Agents updated.")
    cmd_status(cfg)


def cmd_profile(cfg):
    cfg["profile"] = onboarding.collect_profile(cfg.get("profile", ""))
    C.save(cfg)
    ui.ok("Profile updated.")


def cmd_key(cfg):
    cfg["api_key"] = onboarding.collect_key(cfg.get("api_key", ""))
    C.save(cfg)
    ui.ok("Key updated.")


def cmd_chrome(cfg):
    cfg["chrome_version"] = onboarding.collect_chrome(cfg.get("chrome_version", ""))
    C.save(cfg)
    pinned = cfg["chrome_version"]
    ui.ok(f"Chrome version set to {'v' + pinned if pinned else 'auto-detect'}.")


def cmd_login(cfg):
    onboarding.login_step(C.active_agents(cfg))


def cmd_config(cfg):
    new = onboarding.run(cfg)
    fr = new.pop("_firstrun", "skip")
    C.save(new)
    _handle_firstrun(new, fr)
    return new


def _attach_folder_interactive(dirpath: str, attachments: list) -> None:
    """Folder flow (typed, described or spoken): ALWAYS show what's inside,
    then let the user pick specific files or take everything."""
    from core import files as F
    listing = sorted(
        os.path.join(dirpath, f) for f in os.listdir(dirpath)
        if not f.startswith(".") and os.path.isfile(os.path.join(dirpath, f)))
    if not listing:
        ui.warn(f"Folder {_esc(dirpath)} has no attachable files.")
        return
    ui.say(f"  Files in {_esc(os.path.basename(dirpath) or dirpath)}:")
    for i, f in enumerate(listing, 1):
        ui.say(f"   {i}. {_esc(os.path.basename(f))}")
    ui.warn(f"Prism attaches at most {F.MAX_DIR_FILES} files per folder — and on "
            "ChatGPT's FREE plan only a handful of uploads per day get through, "
            "so fewer, well-chosen files give better results on free tiers.")
    ans = _prompt("attach which? (Enter/'a' = all, or numbers like 1 3 5) ").strip().lower()
    if ans in ("", "a", "all", "y", "yes"):
        chosen = listing[:F.MAX_DIR_FILES]
    else:
        nums = [int(t) for t in ans.replace(",", " ").split() if t.isdigit()]
        chosen = [listing[n - 1] for n in nums if 1 <= n <= len(listing)]
        if not chosen:
            ui.info("cancelled.")
            return
        chosen = chosen[:F.MAX_DIR_FILES]
    added = []
    for fp in chosen:
        try:
            added.append(F.attach(fp))
        except Exception as e:
            ui.err(f"Could not attach {os.path.basename(fp)}: {e}")
    attachments.extend(added)
    if added:
        ui.ok(f"Attached {len(added)} file(s): " + ", ".join(_esc(a["name"]) for a in added))


def cmd_find(arg, cfg, attachments):
    """Resolve a spoken/casual description of a file's location and attach it."""
    from core import pathfinder as PF, files as F
    if not arg:
        ui.warn('Usage: /find <where the file is, in your own words>\n'
                'e.g.  /find the brochure pdf in the prism ai flow folder '
                'of python program in documents')
        return
    ui.info("🔎  interpreting the description…")
    res = PF.find(arg, cfg)
    hints = _esc(" → ".join(res["folders"]) or "?")
    files = res["files"]
    if not files and res["dir"]:
        # Folder located, no specific filename — confirm it's the RIGHT
        # folder before listing contents (fuzzy matching can pick a
        # same-named sibling, or mishear a spoken folder name entirely).
        ui.ok(f"Folder found: {_esc(res['dir'])}   (heard: {hints})")
        ans = _prompt("Is this the right folder? (Y/n) ").strip().lower()
        if ans in ("n", "no"):
            corrected = _prompt("type the correct folder name/path: ").strip()
            if not corrected:
                ui.info("cancelled.")
                return
            cp = os.path.abspath(os.path.expanduser(corrected))
            if os.path.isdir(cp):
                _attach_folder_interactive(cp, attachments)
            else:
                cmd_find(corrected, cfg, attachments)
            return
        _attach_folder_interactive(res["dir"], attachments)
        return
    if not files:
        ui.err(f"Couldn't locate anything for: {hints}"
               + (f" / {_esc(res['filename'])}" if res["filename"] else ""))
        return
    if len(files) == 1:
        choice = files[0]
        # A lone fuzzy match can still be the WRONG file — the underlying LLM
        # parse isn't perfectly deterministic even at temperature 0, so the
        # SAME description can resolve differently between runs. ALWAYS
        # confirm before a guess rides silently into every AI tool.
        ans = _prompt(f"Match found: {choice} — attach it? (Y/n) ").strip().lower()
        if ans in ("n", "no"):
            corrected = _prompt("type the correct file name/path (Enter to cancel): ").strip()
            if not corrected:
                ui.info("cancelled.")
                return
            cp = os.path.abspath(os.path.expanduser(corrected))
            if os.path.isfile(cp):
                choice = cp
            else:
                return cmd_find(corrected, cfg, attachments)
    else:
        ui.say("  Matches:")
        for i, f in enumerate(files, 1):
            ui.say(f"   {i}. {_esc(f)}")
        picked = _prompt("attach which? (number, Enter to cancel)").strip()
        if not picked.isdigit() or not (1 <= int(picked) <= len(files)):
            ui.info("cancelled.")
            return
        choice = files[int(picked) - 1]
    try:
        att = F.attach(choice)
    except Exception as e:
        ui.err(f"Could not attach {choice}: {e}")
        return
    attachments.append(att)
    note = "text extracted" if att["text"] else "will upload as-is"
    ui.ok(f"Attached {att['name']} ({att['kind']}, {note})")


def cmd_attach(arg, attachments, cfg=None):
    import shlex
    from core import files as F
    try:
        paths = shlex.split(arg)
    except ValueError:
        paths = arg.split()
    if not paths:
        ui.warn("Usage: /attach <path> [more paths…]   (quote paths with spaces)")
        return
    # An unquoted path with spaces ("/attach my project notes.pdf") is one
    # real file, not a description — attach it directly.
    whole = os.path.expanduser(arg.strip().strip('"').strip("'"))
    if len(paths) > 1 and os.path.isfile(whole):
        paths = [whole]
    # A multi-word argument where nothing exists on disk reads like a spoken
    # description ("the report in my documents folder") — hand it to /find.
    elif cfg is not None and len(paths) >= 3 and not any(
            os.path.exists(os.path.expanduser(p)) for p in paths):
        ui.info("that doesn't look like a path — trying to find it from your description")
        return cmd_find(arg, cfg, attachments)
    for p in paths:
        p_exp = os.path.abspath(os.path.expanduser(p))
        if os.path.isdir(p_exp):
            # A folder: show contents, let the user pick files or take all.
            _attach_folder_interactive(p_exp, attachments)
            continue
        try:
            att = F.attach(p)
        except FileNotFoundError:
            ui.err(f"Not a file: {p}")
            continue
        except Exception as e:
            ui.err(f"Could not attach {p}: {e}")
            continue
        attachments.append(att)
        note = "text extracted" if att["text"] else "will upload as-is"
        ui.ok(f"Attached {att['name']} ({att['kind']}, {note})")


def cmd_files(attachments):
    from core import files as F
    if not attachments:
        ui.info("No files attached. Use /attach <path> to add some.")
        return
    for a in attachments:
        ui.say("  • " + F.describe(a))


def cmd_detach(attachments):
    n = len(attachments)
    attachments.clear()
    ui.ok(f"Cleared {n} attachment(s).")


def cmd_runs(cfg):
    import glob
    import json
    files = sorted(glob.glob(os.path.join(C.RUNS_DIR, "run_*.json")), reverse=True)
    if not files:
        ui.info("No runs yet.")
        return
    for fp in files[:15]:
        try:
            with open(fp) as f:
                d = json.load(f)
            tag = "[dim](dry)[/dim]" if d.get("dry") else ""
            ui.say(f"  {os.path.basename(fp)}  {tag}  {d.get('query','')[:70]}")
        except Exception:
            continue


def cmd_remote(cfg, arg: str):
    import time
    from core import remote

    arg = arg.strip()
    if arg in ("stop", "off"):
        if remote.is_running():
            remote.stop()
            ui.ok("Remote bridge stopped.")
        else:
            ui.info("Remote bridge isn't running.")
        return

    if not arg:
        try:
            link = remote.start()
        except Exception as e:
            ui.err(f"Could not start the remote bridge: {e}")
            return
        ui.panel(
            f"Remote bridge is live at  [bold]{link}[/bold]\n\n"
            "1. Open that link on any device on the same Wi-Fi\n"
            "2. The page shows a 4-digit code\n"
            "3. Back here, type  [bold]/remote <that code>[/bold]  to pair & listen",
            title="📡  Prism Remote", style="blue",
        )
        return

    if arg.startswith("url"):
        link = arg[3:].strip()
        if link:
            cfg["remote_relay"] = link.rstrip("/")
            C.save(cfg)
            ui.ok(f"Relay set to {cfg['remote_relay']} — /remote <code> now pairs over the internet.")
        else:
            current = cfg.get("remote_relay", "")
            ui.info(f"Current relay: {current or 'none (local Wi-Fi bridge only)'}\n"
                    "Set one with: /remote url https://your-relay.example.com")
        return

    if not (arg.isdigit() and len(arg) == 4):
        ui.warn("Usage: /remote            start the local bridge (shows the URL)\n"
                "       /remote <4-digit>  pair a code (local bridge, or relay if set)\n"
                "       /remote url <link> set a hosted relay for internet-wide pairing\n"
                "       /remote stop       shut the local bridge down")
        return

    # ── local bridge mode ──────────────────────────────────────────────────
    if remote.is_running():
        if not remote.pair(arg):
            ui.err(f"No local session with code {arg}. Reload the page and use the code it displays.")
            return
        ui.ok(f"Paired with local remote session {arg}.")
        ui.info("Listening for prompts from the website — press Ctrl-C to leave remote mode.")
        try:
            while True:
                item = remote.next_prompt(arg)
                if item is None:
                    time.sleep(1)
                    continue
                pid, prompt = item
                ui.rule("REMOTE TASK", "blue")
                ui.say(f"[bold]›[/bold] {prompt}")
                try:
                    run_query(cfg, prompt, dry=False, confirm=False)
                    remote.set_status(pid, "done")
                except Exception as e:
                    remote.set_status(pid, f"error: {str(e)[:80]}")
                    ui.err(f"remote task failed: {e}")
        except KeyboardInterrupt:
            ui.info("\nLeft remote mode — the bridge is still up (pair again with "
                    "/remote <code>, or /remote stop to shut it down).")
        return

    # ── hosted relay mode (works from anywhere, e.g. a friend's idea) ──────
    base = cfg.get("remote_relay", "")
    if not base:
        ui.err("Nothing to pair against: the local bridge isn't running and no relay is set.\n"
               "  Same Wi-Fi:  /remote          (starts the local bridge)\n"
               "  Internet:    /remote url <link-to-your-hosted-relay>, then /remote <code>")
        return
    token = remote.relay_pair(base, arg)
    if not token:
        ui.err(f"Relay at {base} has no session with code {arg} (codes expire "
               "after 15 min unpaired — ask them to reload the page).")
        return
    ui.ok(f"Paired with code {arg} on {base}.")
    ui.info("Listening for prompts from the relay — press Ctrl-C to stop.")
    try:
        while True:
            try:
                item = remote.relay_next(base, arg, token)
            except Exception:
                time.sleep(5)   # network blip — back off and retry
                continue
            if item is None:
                time.sleep(2)
                continue
            pid, prompt = item
            ui.rule("REMOTE TASK", "blue")
            ui.say(f"[bold]›[/bold] {prompt}")
            try:
                run_query(cfg, prompt, dry=False, confirm=False)
                remote.relay_set_status(base, pid, token, "done")
            except Exception as e:
                remote.relay_set_status(base, pid, token, f"error: {str(e)[:80]}")
                ui.err(f"remote task failed: {e}")
    except KeyboardInterrupt:
        ui.info("\nLeft remote mode.")


def _discover_recipients(cfg, goal: str) -> list:
    """No address given ('email sarvam about…') — find the right public
    contact email via the research/brains agent, then let the USER pick.
    Never guesses silently: discovery runs only after a yes, and the chosen
    address still goes through the normal preview-and-confirm before sending."""
    import re as _re
    from core.onboarding import _ask_confirm
    agents = C.active_agents(cfg)
    finder = next((s for s in ("research", "brains") if agents.get(s)), None)
    if not finder:
        return []
    _flush_stdin_noise()
    if not _ask_confirm(
            f"No address given — have {agents[finder]} search for the right "
            "public contact email first?", default=True):
        return []
    try:
        from core import automation
    except Exception as e:
        ui.err(f"Automation deps not available ({e}).")
        return []
    routing = {finder: {"needed": True, "questions": [
        "Your ONLY task is: find the official, public contact email address for "
        f"the recipient described here: {goal}. Search the web. Reply with the "
        "1-3 best addresses, one per line, each followed by a dash and what it "
        "is for (e.g. partnerships, support, general). Prefer official domains "
        "over aggregator sites. If none can be found, reply exactly NONE."
    ]}}
    try:
        responses, _links = automation.run(routing, cfg, chatgpt_analysis=False)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        ui.err(f"discovery failed: {e}")
        return []
    text = "\n".join(t for ts in responses.values() for t in ts)
    found = list(dict.fromkeys(_re.findall(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)))
    found = [e for e in found if not e.lower().endswith("example.com")][:5]
    if not found:
        ui.warn("No email address found — give one explicitly instead.")
        return []
    ui.say("  Addresses found:")
    for i, e in enumerate(found, 1):
        ui.say(f"   {i}. {_esc(e)}")
    picked = _prompt("send to which? (number, Enter to cancel) ").strip()
    if not picked.isdigit() or not (1 <= int(picked) <= len(found)):
        ui.info("cancelled.")
        return []
    return [{"email": found[int(picked) - 1], "name": ""}]


def cmd_email(cfg, arg: str, attachments: list):
    """/email — mail-merge through the pipeline.

    /email setup                     configure your sending account (once)
    /email <what the email is for>   analyse attachments → draft → send to CSV
    """
    from core import mailer
    from core.onboarding import _ask_text, _ask_confirm

    arg = arg.strip()

    # ── one-time account setup ──────────────────────────────────────────────
    if arg == "setup" or (arg and not mailer.is_configured(cfg)):
        ui.rule("Email account", "orange")
        ui.panel(
            "Prism sends through YOUR account via SMTP — nothing is stored\n"
            "anywhere but ~/.prism/config.json (chmod 600).\n\n"
            "Gmail users: this needs an [bold]app password[/bold], not your real one —\n"
            "create one at  [bold]myaccount.google.com/apppasswords[/bold]",
            title="✉️  Setup", style="orange",
        )
        address = _ask_text("Your email address:",
                            default=(cfg.get("email") or {}).get("address", ""))
        if not address or "@" not in address:
            ui.err("That doesn't look like an email address — aborting setup.")
            return
        password = _ask_text("App password:", secret=True)
        if not password:
            ui.err("No password entered — aborting setup.")
            return
        known = mailer.smtp_for(address)
        if known:
            host, port = known
        else:
            host = _ask_text("SMTP host (e.g. smtp.yourcompany.com):")
            port = _ask_text("SMTP port (465 = SSL, 587 = STARTTLS):", default="587")
        cfg["email"] = {"address": address.strip(), "password": password,
                        "host": host, "port": int(port)}
        C.save(cfg)
        ui.ok(f"Email account saved ({address} via {host}).")
        if arg == "setup":
            return

    if not arg:
        ui.warn("Usage: /email setup              configure your sending account\n"
                "       /email <goal of the email> draft from attachments & send to the CSV\n"
                "First /attach a recipients CSV + the source file (brochure, doc…).")
        return

    # ── recipients: from an attached CSV and/or typed right in the prompt ───
    csvs, source_files = mailer.split_attachments(attachments)
    inline, arg = mailer.recipients_from_text(arg)   # strip addresses from the goal
    recipients = list(inline)
    for a in csvs:
        recipients += mailer.parse_recipients(a["path"])
    seen = set()
    recipients = [r for r in recipients
                  if not (r["email"] in seen or seen.add(r["email"]))]
    if not recipients:
        # "email sarvam about a partnership" — no address anywhere: offer to
        # discover the right public contact email before giving up.
        recipients = _discover_recipients(cfg, arg)
    if not recipients:
        ui.err("No recipients. /attach a CSV with addresses, write one in the "
               "prompt (/email tell them about X — a@x.com), or say yes to "
               "the email search.")
        return
    if not arg.strip():
        ui.err("The prompt only contained addresses — also say what the email is about.")
        return
    src = " + ".join(filter(None, [
        f"{len(inline)} from the prompt" if inline else "",
        f"{len(recipients) - len(inline)} from {', '.join(a['name'] for a in csvs)}" if csvs else "",
    ]))
    ui.ok(f"{len(recipients)} recipient(s): {src} "
          "(parsed locally — addresses are never shown to any AI).")

    # ── fixed plan: ChatGPT analyses the source files (injected by
    #    automation.run, like every attachment run), then the draft stage ────
    agents = C.active_agents(cfg)
    avail = [s for s in ("research", "brains", "content") if agents.get(s)]
    if not avail:
        ui.err("No research/brains/content agent configured — run /agents first.")
        return
    draft_stage = avail[-1]
    routing = {draft_stage: {"needed": True,
                             "reason": "write the email draft — and ONLY the draft",
                             "questions": [mailer.draft_question(arg)]}}

    ui.routing_plan(routing, agents)
    _flush_stdin_noise()
    if not _ask_confirm("\nRun this plan against your logged-in browser now?", default=True):
        ui.info("Cancelled.")
        return

    try:
        from core import automation
    except Exception as e:
        ui.err(f"Automation deps not available ({e}). Install requirements.txt.")
        return
    responses, links = automation.run(routing, cfg, attachments=source_files,
                                      query=f"write an email: {arg}")

    draft_texts = responses.get(draft_stage) or []
    draft = mailer.parse_draft(draft_texts[0] if draft_texts else "")
    if not draft:
        ui.err("Couldn't find a 'SUBJECT: … / BODY: …' draft in the response.")
        if links.get(draft_stage):
            ui.info(f"Read it yourself and send manually: {links[draft_stage]}")
        return
    subject, body = draft

    # ── preview, confirm, send ──────────────────────────────────────────────
    preview = body if len(body) <= 700 else body[:700] + "…"
    ui.panel(
        f"[bold]Subject:[/bold] {subject}\n\n{preview}\n\n"
        f"[bold]To:[/bold] {len(recipients)} recipient(s) — "
        f"{', '.join(r['email'] for r in recipients[:5])}"
        f"{', …' if len(recipients) > 5 else ''}\n"
        f"[bold]Attachments:[/bold] "
        f"{', '.join(f['name'] for f in source_files) or 'none'}\n"
        f"[bold]From:[/bold] {cfg['email']['address']}",
        title="✉️  Ready to send", style="teal",
    )
    _flush_stdin_noise()
    if not _ask_confirm(f"Send this to all {len(recipients)} recipients now?", default=False):
        ui.info("Not sent. The draft is saved in this run's file (/runs).")
        C.save_run({"query": f"/email {arg}", "routing": routing, "responses": responses,
                    "links": links, "email": {"subject": subject, "sent": [],
                                              "recipients": len(recipients), "confirmed": False}})
        return

    sent, failed = mailer.send_bulk(cfg, recipients, subject, body, source_files)
    if sent:
        ui.ok(f"Sent to {len(sent)}/{len(recipients)} recipient(s).")
    if failed:
        ui.err(f"{len(failed)} failed: " + "; ".join(f"{e} ({msg[:60]})" for e, msg in failed[:5]))
        ui.info("Gmail rejecting logins? Use an app password: myaccount.google.com/apppasswords")
    path = C.save_run({"query": f"/email {arg}", "routing": routing, "responses": responses,
                       "links": links, "email": {"subject": subject, "sent": sent,
                                                 "failed": failed, "recipients": len(recipients)}})
    ui.ok(f"Run saved → {path}")


def _handle_firstrun(cfg, choice):
    if choice == "skip":
        return
    profile = cfg.get("profile", "").strip()
    sample = (f"Give me a quick starter task idea for someone whose work is: {profile}. "
              "Then outline how you'd approach it.") if profile else \
        "Write a short haiku about prisms and refracted light."
    ui.rule("First run", "orange")
    ui.info(f"Sample task: {sample}")
    run_query(cfg, sample, dry=(choice == "dry"))


# ── REPL ──────────────────────────────────────────────────────────────────────

def repl(cfg):
    ui.info("Type [bold]/help[/bold] for commands, or just describe a task. Ctrl-C to quit.\n")
    attachments = []          # ride along with the next task until /detach
    cmd_status(cfg)
    while True:
        try:
            raw, spoken = _get_input(cfg, attachments)
        except (EOFError, KeyboardInterrupt):
            ui.info("\nbye ◈")
            return
        if not raw.strip():
            continue
        line = raw.strip()

        if line in ("/exit", "/quit", "/q"):
            ui.info("bye ◈")
            return
        elif line in ("/help", "/?", "help"):
            ui.panel(HELP.strip(), title="Prism", style="teal")
        elif line == "/status":
            cmd_status(cfg)
            if attachments:
                ui.info(f"📎  {len(attachments)} file(s) attached to your next task.")
        elif line == "/catalog":
            ui.catalog_table()
        elif line == "/agents":
            cmd_agents(cfg)
        elif line == "/profile":
            cmd_profile(cfg)
        elif line == "/key":
            cmd_key(cfg)
        elif line == "/chrome":
            cmd_chrome(cfg)
        elif line == "/login":
            cmd_login(cfg)
        elif line == "/config":
            cfg = cmd_config(cfg)
        elif line.startswith("/attach"):
            cmd_attach(line[len("/attach"):].strip(), attachments, cfg)
        elif line.startswith("/find"):
            cmd_find(line[len("/find"):].strip(), cfg, attachments)
        elif line == "/files":
            cmd_files(attachments)
        elif line == "/detach":
            cmd_detach(attachments)
        elif line == "/runs":
            cmd_runs(cfg)
        elif line.startswith("/remote"):
            cmd_remote(cfg, line[len("/remote"):].strip())
        elif line.startswith("/email"):
            cmd_email(cfg, line[len("/email"):].strip(), attachments)
        elif line.startswith("/dry"):
            run_query(cfg, line[4:].strip(), dry=True, attachments=attachments)
        elif line.startswith("/"):
            ui.warn(f"Unknown command: {line}. Try /help.")
        else:
            run_query(cfg, line, dry=False, attachments=attachments)


def _drain_pending_lines() -> str:
    """Read any lines already sitting in the terminal's input buffer, without
    blocking. A hard-wrapped multi-line paste dumps several newline-separated
    chunks into the tty at once; a single input() call only returns the FIRST
    one, and the rest used to sit there silently and get read as the answer
    to whatever prompt came next (e.g. the Y/n run-confirmation) — corrupting
    the query AND auto-answering the confirm with no chance to respond.
    POSIX only (select on stdin); a no-op on Windows."""
    if os.name == "nt":
        return ""
    import select
    extra = []
    try:
        while True:
            r, _, _ = select.select([sys.stdin], [], [], 0)
            if not r:
                break
            line = sys.stdin.readline()
            if not line:
                break
            extra.append(line.strip())
    except Exception:
        pass
    return " ".join(x for x in extra if x)


def _flush_stdin_noise() -> None:
    """Discard (don't merge) any stray buffered input right before a Y/n-style
    prompt, so a leftover paste fragment can never silently answer it."""
    _drain_pending_lines()


def _prompt(text: str) -> str:
    # Discard any stray buffered input BEFORE showing this prompt — without
    # this, a leftover keystroke from an EARLIER answer (or a paste's
    # overflow) can silently satisfy this NEW question before the user ever
    # sees it rendered. This was the actual cause of "the folder-correction
    # prompt didn't even show up" — it fired and returned instantly against
    # stale buffered text, not against a real keypress.
    _drain_pending_lines()
    try:
        import questionary
        line = questionary.text(text, qmark="◈").ask() or ""
    except Exception:
        line = input(text)
    extra = _drain_pending_lines()
    return f"{line} {extra}".strip() if extra else line


def _confirm_task(task: str) -> str:
    """Show the final task text before it goes to routing and let the user
    confirm or correct it — catches STT mishears and any over-eager cleanup,
    spoken or typed. Typing the fix directly (instead of 'n' first, then
    re-typing) also works. Empty string means the user gave up on this take."""
    ui.say(f'  📝  Prism will route: "{_esc(task)}"')
    ans = _prompt("correct? (Y/n, or type a correction) ").strip()
    low = ans.lower()
    if low in ("", "y", "yes"):
        return task
    if low in ("n", "no"):
        return _prompt("type the corrected task: ").strip()
    return ans   # they typed the fix directly instead of answering y/n first


def _maybe_extract_files(raw: str, cfg, attachments) -> str:
    """Typed queries can mention files/folders too ("grab the delta prototype
    from the desktop and …") — run them through the SAME interpreter used for
    speech so those get located & attached either way, not only when spoken.
    Slash-commands are left completely untouched so /attach, /find, /dry etc.
    still reach the REPL dispatcher verbatim. Only asks for confirmation when
    the interpreter actually changed something — a plain typed task that
    mentioned no files goes straight through, no extra prompt."""
    text = raw.strip()
    if not text or text.startswith("/"):
        return raw
    from core import voice
    intent = voice.interpret(text, cfg)
    if not intent.get("ok", True):
        return raw   # degraded — leave the typed text exactly as given
    for desc in intent["files"]:
        ui.info(f"📎  you mentioned a file: {_esc(desc)}")
        cmd_find(desc, cfg, attachments)
    if not intent["files"]:
        return raw   # nothing to extract — don't risk rewording a typed task
    task = intent["task"].strip()
    if not task:
        return ""   # only a file/folder op was requested — nothing left to route
    return _confirm_task(task)


def _get_input(cfg, attachments) -> tuple[str, bool]:
    """The speak/type gate. Returns (line, was_spoken).
    SPACE at the prompt records a voice take (SPACE again stops it); any other
    key (t, Enter, …) opens the normal typed prompt. Every take — spoken OR
    typed — goes through the interpreter: the transcript is polished
    (Wispr-Flow style), file/folder references are located & attached however
    they were phrased, and the remaining task is returned for routing.
    Without pyaudio or a real terminal it's typed-only, as before."""
    from core import voice
    if not voice.available():
        return _maybe_extract_files(_prompt("prism › "), cfg, attachments), False
    _drain_pending_lines()   # same stale-buffer risk as _prompt() — clear it first
    ch = voice.choose("prism ›  [space] speak · [t] type ")
    if ch != " ":
        # 't' / Enter open a fresh typed prompt. Any OTHER key is treated as
        # the FIRST CHARACTER of typed input — swallowing it would corrupt
        # fast typing and pastes ('/dry …' silently becoming 'dry …').
        if ch in ("t", "T", "\n", "\r"):
            return _maybe_extract_files(_prompt("prism › "), cfg, attachments), False
        try:
            sys.stdout.write(f"prism › {ch}")
            sys.stdout.flush()
            rest = input()
        except EOFError:
            return "", False
        extra = _drain_pending_lines()
        full = ch + rest
        if extra:
            full = f"{full} {extra}"
        return _maybe_extract_files(full, cfg, attachments), False

    ui.info("🎤  recording — press SPACE again when you're done")
    try:
        text, lang = voice.record_and_transcribe(cfg)
    except Exception as e:
        ui.err(f"voice failed ({e}) — type instead")
        return _maybe_extract_files(_prompt("prism › "), cfg, attachments), False
    if not text:
        ui.warn("didn't catch anything — try again, or type")
        return "", False
    lang_note = f"  [dim]({_esc(lang)})[/dim]" if lang and lang != "english" else ""
    ui.info(f'🎤  heard: "{_esc(text)}"{lang_note}')

    intent = voice.interpret(text, cfg)
    if not intent.get("ok", True):
        ui.warn("interpreter unavailable — routing your words as-is; any file "
                "you mentioned was NOT auto-attached (use /find to attach it)")
    if intent["cleaned"] and intent["cleaned"] != text:
        ui.ok(f'✨  understood: "{_esc(intent["cleaned"])}"')
    for desc in intent["files"]:
        ui.info(f"📎  you mentioned a file: {_esc(desc)}")
        cmd_find(desc, cfg, attachments)
    task = intent["task"].strip()
    if not task:
        return "", False   # only file ops this take — back to the prompt
    task = _confirm_task(task)
    if not task:
        return "", False
    return task, True


# ── entry ─────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    cfg = C.load()

    if "--config" in args or "-c" in args:
        cfg = onboarding.run(cfg)
        fr = cfg.pop("_firstrun", "skip")
        C.save(cfg)
        _handle_firstrun(cfg, fr)
        return

    # First-time users always go through onboarding.
    if not C.is_configured(cfg):
        cfg = onboarding.run(cfg)
        fr = cfg.pop("_firstrun", "skip")
        C.save(cfg)
        _handle_firstrun(cfg, fr)
        # then drop into the REPL
        cfg = C.load()

    dry = "--dry" in args or "-d" in args

    # Collect --file <path> (repeatable) and strip them from the task words.
    from core import files as F
    attachments = []
    task_words = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--file", "-f") and i + 1 < len(args):
            try:
                attachments.append(F.attach(args[i + 1]))
            except Exception as e:
                ui.err(f"Could not attach {args[i + 1]}: {e}")
            i += 2
            continue
        if not a.startswith("-"):
            task_words.append(a)
        i += 1
    task = " ".join(task_words).strip()

    if task:
        run_query(cfg, task, dry=dry, attachments=attachments)
        return

    ui.banner()
    repl(cfg)


if __name__ == "__main__":
    main()
