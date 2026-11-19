"""Finds the stretches of a gameplay video where (radio) music is playing.

usage: python radio_detect.py IN_MEDIA OUT_JSON
writes OUT_JSON: {"radio": [[start, end], ...], "radio_seconds": N, "duration": D}

How: music has a steady beat in the low end (kick + bass) that repeats every 0.3 to 1 second
(60-200 BPM). Game sounds (engines, guns, crashes) and talking do not. Every 2 seconds it looks at
the last 8 seconds of the bass band and measures how strongly it repeats at a musical tempo.
Free, fast (a 45-minute video takes well under a minute), no song database needed.
"""
import json
import subprocess
import sys

import numpy as np

SR = 2000          # plenty for the bass band
HOP = 0.02         # 20 ms envelope frames
WIN, STEP = 8.0, 2.0


def bass_envelope(path):
    raw = subprocess.check_output(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", path, "-vn",
                                   "-af", "lowpass=f=170,highpass=f=35", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"])
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    n = int(SR * HOP)
    frames = len(x) // n
    if frames < 10:
        return np.zeros(0), np.zeros(0)
    rms = np.sqrt(np.mean(x[: frames * n].reshape(frames, n) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    onset = np.maximum(0.0, np.diff(np.log(rms + 1e-6), prepend=np.log(rms[0] + 1e-6)))
    return onset, db


def beat_strength(onset, db):
    w, s = int(WIN / HOP), int(STEP / HOP)
    lo, hi = int(0.3 / HOP), int(1.0 / HOP)
    out = []
    for i in range(0, max(1, len(onset) - w + 1), s):
        seg = onset[i:i + w] - onset[i:i + w].mean()
        level = float(np.median(db[i:i + w]))
        den = float(np.dot(seg, seg))
        if den <= 1e-9 or level < -50:
            out.append((i * HOP, 0.0, level)); continue
        ac = np.correlate(seg, seg, mode="full")[len(seg) - 1:] / den
        lag = lo + int(np.argmax(ac[lo:hi]))
        peak = float(ac[lag])
        # A real beat also repeats at twice the period.
        twice = float(ac[min(len(ac) - 1, 2 * lag)]) if 2 * lag < len(ac) else 0.0
        out.append((i * HOP, 0.6 * peak + 0.4 * max(0.0, twice), level))
    return out


def main():
    src, dest = sys.argv[1:3]
    onset, db = bass_envelope(src)
    dur = len(onset) * HOP
    scores = beat_strength(onset, db) if len(onset) else []
    on = [(t, sc >= 0.32) for t, sc, _ in scores]
    spans, start = [], None
    for t, v in on:
        if v and start is None:
            start = t
        if not v and start is not None:
            spans.append([start, t + WIN * 0.5]); start = None
    if start is not None:
        spans.append([start, dur])
    merged = []
    for a, b in spans:
        if merged and a - merged[-1][1] < 6:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    radio = [[round(a, 1), round(min(b, dur), 1)] for a, b in merged if b - a >= 10]
    total = sum(b - a for a, b in radio)
    json.dump({"radio": radio, "radio_seconds": round(total), "duration": round(dur, 1)}, open(dest, "w"))
    print(f"Radio/music found in {len(radio)} stretches, {total / 60:.1f} of {dur / 60:.1f} min")


if __name__ == "__main__":
    main()
