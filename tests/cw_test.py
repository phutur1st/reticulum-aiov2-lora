#!/usr/bin/env python3
"""Emit an unmodulated carrier (SetTxContinuousWave) to verify the TX RF path
(PA, DIO2 antenna switch, frequency) independent of modulation/framing.
Run on the CM5 with rnsd-radio stopped; observe with the AiO V2's onboard RTL-SDR.

    python3 tests/cw_test.py [seconds] [freq_hz]
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from sx1262.driver import SX1262  # noqa: E402

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
freq = int(sys.argv[2]) if len(sys.argv) > 2 else 915_000_000

dev = SX1262()
err = dev.begin(freq_hz=freq, sf=8, bw_hz=125_000, cr_denom=5, tx_power=17)
print(f"bring-up device_errors={err:#06x}; CW ON @ {freq/1e6:.3f} MHz for {secs:.0f}s")
dev.cmd([0xD1])                      # SetTxContinuousWave
time.sleep(secs)
dev.cmd([0x80, 0x00])                # SetStandby(RC) -> carrier off
print("CW OFF")
dev.close()
