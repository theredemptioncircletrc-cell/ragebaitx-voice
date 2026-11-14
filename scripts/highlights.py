"""Finds the hype moments in a long gameplay video, without OpusClip.

How it decides: it listens to the whole video and looks for spikes in loudness
compared with the minute around them (crowd roars after a goal, your reactions,
explosions, sirens). Each spike becomes a candidate window that starts well before
the spike (the build-up) and ends shortly after it (the reaction). The AI in n8n
then looks at each window and picks the exact start and end.

usage: python highlights.py IN_VIDEO OUT_DIR MAX_CANDIDATES
writes: OUT_DIR/candidates.json  (list of {id, peak, start, end, score, file})
"""
import bisect
import json

import subprocess

import numpy as np
import sys

STEP = 0.5          # seconds per loudness reading
SR = 8000           # audio sample rate used for scanning (fast, plenty for loudness)
BEFORE = 22.0       # seconds of build-up kept before a spike
AFTER = 12.0        # seconds of reaction kept after a spike
MIN_GAP = 45.0      # two candidates are at least this far apart
EDGE = 10.0         # ignore the first/last seconds (menus, stream start/end)


def loudness(path):
    """dB loudness every STEP seconds, read straight from ffmpeg without loading the whole file."""
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", path,
           "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    per = int(SR * STEP)
    out = []
    while True:
        buf = proc.stdout.read(per * 2 * 600)  # 5 minutes at a time
        if len(buf) < 4:
            break
        a = np.frombuffer(buf[: len(buf) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
        full = len(a) // per
        if full:
            rms = np.sqrt((a[: full * per].reshape(full, per) ** 2).mean(axis=1))
            out.extend((20 * np.log10(rms + 1e-6)).tolist())
        if len(a) % per > per // 4:
            rest = a[full * per:]
            out.append(float(20 * np.log10(np.sqrt((rest ** 2).mean()) + 1e-6)))
    proc.wait()
    return out


def smooth(vals, width):
    half = width // 2
    pref = [0.0]
    for v in vals:
        pref.append(pref[-1] + v)
    res = []
    for i in range(len(vals)):
        a, b = max(0, i - half), min(len(vals), i + half + 1)
        res.append((pref[b] - pref[a]) / (b - a))
    return res


def rolling_median(vals, width):
    half = width // 2
    win, res = [], []
    lo = hi = 0
    for i in range(len(vals)):
        a, b = max(0, i - half), min(len(vals), i + half + 1)
        while hi < b:
            bisect.insort(win, vals[hi]); hi += 1
        while lo < a:
            del win[bisect.bisect_left(win, vals[lo])]; lo += 1
        res.append(win[len(win) // 2])
    return res


def main():
    path, out_dir, max_c = sys.argv[1], sys.argv[2], int(sys.argv[3])
    dur = float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).decode().strip() or 0)
    db = loudness(path)
    if not db:
        sys.exit("No audio found in the video, so there is nothing to listen to for hype moments.")
    short = smooth(db, int(3 / STEP))                # 3 s of sound
    base = rolling_median(short, int(90 / STEP))     # the "normal" level for that part of the video
    # Excitement = how much louder than normal, plus a little credit for being loud at all.
    top = sorted(short)[int(len(short) * 0.95)]
    score = [max(0.0, s - b) + 0.15 * max(0.0, s - (top - 12)) for s, b in zip(short, base)]

    order = sorted(range(len(score)), key=lambda i: score[i], reverse=True)
    # A moment must stand out: at least 2 dB above normal and at least a fifth as strong as the best one.
    floor = max(2.0, 0.2 * score[order[0]]) if order else 2.0
    picked = []
    for i in order:
        t = i * STEP
        if t < EDGE or t > dur - EDGE or score[i] < floor:
            continue
        if any(abs(t - p) < MIN_GAP for p, _ in picked):
            continue
        picked.append((t, score[i]))
        if len(picked) >= max_c:
            break
    if not picked:
        # Very flat audio: fall back to evenly spaced windows so the AI still has something to judge.
        k = max(1, min(max_c, int(dur // 60)))
        picked = [(dur * (j + 1) / (k + 1), 0.1) for j in range(k)]

    cands = []
    for n, (t, s) in enumerate(sorted(picked), start=1):
        start = max(0.0, t - BEFORE)
        end = min(dur, t + AFTER)
        cands.append({"id": f"c{n:02d}", "peak": round(t, 1), "start": round(start, 1), "end": round(end, 1),
                      "length": round(end - start, 1), "score": round(s, 2), "file": f"cand_{n:02d}.mp4"})
    with open(f"{out_dir}/candidates.json", "w") as f:
        json.dump({"duration": round(dur, 1), "candidates": cands}, f, indent=1)
    print(f"Video {dur/60:.1f} min, {len(cands)} hype moments:")
    for c in cands:
        print(f"  {c['id']}  {c['start']//60:.0f}:{c['start']%60:04.1f} -> {c['end']//60:.0f}:{c['end']%60:04.1f}  score {c['score']}")


if __name__ == "__main__":
    main()
