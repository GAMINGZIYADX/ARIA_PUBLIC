"""
ARIA World Intelligence — Real-time world news feed via RSS.

Polls configurable RSS feeds in a background thread, detects breaking events,
and stores summaries for on-demand queries. Fail-silent: no internet = no-op.
"""

import os
import json
import re
import threading
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_POLL_INTERVAL = 900  # 15 minutes

BREAKING_KEYWORDS = frozenset([
    "breaking", "urgent", "alert", "emergency", "explosion", "attack",
    "earthquake", "tsunami", "hurricane", "crash", "assassination",
    "invasion", "coup", "nuclear", "outbreak", "disaster", "crisis",
    "mass shooting", "terror", "war declared", "collapse",
])

TOPIC_FEEDS: dict[str, list[tuple[str, str]]] = {
    "f1_motorsports": [
        ("Autosport F1",  "https://www.autosport.com/rss/f1/news/"),
        ("RaceFans",      "https://www.racefans.net/feed/"),
    ],
    "morocco": [
        ("Morocco World News", "https://www.moroccoworldnews.com/feed/"),
    ],
    "ai_technology": [
        ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
        ("The Verge",     "https://www.theverge.com/rss/index.xml"),
        ("Ars Technica",  "http://feeds.arstechnica.com/arstechnica/technology-lab"),
    ],
    "gaming": [
        ("IGN",           "https://feeds.ign.com/ign/games-all"),
        ("Eurogamer",     "https://www.eurogamer.net/?format=rss"),
    ],
    "geopolitics": [
        ("BBC Middle East", "http://feeds.bbci.co.uk/news/world/middle_east/rss.xml"),
        ("BBC Europe",      "http://feeds.bbci.co.uk/news/world/europe/rss.xml"),
        ("Al Jazeera",      "https://www.aljazeera.com/xml/rss/all.xml"),
    ],
    "world": [
        ("BBC World",    "http://feeds.bbci.co.uk/news/world/rss.xml"),
        ("The Guardian", "https://www.theguardian.com/world/rss"),
    ],
}

TOPIC_LABELS: dict[str, str] = {
    "f1_motorsports": "Formula 1 & Motorsports",
    "morocco":        "Morocco & North Africa",
    "ai_technology":  "AI & Technology",
    "gaming":         "Gaming",
    "geopolitics":    "Geopolitics",
    "world":          "World News",
}

# Map query keywords → topic key
_QUERY_MAP: dict[str, str] = {
    "f1":         "f1_motorsports",
    "formula":    "f1_motorsports",
    "motorsport": "f1_motorsports",
    "racing":     "f1_motorsports",
    "grand prix": "f1_motorsports",
    "morocco":    "morocco",
    "maroc":      "morocco",
    "africa":     "morocco",
    "ai":         "ai_technology",
    "artificial": "ai_technology",
    "tech":       "ai_technology",
    "technology": "ai_technology",
    "gaming":     "gaming",
    "game":       "gaming",
    "playstation":"gaming",
    "xbox":       "gaming",
    "nintendo":   "gaming",
    "geopolit":   "geopolitics",
    "middle east":"geopolitics",
    "europe":     "geopolitics",
}

_ATOM_NS = "http://www.w3.org/2005/Atom"


# ─────────────────────────────────────────────────────────────────────────────
# CLASS
# ─────────────────────────────────────────────────────────────────────────────

class WorldIntelligence:
    """Background RSS aggregator. Thread-safe singleton design."""

    BREAKING_DAILY_CAP = 2     # max breaking-news alerts per day
    ALERT_COOLDOWN     = 1800  # seconds between any two alerts

    def __init__(self, client, model: str, memory_ref: dict, data_dir: str):
        self._client   = client
        self._model    = model
        self._memory   = memory_ref
        self._lock     = threading.Lock()

        self._settings_file = os.path.join(data_dir, "world_intel_settings.json")
        self._events_file   = os.path.join(data_dir, "world_intel.json")

        self._settings: dict = self._load_settings()
        self._events:   list = self._load_events()

        self._pending_alerts: list[dict] = []
        self._last_alert_ts:  float = 0.0
        self._today:          str   = datetime.now().strftime("%Y-%m-%d")
        self._today_alerts:   int   = self._count_today_alerts()
        self._last_poll_ts:   float = 0.0
        self._running:        bool  = False

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start background polling (idempotent)."""
        if self._running:
            return
        self._running = True
        threading.Thread(
            target=self._poll_loop, daemon=True, name="world-intel-poller"
        ).start()

    def get_summary(self, query: str = "") -> str:
        """Return LLM-generated summary. Called by the query_world_intel tool."""
        with self._lock:
            events = list(self._events)

        if not events:
            return (
                "World Intelligence has no events cached yet. "
                "The feed polls every 15 minutes — check back shortly, "
                "or make sure ARIA has internet access."
            )

        topic = self._detect_topic(query)
        if topic:
            relevant = [e for e in events if topic in e.get("topics", [])]
            label = TOPIC_LABELS.get(topic, topic)
        else:
            relevant = events
            label = "world"

        if not relevant:
            relevant = events

        recent = sorted(relevant, key=lambda e: e.get("ts", ""), reverse=True)[:10]
        headlines = "\n".join(
            f"- [{e['source']}] {e['title']}" for e in recent
        )

        prompt = (
            f"You are ARIA. Summarize these recent {label} headlines for the user "
            f"in 3-5 concise sentences. Focus on what's most significant. "
            f"No emojis. Be direct.\n\nHeadlines:\n{headlines}"
        )
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.3,
            )
            result = resp.choices[0].message.content.strip()
            result = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL).strip()
            return result or f"Latest {label} headlines:\n{headlines}"
        except Exception:
            ts = datetime.now().strftime("%H:%M")
            return f"Latest {label} headlines (as of {ts}):\n{headlines}"

    def get_pending_alert(self) -> Optional[dict]:
        """Return a queued breaking-news alert if one should fire now."""
        if not self._settings.get("enabled", True):
            return None
        h = datetime.now().hour
        if not (9 <= h < 24):
            return None
        with self._lock:
            self._rotate_day()
            if self._today_alerts >= self.BREAKING_DAILY_CAP:
                return None
            now = time.monotonic()
            if now - self._last_alert_ts < self.ALERT_COOLDOWN:
                return None
            if not self._pending_alerts:
                return None
            alert = self._pending_alerts.pop(0)
            self._last_alert_ts = now
            self._today_alerts += 1
            self._log_alert(alert)

        return {
            "id":      f"world_intel_{alert.get('id', '')}",
            "trigger": "world_intel",
            "message": f"Heads up — {alert['summary']}",
            "action":  None,
            "source":  "world_intel",
        }

    def get_status(self) -> dict:
        """Status dict for /api/world-intel endpoint."""
        with self._lock:
            events       = list(self._events)
            last_poll_ts = self._last_poll_ts
            pending      = len(self._pending_alerts)

        recent = sorted(events, key=lambda e: e.get("ts", ""), reverse=True)[:6]
        last_updated = (
            datetime.fromtimestamp(time.time() - (time.monotonic() - last_poll_ts))
            .strftime("%H:%M") if last_poll_ts else "never"
        )
        return {
            "enabled":        self._settings.get("enabled", True),
            "topics":         self._settings.get("topics", list(TOPIC_LABELS.keys())),
            "topic_labels":   TOPIC_LABELS,
            "sensitivity":    self._settings.get("sensitivity", "breaking_only"),
            "poll_interval":  self._settings.get("poll_interval", DEFAULT_POLL_INTERVAL),
            "last_updated":   last_updated,
            "event_count":    len(events),
            "pending_alerts": pending,
            "headlines": [
                {"title": e["title"], "source": e["source"],
                 "ts": e.get("ts", ""), "breaking": e.get("breaking", False)}
                for e in recent
            ],
        }

    def get_settings(self) -> dict:
        return dict(self._settings)

    def update_settings(self, data: dict) -> None:
        with self._lock:
            if "enabled" in data:
                self._settings["enabled"] = bool(data["enabled"])
            if "topics" in data and isinstance(data["topics"], list):
                self._settings["topics"] = [t for t in data["topics"] if t in TOPIC_LABELS]
            if "sensitivity" in data and data["sensitivity"] in ("breaking_only", "all"):
                self._settings["sensitivity"] = data["sensitivity"]
            self._save_settings()

    # ── Internal: poll loop ───────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        time.sleep(10)  # let ARIA finish starting
        while True:
            if self._settings.get("enabled", True):
                try:
                    self._do_poll()
                except Exception:
                    pass
            time.sleep(self._settings.get("poll_interval", DEFAULT_POLL_INTERVAL))

    def _do_poll(self) -> None:
        active_topics = self._settings.get("topics", list(TOPIC_LABELS.keys()))
        sensitivity   = self._settings.get("sensitivity", "breaking_only")
        new_events: list[dict] = []

        for topic in active_topics:
            for source_name, url in TOPIC_FEEDS.get(topic, []):
                try:
                    new_events.extend(self._fetch_rss(url, source_name, topic))
                except Exception:
                    pass  # per-feed fail-silent

        with self._lock:
            existing = {e["title"] for e in self._events}
            fresh    = [e for e in new_events if e["title"] not in existing]

            for event in fresh:
                text       = event["title"] + " " + event.get("summary", "")
                is_breaking = self._is_breaking(text)
                event["breaking"] = is_breaking

                if is_breaking and len(self._pending_alerts) < 5:
                    self._pending_alerts.append({
                        "id":      event.get("id", ""),
                        "title":   event["title"],
                        "source":  event["source"],
                        "summary": f"{event['title']} ({event['source']})",
                    })

            self._events = (fresh + self._events)[:200]
            self._last_poll_ts = time.monotonic()

        if fresh:
            sample = fresh[0]["title"][:80]
            self._memory.setdefault("facts", {})[
                "world_intel_last_update"
            ] = {
                "value": f"{len(fresh)} new items — latest: {sample}",
                "ts":    datetime.now().strftime("%Y-%m-%d %H:%M"),
            }

        threading.Thread(target=self._save_events, daemon=True).start()

    # ── RSS / Atom parsing ────────────────────────────────────────────────────

    def _fetch_rss(self, url: str, source: str, topic: str) -> list[dict]:
        req = urllib.request.Request(
            url, headers={"User-Agent": "ARIA-WorldIntel/1.0 (RSS reader)"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_bytes = resp.read(1_000_000)  # cap at 1 MB

        root = ET.fromstring(xml_bytes)
        tag  = root.tag.lower()
        return (
            self._parse_atom(root, source, topic)
            if "feed" in tag
            else self._parse_rss(root, source, topic)
        )

    def _parse_rss(self, root: ET.Element, source: str, topic: str) -> list[dict]:
        channel = root.find("channel") or root
        items   = []
        for item in channel.findall("item")[:15]:
            title = (item.findtext("title") or "").strip()
            if not title:
                continue
            desc = re.sub(r"<[^>]+>", "", item.findtext("description") or "")[:200]
            items.append(self._make_event(
                title=title,
                summary=desc.strip(),
                url=(item.findtext("link") or "").strip(),
                pub=(item.findtext("pubDate") or ""),
                source=source,
                topic=topic,
            ))
        return items

    def _parse_atom(self, root: ET.Element, source: str, topic: str) -> list[dict]:
        def _ns(tag: str) -> str:
            return f"{{{_ATOM_NS}}}{tag}"

        entries = root.findall(_ns("entry")) or root.findall("entry")
        items   = []
        for entry in entries[:15]:
            def _t(tag: str) -> str:
                return (
                    (entry.findtext(_ns(tag)) or entry.findtext(tag) or "").strip()
                )
            title = _t("title")
            if not title:
                continue
            raw_summary = _t("summary") or _t("content")
            summary = re.sub(r"<[^>]+>", "", raw_summary)[:200]
            link_el = entry.find(_ns("link")) or entry.find("link")
            link    = (link_el.get("href", "") if link_el is not None else "")
            pub     = _t("updated") or _t("published")
            items.append(self._make_event(
                title=title, summary=summary.strip(),
                url=link, pub=pub, source=source, topic=topic,
            ))
        return items

    @staticmethod
    def _make_event(title: str, summary: str, url: str, pub: str,
                    source: str, topic: str) -> dict:
        return {
            "id":       f"{source}_{hash(title) & 0xFFFFFF:06x}",
            "title":    title,
            "summary":  summary,
            "url":      url,
            "source":   source,
            "topics":   [topic],
            "ts":       pub or datetime.now().isoformat(),
            "breaking": False,
        }

    @staticmethod
    def _is_breaking(text: str) -> bool:
        lower = text.lower()
        return any(kw in lower for kw in BREAKING_KEYWORDS)

    @staticmethod
    def _detect_topic(query: str) -> Optional[str]:
        q = query.lower()
        for kw, topic in _QUERY_MAP.items():
            if kw in q:
                return topic
        return None

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_settings(self) -> dict:
        try:
            with open(self._settings_file) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {
                "enabled":      True,
                "topics":       list(TOPIC_LABELS.keys()),
                "sensitivity":  "breaking_only",
                "poll_interval": DEFAULT_POLL_INTERVAL,
            }

    def _save_settings(self) -> None:
        try:
            tmp = self._settings_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._settings, f, indent=2)
            os.replace(tmp, self._settings_file)
        except Exception:
            pass

    def _load_events(self) -> list:
        try:
            with open(self._events_file) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return []

    def _save_events(self) -> None:
        try:
            with self._lock:
                data = list(self._events[:200])
            tmp = self._events_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self._events_file)
        except Exception:
            pass

    def _count_today_alerts(self) -> int:
        return (
            self._memory.get("world_intel_alerts", {})
            .get(self._today, {})
            .get("count", 0)
        )

    def _log_alert(self, alert: dict) -> None:
        day = (
            self._memory
            .setdefault("world_intel_alerts", {})
            .setdefault(self._today, {"count": 0, "titles": []})
        )
        day["count"] += 1
        day["titles"].append(alert.get("title", "")[:80])

    def _rotate_day(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._today:
            self._today        = today
            self._today_alerts = 0
