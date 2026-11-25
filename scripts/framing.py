"""Smarter vertical framing for landscape clips + scene-change detection (Clip Polisher).

  python framing.py IN.mp4 FOCUS_JSON MAX_RIGHT OUT_FOCUS.json OUT_CUTS.json

- Finds where the real picture is in every moment. Games often show a photo / selfie / menu as a box in the
  middle with blurred or black sides; the crop must stay inside that box, never on the blurred sides.
- Follows the AI's focus points, clamped to the real picture, smoothed so the camera glides.
- Finds scene changes (phone comes out, camera switches, menu opens) for the transition effects.
Writes OUT_FOCUS as [[seconds, x 0..1], ...] (dense, ready for cropexpr.py) and OUT_CUTS as [seconds, ...].
"""
import json
import subprocess
import sys

import numpy as np

SW, SH, FPS = 320, 180, 4


def frames(src):
    p = subprocess.Popen(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", src, "-vf",
                          f"fps={FPS},scale={SW}:{SH},format=gray", "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    out = []
    while True:
        b = p.stdout.read(SW * SH)
        if len(b) < SW * SH:
            break
        out.append(np.frombuffer(b, np.uint8).reshape(SH, SW).astype(np.float32))
    p.wait()
    return out


def side_margin(f):
    """Width (in small-frame columns) of blurred / flat bars on BOTH sides, or 0."""
    e = np.abs(np.diff(f, axis=1))
    e = np.pad(e, ((0, 0), (0, 1)))
    e = e + np.pad(np.abs(np.diff(f, axis=0)), ((0, 1), (0, 0)))
    col = e[10:-10].mean(axis=0)  # skip top/bottom rows (HUD text)
    def edge(c):
        # first column (from this side) where the real picture starts after a flat run of >= 16 columns
        for i in range(16, SW // 2 - 20):
            if c[i] > 2.5 and c[i + 1] > 2.5 and c[i + 2] > 2.5:
                return i if np.median(c[2:i]) < 1.2 and np.percentile(c[2:i], 80) < 2.0 else 0
        return 0
    ml, mr = edge(col), edge(col[::-1])
    if ml and mr:
        return min(ml, mr)
    m = ml or mr
    if m:
        other = col[SW - m + 2:SW - 2] if ml else col[2:m - 2]
        if np.percentile(other, 30) < 1.2:  # the other side is mostly flat too (a menu may sit on it)
            return m
    return 0


def main():
    src, focus_json, max_right, out_focus, out_cuts = sys.argv[1:6]
    info = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                    "stream=width,height", "-of", "csv=p=0", src]).decode().strip().split(",")
    iw, ih = int(info[0]), int(info[1])
    cw = int(ih * 9 / 16) // 2 * 2
    mr = int(float(max_right)) if max_right else iw
    fr = frames(src)
    n = len(fr)
    if n == 0:
        json.dump([], open(out_focus, "w")); json.dump([], open(out_cuts, "w")); return
    ts = np.arange(n) / FPS

    # Real-picture bounds over time (median over ~2 s so it does not flicker).
    m = np.array([side_margin(f) for f in fr], dtype=float)
    k = 4
    m = np.array([np.median(m[max(0, i - k):i + k + 1]) for i in range(n)])
    left = m / SW * iw
    right = np.minimum(iw - left, mr)

    # The AI's focus points (fraction of width) -> pixels, interpolated to every sample.
    pts = sorted((float(t), float(x)) for t, x in json.loads(focus_json or "[]") if 0 <= float(x) <= 1) or [(0.0, 0.5)]
    want = np.interp(ts, [p[0] for p in pts], [p[1] * iw for p in pts])

    def clamp(c):
        lo, hi = left + cw / 2, right - cw / 2
        mid = (left + right) / 2
        return np.where(hi < lo, mid, np.clip(c, lo, hi))

    c = clamp(want)
    w = 7  # ~1.75 s moving average: the camera glides instead of jumping
    c = np.convolve(np.pad(c, (w // 2, w // 2), mode="edge"), np.ones(w) / w, mode="valid")
    c = clamp(c)
    step = 2  # one point every 0.5 s
    dense = [[round(float(ts[i]), 2), round(float(c[i] / iw), 4)] for i in range(0, n, step)]
    json.dump(dense, open(out_focus, "w"))

    # Scene changes: a big jump between frames compared to the moments around it.
    d = np.array([0.0] + [float(np.abs(fr[i] - fr[i - 1]).mean()) for i in range(1, n)])
    cuts, last = [], -9.0
    for i in range(1, n):
        local = np.median(d[max(1, i - 8):i + 9])
        t = ts[i]
        if d[i] > 22 and d[i] > 3 * local and 0.6 < t < ts[-1] - 1.2 and t - last >= 3.0:
            cuts.append(round(float(t) - 0.12, 2)); last = t
    json.dump(cuts[:5], open(out_cuts, "w"))
    pill = sorted(set(int(x) for x in m if x > 0))
    print(f"Framing: {n} samples, blurred-side boxes found in {int((m > 0).sum())} of them {pill[:3]}, scene changes at {cuts[:5]}")


if __name__ == "__main__":
    main()
