#!/usr/bin/env python3
"""Mac-side peer: bring up Reticulum on the RNode and announce periodically,
generating known LoRa traffic for the CM5 RX test to receive.

    python3 tests/announce_peer.py [count] [interval_s]

Uses the RNode on /dev/cu.usbmodem101 via rns/mac-test/config.
"""
import os
import sys
import time

import RNS

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "rns", "mac-test")
count = int(sys.argv[1]) if len(sys.argv) > 1 else 12
interval = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0

r = RNS.Reticulum(configdir=os.path.abspath(CONFIG_DIR))
ident = RNS.Identity()
dest = RNS.Destination(ident, RNS.Destination.IN, RNS.Destination.SINGLE,
                       "aio", "probe")
RNS.log(f"announcing {dest.hash.hex()} {count}x every {interval}s")
for i in range(count):
    dest.announce()
    RNS.log(f"announce {i} sent")
    time.sleep(interval)
RNS.log("done")
