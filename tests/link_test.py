#!/usr/bin/env python3
"""Bidirectional Reticulum link test over LoRa.

Connects to the running rnsd (shared instance) for the given config dir,
announces a destination periodically, and prints any announces it hears.
Run one instance on each node; each should print the other's announces.

    python3 tests/link_test.py <configdir> <label> [duration_s] [interval_s]
"""
import os
import sys
import time

import RNS

configdir = os.path.abspath(sys.argv[1])
label = sys.argv[2] if len(sys.argv) > 2 else "node"
duration = float(sys.argv[3]) if len(sys.argv) > 3 else 60.0
interval = float(sys.argv[4]) if len(sys.argv) > 4 else 8.0


PEERS = {b"cm5", b"peer"}


class AnnounceHandler:
    # None = receive every announce; we filter to our two nodes via app_data
    # so ambient LoRa traffic on the same params is ignored.
    aspect_filter = None

    def received_announce(self, destination_hash, announced_identity, app_data):
        if app_data in PEERS:
            RNS.log(f"RX-ANNOUNCE peer={app_data.decode()} "
                    f"{RNS.prettyhexrep(destination_hash)}", RNS.LOG_NOTICE)


r = RNS.Reticulum(configdir=configdir)
RNS.Transport.register_announce_handler(AnnounceHandler())

ident = RNS.Identity()
dest = RNS.Destination(ident, RNS.Destination.IN, RNS.Destination.SINGLE,
                       "aioprobe", label)
RNS.log(f"[{label}] dest {RNS.prettyhexrep(dest.hash)} "
        f"announcing every {interval}s for {duration:.0f}s", RNS.LOG_NOTICE)

t0 = time.time()
i = 0
while time.time() - t0 < duration:
    dest.announce(app_data=label.encode())
    RNS.log(f"[{label}] TX announce {i}", RNS.LOG_NOTICE)
    i += 1
    time.sleep(interval)
RNS.log(f"[{label}] done", RNS.LOG_NOTICE)
