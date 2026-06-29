#!/usr/bin/env python3
"""Read-only SX1262 probe: reset, status, device errors, sync-word register.
Does not transmit. Run on the CM5 with meshtasticd stopped.

    python3 tests/probe_readonly.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from sx1262.driver import SX1262, CHIPMODE  # noqa: E402

dev = SX1262()
busy0 = dev._wait_busy(0.05)
dev.reset()
st = dev.get_status()
mode = (st >> 4) & 0x7
err = dev.get_device_errors()
sync = dev.read_reg(0x0740, 2)

print(f"GetStatus      : {st:#04x}  mode={CHIPMODE.get(mode, mode)}")
print(f"GetDeviceErrors: {err:#06x}  "
      f"({'none' if err == 0 else 'XOSC_START_ERR (expected before TCXO setup)' if err & 0x20 else 'see datasheet'})")
print(f"LoRaSyncWord   : {sync[0]:#04x} {sync[1]:#04x}  (POR default 0x14 0x24)")

ok = mode in (2, 3) and sync == [0x14, 0x24]
print("\nVERDICT:", "PASS - SPI control confirmed" if ok else "CHECK above")
dev.close()
sys.exit(0 if ok else 1)
