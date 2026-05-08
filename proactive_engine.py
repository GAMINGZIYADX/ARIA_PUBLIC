"""
ARIA Proactive Engine — time-based triggers for ARIA-initiated messages.

Triggers (max 3/day, 10-min cooldown between any two):
  morning    — first launch of the day, personalized greeting
  idle       — 45+ min silence during active hours (9am–midnight)
  late_night — after midnight while still active
  context    — placeholder for future Spotify/app-switch hooks

All triggers are gated by ARIA_SILENT_MODE.
"""

import os
import json
import threading
from datetime import datetime


# ─────────────────────────────────────────────
# MOOD
# ─────────────────────────────────────────────

def get_mood() -> str:
    """Return ARIA's current mood based on time of day."""
    h = datetime.now().hour
    if 5 <= h < 11:   return "warm"      # morning
    if 11 <= h < 18:  return "focused"   # daytime
    if 18 <= h < 23:  return "curious"   # evening
    return "quiet"                        # late night / early morning


_MOOD_HINTS = {
    "warm":    "It's morning. Be gently warm — brief, grounded, present.",
    "focused": "Daytime energy. Stay sharp, efficient, to the point.",
    "curious": "Evening. You're more reflective. Ask things. Muse a little.",
    "quiet":   "Late night. Sparse words. A little softer. Not cheerful.",
}

def get_mood_hint() -> str:
    return _MOOD_HINTS[get_mood()]


# ─────────────────────────────────────────────
# ENGINE
# ─────────────────────────────────────────────

class ProactiveEngine:
    """Manages ARIA-initiated messages. Thread-safe singleton."""

    DAILY_CAP      = 3      # max proactive messages per calendar day
    COOLDOWN_SECS  = 600    # 10 min between any two proactive messages
    IDLE_THRESHOLD = 2700   # 45 min silence → idle trigger
    ACTIVE_START   = 9      # active hours start (9am)
    ACTIVE_END     = 24     # active hours end (midnight = 0h next day)

    def __init__(self, client, model: str, memory_ref: dict, memory_file: str,
                 persona_ref: dict):
        self._client       = client
        self._model        = model
        self._memory       = memory_ref    # live _memory dict from app.py
        self._mem_file     = memory_file
        self._persona      = persona_ref   # live _persona dict from app.py
        self._lock         = threading.Lock()

        self._last_interaction: float = datetime.now().timestamp()
        self._last_proactive:   float = 0.0
        self._today:            str   = datetime.now().strftime("%Y-%m-%d")
        self._today_count:      int   = self._load_today_count()
        self._morning_sent:     bool  = self._was_sent_today("morning")
        self._late_night_sent:  bool  = False   # resets each launch

        # Silent mode: read from env, can be toggled at runtime
        self._silent: bool = os.environ.get("ARIA_SILENT_MODE", "0") == "1"

    # ── Public API ────────────────────────────────────────────────────

    @property
    def silent(self) -> bool:
        return self._silent

    @silent.setter
    def silent(self, value: bool):
        self._silent = value

    def ping(self) -> None:
        """Call on every user interaction to reset idle timer."""
        with self._lock:
            self._last_interaction = datetime.now().timestamp()

    def check(self) -> dict | None:
        """
        Evaluate all triggers. Returns a proactive dict if one fires, else None.
        Safe to call from any thread or HTTP handler.
        """
        if self._silent:
            return None

        with self._lock:
            self._rotate_day()
            if self._today_count >= self.DAILY_CAP:
                return None

            now = datetime.now().timestamp()
            if now - self._last_proactive < self.COOLDOWN_SECS:
                return None

            result = (
                self._check_morning() or
                self._check_idle(now) or
                self._check_late_night()
            )

            if result:
                self._last_proactive = now
                self._today_count   += 1
                self._log_proactive(result["trigger"], result["message"])

            return result

    # ── Trigger checkers ─────────────────────────────────────────────

    def _check_morning(self) -> dict | None:
        h = datetime.now().hour
        if self._morning_sent or not (5 <= h < 11):
            return None
        self._morning_sent = True
        msg = self._generate_opening("morning", idle_minutes=0)
        return {"id": "morning", "trigger": "morning", "message": msg, "action": None}

    def _check_idle(self, now: float) -> dict | None:
        h = datetime.now().hour
        if not (self.ACTIVE_START <= h < self.ACTIVE_END):
            return None
        idle = now - self._last_interaction
        if idle < self.IDLE_THRESHOLD:
            return None
        idle_min = int(idle / 60)
        msg = self._generate_opening("idle", idle_minutes=idle_min)
        return {"id": f"idle_{int(now)}", "trigger": "idle", "message": msg, "action": None}

    def _check_late_night(self) -> dict | None:
        h = datetime.now().hour
        if self._late_night_sent or h >= 4 or h == 0:
            # fire between midnight (0) and 4am, once per session
            if h != 0:
                return None
        if h >= 4 or self._late_night_sent:
            return None
        idle = datetime.now().timestamp() - self._last_interaction
        if idle > 3600:   # don't nag if they've been gone an hour
            return None
        self._late_night_sent = True
        msg = self._generate_opening("late_night", idle_minutes=int(idle / 60))
        return {"id": "late_night", "trigger": "late_night", "message": msg, "action": None}

    # ── LLM opening line generation ───────────────────────────────────

    def _generate_opening(self, trigger: str, idle_minutes: int) -> str:
        """Generate one contextual opening line via a lightweight LLM call."""
        now_str   = datetime.now().strftime("%I:%M %p").lstrip("0")
        mood      = get_mood()
        mood_hint = get_mood_hint()
        name      = self._persona.get("user", {}).get("name", "YOUR_NAME")

        # Build a minimal context snippet from memory
        facts   = self._memory.get("facts", {})
        context_bits = []
        if "last_search" in facts:
            context_bits.append(f"last search: {facts['last_search']['value']}")
        if "current_project" in facts:
            context_bits.append(f"working on: {facts['current_project']['value']}")
        if "current_track" in facts:
            context_bits.append(f"currently playing: {facts['current_track']['value']}")
        elif "last_music" in facts:
            context_bits.append(f"last music: {facts['last_music']['value']}")
        ctx_str = "; ".join(context_bits) if context_bits else "no recent activity logged"

        # Trigger-specific framing
        if trigger == "morning":
            situation = f"It's {now_str}. This is the first time {name} has opened ARIA today."
        elif trigger == "idle":
            situation = f"{name} hasn't spoken to you in {idle_minutes} minutes. It's {now_str}."
        else:  # late_night
            situation = f"It's {now_str} — past midnight. {name} is still here."

        prompt = (
            f"You are ARIA. {situation}\n"
            f"What you know about {name}: {ctx_str}.\n"
            f"Mood: {mood}. {mood_hint}\n\n"
            f"Generate ONE short, natural opening line to start a conversation. "
            f"It can be a question, observation, or something you've been thinking about. "
            f"Under 2 sentences. Not generic. Not sycophantic. "
            f"Refer to {name} by name at most once. No emojis."
        )

        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=80,
                temperature=0.85,
            )
            line = resp.choices[0].message.content.strip()
            # Strip any <think> blocks the model might emit
            import re
            line = re.sub(r"<think>.*?</think>", "", line, flags=re.DOTALL).strip()
            return line if line else self._fallback(trigger, name, now_str)
        except Exception:
            return self._fallback(trigger, name, now_str)

    def _fallback(self, trigger: str, name: str, now_str: str) -> str:
        """Static fallback if LLM call fails."""
        if trigger == "morning":
            return f"Good morning, {name}. It's {now_str}."
        if trigger == "late_night":
            return f"It's past midnight. Still here?"
        return f"{name}, still around?"

    # ── Memory helpers ────────────────────────────────────────────────

    def _load_today_count(self) -> int:
        log = self._memory.get("proactive_log", {})
        return log.get(self._today, {}).get("count", 0)

    def _was_sent_today(self, trigger: str) -> bool:
        log = self._memory.get("proactive_log", {})
        return trigger in log.get(self._today, {}).get("triggers", [])

    def _log_proactive(self, trigger: str, message: str) -> None:
        """Persist the proactive send to memory.json."""
        log  = self._memory.setdefault("proactive_log", {})
        day  = log.setdefault(self._today, {"count": 0, "triggers": [], "messages": []})
        day["count"]    = self._today_count   # already incremented by caller
        day["triggers"].append(trigger)
        day["messages"].append({"trigger": trigger, "message": message,
                                 "ts": datetime.now().strftime("%H:%M")})
        # Prune old days (keep last 7)
        old_days = sorted(log.keys())[:-7]
        for d in old_days:
            del log[d]
        # Async write — best effort
        import json as _json, threading as _t
        def _write():
            try:
                tmp = self._mem_file + ".tmp"
                with open(tmp, "w") as f:
                    _json.dump(self._memory, f, indent=2)
                import os as _os
                _os.replace(tmp, self._mem_file)
            except Exception:
                pass
        _t.Thread(target=_write, daemon=True).start()

    def _rotate_day(self) -> None:
        """Reset daily counters at midnight."""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._today:
            self._today         = today
            self._today_count   = 0
            self._morning_sent  = False
            self._late_night_sent = False
