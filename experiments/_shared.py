"""Shared helpers for the experiments: paths, .env, Featherless client, memory guard.

The experiments import Jessica's code from src/ and never write to artifacts/ or data/clean/.
Their outputs go to experiments/results/.
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
RESULTS = Path(__file__).resolve().parent / "results"
CACHE = Path(__file__).resolve().parent / "cache"   # embeddings etc. (git-ignored)
RESULTS.mkdir(exist_ok=True)
CACHE.mkdir(exist_ok=True)

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
os.chdir(ROOT)  # src/common.py paths are relative to the repo root

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

MAX_GB = float(os.environ.get("EXP_MAX_GB", "3.5"))  # stay under the 4 GB budget


def mem_gb() -> float:
    """Current working set of this process in GB (Windows; falls back to psutil/resource)."""
    if sys.platform == "win32":
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                               "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                               "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        psapi.GetProcessMemoryInfo(wintypes.HANDLE(k32.GetCurrentProcess()), ctypes.byref(c), c.cb)
        return c.WorkingSetSize / 1e9
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6


def guard(step: str = ""):
    g = mem_gb()
    if g > MAX_GB:
        raise SystemExit(f"memory {g:.2f} GB > {MAX_GB} GB at '{step}': stopping")
    return g


def featherless():
    from openai import OpenAI
    key = os.environ.get("FEATHERLESS_API_KEY")
    if not key:
        raise SystemExit("Set FEATHERLESS_API_KEY in .env")
    return OpenAI(base_url="https://api.featherless.ai/v1", api_key=key, max_retries=4, timeout=120)
