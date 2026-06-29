# Deployment — SX1262 radio node on the uConsole CM5

Reference for standing the radio node back up from scratch (e.g. after a reflash).
It runs `rnsd` from this repo's venv as a **shared Reticulum instance** that owns the
SX1262 radio, and exposes a local **TCP bridge** that a client app (MeshChatX) connects
to — so the client never has to load the GPIO driver and never touches the radio config.

```
 MeshChatX (frozen RNS, no lgpio)              this repo's .venv
   ~/.reticulum  ──TCP 127.0.0.1:4242──▶  rnsd  ──SPI──▶  SX1262  ──LoRa──▶  RNode gateway
                  (TCPServerInterface)   (--config ~/.reticulum-radio)
```

## Files here

| repo file | deploy to | what it is |
|---|---|---|
| `deploy/reticulum-radio/config` | `~/.reticulum-radio/config` | dedicated RNS config (radio + TCP bridge) |
| `deploy/systemd/rnsd-radio.service` | `~/.config/systemd/user/rnsd-radio.service` | user service that runs rnsd on boot |
| `rns/interfaces/SX1262Interface.py` | `~/.reticulum-radio/interfaces/SX1262Interface.py` | the custom RNS interface (framing + CSMA) |

## Steps (Raspberry Pi CM5, e.g. uConsole AiO V2)

```bash
# 1. Clone + create the venv, install the driver/interface package editable.
#    Editable install puts src/ on the path so `import sx1262` resolves; rnsd needs it.
cd ~/code/reticulum-aiov2-lora
python3 -m venv .venv
.venv/bin/pip install -e .            # installs aiov2-sx1262 (deps: spidev, lgpio)
.venv/bin/pip install 'rns==1.3.5'   # rnsd lives at .venv/bin/rnsd; pin: the config
                                      # landmines below are specific to this RNS version

# 2. Lay down the dedicated radio config dir + the custom interface.
mkdir -p ~/.reticulum-radio/interfaces
cp deploy/reticulum-radio/config           ~/.reticulum-radio/config
cp rns/interfaces/SX1262Interface.py        ~/.reticulum-radio/interfaces/

# 3. Install + enable the service (linger = survives logout / boots headless).
mkdir -p ~/.config/systemd/user
cp deploy/systemd/rnsd-radio.service ~/.config/systemd/user/
loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now rnsd-radio
```

## Verify

```bash
systemctl --user status rnsd-radio
# SX1262 interface up + traffic (↑ on TX, ↓ once it hears a peer):
.venv/bin/rnstatus --config ~/.reticulum-radio
# learned LoRa routes:
.venv/bin/rnpath  --config ~/.reticulum-radio --table
```

Then point the client (MeshChatX) at a `TCPClientInterface` → `127.0.0.1:4242` in its
**own** `~/.reticulum` config. It connects as a client of the shared instance; the radio
stays exclusively owned by `rnsd-radio`.

## Gotchas (learned the hard way — see ../HANDOFF.md)

- **Keep `interface_mode = full`.** On RNS 1.3.5, `gateway` throws `KeyError 'mode'` and
  `pointtopoint` silently stops announce propagation (client traffic won't bridge).
- **Don't** add `discover_interfaces`, `autoconnect_discovered_interfaces`,
  `selected_interface_mode`, or `instance_name` — rnsd exits 255 on these.
- The radio is **half-duplex and single-owner**: only `rnsd-radio` may open the SX1262.
  A second process opening `/dev/spidev1.0` (or another rnsd) will conflict.
- Radio params (915 MHz / BW125 / SF8 / CR5 / sync 0x1424 / preamble 64) must match the
  peer. The preamble being 64 (not 22) is what makes an RNode's CSMA receiver lock on.
