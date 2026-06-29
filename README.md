# reticulum-aiov2-lora

Drive the **HackerGadgets uConsole AiO V2** LoRa radio (Semtech **SX1262**) from
userspace on a Raspberry Pi **CM5**, and expose it to the
[Reticulum Network Stack](https://reticulum.network) as a custom interface — so
the AiO V2 works as a Reticulum LoRa radio (for apps like MeshChat / MeshChatX)
and interoperates on-air with standard [RNode](https://unsigned.io/rnode/) devices.

## Why

The AiO V2's SX1262 is a **bare transceiver wired straight to the CM5 SPI bus** —
there is no on-board microcontroller, so the usual RNode path (a dedicated MCU
running RNode firmware and speaking the RNode serial protocol) doesn't apply.
This project fills that gap with two pieces:

- a **userspace driver** (`lgpio` + `spidev`) that resets, configures, and runs
  the SX1262 entirely from Python on the CM5; and
- a **Reticulum interface** that speaks the **RNode on-air format** (1-byte link
  header + 2-packet split framing for the full MTU) and does **CSMA /
  listen-before-talk**, so it shares the channel with — and is demodulated by —
  real RNodes.

## How it works

```
  Reticulum (rnsd)
        │  loads as a custom interface
        ▼
  SX1262Interface  ── RNode on-air framing (header + split) + CSMA/DCF
        │
        ▼
  SX1262 driver    ──  lgpio (GPIO) + spidev (SPI)
        │
        ▼
  SX1262 radio  ──LoRa──▶  RNode peers / Reticulum mesh
```

- **`src/sx1262/`** — the driver: reset/bring-up, LoRa modem config, TX, RX,
  carrier-sense RSSI. Pins and parameters are in [docs/hardware.md](docs/hardware.md).
- **`rns/interfaces/SX1262Interface.py`** — the Reticulum interface. A single
  service thread owns the radio: it polls RX, tracks an adaptive noise floor, and
  runs a non-blocking DCF state machine for CSMA. `process_outgoing` only enqueues;
  the service loop transmits when the channel is clear. On-air framing matches the
  RNode firmware so frames interoperate (sync word `0x1424`, 1-byte
  `seq<<4 | flags` header, `FLAG_SPLIT` for frames spanning two LoRa packets).

## Install

On the CM5:

```bash
git clone https://github.com/phutur1st/reticulum-aiov2-lora
cd reticulum-aiov2-lora
python3 -m venv .venv
.venv/bin/pip install -e .     # installs this package + lgpio, spidev
.venv/bin/pip install rns      # Reticulum
```

The interface must run from an interpreter that can import `sx1262` (+ `lgpio`,
`spidev`) — i.e. this venv's `rnsd`. Frozen GUI clients that bundle their own
Python (e.g. MeshChatX) can't load the GPIO driver; run `rnsd` here as a shared
instance and connect the client to it (see deployment, below).

## Use it with Reticulum

Make the interface discoverable and reference it from your Reticulum config:

```bash
mkdir -p ~/.reticulum/interfaces
cp rns/interfaces/SX1262Interface.py ~/.reticulum/interfaces/
```

```ini
# ~/.reticulum/config
[[AiO LoRa]]
  type = SX1262Interface
  interface_enabled = True
  interface_mode = full
  frequency = 915000000
  bandwidth = 125000
  spreadingfactor = 8
  codingrate = 5
  txpower = 17
```

```bash
.venv/bin/rnsd            # the radio comes up as SX1262Interface[AiO LoRa]
```

For a persistent, headless setup — `rnsd` as a shared instance that owns the
radio, plus a local TCP bridge so a GUI client (MeshChatX) can use it without
touching the radio config — see **[deploy/README.md](deploy/README.md)**.

## Hardware

| Signal | Connection |
|---|---|
| SPI | `/dev/spidev1.0` |
| BUSY | GPIO24 |
| RESET | GPIO25 |
| DIO2 | RF switch (on-chip) |
| DIO3 | TCXO power (on-chip) |

Defaults: 915 MHz, BW 125 kHz, SF8, CR4/5, sync word `0x1424`, preamble 64
symbols, TCXO 1.8 V. Full pin map and register details in
[docs/hardware.md](docs/hardware.md).

## Implementation notes

- **TX preamble is 64 symbols.** A short preamble (e.g. 22) is detected by an
  RNode's intermittently-listening CSMA receiver but not demodulated; an
  always-on receiver tolerates short preambles, which can mask the issue.
- **RNode-compatible framing.** Each LoRa packet is `[1-byte header][chunk]`
  (`header = seq<<4 | flags`, `FLAG_SPLIT = 0x01`). Frames larger than one packet
  are sent as two packets sharing a sequence number; the receiver reassembles.
  This carries the full 508-byte Reticulum MTU.
- **SX1262 errata + init.** `_set_packet_params` applies erratum 15.4 (IQ, reg
  `0x0736` bit 2); bring-up also sets RX gain (`0x08AC`), the antenna-mismatch
  clamp (erratum 15.2, `0x08D8`), and a 40 µs TX ramp. `CalibrateImage` for the
  902–928 MHz band must run after `SetRfFrequency` or TX chirps are malformed.
- **Non-blocking CSMA.** The interface mirrors the RNode firmware's
  `tx_queue_handler`: draw a contention window, wait a free DIFS, count down
  random backoff slots while the medium stays free (instantaneous RSSI vs. an
  adaptive median noise floor), and transmit when the count completes.

## Acknowledgements

- [Reticulum](https://github.com/markqvist/Reticulum) (Mark Qvist) — the network
  stack this plugs into.
- [RNode Firmware](https://github.com/markqvist/RNode_Firmware) /
  [RNode Firmware CE](https://github.com/liberatedsystems/RNode_Firmware_CE) — the
  on-air framing and CSMA behavior this interface reimplements for interoperability.
- Semtech SX1262 datasheet — command/register reference and errata.

## License

[GPL-3.0-or-later](LICENSE).
