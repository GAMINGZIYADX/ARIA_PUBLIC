"""
ARIA Diagnostic Engine — 5 parallel agents, structured JSON + plain-text reports.

Agents (run concurrently via daemon threads):
  1. security     — secret/permission scan, pip-audit
  2. performance  — Ollama latency, RAM/VRAM
  3. memory       — validate JSON data files, sizes
  4. dependencies — pip outdated, required packages
  5. system       — CPU/GPU temp, disk, Ollama health, uptime

Results saved to:
  logs/diagnostic_YYYY-MM-DD_HH-MM.json   (full JSON)
  logs/diagnostic_latest.txt              (human-readable)
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

# ─── paths ────────────────────────────────────────────────────────────────────
_ROOT     = Path(__file__).resolve().parent
_LOGS_DIR = _ROOT / "logs"
_DATA_DIR = _ROOT / "data"
_LOGS_DIR.mkdir(exist_ok=True)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str, str]:
    """Run a subprocess. Returns (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError:
        return -1, "", f"not found: {cmd[0]}"
    except Exception as e:
        return -1, "", str(e)


def _ok(msg: str)   -> dict: return {"status": "ok",   "detail": msg}
def _warn(msg: str) -> dict: return {"status": "warn", "detail": msg}
def _fail(msg: str) -> dict: return {"status": "fail", "detail": msg}


# ─── Agent 1 — Security ───────────────────────────────────────────────────────

_SECRET_PATTERNS = [
    (re.compile(r'(?i)(api[_-]?key|secret|password|token|passwd)\s*=\s*["\']?[A-Za-z0-9/+_\-]{12,}'),
     "hardcoded credential pattern"),
    (re.compile(r'ghp_[A-Za-z0-9]{36}'), "GitHub PAT"),
    (re.compile(r'sk-[A-Za-z0-9]{32,}'),  "OpenAI-style API key"),
    (re.compile(r'AIza[0-9A-Za-z\-_]{35}'), "Google API key"),
]


def _agent_security() -> dict[str, Any]:
    findings: list[str] = []
    checks:   list[dict] = []

    # 1a. Secret scan (py + sh + env files only, skip .venv / __pycache__)
    scan_files: list[Path] = []
    for ext in ("*.py", "*.sh", "*.env", ".env"):
        for p in _ROOT.rglob(ext):
            if ".venv" in p.parts or "__pycache__" in p.parts:
                continue
            scan_files.append(p)

    hits: list[str] = []
    for path in scan_files:
        try:
            text = path.read_text(errors="ignore")
        except Exception:
            continue
        for pattern, label in _SECRET_PATTERNS:
            for m in pattern.finditer(text):
                # Show context but redact the match value
                snippet = m.group(0)[:40]
                hits.append(f"{path.name}:{m.start()} — {label}: {snippet[:20]}…")

    if hits:
        checks.append(_warn(f"{len(hits)} potential secret(s) found"))
        findings.extend(hits[:10])   # cap at 10
    else:
        checks.append(_ok("No obvious secrets found in source files"))

    # 1b. .env file existence + permissions
    env_path = _ROOT / ".env"
    if env_path.exists():
        mode = oct(env_path.stat().st_mode)[-3:]
        if mode in ("600", "400"):
            checks.append(_ok(f".env exists, permissions {mode}"))
        else:
            checks.append(_warn(f".env permissions {mode} — should be 600"))
    else:
        checks.append(_ok(".env not present (credentials may be in environment)"))

    # 1c. pip-audit
    rc, out, err = _run(
        [sys.executable, "-m", "pip_audit", "--format=json", "-q"],
        timeout=30,
    )
    if rc == -1:
        # try plain pip-audit binary
        rc, out, err = _run(["pip-audit", "--format=json", "-q"], timeout=30)

    if rc == 0:
        try:
            data = json.loads(out) if out else {}
            vulns = data.get("vulnerabilities", [])
            if not vulns:
                checks.append(_ok("pip-audit: no known vulnerabilities"))
            else:
                checks.append(_warn(f"pip-audit: {len(vulns)} vulnerability(ies) found"))
                for v in vulns[:5]:
                    findings.append(f"{v.get('name')} {v.get('version')}: {v.get('vulns', [{}])[0].get('id', '?')}")
        except Exception:
            checks.append(_ok("pip-audit ran (could not parse output)"))
    else:
        checks.append(_warn("pip-audit not available — install with: pip install pip-audit"))

    return {"checks": checks, "findings": findings}


# ─── Agent 2 — Performance ────────────────────────────────────────────────────

def _agent_performance(ollama_url: str = "http://localhost:11434") -> dict[str, Any]:
    checks: list[dict] = []

    # 2a. Ollama round-trip latency
    try:
        start = time.perf_counter()
        req = urllib.request.Request(
            ollama_url + "/api/tags",
            headers={"User-Agent": "aria-diag/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
        ms = int((time.perf_counter() - start) * 1000)
        label = "ok" if ms < 300 else "warn"
        checks.append({"status": label, "detail": f"Ollama latency {ms} ms"})
    except Exception as e:
        checks.append(_fail(f"Ollama unreachable: {e}"))

    # 2b. RAM via /proc/meminfo
    try:
        info: dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(":")] = int(parts[1])
        total_mb = info.get("MemTotal", 0) // 1024
        avail_mb = info.get("MemAvailable", 0) // 1024
        used_pct = 100 - int(avail_mb / total_mb * 100) if total_mb else 0
        label = "ok" if used_pct < 80 else "warn"
        checks.append({"status": label,
                        "detail": f"RAM {used_pct}% used ({avail_mb} MB free / {total_mb} MB total)"})
    except Exception as e:
        checks.append(_warn(f"RAM check failed: {e}"))

    # 2c. VRAM via nvidia-smi
    rc, out, _ = _run(
        ["nvidia-smi", "--query-gpu=memory.used,memory.total",
         "--format=csv,noheader,nounits"],
        timeout=5,
    )
    if rc == 0 and out:
        parts = [p.strip() for p in out.split(",")]
        if len(parts) == 2:
            try:
                used_mb, total_mb = int(parts[0]), int(parts[1])
                pct = int(used_mb / total_mb * 100)
                label = "ok" if pct < 85 else "warn"
                checks.append({"status": label,
                                "detail": f"VRAM {pct}% used ({used_mb} MB / {total_mb} MB)"})
            except ValueError:
                checks.append(_warn(f"VRAM parse error: {out}"))
    else:
        checks.append({"status": "info", "detail": "nvidia-smi not available (no GPU or no driver)"})

    return {"checks": checks}


# ─── Agent 3 — Memory Integrity ───────────────────────────────────────────────

_JSON_FILES = [
    "memory.json", "persona.json", "self_model.json",
    "opinions.json", "macros.json", "audit.log",
]


def _agent_memory() -> dict[str, Any]:
    checks: list[dict] = []

    for fname in _JSON_FILES:
        path = _DATA_DIR / fname
        if not path.exists():
            checks.append(_warn(f"{fname} — not found"))
            continue

        stat = path.stat()
        size_kb = stat.st_size // 1024
        age_h   = int((time.time() - stat.st_mtime) / 3600)

        if fname.endswith(".json"):
            try:
                with open(path) as f:
                    json.load(f)
                checks.append(_ok(f"{fname} — valid JSON, {size_kb} KB, last modified {age_h}h ago"))
            except json.JSONDecodeError as e:
                checks.append(_fail(f"{fname} — INVALID JSON: {e}"))
        else:
            # audit.log — just check readability
            checks.append(_ok(f"{fname} — {size_kb} KB, last modified {age_h}h ago"))

    # ChromaDB directory
    chroma_path = _DATA_DIR / "chroma_db"
    if chroma_path.exists():
        n_files = sum(1 for _ in chroma_path.rglob("*") if _.is_file())
        checks.append(_ok(f"chroma_db — {n_files} file(s)"))
    else:
        checks.append(_warn("chroma_db — directory not found (MemPalace disabled?)"))

    return {"checks": checks}


# ─── Agent 4 — Dependencies ───────────────────────────────────────────────────

_REQUIRED_PKGS = [
    "flask", "flask_cors", "flask_limiter", "openai",
    "faster_whisper", "soundfile", "chromadb",
]


def _agent_dependencies() -> dict[str, Any]:
    checks:  list[dict] = []
    missing: list[str]  = []

    # 4a. Required package presence
    import importlib.util
    for pkg in _REQUIRED_PKGS:
        if importlib.util.find_spec(pkg.replace("-", "_")) is not None:
            checks.append(_ok(f"{pkg} installed"))
        else:
            checks.append(_fail(f"{pkg} missing"))
            missing.append(pkg)

    # 4b. pip list --outdated (best-effort, slow)
    rc, out, _ = _run(
        [sys.executable, "-m", "pip", "list", "--outdated", "--format=json"],
        timeout=30,
    )
    if rc == 0 and out:
        try:
            outdated = json.loads(out)
            if outdated:
                names = [f"{p['name']} {p['version']}→{p['latest_version']}"
                         for p in outdated[:8]]
                checks.append(_warn(f"{len(outdated)} outdated package(s): {', '.join(names)}"))
            else:
                checks.append(_ok("All packages up to date"))
        except Exception:
            checks.append(_ok("pip outdated check ran (parse error)"))
    else:
        checks.append({"status": "info", "detail": "pip outdated check skipped"})

    return {"checks": checks, "missing": missing}


# ─── Agent 5 — System Health ──────────────────────────────────────────────────

def _agent_system(ollama_url: str = "http://localhost:11434") -> dict[str, Any]:
    checks: list[dict] = []

    # 5a. CPU temp via sensors
    rc, out, _ = _run(["sensors", "-j"], timeout=5)
    if rc == 0 and out:
        try:
            data = json.loads(out)
            temps: list[float] = []
            for chip in data.values():
                for sub in chip.values():
                    if isinstance(sub, dict):
                        for k, v in sub.items():
                            if "input" in k and isinstance(v, (int, float)):
                                temps.append(float(v))
            if temps:
                max_c = max(temps)
                label = "ok" if max_c < 80 else "warn"
                checks.append({"status": label, "detail": f"CPU max temp {max_c:.0f}°C"})
        except Exception:
            checks.append({"status": "info", "detail": "CPU temp parse error"})
    else:
        checks.append({"status": "info", "detail": "lm-sensors not available"})

    # 5b. GPU temp
    rc, out, _ = _run(
        ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
        timeout=5,
    )
    if rc == 0 and out:
        try:
            temp = float(out.split()[0])
            label = "ok" if temp < 85 else "warn"
            checks.append({"status": label, "detail": f"GPU temp {temp:.0f}°C"})
        except ValueError:
            pass
    # (skip if no GPU — already noted in performance agent)

    # 5c. Disk space (project partition)
    try:
        usage = shutil.disk_usage(_ROOT)
        free_gb  = usage.free  // (1024 ** 3)
        total_gb = usage.total // (1024 ** 3)
        pct      = int((usage.used / usage.total) * 100)
        label = "ok" if pct < 85 else "warn"
        checks.append({"status": label,
                        "detail": f"Disk {pct}% used ({free_gb} GB free / {total_gb} GB total)"})
    except Exception as e:
        checks.append(_warn(f"Disk check failed: {e}"))

    # 5d. Ollama model health (POST generate with empty stream)
    try:
        payload = json.dumps({"model": "qwen2.5:14b", "prompt": "hi",
                               "stream": False, "options": {"num_predict": 1}}).encode()
        req = urllib.request.Request(
            ollama_url + "/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        start = time.perf_counter()
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        ms = int((time.perf_counter() - start) * 1000)
        checks.append(_ok(f"Ollama generate healthy ({ms} ms first-token)"))
    except Exception as e:
        checks.append(_warn(f"Ollama generate check failed: {e}"))

    # 5e. Uptime of this Python process
    try:
        with open("/proc/self/stat") as f:
            fields = f.read().split()
        # field 22 = process start time in clock ticks since boot
        clk = os.sysconf("SC_CLK_TCK")
        with open("/proc/uptime") as f:
            boot_sec = float(f.read().split()[0])
        start_sec = int(fields[21]) / clk
        uptime_sec = boot_sec - start_sec
        if uptime_sec < 0:
            uptime_sec = 0
        h, rem = divmod(int(uptime_sec), 3600)
        m = rem // 60
        checks.append(_ok(f"ARIA process uptime {h}h {m}m"))
    except Exception:
        checks.append({"status": "info", "detail": "Process uptime unavailable"})

    return {"checks": checks}


# ─── DiagnosticEngine ─────────────────────────────────────────────────────────

class DiagnosticEngine:
    """Run all 5 diagnostic agents in parallel and produce a structured report."""

    MAX_REPORTS = 10   # keep last N reports in logs/

    def __init__(self, ollama_url: str = "http://localhost:11434"):
        self._ollama_url = ollama_url

    # ── Public API ─────────────────────────────────────────────────────────

    def run(self) -> dict[str, Any]:
        """
        Execute all 5 agents concurrently, compile results, persist logs.
        Returns the full report dict.
        """
        results: dict[str, Any] = {}
        errors:  dict[str, str] = {}
        lock = threading.Lock()

        def _run_agent(name: str, fn) -> None:
            try:
                out = fn()
            except Exception as e:
                out = None
                with lock:
                    errors[name] = str(e)
            if out is not None:
                with lock:
                    results[name] = out

        agents = [
            ("security",     lambda: _agent_security()),
            ("performance",  lambda: _agent_performance(self._ollama_url)),
            ("memory",       lambda: _agent_memory()),
            ("dependencies", lambda: _agent_dependencies()),
            ("system",       lambda: _agent_system(self._ollama_url)),
        ]

        threads = []
        for name, fn in agents:
            t = threading.Thread(target=_run_agent, args=(name, fn), daemon=True)
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=60)

        report = self._compile(results, errors)
        self._save(report)
        return report

    def load_latest(self) -> dict[str, Any] | None:
        """Return the most recent saved report, or None if no reports exist."""
        reports = self._list_reports()
        if not reports:
            return None
        with open(reports[-1]) as f:
            return json.load(f)

    def summary_text(self, report: dict[str, Any]) -> str:
        """Return a ≤5-sentence spoken summary of the report."""
        counts = report.get("summary", {})
        ok   = counts.get("ok",   0)
        warn = counts.get("warn", 0)
        fail = counts.get("fail", 0)
        total = ok + warn + fail

        sentences: list[str] = []
        sentences.append(
            f"Diagnostic complete. {total} checks run — {ok} passed, "
            f"{warn} warning{'s' if warn != 1 else ''}, {fail} failure{'s' if fail != 1 else ''}."
        )

        # Surface the most critical findings
        critical: list[str] = []
        for agent_name, agent_data in report.get("agents", {}).items():
            for chk in agent_data.get("checks", []):
                if chk.get("status") == "fail":
                    critical.append(f"{agent_name}: {chk['detail']}")
        if critical:
            sentences.append("Failures: " + "; ".join(critical[:3]) + ".")

        warnings: list[str] = []
        for agent_name, agent_data in report.get("agents", {}).items():
            for chk in agent_data.get("checks", []):
                if chk.get("status") == "warn":
                    warnings.append(chk["detail"])
        if warnings:
            sentences.append("Warnings include: " + "; ".join(warnings[:3]) + ".")

        diff = report.get("diff", {})
        new_issues = diff.get("new_issues", [])
        if new_issues:
            sentences.append(f"New since last scan: {'; '.join(new_issues[:2])}.")

        if fail == 0 and warn == 0:
            sentences.append("Everything looks healthy.")

        return " ".join(sentences[:5])

    # ── Internals ──────────────────────────────────────────────────────────

    def _compile(self, results: dict, errors: dict) -> dict[str, Any]:
        """Merge agent results into a single structured report."""
        summary = {"ok": 0, "warn": 0, "fail": 0, "info": 0}
        for agent_data in results.values():
            for chk in agent_data.get("checks", []):
                s = chk.get("status", "info")
                summary[s] = summary.get(s, 0) + 1

        report: dict[str, Any] = {
            "ts":      datetime.now().isoformat(timespec="seconds"),
            "summary": summary,
            "agents":  results,
            "errors":  errors,
        }

        # Diff against last report
        prev = self.load_latest()
        report["diff"] = self._diff(prev, report) if prev else {"new_issues": [], "resolved": []}

        return report

    @staticmethod
    def _diff(prev: dict, curr: dict) -> dict[str, list[str]]:
        """Compare check statuses across reports, highlight changes."""
        def _extract_fail_warn(r: dict) -> set[str]:
            out: set[str] = set()
            for ag, data in r.get("agents", {}).items():
                for chk in data.get("checks", []):
                    if chk.get("status") in ("fail", "warn"):
                        out.add(f"{ag}: {chk['detail']}")
            return out

        prev_issues = _extract_fail_warn(prev)
        curr_issues = _extract_fail_warn(curr)
        return {
            "new_issues": sorted(curr_issues - prev_issues),
            "resolved":   sorted(prev_issues - curr_issues),
        }

    def _save(self, report: dict) -> None:
        """Persist JSON + plain-text reports; prune old files."""
        ts_str  = datetime.now().strftime("%Y-%m-%d_%H-%M")
        json_path = _LOGS_DIR / f"diagnostic_{ts_str}.json"
        txt_path  = _LOGS_DIR / "diagnostic_latest.txt"

        # Write JSON
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2)

        # Write plain-text
        with open(txt_path, "w") as f:
            f.write(self._format_text(report))

        # Prune old reports
        reports = self._list_reports()
        for old in reports[: max(0, len(reports) - self.MAX_REPORTS)]:
            try:
                os.remove(old)
            except Exception:
                pass

    @staticmethod
    def _list_reports() -> list[str]:
        """Sorted list of JSON report paths (oldest first)."""
        return sorted(glob.glob(str(_LOGS_DIR / "diagnostic_*.json")))

    @staticmethod
    def _format_text(report: dict) -> str:
        """Render the report as a human-readable string."""
        lines: list[str] = []
        ts      = report.get("ts", "unknown")
        summary = report.get("summary", {})

        lines.append("═" * 50)
        lines.append(f"  ARIA DIAGNOSTICS — {ts}")
        lines.append("═" * 50)
        lines.append(
            f"  OK: {summary.get('ok',0)}  "
            f"WARN: {summary.get('warn',0)}  "
            f"FAIL: {summary.get('fail',0)}"
        )
        lines.append("")

        STATUS_ICONS = {"ok": "[OK]  ", "warn": "[WARN]", "fail": "[FAIL]", "info": "[INFO]"}

        for agent_name, agent_data in report.get("agents", {}).items():
            lines.append(f"── {agent_name.upper()} ──")
            for chk in agent_data.get("checks", []):
                icon = STATUS_ICONS.get(chk.get("status", "info"), "[INFO]")
                lines.append(f"  {icon}  {chk.get('detail', '')}")
            findings = agent_data.get("findings", [])
            if findings:
                for fn in findings[:5]:
                    lines.append(f"         ↳ {fn}")
            missing = agent_data.get("missing", [])
            if missing:
                lines.append(f"         missing: {', '.join(missing)}")
            lines.append("")

        # Errors from agent crashes
        errors = report.get("errors", {})
        if errors:
            lines.append("── AGENT ERRORS ──")
            for ag, err in errors.items():
                lines.append(f"  [FAIL]  {ag}: {err}")
            lines.append("")

        # Diff
        diff = report.get("diff", {})
        if diff.get("new_issues"):
            lines.append("── NEW ISSUES (since last scan) ──")
            for issue in diff["new_issues"]:
                lines.append(f"  ▲ {issue}")
            lines.append("")
        if diff.get("resolved"):
            lines.append("── RESOLVED (since last scan) ──")
            for issue in diff["resolved"]:
                lines.append(f"  ✓ {issue}")
            lines.append("")

        lines.append("═" * 50)
        return "\n".join(lines)
