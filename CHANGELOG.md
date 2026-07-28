# Changelog

Notable changes to ARIA are documented in this file.

## 2026-07-28 — v1.1: Apache 2.0, security policy, slimmer install

**Licensing**
- **Relicensed under Apache 2.0** — ARIA shipped under MIT while the contributing guide and code of conduct described it as "source-available" and barred commercial use. MIT grants exactly the rights those documents tried to withhold, so they contradicted the license sitting next to them. Apache 2.0 keeps ARIA properly open source, adds an explicit patent grant, and requires anyone redistributing a modified version to state what they changed.
- **`NOTICE` file added** — Apache 2.0 obliges redistributors to carry it forward, which gives the attribution requirement an actual mechanism instead of a request with nothing behind it.
- **Contributor terms simplified** — the bespoke contributor license agreement is gone. Apache 2.0 already licenses inbound contributions and covers the patent grant, so there is nothing extra to sign.

**Security**
- **Private vulnerability reporting** — ARIA executes tools and shell commands with your privileges, so an injection bug is effectively remote code execution. A new `SECURITY.md` sets out what is in scope and how to report privately, and GitHub private security advisories are now enabled. Please do not file security bugs as public issues.
- **Code of conduct rewritten** — it was largely an intellectual-property notice with no conduct standards. It now covers harassment and discrimination, has a proportionate enforcement ladder, and keeps reports confidential.

**Requirements**
- **Python 3.11 is now the minimum** — the docs and both Windows installers advertised 3.10, but nothing had ever been run below 3.12, and `numpy` requires 3.11+ — so a 3.10 install quietly resolved to an older, untested numpy. The installer version checks were raised to match. Python 3.10 reaches end of life in October 2026 in any case.

**Dependencies**
- **PyQt6 removed** — every install pulled in PyQt6 and PyQt6-WebEngine, a large download that was never actually used. On Windows the desktop wrapper uses WebView2, on Linux it uses GTK/WebKit, and both installers launch `app.py` rather than the desktop launcher at all. Fresh installs are now noticeably smaller.
- **Desktop window is now opt-in** — `launch.py` needs `pip install -r requirements-desktop.txt` first, which documents the per-platform rendering backend. If pywebview is missing, `launch.py` now keeps serving the UI in your browser instead of failing outright.

**Windows installer**
- **Rebuilt as v1.1** — the previously published installer predated everything above: it still required Python 3.10 and installed PyQt6. It has been rebuilt from current source and replaced on the releases page.
- **No longer bundles the build machine's `data` folder** — earlier builds packaged `data\` into the installer. That directory holds runtime state — conversation history, memories, persona, the memory-palace store — rather than blank defaults, so a fresh install started life with content from whichever machine built it. ARIA creates `data\` itself on first run, so nothing needs to be shipped. If you installed the earlier build and have not built up your own history yet, delete the `data` folder inside your ARIA directory and restart to begin clean.
- **License files now included** — `LICENSE` and `NOTICE` ship with the installer, which Apache 2.0 requires of any redistribution.
- **"What's New" now works in installed copies** — `CHANGELOG.md` was never packaged, so this panel was empty for anyone who installed from the `.exe` rather than running from source.
- **Smaller package** — stale `__pycache__` bytecode is no longer bundled.

## 2026-07-12 — Security: close prompt-injection RCE

**Security**
- **Model can no longer run bash** — ARIA used to auto-run ```bash blocks the model emitted, which (via web-search/RSS/clipboard content steering the model) was an indirect-prompt-injection path to arbitrary command execution. That path is removed. Bash now runs only from the **Terminal** panel, on commands you type yourself. The chat **EXEC** toggle is gone with it.
- **`create_file` hardened + sandboxed** — plain filenames now default into a `~/.aria-workspace` directory instead of your home root, and writes to hidden or sensitive paths (`~/.ssh`, `~/.bashrc`, shell profiles, autostart) are blocked even inside `$HOME`, so an injected tool call can't plant a persistence backdoor.

## 2026-06-22 — Flat dark UI redesign

**Interface**
- **New visual theme** — replaced the chat, intro, and login pages with a flat, professional dark theme built on a single indigo accent (no gradients, glow, neon, or particles).
- **Consolidated stylesheet** — merged the former `aria.css` + `style.css` pair into a single `static/css/aria.css`; `style.css` is now a stub kept so existing deploys don't 404.
- **Update log on the welcome page** — the intro page now renders this changelog under a "What's New" section, sourced directly from `CHANGELOG.md`.
- **Favicon fix** — the PNG `<link>` now points at the existing `aria_icon.png` instead of a missing `favicon.png`.

## 2026-06-09 — Concurrency & memory fixes

**Race conditions**
- **Atomic JSON writes fixed** — concurrent background threads saving `memory.json` / `persona.json` shared a single `<file>.tmp` and could truncate each other mid-write, corrupting the file. Saves now use a unique temp file per write and serialize per-file through a lock. The proactive engine's duplicate write path was routed through the same writer.
- **`conversations.json` write lock** — parallel session saves (and `/api/clear`) did unlocked read-modify-writes of the whole file and could silently drop each other's sessions. All writers now hold a shared lock across the full read-modify-write.

**Memory growth**
- **Bounded in-memory caches** — the conversation cache, proactive session state, and memory-context cache all grew without limit on long-running servers. They are now LRU-capped (50 sessions / 100 sessions / 128 entries), with expired context-cache entries pruned on insert.
- **On-disk conversation pruning** — `conversations.json` accumulated one entry per session forever. Per-session last-activity timestamps are now tracked in `conversations_meta.json`; sessions idle for 30+ days are pruned (hard cap of 200 sessions), once at startup and on every save.
