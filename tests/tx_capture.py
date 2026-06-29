#!/usr/bin/env python3
"""Capture the exact raw bytes RNS hands to the RNode for transmission.
Run standalone on the Mac (stop the Mac rnsd first so this owns the RNode).

    python3 tests/tx_capture.py <configdir>
"""
import os
import sys
import time

import RNS
from RNS.Interfaces.RNodeInterface import RNodeInterface

configdir = os.path.abspath(sys.argv[1])
_orig = RNodeInterface.process_outgoing


def _patched(self, data):
    RNS.log(f"TX-RAW {len(data)}B {bytes(data).hex()}", RNS.LOG_NOTICE)
    return _orig(self, data)


RNodeInterface.process_outgoing = _patched

serve = len(sys.argv) > 2 and sys.argv[2] == "serve"
r = RNS.Reticulum(configdir=configdir)

if serve:
    # Act as the shared-instance server (owns the RNode); a separate
    # link_test client announces through us so we log the relayed HEADER_2 bytes.
    RNS.log("serving; waiting for client announces...", RNS.LOG_NOTICE)
    time.sleep(45)
else:
    ident = RNS.Identity()
    dest = RNS.Destination(ident, RNS.Destination.IN, RNS.Destination.SINGLE,
                           "aioprobe", "mac")
    for i in range(3):
        dest.announce(app_data=b"mac")
        time.sleep(3)
    time.sleep(1)
