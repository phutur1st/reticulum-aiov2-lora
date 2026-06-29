#!/usr/bin/env python3
"""Minimal LoRa analyzer for an rtl_sdr uint8 IQ capture.

Frequency-shifts the LoRa signal to baseband, resamples to BW*OSF, then
dechirps each symbol-length block and FFTs it. A valid LoRa frame shows a
flat preamble plateau (constant FFT bin), then the SFD down-chirps, then
scattered data symbols. Produces a heatmap of dechirped FFT magnitude
(symbol index vs bin) and prints preamble statistics.

    python3 loradecode.py <iq.bin> <out.png> <center_hz> <sig_hz> \
        <samp_rate> <sf> <bw> [osf] [start_ms] [dur_ms]
"""
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import signal

binf = sys.argv[1]
outf = sys.argv[2]
center = float(sys.argv[3])
sig = float(sys.argv[4])
sr0 = float(sys.argv[5])
sf = int(sys.argv[6])
bw = float(sys.argv[7])
osf = int(sys.argv[8]) if len(sys.argv) > 8 else 4
start_ms = float(sys.argv[9]) if len(sys.argv) > 9 else None
dur_ms = float(sys.argv[10]) if len(sys.argv) > 10 else None

N = 1 << sf
sps = N * osf
fs = bw * osf

# --- load IQ ---
raw = np.fromfile(binf, dtype=np.uint8).astype(np.float32)
raw = (raw - 127.5) / 127.5
iq = raw[0::2] + 1j * raw[1::2]
if start_ms is not None:
    a = int(start_ms / 1000 * sr0)
    b = int((start_ms + (dur_ms or 300)) / 1000 * sr0)
    iq = iq[a:b]

# --- shift signal to DC ---
offset = sig - center                      # signal offset from capture center
n = np.arange(len(iq))
iq = iq * np.exp(-1j * 2 * np.pi * offset / sr0 * n)

# --- resample to fs = bw*osf ---
from math import gcd
g = gcd(int(fs), int(sr0))
up, down = int(fs) // g, int(sr0) // g
x = signal.resample_poly(iq, up, down)

# --- base chirps ---
k = np.arange(sps)
t = k / fs
phase = 2 * np.pi * (-bw / 2 * t + bw / (2 * (sps / fs)) * t * t)
upchirp = np.exp(1j * phase)
downchirp = np.conj(upchirp)

# --- find burst by energy ---
pwr = np.abs(x) ** 2
win = np.ones(sps) / sps
env = np.convolve(pwr, win, mode="same")
thr = 0.15 * env.max()
above = np.where(env > thr)[0]
if len(above) == 0:
    print("NO BURST FOUND")
    sys.exit(1)
b0, b1 = above[0], above[-1]
print(f"burst samples {b0}..{b1}  ({(b1-b0)/fs*1000:.1f} ms)  "
      f"snr_env={10*np.log10(env.max()/np.median(env)):.1f} dB")

# step from a bit before burst start, aligned to sps
start = max(0, b0 - sps)
nsym = (b1 - start) // sps + 2
folded = np.zeros((nsym, N))
peakbin = np.zeros(nsym, int)
sharp = np.zeros(nsym)
for i in range(nsym):
    s = start + i * sps
    blk = x[s:s + sps]
    if len(blk) < sps:
        break
    d = blk * downchirp
    X = np.abs(np.fft.fft(d))
    fold = X.reshape(osf, N).sum(axis=0) if X.size == sps else X[:N]
    folded[i] = fold
    peakbin[i] = int(np.argmax(fold))
    sharp[i] = fold.max() / (np.median(fold) + 1e-9)

# preamble = leading run of consistent peak bins with good sharpness
good = sharp > 5
print("first 24 symbols: bin(sharp)")
print("  " + " ".join(f"{peakbin[i]}({sharp[i]:.0f})" for i in range(min(24, nsym))))
# consistency of first several strong symbols
strong = [i for i in range(min(20, nsym)) if sharp[i] > 5]
if strong:
    bins = peakbin[strong[:8]]
    print(f"preamble candidate bins (first strong): {list(bins)}  "
          f"std={np.std(bins):.2f}  mean_sharp={np.mean(sharp[strong[:8]]):.0f}")

# --- heatmap ---
plt.figure(figsize=(13, 5))
plt.imshow(20 * np.log10(folded.T + 1e-6), aspect="auto", origin="lower",
           cmap="magma", interpolation="nearest")
plt.xlabel("symbol index")
plt.ylabel("dechirped FFT bin")
plt.title(f"{binf}  SF{sf} BW{int(bw/1000)} osf{osf}")
plt.colorbar(label="dB")
plt.tight_layout()
plt.savefig(outf, dpi=90)
print("wrote", outf)
