# RF diagnostics

Tools for validating the SX1262 transmit path on-air, using the CM5's
onboard RTL-SDR (RTL2838). They were used to prove that the CM5 emits a
fully-formed, decodable LoRa frame.

## Capture

Record IQ with `rtl_sdr` while the radio transmits. Tune the SDR a little
off the signal so the LoRa carrier sits clear of the SDR's DC spike:

```
# capture ~9 s at 1.024 Msps, centered 250 kHz above a 920.0 MHz signal
rtl_sdr -f 920250000 -s 1024000 -g 0 -n 9216000 cap.bin
```

Use a low gain (`-g 0`) for a co-located transmitter (strong) and a higher
gain (`-g 40`) for a distant one.

## specgram.py

Render a magnitude spectrogram PNG from a capture — shows burst timing,
center frequency, and occupied bandwidth.

```
python3 specgram.py cap.bin out.png <samp_rate> <center_hz> [title] \
    [start_ms] [dur_ms] [nperseg]
```

## loradecode.py

Dechirp the capture and FFT each symbol. A valid LoRa frame shows a flat
preamble plateau (constant FFT bin), the sync-word step, the SFD
down-chirps, then scattered data symbols. Prints the per-symbol bins and
writes a dechirped heatmap.

```
python3 loradecode.py cap.bin out.png <center_hz> <sig_hz> <samp_rate> \
    <sf> <bw> [osf] [start_ms] [dur_ms]
```

Window `start_ms`/`dur_ms` to begin just before a burst so the preamble is
captured. The sync word reads out as `(bin - preamble_bin)/8` per nibble:
a preamble at bin 138 with sync symbols at 146 and 154 is sync word 0x12.
