#!/usr/bin/env python3
"""Transmit periodic LoRa beacons from the SX1262 (RNode-compatible PHY).

    python3 tests/tx_beacon.py [count] [interval_s]

Run on the CM5 with meshtasticd stopped. Verify reception on the RNode
peer or an RTL-SDR.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from sx1262.driver import SX1262  # noqa: E402

count = int(sys.argv[1]) if len(sys.argv) > 1 else 10
interval = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
preamble = int(sys.argv[3]) if len(sys.argv) > 3 else 22
power = int(sys.argv[4]) if len(sys.argv) > 4 else 17

dev = SX1262()
err = dev.begin(freq_hz=920_000_000, sf=8, bw_hz=125_000, cr_denom=5,
                preamble=preamble, sync=(0x14, 0x24), tcxo_voltage=1.8,
                tx_power=power)
print(f"bring-up device_errors={err:#06x} freq=920 preamble={preamble} power={power}")
for i in range(count):
    payload = f"AIO-CM5 beacon {i}".encode()
    ok = dev.transmit(payload)
    print(f"tx {i}: {'TxDone' if ok else 'TIMEOUT'}  ({payload!r})")
    time.sleep(interval)
dev.close()
