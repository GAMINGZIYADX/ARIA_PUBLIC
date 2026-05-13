"""
hw_detect.py — ARIA Hardware Detection
=======================================
Probes NVIDIA GPU VRAM at startup and returns an optimal configuration
for faster-whisper and a warning if the configured LLM model is likely
too large for available VRAM.

Detection strategy (tries each in order, uses first success):
  1. nvidia-smi subprocess  — reliable on all platforms with NVIDIA drivers
  2. NVML via ctypes        — same data, no subprocess overhead
  3. torch.cuda             — free if PyTorch is already in the process
  4. CPU fallback           — returned when no GPU is found

Cross-platform: Linux, Windows 10/11, macOS.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional


# ── Whisper model VRAM thresholds ─────────────────────────────────────────────
# Each row: (min_vram_mb, size, device, compute_type)
# Rows must be in ascending VRAM order — last matching row wins.
#
#   tiny    ~390 MB VRAM  |  39 M params   |  fast, lower accuracy
#   base    ~500 MB VRAM  |  74 M params   |  good for clean speech
#   small  ~1500 MB VRAM  | 244 M params   |  solid accuracy
#   medium ~5000 MB VRAM  | 769 M params   |  high accuracy (current default)
#   large  ~10 GB VRAM    | 1550 M params  |  best, but rarely worth the overhead
_WHISPER_TIERS: list[tuple[int, str, str, str]] = [
    (    0, "tiny",   "cpu",  "int8"),      # No GPU / unknown
    ( 1024, "base",   "cuda", "int8"),      # ≥ 1 GB  VRAM
    ( 4096, "small",  "cuda", "int8"),      # ≥ 4 GB  VRAM
    ( 8192, "medium", "cuda", "int8"),      # ≥ 8 GB  VRAM
    (10240, "medium", "cuda", "float16"),   # ≥ 10 GB VRAM  (float16 quality bump)
]

# ── LLM VRAM requirements (rough Q4 quantisation estimates) ───────────────────
# Maps a regex matched against the model name to (min_vram_mb, [suggestions]).
# The regex is tested case-insensitively against the full model string.
_LLM_RULES: list[tuple[re.Pattern, int, list[str]]] = [
    (re.compile(r"70b"),   40_000, ["qwen2.5:14b",  "qwen2.5:7b"]),
    (re.compile(r"34b"),   20_000, ["qwen2.5:14b",  "qwen2.5:7b"]),
    (re.compile(r"1[3-9]b|14b"), 8_000, ["qwen2.5:7b",   "qwen2.5:3b"]),
    (re.compile(r"8b"),     5_000, ["qwen2.5:7b",   "qwen2.5:3b"]),
    (re.compile(r"7b"),     4_500, ["qwen2.5:3b",   "phi3:mini"]),
    (re.compile(r"[45]b"),  3_000, ["qwen2.5:3b",   "phi3:mini"]),
    (re.compile(r"3b"),     2_000, ["phi3:mini",    "tinyllama"]),
]


@dataclass
class HardwareProfile:
    """Detected hardware configuration returned by :func:`probe_gpu`."""
    vram_mb: int            # Total VRAM on the best GPU in MB; 0 = CPU-only
    whisper_size: str       # Recommended faster-whisper model: tiny/base/small/medium
    whisper_device: str     # "cuda" or "cpu"
    whisper_compute: str    # "float16" or "int8"
    source: str             # How VRAM was detected, e.g. "nvidia-smi"
    llm_warning: Optional[str] = field(default=None)  # Set by add_llm_warning()


# ── Internal probes ────────────────────────────────────────────────────────────

def _probe_nvidia_smi() -> int:
    """Run nvidia-smi and return total VRAM in MB of the largest GPU, or 0."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return 0
        vals = []
        for line in r.stdout.strip().splitlines():
            line = line.strip()
            if line.isdigit():
                vals.append(int(line))
        return max(vals) if vals else 0
    except Exception:
        return 0


def _probe_nvml() -> int:
    """
    Query VRAM via libnvidia-ml (NVML) through ctypes.
    Avoids a subprocess and works even when nvidia-smi is not on PATH.
    Returns total VRAM in MB of the largest GPU, or 0.
    """
    import ctypes

    lib_candidates = (
        ["libnvidia-ml.so.1", "libnvidia-ml.so"]
        if sys.platform != "win32"
        else ["nvml.dll"]
    )
    nvml = None
    for name in lib_candidates:
        try:
            nvml = ctypes.CDLL(name)
            break
        except OSError:
            continue
    if nvml is None:
        return 0

    try:
        if nvml.nvmlInit_v2() != 0:
            return 0

        count = ctypes.c_uint()
        nvml.nvmlDeviceGetCount_v2(ctypes.byref(count))
        if count.value == 0:
            nvml.nvmlShutdown()
            return 0

        class _MemInfo(ctypes.Structure):
            _fields_ = [
                ("total", ctypes.c_ulonglong),
                ("free",  ctypes.c_ulonglong),
                ("used",  ctypes.c_ulonglong),
            ]

        best = 0
        for i in range(count.value):
            handle = ctypes.c_void_p()
            nvml.nvmlDeviceGetHandleByIndex_v2(i, ctypes.byref(handle))
            mem = _MemInfo()
            if nvml.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(mem)) == 0:
                best = max(best, int(mem.total) // (1024 * 1024))

        nvml.nvmlShutdown()
        return best
    except Exception:
        return 0


def _probe_torch() -> int:
    """
    Return VRAM of the default CUDA device via torch, or 0.
    Zero-overhead when torch is not installed.
    """
    try:
        import torch
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            return props.total_memory // (1024 * 1024)
    except Exception:
        pass
    return 0


# ── Public API ─────────────────────────────────────────────────────────────────

def probe_gpu() -> HardwareProfile:
    """
    Probe the system for an NVIDIA GPU and return a :class:`HardwareProfile`.

    Tries three detection strategies in order (first success wins):
    1. ``nvidia-smi`` subprocess
    2. NVML via ctypes
    3. ``torch.cuda`` (free if torch already loaded)

    Falls back to a CPU-only profile when nothing succeeds.
    """
    vram_mb = 0
    source = "cpu-fallback"

    v = _probe_nvidia_smi()
    if v:
        vram_mb, source = v, "nvidia-smi"
    else:
        v = _probe_nvml()
        if v:
            vram_mb, source = v, "nvml-ctypes"
        else:
            v = _probe_torch()
            if v:
                vram_mb, source = v, "torch.cuda"

    # Pick Whisper config from tiers — last row whose threshold is met wins
    whisper_size, whisper_device, whisper_compute = "tiny", "cpu", "int8"
    for threshold, size, device, compute in _WHISPER_TIERS:
        if vram_mb >= threshold:
            whisper_size, whisper_device, whisper_compute = size, device, compute

    return HardwareProfile(
        vram_mb=vram_mb,
        whisper_size=whisper_size,
        whisper_device=whisper_device,
        whisper_compute=whisper_compute,
        source=source,
    )


def add_llm_warning(profile: HardwareProfile, model_name: str) -> HardwareProfile:
    """
    Attach a human-readable ``llm_warning`` to *profile* if *model_name*
    is likely too large for the detected VRAM.  Returns the same object.
    """
    model_lower = model_name.lower().strip()
    for pattern, required_mb, alternatives in _LLM_RULES:
        if not pattern.search(model_lower):
            continue
        if profile.vram_mb == 0:
            profile.llm_warning = (
                f"No GPU detected — {model_name} will run on CPU, "
                f"which may be very slow.\n"
                f"  Consider a smaller model: {', '.join(alternatives)}"
            )
        elif profile.vram_mb < required_mb:
            have_gb  = profile.vram_mb / 1024
            need_gb  = required_mb / 1024
            profile.llm_warning = (
                f"GPU has {have_gb:.1f} GB VRAM, but {model_name} "
                f"needs ~{need_gb:.0f} GB (Q4).\n"
                f"  Consider: {', '.join(alternatives)}"
            )
        return profile   # matched this rule — stop
    return profile


def summarize(profile: HardwareProfile) -> str:
    """One-line description of the detected hardware configuration."""
    if profile.vram_mb:
        gb = profile.vram_mb / 1024
        return (
            f"GPU {gb:.1f} GB VRAM ({profile.source}) → "
            f"Whisper '{profile.whisper_size}' on "
            f"{profile.whisper_device.upper()}/{profile.whisper_compute}"
        )
    return (
        f"No GPU ({profile.source}) → "
        f"Whisper '{profile.whisper_size}' on CPU"
    )


# ── Module-level cache ─────────────────────────────────────────────────────────
_profile: Optional[HardwareProfile] = None


def get_profile() -> HardwareProfile:
    """Return the cached :class:`HardwareProfile`, probing on first call."""
    global _profile
    if _profile is None:
        _profile = probe_gpu()
    return _profile
