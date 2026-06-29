#!/usr/bin/env python3
"""Quick environment check for MinerU batch conversion."""

from __future__ import annotations

import shutil
import subprocess
import sys


def check_python() -> bool:
    major, minor = sys.version_info[:2]
    ok = (3, 10) <= (major, minor) <= (3, 13)
    status = "OK" if ok else "WARN"
    print(f"[{status}] Python {major}.{minor}.{sys.version_info.micro} (MinerU recommends 3.10–3.13)")
    return ok


def check_command(name: str) -> bool:
    path = shutil.which(name)
    if path:
        print(f"[OK] {name} found: {path}")
        return True
    print(f"[MISSING] {name} not found in PATH")
    return False


def check_mineru() -> bool:
    if not shutil.which("mineru"):
        return False
    try:
        proc = subprocess.run(
            ["mineru", "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        out = (proc.stdout or proc.stderr or "").strip()
        print(f"[OK] mineru --version: {out or '(no output)'}")
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        print("[WARN] mineru --version timed out")
        return False
    except OSError as exc:
        print(f"[FAIL] mineru error: {exc}")
        return False


def main() -> int:
    print("=== MinerU environment check ===\n")
    py_ok = check_python()
    uv_ok = check_command("uv")
    mineru_ok = check_mineru()

    print("\n=== Install hints (if missing) ===")
    if not uv_ok:
        print("  pip install --upgrade pip")
        print("  pip install uv")
    if not mineru_ok:
        print('  uv pip install -U "mineru[all]"')
        print('  # or: pip install -U "mineru[all]"')

    if py_ok and mineru_ok:
        print("\n[OK] Ready to run batch_pdf_to_md.py")
        return 0
    print("\n[WARN] Fix missing items before batch conversion.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
