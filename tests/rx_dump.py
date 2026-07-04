#!/usr/bin/env python3
"""Dump full SX1262 RX buffer reads to diagnose ReadBuffer offset alignment.
Run on the CM5 (rnsd-radio stopped) while a peer announces (no IFAC).

    python3 tests/rx_dump.py [seconds]
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from sx1262.driver import SX1262  # noqa: E402

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0
dev = SX1262()
dev.begin(freq_hz=915_000_000, sf=8, bw_hz=125_000, cr_denom=5)
dev.listen()
print("dumping...")
t0 = time.time()
while time.time() - t0 < secs:
    rx = dev.cmd([0x12, 0, 0, 0])              # GetIrqStatus
    irq = (rx[2] << 8) | rx[3]
    if irq:
        dev.cmd([0x02, (irq >> 8) & 0xFF, irq & 0xFF])   # ClearIrqStatus
        if irq & 0x0002:                       # RxDone
            rb = dev.cmd([0x13, 0, 0, 0])      # GetRxBufferStatus
            plen, start = rb[2], rb[3]
            # ReadBuffer with extra trailing NOPs so we can see surrounding bytes
            full = dev.cmd([0x1E, start] + [0] * (plen + 6))
            print(f"plen={plen} start={start} crcfail={bool(irq & 0x40)}")
            print("  raw=" + bytes(full).hex())
    time.sleep(0.005)
dev.close()
