# Changelog

Notable changes to ARIA are documented in this file.

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
