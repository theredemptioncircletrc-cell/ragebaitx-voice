"""Reads a commentary script with ElevenLabs (your cloned voice) and writes:
  - the speech as a WAV file, sped up a little if needed so it fits the clip
  - an .ass caption file with 1-3 words on screen at a time, timed to the speech

The script may contain ElevenLabs v3 audio tags like [excited] or [laughs]; they steer
the performance and are left out of the captions.

usage: python tts_eleven.py SCRIPT_TXT CLIP_SECONDS OUT_WAV OUT_ASS VOICE_ID [START_OFFSET]
env:   ELEVENLABS_API_KEY (required), ELEVEN_MODEL (default eleven_v3), ELEVEN_STABILITY
"""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

from tts import write_ass


def call(voice_id, text, model, stability):
    body = {"text": text, "model_id": model,
            "voice_settings": {"stability": stability, "similarity_boost": 0.8, "use_speaker_boost": True}}
    if model != "eleven_v3":
        body["voice_settings"]["style"] = 0.45
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps?output_format=mp3_44100_128",
        data=json.dumps(body).encode(), method="POST",
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


def words_from_alignment(al):
    """Groups characters into words with start/end times, dropping [audio tags]."""
    chars = al.get("characters") or []
    st = al.get("character_start_times_seconds") or []
    en = al.get("character_end_times_seconds") or []
    words, cur, t0, t1, in_tag = [], "", None, None, False
    for c, a, b in zip(chars, st, en):
        if c == "[":
            in_tag = True
        if in_tag:
            if c == "]":
                in_tag = False
            continue
        if c.isspace():
            if cur.strip():
                words.append((cur.strip(), t0, t1))
            cur, t0 = "", None
            continue
        if t0 is None:
            t0 = a
        cur += c
        t1 = b
    if cur.strip():
        words.append((cur.strip(), t0, t1))
    return [w for w in words if re.search(r"\w", w[0])]


def main():
    script_path, clip_s, out_wav, out_ass, voice_id = sys.argv[1], float(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
    offset = float(sys.argv[6]) if len(sys.argv) > 6 else 0.3
    text = open(script_path, encoding="utf-8").read().strip()
    model = os.environ.get("ELEVEN_MODEL") or "eleven_v3"
    stability = float(os.environ.get("ELEVEN_STABILITY") or 0.5)
    try:
        res = call(voice_id, text, model, stability)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        print(f"ElevenLabs {model} failed ({e.code}): {detail}")
        if model == "eleven_multilingual_v2":
            raise
        # Older model has no audio tags: strip them and try again.
        text = re.sub(r"\[[^\]]*\]", "", text).strip()
        res = call(voice_id, text, "eleven_multilingual_v2", 0.4)
    tmp = tempfile.mkdtemp()
    mp3 = os.path.join(tmp, "eleven.mp3")
    with open(mp3, "wb") as f:
        f.write(base64.b64decode(res["audio_base64"]))
    words = words_from_alignment(res.get("normalized_alignment") or res.get("alignment") or {})
    length = float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp3]).decode().strip() or 0)
    room = max(2.0, clip_s - offset - 0.3)
    tempo = 1.0
    if length > room:
        tempo = min(1.3, length / room * 1.02)
        print(f"Speech was {length:.1f}s for a {clip_s:.1f}s clip, speeding up x{tempo:.2f}")
        words = [(w, a / tempo, b / tempo) for w, a, b in words]
    subprocess.check_call(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", mp3,
                           "-af", f"atempo={tempo:.3f}", "-ar", "44100", "-ac", "1", out_wav])
    print(f"ElevenLabs speech: {length / tempo:.1f}s, {len(words)} words, clip {clip_s:.1f}s")
    write_ass([w for w in words if w[1] < clip_s], out_ass, offset)


if __name__ == "__main__":
    main()
