#!/usr/bin/env python3
"""Regression check for loradecode.py against the committed sample capture.

Runs the decoder on tools/samples/lora_sf8_bw125.bin and asserts it recovers the
LoRa frame structure: a flat preamble plateau (constant dechirped bin) and strong,
sharp per-symbol peaks. Independent of the payload, so it stays stable.

    python3 tests/test_loradecode.py
"""
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(__file__), "..")
SAMPLE = os.path.join(ROOT, "tools", "samples", "lora_sf8_bw125.bin")
DECODER = os.path.join(ROOT, "tools", "loradecode.py")

try:
    import matplotlib  # noqa: F401
    import numpy       # noqa: F401
    import scipy        # noqa: F401
except ImportError as e:
    print(f"SKIP: loradecode's DSP deps not available ({e})")
    sys.exit(0)

out = os.path.join(tempfile.gettempdir(), "loradecode_test.png")
proc = subprocess.run(
    [sys.executable, DECODER, SAMPLE, out,
     "915000000", "915000000", "256000", "8", "125000"],
    capture_output=True, text=True)
sys.stdout.write(proc.stdout)
if proc.returncode != 0:
    sys.exit("FAIL: decoder errored\n" + proc.stderr)

m = re.search(r"std=([\d.]+)\s+mean_sharp=([\d.]+)", proc.stdout)
if not m:
    sys.exit("FAIL: no preamble analysis in decoder output")
std, sharp = float(m.group(1)), float(m.group(2))
assert std < 0.5, f"FAIL: preamble plateau not flat (std={std})"
assert sharp > 20, f"FAIL: symbol peaks too weak (mean_sharp={sharp})"
print(f"PASS: flat preamble (std={std}) + strong peaks (mean_sharp={sharp})")
