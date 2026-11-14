"""Subtitles + chapter cards for long (16:9) videos.

usage: python long_subs.py WORDS_JSON PAYLOAD_JSON_FILE OUT_ASS OUT_SRT SRT_OFFSET
  WORDS_JSON : [[word, start, end], ...] in main-video seconds (from tts_timed.py)
  PAYLOAD    : the render payload (uses meta.chapters for the chapter cards)
  OUT_ASS    : burned in on the main video (times relative to the main video)
  OUT_SRT    : for YouTube closed captions (times shifted by SRT_OFFSET = intro length)
"""
import json
import re
import sys


def t_ass(s):
    s = max(0.0, s)
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"


def t_srt(s):
    s = max(0.0, s)
    ms = int(round(s * 1000))
    return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"


def lines_from_words(words, max_words=7, max_chars=42):
    out, cur = [], []
    for i, (w, a, b) in enumerate(words):
        gap = cur and a - cur[-1][2] > 0.7
        if cur and (gap or len(cur) >= max_words or len(" ".join(x[0] for x in cur + [(w, a, b)])) > max_chars):
            out.append(cur)
            cur = []
        cur.append((w, a, b))
        if re.search(r"[.!?]$", w):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    res = []
    for i, g in enumerate(out):
        start = g[0][1]
        end = max(g[-1][2] + 0.25, start + 0.8)
        if i + 1 < len(out):
            end = min(end, out[i + 1][0][1] - 0.02)
        text = " ".join(x[0] for x in g)
        res.append((start, max(end, start + 0.3), text))
    return res


def main():
    words = [(str(w), float(a), float(b)) for w, a, b in json.load(open(sys.argv[1]))]
    payload = json.load(open(sys.argv[2]))
    out_ass, out_srt, off = sys.argv[3], sys.argv[4], float(sys.argv[5])
    subs = lines_from_words(words)
    chapters = (payload.get("meta") or {}).get("chapters") or []

    head = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,DejaVu Sans,50,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,160,160,70,1
Style: Chap,DejaVu Sans,40,&H0000E5FF,&H00FFFFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,1,0,3,14,0,7,70,70,60,1
Style: ChapTitle,DejaVu Sans,58,&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,3,14,0,7,70,70,118,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    for a, b, text in subs:
        clean = re.sub(r"[{}\\]", "", text)
        ev.append(f"Dialogue: 0,{t_ass(a)},{t_ass(b)},Sub,,0,0,0,,{clean}")
    for n, c in enumerate(chapters, start=1):
        t = max(0.4, float(c.get("t", 0)))
        title = re.sub(r"[{}\\]", "", str(c.get("title", ""))).upper()[:40]
        if not title:
            continue
        fx = r"{\fad(250,400)\move(-300,%d,70,%d,0,350)}"
        ev.append(f"Dialogue: 1,{t_ass(t)},{t_ass(t + 4.2)},Chap,,0,0,0,,{fx % (60, 60)}CHAPTER {n}")
        ev.append(f"Dialogue: 1,{t_ass(t + 0.15)},{t_ass(t + 4.2)},ChapTitle,,0,0,0,,{fx % (118, 118)}{title}")
    with open(out_ass, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(ev) + "\n")
    with open(out_srt, "w", encoding="utf-8") as f:
        for i, (a, b, text) in enumerate(subs, start=1):
            f.write(f"{i}\n{t_srt(a + off)} --> {t_srt(b + off)}\n{text}\n\n")
    print(f"{len(subs)} subtitle lines, {len(chapters)} chapter cards")


if __name__ == "__main__":
    main()
