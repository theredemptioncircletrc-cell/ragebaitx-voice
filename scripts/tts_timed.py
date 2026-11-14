"""Reads a timed commentary script so every line lands on the moment it talks about.

Each line is spoken separately (ElevenLabs cloned voice if available, else free Kokoro),
then placed on a timeline at its own time. If a line runs long, the next one waits
for it; if the whole thing would overrun the clip, it is sped up a little at the end.

usage: python tts_timed.py LINES_JSON CLIP_SECONDS OUT_WAV OUT_ASS ENGINE VOICE [START_OFFSET]
  LINES_JSON: file with [{"t": seconds into the clip, "say": "words"}, ...]
  ENGINE: eleven | kokoro
writes OUT_WAV (24 kHz mono), OUT_ASS captions, prints a short timing report
"""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf

from tts import SR, write_ass

MIN_GAP = 0.12


def to_array(path):
    raw = subprocess.check_output(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", path,
                                   "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"])
    return np.frombuffer(raw, dtype=np.float32).copy()


def speak_eleven(text, voice_id, tmp, n):
    from tts_eleven import call, words_from_alignment
    model = os.environ.get("ELEVEN_MODEL") or "eleven_v3"
    stability = float(os.environ.get("ELEVEN_STABILITY") or 0.5)
    try:
        res = call(voice_id, text, model, stability)
    except Exception as e:  # noqa: BLE001 - fall back to the older model without tags
        print(f"  {model} failed on line {n}: {e}; retrying without tags")
        text = re.sub(r"\[[^\]]*\]", "", text).strip()
        res = call(voice_id, text, "eleven_multilingual_v2", 0.4)
    mp3 = os.path.join(tmp, f"l{n}.mp3")
    with open(mp3, "wb") as f:
        f.write(base64.b64decode(res["audio_base64"]))
    audio = to_array(mp3)
    words = words_from_alignment(res.get("normalized_alignment") or res.get("alignment") or {})
    return audio, words


_PIPE = None


def speak_kokoro(text, voice, speed):
    global _PIPE
    from tts import speak
    if _PIPE is None:
        from kokoro import KPipeline
        _PIPE = KPipeline(lang_code="a")
    text = re.sub(r"\[[^\]]*\]", "", text).strip()
    audio, words = speak(_PIPE, [text], voice, speed)
    return audio.astype(np.float32), words


def trim_silence(audio, words):
    """Cuts leading/trailing near-silence so lines can sit right on their moment."""
    if not len(audio):
        return audio, words
    loud = np.where(np.abs(audio) > 0.01)[0]
    if not len(loud):
        return audio, words
    a = max(0, loud[0] - int(0.03 * SR))
    b = min(len(audio), loud[-1] + int(0.08 * SR))
    shift = a / SR
    return audio[a:b], [(w, s - shift, e - shift) for w, s, e in words]


def main():
    lines_path, clip_s, out_wav, out_ass, engine, voice = sys.argv[1:7]
    clip_s = float(clip_s)
    offset = float(sys.argv[7]) if len(sys.argv) > 7 else 0.15
    lines = [l for l in json.load(open(lines_path)) if str(l.get("say", "")).strip()]
    if not lines:
        sys.exit("No timed lines")
    speed = float(os.environ.get("TTS_SPEED") or 1.05)
    tmp = tempfile.mkdtemp()

    pieces = []
    for n, l in enumerate(lines):
        text = str(l["say"]).strip()
        if engine == "eleven":
            audio, words = speak_eleven(text, voice, tmp, n)
        else:
            audio, words = speak_kokoro(text, voice, speed)
        audio, words = trim_silence(audio, words)
        pieces.append((max(0.0, float(l.get("t", 0))), audio, words, text))

    # Place each line at its moment; a line that is still talking pushes the next one back.
    placed, cursor = [], offset
    for want, audio, words, text in pieces:
        at = max(want + offset, cursor)
        placed.append((at, audio, words))
        cursor = at + len(audio) / SR + MIN_GAP
    end = cursor - MIN_GAP
    room = max(2.0, clip_s - 0.25)
    tempo = 1.0
    if end > room:
        # Squeeze: everything is played a little faster, so the last line still fits.
        tempo = min(1.3, end / room * 1.01)
        print(f"Lines ran to {end:.1f}s for a {clip_s:.1f}s clip, speeding up x{tempo:.2f}")

    total = int((clip_s + 1) * SR)
    track = np.zeros(total, dtype=np.float32)
    all_words = []
    for (at, audio, words), (want, *_rest) in zip(placed, pieces):
        start = at / tempo
        a = audio
        if tempo != 1.0:
            p_in, p_out = os.path.join(tmp, "s_in.wav"), os.path.join(tmp, "s_out.wav")
            sf.write(p_in, a, SR)
            subprocess.check_call(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", p_in,
                                   "-af", f"atempo={tempo:.3f}", "-ar", str(SR), p_out])
            a = sf.read(p_out, dtype="float32")[0]
            words = [(w, s / tempo, e / tempo) for w, s, e in words]
        i0 = int(start * SR)
        i1 = min(total, i0 + len(a))
        if i1 > i0:
            track[i0:i1] += a[: i1 - i0]
        late = start - want
        print(f"  line at {want:5.1f}s -> plays {start:5.1f}s ({'+' if late >= 0 else ''}{late:.1f}s)")
        all_words += [(w, start + s, start + e) for w, s, e in words]
    peak = float(np.max(np.abs(track))) or 1.0
    track = track / max(1.0, peak / 0.95)
    sf.write(out_wav, track, SR)
    # Captions use absolute times already, so no extra offset.
    write_ass([w for w in all_words if w[1] < clip_s], out_ass, 0.0)
    print(f"Timed speech: {len(pieces)} lines, {len(all_words)} words, ends {min(end, room) / 1:.1f}s, clip {clip_s:.1f}s")


if __name__ == "__main__":
    main()
