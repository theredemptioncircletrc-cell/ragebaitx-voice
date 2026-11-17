"""Voices each line on its own and reports how long it takes, so the video can be timed to the voice.

usage: python tts_lines.py TEXTS_JSON OUT_DIR ENGINE VOICE
  TEXTS_JSON: {"key": "words to say", ...}   (empty strings are skipped)
writes OUT_DIR/<key>.wav (24 kHz mono, silence trimmed) and OUT_DIR/lines.json:
  {"key": {"wav": path, "dur": seconds, "words": [[word, start, end], ...]}, ...}
"""
import json
import os
import sys
import tempfile

import soundfile as sf

from tts import SR
from tts_timed import speak_eleven, speak_kokoro, trim_silence


def main():
    texts_path, out_dir, engine, voice = sys.argv[1:5]
    os.makedirs(out_dir, exist_ok=True)
    texts = json.load(open(texts_path))
    tmp = tempfile.mkdtemp()
    speed = float(os.environ.get("TTS_SPEED") or 1.05)
    out = {}
    for n, (key, text) in enumerate(texts.items()):
        text = str(text or "").strip()
        if not text:
            continue
        try:
            if engine == "eleven":
                audio, words = speak_eleven(text, voice, tmp, n)
            else:
                audio, words = speak_kokoro(text, voice, speed)
        except Exception as e:  # noqa: BLE001 - one bad line should not sink the video
            print(f"  {key}: {engine} failed ({e}), using Kokoro")
            audio, words = speak_kokoro(text, "am_puck", speed)
        audio, words = trim_silence(audio, words)
        path = os.path.join(out_dir, f"{key}.wav")
        sf.write(path, audio, SR)
        out[key] = {"wav": path, "dur": round(len(audio) / SR, 3), "words": [[w, round(a, 3), round(b, 3)] for w, a, b in words]}
        print(f"  {key}: {out[key]['dur']:.1f}s  {text[:60]}")
    json.dump(out, open(os.path.join(out_dir, "lines.json"), "w"))


if __name__ == "__main__":
    main()
