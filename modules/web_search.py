"""
ARIA Web Search — real-time DuckDuckGo search, no API key required.

Public API:
  search(query, max_results=5)       → list[{title, url, snippet}]
  summarize(query, results, client, model) → str  (natural-language answer)
  search_and_summarize(query, client, model, world_intel=None) → str
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Avoid a hard import cycle — only used for type hints
    from openai import OpenAI

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

MAX_RESULTS    = 5
SEARCH_TIMEOUT = 10   # seconds before giving up on DuckDuckGo
CACHE_TTL      = 1800  # 30 minutes — world-intel cache freshness threshold

# ─────────────────────────────────────────────────────────────────────────────
# Search
# ─────────────────────────────────────────────────────────────────────────────

def search(query: str, max_results: int = MAX_RESULTS) -> list[dict]:
    """
    Run a DuckDuckGo text search.

    Returns a list of dicts:
      [{"title": "...", "url": "...", "snippet": "..."}, ...]

    Fail-silent: returns [] on any error (network failure, rate-limit, etc.).
    Enforces a hard 10-second timeout via a background thread.
    """
    if not query or not query.strip():
        return []

    results: list[dict] = []
    error_holder: list[Exception] = []

    def _do_search():
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                for r in ddgs.text(query.strip(), max_results=max_results):
                    results.append({
                        "title":   r.get("title", "").strip(),
                        "url":     r.get("href",  "").strip(),
                        "snippet": r.get("body",  "").strip(),
                    })
        except Exception as exc:
            error_holder.append(exc)

    import threading
    t = threading.Thread(target=_do_search, daemon=True)
    t.start()
    t.join(timeout=SEARCH_TIMEOUT)

    if t.is_alive():
        # Thread is still running — timed out
        return []
    if error_holder:
        return []

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Summarise
# ─────────────────────────────────────────────────────────────────────────────

_SUMMARIZE_PROMPT = """\
You are ARIA. Answer the question below using the search snippets provided.
The snippets contain real content — read them and write a direct factual answer.

Question: {query}

Search snippets:
{results_block}

Instructions:
- Write 2-3 sentences that directly answer the question using the snippet content.
- Be specific: names, dates, numbers, facts from the snippets.
- Do not describe what the sources are about — state the facts directly.
- After the summary, output exactly:

Sources:
[1] Title — url
[2] Title — url
...

If the snippets genuinely don't answer the question, say so in one sentence, then list sources."""


def summarize(
    query:   str,
    results: list[dict],
    client,          # openai.OpenAI instance
    model:   str,
) -> str:
    """
    Ask the local LLM to summarise search results into a natural-language answer.
    Returns a formatted string with answer + source list (cleanly separated).
    Falls back to a plain source list if the LLM call fails.
    """
    if not results:
        return "I couldn't find anything relevant for that query."

    results_block = "\n\n".join(
        f"[{i+1}] {r['title']}\n{r['snippet']}"
        for i, r in enumerate(results)
        if r.get("snippet")
    ) or "\n".join(f"[{i+1}] {r['title']}" for i, r in enumerate(results))

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": _SUMMARIZE_PROMPT.format(
                    query=query,
                    results_block=results_block,
                )},
            ],
            max_tokens=500,
            temperature=0.2,
        )
        answer = resp.choices[0].message.content.strip()
        import re
        answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL).strip()

        # Ensure sources block is always accurate — rebuild it from actual results
        # in case the LLM hallucinated or reordered them
        answer = _replace_sources_block(answer, results)

        return answer if answer else _plain_sources(results)
    except Exception:
        return _plain_sources(results)


def _replace_sources_block(answer: str, results: list[dict]) -> str:
    """
    Strip any 'Sources:' block the LLM produced and append a clean, accurate one.
    Outputs markdown links so the chat UI renders them as clickable <a> tags.
    This prevents hallucinated URLs from reaching the user.
    """
    import re
    # Remove everything from "Sources:" onward (case-insensitive)
    body = re.split(r"\n\s*[Ss]ources\s*:\s*\n", answer, maxsplit=1)[0].rstrip()

    sources_lines = "\n".join(
        f"• [{r['title']}]({r['url']})"
        for r in results
        if r.get("url", "").startswith(("http://", "https://"))
    )
    return f"{body}\n\n─────────────────\nSources:\n{sources_lines}"


def _plain_sources(results: list[dict]) -> str:
    """Fallback when LLM summarisation fails — just list the sources."""
    lines = ["Here's what I found:\n\n─────────────────\nSources:"]
    for r in results:
        if r.get("url", "").startswith(("http://", "https://")):
            lines.append(f"• [{r['title']}]({r['url']})")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Combined entry point
# ─────────────────────────────────────────────────────────────────────────────

def search_and_summarize(
    query:       str,
    client,
    model:       str,
    world_intel=None,   # WorldIntelligence instance or None
) -> str:
    """
    Full pipeline: check world-intel cache → DuckDuckGo → LLM summary.

    1. If world_intel is provided and has a recent (< 30 min) relevant
       summary, return that immediately — no network round-trip needed.
    2. Otherwise run a live DuckDuckGo search.
    3. Summarise results with the local LLM.
    4. Return formatted answer with sources.
    """
    # ── 1. Check world-intel local cache ──────────────────────────────────
    if world_intel is not None:
        try:
            cached = world_intel.get_summary(query)
            if cached and _cache_is_fresh(world_intel, query):
                return cached
        except Exception:
            pass   # world-intel unavailable — fall through to live search

    # ── 2. Live DuckDuckGo search ──────────────────────────────────────────
    results = search(query)
    if not results:
        return (
            "I searched DuckDuckGo but didn't get any results — "
            "DuckDuckGo may be rate-limiting or unreachable right now."
        )

    # ── 3. LLM summary ────────────────────────────────────────────────────
    return summarize(query, results, client, model)


def _cache_is_fresh(world_intel, query: str) -> bool:
    """
    Return True if the world-intel has been updated within CACHE_TTL seconds.
    Checks the 'last_updated' field if available; conservative default = False.
    """
    try:
        status = world_intel.get_status()
        last_updated = status.get("last_updated")
        if not last_updated:
            return False
        import datetime
        # last_updated is an ISO string or epoch float
        if isinstance(last_updated, (int, float)):
            age = time.time() - last_updated
        else:
            dt = datetime.datetime.fromisoformat(str(last_updated))
            age = (datetime.datetime.now() - dt).total_seconds()
        return age < CACHE_TTL
    except Exception:
        return False
