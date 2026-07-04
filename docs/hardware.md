# Hardware & on-air parameters

## Host
- Raspberry Pi Compute Module 5 Lite, in a ClockworkPi uConsole.
- Kernel 6.12.93-v8+. RP1 GPIO is `gpiochip0` (54 lines).
- Headless; driven over SSH.

## Radio (HackerGadgets AiO V2)
- Semtech **SX1262** wired directly to the CM5 SPI bus — no MCU.
- SPI: `/dev/spidev1.0` (SPI1-CE0 = GPIO18), enabled via `dtoverlay=spi1-1cs`.

### Pin map (BCM, gpiochip0)
| Function | Pin |
|----------|-----|
| SPI CS   | GPIO18 (SPI1-CE0) |
| BUSY     | GPIO24 |
| RESET    | GPIO25 |
| IRQ/DIO1 | GPIO26 |
| DIO2     | on-chip RF switch control |
| DIO3     | on-chip TCXO power |

TCXO is powered from DIO3, so `SetDIO3AsTCXOCtrl` (1.8 V) + `ClearDeviceErrors`
must run during bring-up or the chip reports `XOSC_START_ERR` (0x0020) and the
oscillator never starts. Seeing that error *before* TCXO setup is expected.

## LoRa parameters (US 902–928, matched to the RNode peer)
| Param | Value |
|-------|-------|
| Frequency | 915.000 MHz |
| Bandwidth | 125 kHz |
| Spreading factor | SF8 |
| Coding rate | 4:5 |
| Preamble | 64 symbols (TX) — 22 was too short for the RNode's CSMA receiver to lock |
| Header | explicit |
| CRC | on |
| Sync word | 0x1424 (SX1262 POR default; matches RNode) |

## Peer
- Tested against an RNode peer: Ebyte EoRa-S3 (ESP32-S3 + SX1262), host-controlled
  mode (LoRa parameters set at runtime by RNS).

## Backend decision
Driver uses **lgpio + spidev** (both preinstalled on the CM5). The `LoRaRF`
library was rejected: it officially supports only up to the Pi 4, not the
RP1-based CM5.

## Radio ownership
The SX1262 has a single owner at a time. In this deployment the `rnsd-radio`
service (see `deploy/`) owns it; stop it before running the direct-driver
scripts in `tests/`:

    systemctl --user stop rnsd-radio     # release the radio
    systemctl --user start rnsd-radio    # restore

If `meshtasticd` is also installed it will claim the SPI/GPIO on boot too, so
stop that as well (`sudo systemctl stop meshtasticd`).
