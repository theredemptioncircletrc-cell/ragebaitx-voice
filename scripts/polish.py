"""Helpers for the Clip Polisher (your own clipped Shorts, no AI voice).

  python polish.py scan IN.mp4 OUT_DIR          -> OUT_DIR/grid.jpg (5x4 frames stamped with seconds) and
                                                    OUT_DIR/scan.json {duration, width, height, vertical, words, text}
  python polish.py ass PAYLOAD.json SCAN.json DUR OUTRO OUT.ass
                                                 -> captions (from the transcript), hook at the top, end question
"""
import json
import os
import subprocess
import sys

W, H = 1080, 1920


def probe(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                   "stream=width,height:format=duration", "-of", "json", path])
    j = json.loads(out)
    st = j["streams"][0]
    return float(j["format"]["duration"]), int(st["width"]), int(st["height"])


def scan(src, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    dur, w, h = probe(src)
    vertical = h > w
    tw = 216 if vertical else 384
    step = dur / 20
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    vf = (f"fps=1/{step:.4f},scale={tw}:-2,"
          f"drawtext=fontfile={font}:text='%{{eif\\:n*{step:.4f}\\:d}}s':x=6:y=6:fontsize=22:fontcolor=yellow:box=1:boxcolor=black@0.6,"
          "tile=5x4")
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-vf", vf,
                    "-frames:v", "1", "-q:v", "5", os.path.join(out_dir, "grid.jpg")], check=True)
    words, text = [], ""
    try:
        wav = os.path.join(out_dir, "a.wav")
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", wav], check=True)
        from faster_whisper import WhisperModel
        model = WhisperModel("small", device="cpu", compute_type="int8")
        segs, _ = model.transcribe(wav, word_timestamps=True, vad_filter=True)
        parts = []
        for s in segs:
            parts.append(s.text.strip())
            for wd in (s.words or []):
                if wd.word.strip():
                    words.append([wd.word.strip(), round(wd.start, 2), round(wd.end, 2)])
        text = " ".join(parts)
    except Exception as e:  # noqa: BLE001 - captions are a bonus; never fail the clip for them
        print(f"Transcript skipped: {e}")
    json.dump({"duration": round(dur, 2), "width": w, "height": h, "vertical": vertical, "words": words, "text": text},
              open(os.path.join(out_dir, "scan.json"), "w"))
    print(f"Scanned: {dur:.1f}s {w}x{h}, {len(words)} words")


def ts(x):
    x = max(0.0, x)
    return f"{int(x // 3600)}:{int(x % 3600 // 60):02d}:{x % 60:05.2f}"


def esc(t):
    return str(t).replace("\\", "").replace("{", "").replace("}", "").replace("\n", " ").strip()


def build_ass(payload_path, scan_path, dur, outro, out):
    p = json.load(open(payload_path))
    sc = json.load(open(scan_path)) if os.path.exists(scan_path) else {}
    dur, outro = float(dur), float(outro)
    ev = []
    # Captions: 1-3 words at a time, the current word in yellow, in the lower third.
    if p.get("captions", True):
        words = [w for w in sc.get("words", []) if w[1] < dur]
        groups, cur = [], []
        for w in words:
            if cur and (len(cur) >= 3 or w[1] - cur[-1][2] > 0.6):
                groups.append(cur); cur = []
            cur.append(w)
        if cur:
            groups.append(cur)
        for g in groups:
            for k, w in enumerate(g):
                end = g[k + 1][1] if k + 1 < len(g) else min(w[2] + 0.25, dur)
                line = " ".join(("{\\c&H0000E5FF&}" + esc(x[0]).upper() + "{\\c&HFFFFFF&}") if j == k else esc(x[0]).upper()
                                for j, x in enumerate(g))
                ev.append(f"Dialogue: 1,{ts(w[1])},{ts(max(end, w[1] + 0.12))},Cap,,0,0,0,,{line}")
    hook = esc(p.get("hook_text", "")).upper()[:60]
    if hook:
        ev.append(f"Dialogue: 2,{ts(0)},{ts(dur)},Hook,,0,0,0,,{{\\fscx40\\fscy40\\t(80,260,\\fscx114\\fscy114)\\t(260,360,\\fscx100\\fscy100)}}{hook}")
    q = esc(p.get("outro_text", "")).upper()[:60]
    if q and outro > 0:
        # A question gets "COMMENT BELOW" under it; a fact / statement stands on its own.
        tail = "\\N{\\fs42\\c&HFFFFFF&}COMMENT BELOW" if q.endswith("?") else ""
        ev.append(f"Dialogue: 3,{ts(dur)},{ts(dur + outro)},Outro,,0,0,0,,{{\\fscx30\\fscy30\\t(0,200,\\fscx110\\fscy110)\\t(200,300,\\fscx100\\fscy100)\\c&H0000E5FF&}}{q}{tail}")
    open(out, "w").write(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,DejaVu Sans,60,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,2,70,70,470,1
Style: Hook,DejaVu Sans,48,&H0000E5FF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,6,2,8,70,70,190,1
Style: Outro,DejaVu Sans,58,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,8,4,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(ev) + "\n")
    print(f"Overlay: {len(ev)} lines (captions {'on' if p.get('captions', True) else 'off'})")


if __name__ == "__main__":
    if sys.argv[1] == "scan":
        scan(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "ass":
        build_ass(*sys.argv[2:7])
