# Custom Reticulum interface for the AiO V2 SX1262 (CM5).
#
# Install: copy this file to ~/.reticulum/interfaces/ and ensure the `sx1262`
# package (this repo) is importable by the process that loads the interface.
# Reference it from ~/.reticulum/config:
#
#   [[AiO LoRa]]
#     type = SX1262Interface
#     interface_enabled = True
#     interface_mode = pointtopoint
#     frequency = 915000000
#     bandwidth = 125000
#     spreadingfactor = 8
#     codingrate = 5
#     txpower = 17
#
# RNS loads this file with exec(), injecting `Interface` and `RNS` into globals
# and reading the module-level `interface_class` below. It instantiates
# interface_class(RNS.Transport, interface_config).
#
# IMPORTANT: the process that brings up this interface needs `sx1262` + `lgpio`
# + `spidev`, so it must run from this repo's .venv (e.g. `.venv/bin/rnsd`).
# A frozen client like MeshChatX cannot import these; instead run rnsd from the
# .venv as the shared instance (share_instance = Yes) and point the client at
# the same config dir so it connects as a client over the shared-instance port.
#
# This interface implements the RNode on-air framing: a 1-byte link header per
# LoRa packet (sequence + flags) and 2-packet FLAG_SPLIT fragmentation, so it
# carries the full RNS MTU (HW_MTU 508). TX does CSMA / listen-before-talk.
import random
import threading
import time
from collections import deque

from sx1262.driver import SX1262

# Loaded via RNS exec (Interface and RNS injected); fall back for normal
# import/tests so the module is usable standalone too.
try:
    Interface
except NameError:
    from RNS.Interfaces.Interface import Interface
try:
    RNS
except NameError:
    import RNS

# RNode on-air link framing (matches RNode_Firmware Framing.h). Every LoRa
# packet carries a 1-byte header: high nibble = frame sequence, low nibble =
# flags. A frame larger than one LoRa packet sets FLAG_SPLIT and is sent as two
# packets that share one sequence number; the receiver reassembles them.
SINGLE_MTU = 255              # max bytes in one LoRa packet (header + chunk)
HEADER_L = 1
FLAG_SPLIT = 0x01
NIBBLE_SEQ = 0xF0
MAX_CHUNK = SINGLE_MTU - HEADER_L   # 254 frame bytes per LoRa packet

# CSMA / listen-before-talk, mirroring RNode_Firmware's non-blocking
# tx_queue_handler: process_outgoing only enqueues; the radio service loop runs a
# DCF state machine (draw a contention window, wait a DIFS of quiet, count down
# random backoff slots, freezing whenever the channel goes busy) and transmits
# when clear. "Busy" = instantaneous RSSI more than CSMA_INFR_THRESHOLD_DB above
# an adaptively-tracked noise floor.
CSMA_SLOT_SYMBOLS = 12        # slot ~= 12 symbol times (~24 ms at SF8/BW125)
CSMA_DIFS_SLOTS = 2           # DIFS = 2 slots (~48 ms), as the RNode reports
CSMA_CW_MIN = 0
CSMA_CW_MAX = 15              # contention window, in slots
CSMA_INFR_THRESHOLD_DB = 6    # RSSI this far above the noise floor => busy
TX_QUEUE_MAX_FRAMES = 64      # outbound frames buffered while the channel is busy


class SX1262Interface(Interface):
    DEFAULT_IFAC_SIZE = 8
    HW_MTU = 2 * MAX_CHUNK        # 508: a frame spans at most two LoRa packets

    def __init__(self, owner, configuration):
        super().__init__()
        c = Interface.get_config_obj(configuration)

        self.owner = owner
        self.name = str(c["name"])
        self.IN = True
        self.OUT = True
        self.online = False
        self.detached = False
        # base __init__ sets self.HW_MTU = None (instance attr), which shadows
        # the class attribute, so set it explicitly here.
        self.HW_MTU = SX1262Interface.HW_MTU

        self.frequency = int(c.get("frequency", 915_000_000))
        self.bandwidth = int(c.get("bandwidth", 125_000))
        self.sf = int(c.get("spreadingfactor", 8))
        self.cr_denom = int(c.get("codingrate", 5))
        self.txpower = int(c.get("txpower", 17))

        # LoRa on-air bitrate (bits/s): SF * (BW / 2^SF) * 4/(4+CR)
        cr = self.cr_denom - 4
        self.bitrate = int(self.sf * (self.bandwidth / (1 << self.sf)) * 4 / (4 + cr))

        self._lock = threading.Lock()
        self._rx_seq = None       # sequence of an in-progress split frame
        self._rx_buf = b""        # first fragment of an in-progress split frame

        # CSMA timing, derived from the LoRa symbol time
        sym_s = (1 << self.sf) / self.bandwidth
        self._csma_slot = CSMA_SLOT_SYMBOLS * sym_s
        self._csma_difs = CSMA_DIFS_SLOTS * self._csma_slot
        self._noise_floor = -100.0
        self._noise_init = False
        self._nf_buf = []         # rolling RSSI window -> robust median noise floor
        self._nf_next = 0.0

        # Non-blocking TX queue + CSMA state machine (mirrors RNode firmware)
        self._tx_queue = deque()
        self._csma_cw = -1
        self._cw_wait_target = 0.0
        self._cw_wait_passed = 0.0
        self._difs_wait_start = -1.0
        self._cw_wait_start = -1.0

        self.radio = SX1262()
        err = self.radio.begin(freq_hz=self.frequency, sf=self.sf,
                               bw_hz=self.bandwidth, cr_denom=self.cr_denom,
                               tx_power=self.txpower)
        if err & 0x20:
            raise RuntimeError(f"SX1262 XOSC_START_ERR (device_errors={err:#06x})")
        self.radio.listen()
        self.online = True

        self._radio_thread = threading.Thread(target=self._service_loop, daemon=True)
        self._radio_thread.start()
        RNS.log(f"{self} online: {self.frequency/1e6:.3f} MHz SF{self.sf} "
                f"BW{self.bandwidth//1000} CR4:{self.cr_denom} "
                f"bitrate {self.bitrate} bps", RNS.LOG_NOTICE)

    def _service_loop(self):
        # Single thread owns the radio: poll RX, track the noise floor, and run
        # the non-blocking TX/CSMA state machine -- mirroring the RNode firmware's
        # main loop rather than blocking process_outgoing.
        while not self.detached:
            try:
                with self._lock:
                    pkt = self.radio.poll_rx()
                if pkt:
                    payload, rssi, snr, crc_ok = pkt
                    if crc_ok and len(payload) >= HEADER_L:
                        self.r_stat_rssi = rssi
                        self.r_stat_snr = snr
                        self._handle_payload(payload)
                else:
                    now = time.time()
                    if now >= self._nf_next:    # periodically sample noise floor
                        self._nf_next = now + 0.1
                        with self._lock:
                            r = self.radio.rssi_inst()
                        self._update_noise_floor(r)
                self._tx_queue_handler()
                if not pkt:
                    time.sleep(0.003)
            except Exception as e:
                RNS.log(f"{self} service loop error: {e}", RNS.LOG_ERROR)
                time.sleep(0.1)

    def _update_noise_floor(self, rssi):
        # Noise floor = median of a rolling window of idle RSSI samples. The
        # median rejects both received-signal spikes (high) and the unsettled
        # post-listen reading (~-127.5 dBm, low). A previous version seeded the
        # floor from a single first sample and only folded in lower ones, so a
        # -127.5 first read stuck the floor near the bottom -> the channel read
        # permanently "busy" and CSMA blocked ALL transmits.
        if rssi <= -125:
            return
        self._nf_buf.append(rssi)
        if len(self._nf_buf) > 32:
            self._nf_buf.pop(0)
        if len(self._nf_buf) >= 8:
            self._noise_floor = sorted(self._nf_buf)[len(self._nf_buf) // 2]
            self._noise_init = True

    def _medium_free(self):
        with self._lock:
            r = self.radio.rssi_inst()
        return r <= self._noise_floor + CSMA_INFR_THRESHOLD_DB

    def _tx_queue_handler(self):
        # Non-blocking DCF CSMA, called once per service-loop pass (mirrors
        # RNode_Firmware tx_queue_handler): draw a contention window, wait a free
        # DIFS, count down random backoff slots while the medium stays free, and
        # transmit when the count completes. Any busy sample restarts the wait.
        if not self._tx_queue:
            return
        now = time.time()
        if self._csma_cw == -1:
            self._csma_cw = random.randint(CSMA_CW_MIN, CSMA_CW_MAX)
            self._cw_wait_target = self._csma_cw * self._csma_slot
        if self._difs_wait_start == -1:
            if self._medium_free():
                self._difs_wait_start = now
            return
        if not self._medium_free():
            self._difs_wait_start = -1
            self._cw_wait_start = -1
            return
        if now < self._difs_wait_start + self._csma_difs:
            return
        if self._cw_wait_start == -1:
            self._cw_wait_start = now
            return
        self._cw_wait_passed += now - self._cw_wait_start
        self._cw_wait_start = now
        if self._cw_wait_passed < self._cw_wait_target:
            return
        self._flush_one()                       # clear to transmit
        self._cw_wait_passed = 0.0
        self._csma_cw = -1
        self._difs_wait_start = -1
        self._cw_wait_start = -1

    def _flush_one(self):
        packets, datalen = self._tx_queue.popleft()
        ok = True
        with self._lock:
            for pkt in packets:
                ok = self.radio.transmit(pkt) and ok
            self.radio.listen()
        if ok:
            self.txb += datalen
        else:
            RNS.log(f"{self} TX timeout", RNS.LOG_WARNING)

    def _handle_payload(self, payload):
        # Strip the RNode link header and reassemble split frames before
        # handing a complete RNS frame up the stack.
        header = payload[0]
        chunk = payload[HEADER_L:]
        seq = header & NIBBLE_SEQ
        if header & FLAG_SPLIT:
            if self._rx_seq is not None and self._rx_seq == seq:
                frame = self._rx_buf + chunk     # second fragment completes it
                self._rx_seq = None
                self._rx_buf = b""
                self.process_incoming(frame)
            else:
                self._rx_seq = seq               # first fragment (or resync)
                self._rx_buf = chunk
        else:
            self._rx_seq = None
            self._rx_buf = b""
            self.process_incoming(chunk)

    def process_incoming(self, data):
        self.rxb += len(data)
        self.owner.inbound(data, self)

    def process_outgoing(self, data):
        # Non-blocking: build the on-air packets and enqueue them; the service
        # loop's CSMA state machine transmits when the channel is clear.
        if self.detached or not self.online:
            return
        if len(data) > self.HW_MTU:
            RNS.log(f"{self} dropping {len(data)}B frame (exceeds HW_MTU "
                    f"{self.HW_MTU})", RNS.LOG_WARNING)
            return
        if len(self._tx_queue) >= TX_QUEUE_MAX_FRAMES:
            RNS.log(f"{self} TX queue full ({TX_QUEUE_MAX_FRAMES}); dropping frame",
                    RNS.LOG_WARNING)
            return
        # RNode on-air framing: one sequence per frame; >MAX_CHUNK bytes are sent
        # as two LoRa packets sharing the sequence, with FLAG_SPLIT set.
        seq = (random.randint(0, 15) << 4) & NIBBLE_SEQ
        if len(data) <= MAX_CHUNK:
            packets = [bytes([seq]) + data]
        else:
            hdr = seq | FLAG_SPLIT
            packets = [bytes([hdr]) + data[:MAX_CHUNK],
                       bytes([hdr]) + data[MAX_CHUNK:]]
        self._tx_queue.append((packets, len(data)))

    def should_ingress_limit(self):
        return False

    def detach(self):
        self.detached = True
        self.online = False
        try:
            self.radio.close()
        except Exception:
            pass

    def __str__(self):
        return f"SX1262Interface[{self.name}]"


interface_class = SX1262Interface
