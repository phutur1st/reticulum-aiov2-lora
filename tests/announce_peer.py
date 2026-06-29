#!/usr/bin/env python3
"""Peer side: bring up Reticulum on the RNode and announce periodically,
generating known LoRa traffic for the CM5 RX test to receive.

    python3 tests/announce_peer.py [count] [interval_s]

Uses the RNode configured in rns/peer/config (set its serial port there).
"""
import os
import sys
import time

import RNS

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "rns", "peer")
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
