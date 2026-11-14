"""Reads a commentary script with Kokoro (free, runs on CPU) and writes:
  - the speech as a WAV file, sped up a little if needed so it fits the clip
  - an .ass caption file with 1-3 words on screen at a time, timed to the speech

usage: python tts.py SCRIPT_TXT CLIP_SECONDS OUT_WAV OUT_ASS [VOICE] [START_OFFSET]
"""
import os
import re
import sys

import numpy as np
import soundfile as sf

SR = 24000
GAP = 0.12  # pause between sentences, in seconds


def speak(pipe, lines, voice, speed):
    """Returns (audio, words) where words = [(text, start, end), ...] in seconds."""
    chunks, words, t = [], [], 0.0
    for line in lines:
        for res in pipe(line, voice=voice, speed=speed, split_pattern=None):
            audio = res.audio.detach().cpu().numpy() if hasattr(res.audio, "detach") else np.asarray(res.audio)
            seg = len(audio) / SR
            toks = [tk for tk in (getattr(res, "tokens", None) or []) if re.search(r"\w", tk.text or "")]
            timed = [tk for tk in toks if getattr(tk, "start_ts", None) is not None and getattr(tk, "end_ts", None) is not None]
            if toks and len(timed) == len(toks):
                for tk in toks:
                    words.append((tk.text, t + float(tk.start_ts), t + float(tk.end_ts)))
            else:
                # No word timings from this Kokoro version: spread the words evenly over the sentence.
                ws = re.findall(r"[\w'’-]+[.,!?]*", res.graphemes or line)
                for i, w in enumerate(ws):
                    words.append((w, t + seg * i / max(1, len(ws)), t + seg * (i + 1) / max(1, len(ws))))
            chunks.append(audio)
            t += seg
        chunks.append(np.zeros(int(GAP * SR), dtype=np.float32))
        t += GAP
    audio = np.concatenate(chunks) if chunks else np.zeros(SR, dtype=np.float32)
    return audio, words


def ass_time(s):
    s = max(0.0, s)
    h = int(s // 3600)
    m = int(s % 3600 // 60)
    return f"{h}:{m:02d}:{s % 60:05.2f}"


def write_ass(words, path, offset):
    groups, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= 3 or re.search(r"[.,!?]$", w[0]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    lines = []
    for i, g in enumerate(groups):
        start = g[0][1] + offset
        end = (groups[i + 1][0][1] + offset) if i + 1 < len(groups) else g[-1][2] + offset + 0.3
        text = " ".join(re.sub(r"[{}\\]", "", w[0]) for w in g).upper()
        text = re.sub(r"[.,]+$", "", text)
        # Pop in with a little bounce; shouted/question moments go yellow.
        fx = r"{\fscx72\fscy72\t(0,90,\fscx112\fscy112)\t(90,170,\fscx100\fscy100)"
        if re.search(r"[!?]", text) or i == 0:
            fx += r"\c&H0000E5FF&"
        fx += "}"
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Cap,,0,0,0,,{fx}{text}")
    head = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,DejaVu Sans,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,3,2,70,70,560,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(lines) + "\n")


def main():
    script_path, clip_s, out_wav, out_ass = sys.argv[1], float(sys.argv[2]), sys.argv[3], sys.argv[4]
    voice = sys.argv[5] if len(sys.argv) > 5 else "am_michael"
    offset = float(sys.argv[6]) if len(sys.argv) > 6 else 0.3
    text = open(script_path, encoding="utf-8").read().strip()
    lines = [ln.strip() for ln in re.split(r"\n+|(?<=[.!?])\s+", text) if ln.strip()]
    if not lines:
        sys.exit("Empty script")

    from kokoro import KPipeline  # imported here so write_ass can be reused without Kokoro
    pipe = KPipeline(lang_code="a")
    room = max(2.0, clip_s - offset - 0.3)
    speed = float(os.environ.get("TTS_SPEED") or 1.05)
    audio, words = speak(pipe, lines, voice, speed)
    length = len(audio) / SR
    if length > room:
        speed = min(1.35, speed * length / room * 1.02)
        print(f"Speech was {length:.1f}s for a {clip_s:.1f}s clip, re-reading at speed {speed:.2f}")
        audio, words = speak(pipe, lines, voice, speed)
        length = len(audio) / SR
    print(f"Speech: {length:.1f}s, {len(words)} words, clip {clip_s:.1f}s")
    sf.write(out_wav, audio.astype(np.float32), SR)
    write_ass([w for w in words if w[1] < clip_s], out_ass, offset)


if __name__ == "__main__":
    main()
