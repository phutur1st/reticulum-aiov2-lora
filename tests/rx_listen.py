#!/usr/bin/env python3
"""Bring up the SX1262 in RX and print received LoRa packets.
Matches the RNode on-air format so an RNode peer's transmissions are received.

    python3 tests/rx_listen.py [seconds]

Run on the CM5 with meshtasticd stopped.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from sx1262.driver import SX1262  # noqa: E402

LISTEN_S = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0

dev = SX1262()
err = dev.begin(freq_hz=915_000_000, sf=8, bw_hz=125_000, cr_denom=5,
                preamble=18, sync=(0x14, 0x24), tcxo_voltage=1.8)
print(f"bring-up: status={dev.get_status():#04x} device_errors={err:#06x} "
      f"({'XOSC OK' if err == 0 else 'XOSC_START_ERR!' if err & 0x20 else 'see datasheet'})")
print(f"listening {LISTEN_S:.0f}s @ 915.000 MHz SF8 BW125 CR4:5 ...")

dev.listen()
t0 = time.time()
n = 0
while time.time() - t0 < LISTEN_S:
    pkt = dev.poll_rx()
    if pkt:
        data, rssi, snr, crc_ok = pkt
        n += 1
        tag = "OK" if crc_ok else "CRC_FAIL"
        print(f"[{tag}] len={len(data)} rssi={rssi:.0f}dBm snr={snr:.1f}dB "
              f"data={data.hex()}")
    time.sleep(0.005)

print(f"done. packets received: {n}")
dev.close()
sys.exit(0 if n > 0 else 2)
