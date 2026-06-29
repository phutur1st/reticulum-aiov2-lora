#!/usr/bin/env python3
"""Render a spectrogram PNG from an rtl_sdr uint8 IQ capture.

    python3 specgram.py <iq.bin> <out.png> <samp_rate_hz> <center_hz> [title]
"""
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import signal

binf, outf, sr, center = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
title = sys.argv[5] if len(sys.argv) > 5 else binf
# optional crop: start_ms dur_ms  and  optional nperseg
start_ms = float(sys.argv[6]) if len(sys.argv) > 6 else None
dur_ms = float(sys.argv[7]) if len(sys.argv) > 7 else None
nperseg = int(sys.argv[8]) if len(sys.argv) > 8 else 256

raw = np.fromfile(binf, dtype=np.uint8).astype(np.float32)
raw = (raw - 127.5) / 127.5
iq = raw[0::2] + 1j * raw[1::2]

t0 = 0.0
if start_ms is not None:
    a = int(start_ms / 1000 * sr)
    b = int((start_ms + (dur_ms or 200)) / 1000 * sr)
    iq = iq[a:b]
    t0 = start_ms

f, t, Sxx = signal.spectrogram(iq, fs=sr, nperseg=nperseg, noverlap=nperseg * 7 // 8,
                               return_onesided=False, scaling="spectrum")
f = np.fft.fftshift(f)
Sxx = np.fft.fftshift(Sxx, axes=0)
Sdb = 10 * np.log10(Sxx + 1e-12)

plt.figure(figsize=(12, 5))
plt.pcolormesh(t * 1000 + t0, (f + center) / 1e6, Sdb, shading="auto",
               vmin=np.percentile(Sdb, 60), vmax=np.percentile(Sdb, 99.9),
               cmap="viridis")
plt.ylabel("MHz")
plt.xlabel("ms")
plt.title(title)
plt.colorbar(label="dB")
plt.tight_layout()
plt.savefig(outf, dpi=90)
print("wrote", outf, "samples", len(iq))
