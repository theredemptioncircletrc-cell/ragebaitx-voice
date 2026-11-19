"""Swap the music out of a gameplay/stream sound track, keep the talking and the game effects.

usage: python audio_swap.py IN_WAV OUT_DIR DEMUCS_PY [LINES_JSON]
  1. Demucs (4 stems) splits the sound into vocals / drums / bass / other.
  2. OUT_DIR/game_nomusic.wav = vocals + other  (talking + most game effects; the beat and bass of
     the music are gone, a little melody can remain)
     OUT_DIR/vocals.wav       = only the talking (used so your song and the AI voice duck under you)
  3. OUT_DIR/speech.json      = [[start, end], ...] when someone is talking (mic / mates / dialogue)
  4. If LINES_JSON is given, AI voice lines that would talk over you are removed from it (in place),
     so the AI only fills the quiet gaps.
exit code 0 and the files above on success; non-zero if the split failed (caller keeps the original).
"""
import json
import os
import shutil
import subprocess
import sys

import numpy as np

SR = 8000
STEP = 0.1


def ff(*a):
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *a], check=True)


def speech_intervals(vocals):
    raw = subprocess.check_output(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", vocals,
                                   "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"])
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    n = int(SR * STEP)
    frames = len(x) // n
    if frames == 0:
        return []
    rms = np.sqrt(np.mean(x[: frames * n].reshape(frames, n) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    loud = db[db > -60]
    thr = max(-38.0, float(np.percentile(loud, 30)) if len(loud) else -38.0)
    on = db > thr
    out, start = [], None
    for i, v in enumerate(on):
        t = i * STEP
        if v and start is None:
            start = t
        if not v and start is not None:
            out.append([start, t]); start = None
    if start is not None:
        out.append([start, frames * STEP])
    merged = []
    for a, b in out:
        if merged and a - merged[-1][1] < 0.45:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [[round(a, 2), round(b, 2)] for a, b in merged if b - a >= 0.35]


def filter_lines(path, speech):
    lines = json.load(open(path))
    kept = []
    for i, l in enumerate(lines):
        words = len(str(l.get("say", "")).replace("[", " [").split())
        t0 = float(l.get("t", 0))
        t1 = t0 + 0.42 * words + 0.3
        over = sum(max(0.0, min(t1, b) - max(t0, a)) for a, b in speech)
        last = i == len(lines) - 1
        if over / max(0.1, t1 - t0) <= 0.3 or (last and over / max(0.1, t1 - t0) <= 0.6):
            kept.append(l)
    json.dump(kept, open(path, "w"))
    print(f"AI lines: kept {len(kept)} of {len(lines)} (the rest would have talked over you)")


def main():
    src, out, demucs = sys.argv[1:4]
    lines = sys.argv[4] if len(sys.argv) > 4 else ""
    os.makedirs(out, exist_ok=True)
    sep = os.path.join(out, "sep")
    subprocess.run([demucs, "-m", "demucs", "-n", "htdemucs", "-d", "cpu", "-o", sep, src], check=True)
    name = os.path.splitext(os.path.basename(src))[0]
    d = os.path.join(sep, "htdemucs", name)
    voc, oth = os.path.join(d, "vocals.wav"), os.path.join(d, "other.wav")
    if not (os.path.exists(voc) and os.path.exists(oth)):
        sys.exit("Demucs did not produce the stems")
    ff("-i", voc, "-i", oth, "-filter_complex", "[0:a][1:a]amix=inputs=2:normalize=0[a]", "-map", "[a]",
       os.path.join(out, "game_nomusic.wav"))
    shutil.copy(voc, os.path.join(out, "vocals.wav"))
    speech = speech_intervals(voc)
    json.dump(speech, open(os.path.join(out, "speech.json"), "w"))
    total = sum(b - a for a, b in speech)
    print(f"Talking found: {len(speech)} stretches, {total:.0f}s in total")
    if lines and os.path.exists(lines):
        filter_lines(lines, speech)


if __name__ == "__main__":
    main()
