"""GTA V vs GTA VI style comparison videos from two trailers.

usage:
  python compare.py scan   V_MP4 VI_MP4 OUT_DIR
      4 frame grids per video (6x5 frames, stamped "V 12s" / "VI 12s") + info.json with durations
  python compare.py render V_MP4 VI_MP4 PAYLOAD_JSON OUT_DIR
      builds compare_short.mp4 (1080x1920, V on top, VI below) and/or compare_long.mp4
      (1920x1080, side by side + slider wipes), each with an intro card, a matched pair per
      topic, smooth transitions, an outro question card, the newer trailer's sound underneath,
      optional voice lines (VOICE_WAV + WORDS_JSON env) with captions, and the logo (LOGO env).

PAYLOAD: {"old_name": "GTA V", "old_year": "2013", "new_name": "GTA VI", "new_year": "2026",
          "hook": "13 YEARS OF UPGRADES", "outro_text": "WHICH ONE WINS?",
          "formats": ["short", "long"],
          "pairs": [{"label": "BEACHES", "old": [s, e], "new": [s, e], "style": "split" | "wipe"}]}
"""
import json
import os
import re
import subprocess
import sys

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"
FPS = 30
XT = 0.4                     # transition between pairs
INTRO = 2.6
OUTRO = 3.4
TRANS = ["fade", "smoothleft", "fadeblack", "slideup", "dissolve", "smoothright", "circleopen", "fade"]
PINK = "0xFF3FA4"
GREY = "0x4A4F57"
YEL = "0xFFE500"


def run(cmd):
    subprocess.run(cmd, check=True)


def ff(*args):
    run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args])


def dur(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    return float(out.strip() or 0)


def esc(t):
    """Text for drawtext (inside a filter graph)."""
    return str(t).replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%").replace(",", "\\,")


def text(t, x, y, size, color="white", border=6, box=None, alpha=None, enable=None):
    s = f"drawtext=fontfile={FONT}:text='{esc(t)}':x={x}:y={y}:fontsize={size}:fontcolor={color}:borderw={border}:bordercolor=black"
    if box:
        s += f":box=1:boxcolor={box}:boxborderw=18"
    if alpha:
        s += f":alpha='{alpha}'"
    if enable:
        s += f":enable='{enable}'"
    return s


# ---------------------------------------------------------------- scan
def scan(v, vi, out):
    os.makedirs(out, exist_ok=True)
    info = {}
    for tag, path in (("v", v), ("vi", vi)):
        d = dur(path)
        info[tag] = round(d, 2)
        seg = d / 4
        for i in range(4):
            start = seg * i
            ff("-ss", f"{start:.3f}", "-i", path, "-t", f"{seg:.3f}", "-vf",
               f"fps={30 / seg:.5f},scale=300:-2,drawtext=fontfile={FONT}:text='{tag.upper()} %{{eif\\:t+{start:.3f}\\:d}}s'"
               f":x=6:y=6:fontsize=26:fontcolor={'yellow' if tag == 'v' else 'cyan'}:box=1:boxcolor=black@0.7,tile=6x5",
               "-frames:v", "1", "-q:v", "5", os.path.join(out, f"grid_{tag}_{i}.jpg"))
    json.dump(info, open(os.path.join(out, "info.json"), "w"))
    print(info)


# ---------------------------------------------------------------- render
def cut(src, start, length, out):
    ff("-ss", f"{max(0, start):.3f}", "-i", src, "-t", f"{length:.3f}", "-an",
       "-vf", f"scale=1920:1080:force_original_aspect_ratio=increase:flags=lanczos,crop=1920:1080,setsar=1,fps={FPS},format=yuv420p",
       "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", out)


def badge(name, year, x, y, color, size, enable=None):
    return text(f"{name}  {year}", x, y, size, "white", 0, box=f"{color}@0.92", enable=enable)


def pair_clip(p, fmt, a, b, D, out, names):
    on, oy, nn, ny = names
    label = p["label"]
    if fmt == "long" and p.get("style") == "wipe":
        hold = 0.6
        wipe = max(0.8, D - 2 * hold)
        # The new game wipes in from the right over the old one, with a bright divider on the edge.
        fc = (f"[0:v][1:v]xfade=transition=wipeleft:duration={wipe:.3f}:offset={hold:.3f}[w];"
              f"color=c=white:s=8x1080:r={FPS}[bar];"
              f"[w][bar]overlay=x='if(lt(t,{hold}),W,if(gt(t,{hold + wipe}),-20,W*(1-(t-{hold})/{wipe})-4))':y=0:shortest=1,"
              + badge(on, oy, 40, 40, GREY, 46, f"lt(t,{hold + wipe / 2})") + ","
              + badge(nn, ny, "w-tw-58", 40, PINK, 46, f"gte(t,{hold + wipe / 2})") + ","
              + text(label, "(w-tw)/2", 44, 60, YEL, 7) + f",trim=duration={D:.3f}[o]")
    elif fmt == "long":
        fc = ("[0:v]crop=960:1080:480:0[l];[1:v]crop=960:1080:480:0[r];[l][r]hstack[s];"
              "[s]drawbox=x=956:y=0:w=8:h=1080:color=white@1:t=fill,"
              + badge(on, oy, 40, 40, GREY, 46) + "," + badge(nn, ny, "w-tw-58", 40, PINK, 46) + ","
              + text(label, "(w-tw)/2", 44, 60, YEL, 7) + "[o]")
    else:
        # Short: old game on top, new game below, VS badge on the divider.
        fc = ("[0:v]scale=-2:960,crop=1080:960[t];[1:v]scale=-2:960,crop=1080:960[u];[t][u]vstack[s];"
              "[s]drawbox=x=0:y=952:w=1080:h=16:color=white@1:t=fill,"
              + text("VS", "(w-tw)/2", "960-th/2", 92, YEL, 9, box="black@0.85") + ","
              + text(label, "(w-tw)/2", 170, 76, YEL, 8) + ","
              + badge(on, oy, 40, 960 - 110, GREY, 50) + "," + badge(nn, ny, 40, 960 + 50, PINK, 50) + "[o]")
    ff("-i", a, "-i", b, "-filter_complex", fc, "-map", "[o]", "-t", f"{D:.3f}",
       "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", out)


def card(bg, fmt, kind, P, out, logo=None):
    W, H = (1080, 1920) if fmt == "short" else (1920, 1080)
    L = INTRO if kind == "intro" else OUTRO
    big = 150 if fmt == "short" else 170
    base = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=18:2,eq=brightness=-0.28:saturation=1.3,"
            f"zoompan=z='1+0.0009*on':d={int(L * FPS)}:s={W}x{H}:fps={FPS}")
    fade_in = lambda t0: f"if(lt(t,{t0}),0,min(1,(t-{t0})/0.25))"  # noqa: E731
    if kind == "intro":
        cy = H / 2
        vf = (base + "," + text(P["old_name"], "(w-tw)/2", f"{cy - big * 1.55:.0f}", big, "0xC9CED6", 10, alpha=fade_in(0.1))
              + "," + text("VS", "(w-tw)/2", f"{cy - big * 0.45:.0f}", int(big * 0.8), YEL, 10, alpha=fade_in(0.45))
              + "," + text(P["new_name"], "(w-tw)/2", f"{cy + big * 0.45:.0f}", big, PINK, 10, alpha=fade_in(0.8)))
        if P.get("hook"):
            vf += "," + text(P["hook"], "(w-tw)/2", f"{cy + big * 1.75:.0f}", int(big * 0.36), "white", 6, box="black@0.6", alpha=fade_in(1.2))
    else:
        vf = (base + "," + text(P.get("outro_text") or "WHICH ONE WINS?", "(w-tw)/2", f"{H / 2 - big * 0.9:.0f}", int(big * 0.62), YEL, 9, alpha=fade_in(0.15))
              + "," + text(f"COMMENT  {P['old_name'].split()[-1]}  OR  {P['new_name'].split()[-1]}", "(w-tw)/2", f"{H / 2 + big * 0.1:.0f}",
                           int(big * 0.4), "white", 6, box="black@0.6", alpha=fade_in(0.5))
              + "," + text("SUBSCRIBE FOR MORE", "(w-tw)/2", f"{H / 2 + big * 0.9:.0f}", int(big * 0.3), PINK, 5, alpha=fade_in(0.9)))
    ff("-loop", "1", "-t", f"{L:.3f}", "-i", bg, "-vf", vf + ",format=yuv420p", "-t", f"{L:.3f}",
       "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", out)
    return L


def captions(words, fmt, path):
    per = 3 if fmt == "short" else 6
    groups, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= per or re.search(r"[.,!?]$", w[0]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    W, H = (1080, 1920) if fmt == "short" else (1920, 1080)
    size, mv = (70, 330) if fmt == "short" else (54, 60)

    def ts(s):
        s = max(0, s)
        return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"
    lines = []
    for i, g in enumerate(groups):
        a, b = g[0][1], g[-1][2] + 0.3
        if i + 1 < len(groups):
            b = min(max(b, a + 0.4), groups[i + 1][0][1])
        t = " ".join(re.sub(r"[{}\\\[\]]", "", w[0]) for w in g).upper().rstrip(".,")
        fx = r"{\fscx80\fscy80\t(0,90,\fscx106\fscy106)\t(90,160,\fscx100\fscy100)}"
        lines.append(f"Dialogue: 0,{ts(a)},{ts(b)},Cap,,0,0,0,,{fx}{t}")
    open(path, "w").write(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,DejaVu Sans,{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,3,2,60,60,{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(lines) + "\n")


def timeline(P, total_pairs):
    """Start time of each pair in the joined video (intro first, XT overlap at every join)."""
    t, starts = INTRO - XT, []
    for d in total_pairs:
        starts.append(t)
        t += d - XT
    return starts, t + OUTRO


def plan_pairs(P, dv, dvi):
    pairs = []
    for p in P.get("pairs", []):
        try:
            a0, a1 = map(float, p["old"]); b0, b1 = map(float, p["new"])
        except Exception:  # noqa: BLE001
            continue
        a0, b0 = max(0, min(a0, dv - 2)), max(0, min(b0, dvi - 2))
        D = max(2.5, min(7.0, a1 - a0, b1 - b0, dv - a0, dvi - b0))
        pairs.append({**p, "a0": a0, "b0": b0, "D": round(D, 2)})
    if len(pairs) < 2:
        sys.exit("Need at least 2 matched pairs")
    return pairs


def voice_lines(v, vi, payload_path, out_json):
    """Timed voice lines on the joined timeline: the intro line, then one line per pair."""
    P = json.load(open(payload_path))
    pairs = plan_pairs(P, dur(v), dur(vi))
    starts, total = timeline(P, [p["D"] for p in pairs])
    lines = []
    if str(P.get("intro_say", "")).strip():
        lines.append({"t": 0.3, "say": P["intro_say"]})
    for s, p in zip(starts, pairs):
        if str(p.get("say", "")).strip():
            lines.append({"t": round(s + 0.35, 2), "say": p["say"]})
    if str(P.get("outro_say", "")).strip():
        lines.append({"t": round(total - OUTRO + 0.2, 2), "say": P["outro_say"]})
    json.dump(lines, open(out_json, "w"))
    print(f"{len(lines)} voice lines, video {total:.1f}s")
    print(f"{total:.2f}", file=open(out_json + ".total", "w"))


def render(v, vi, payload_path, out):
    P = json.load(open(payload_path))
    P.setdefault("old_name", "GTA V"); P.setdefault("old_year", "2013")
    P.setdefault("new_name", "GTA VI"); P.setdefault("new_year", "2026")
    names = (P["old_name"], P["old_year"], P["new_name"], P["new_year"])
    os.makedirs(out, exist_ok=True)
    work = os.path.join(out, "work")
    os.makedirs(work, exist_ok=True)
    pairs = plan_pairs(P, dur(v), dur(vi))
    for i, p in enumerate(pairs):
        cut(v, p["a0"], p["D"], f"{work}/a{i}.mp4")
        cut(vi, p["b0"], p["D"], f"{work}/b{i}.mp4")
    ff("-ss", f"{pairs[0]['b0'] + 0.5:.2f}", "-i", vi, "-frames:v", "1", f"{work}/bg_in.png")
    ff("-ss", f"{pairs[-1]['b0'] + pairs[-1]['D'] / 2:.2f}", "-i", vi, "-frames:v", "1", f"{work}/bg_out.png")
    starts, total = timeline(P, [p["D"] for p in pairs])
    json.dump({"starts": [round(s, 2) for s in starts], "total": round(total, 2)}, open(f"{out}/timeline.json", "w"))

    for fmt in P.get("formats") or ["short", "long"]:
        clips = [f"{work}/{fmt}_intro.mp4"]
        card(f"{work}/bg_in.png", fmt, "intro", P, clips[0])
        for i, p in enumerate(pairs):
            o = f"{work}/{fmt}_p{i}.mp4"
            pair_clip(p, fmt, f"{work}/a{i}.mp4", f"{work}/b{i}.mp4", p["D"], o, names)
            clips.append(o)
        clips.append(f"{work}/{fmt}_outro.mp4")
        card(f"{work}/bg_out.png", fmt, "outro", P, clips[-1])
        # Join everything with varied transitions.
        ins, fc, V, acc = [], "", "[0:v]", INTRO
        for c in clips:
            ins += ["-i", c]
        for k in range(1, len(clips)):
            tr = TRANS[(k - 1) % len(TRANS)]
            fc += f"{V}[{k}:v]xfade=transition={tr}:duration={XT}:offset={acc - XT:.3f}[x{k}];"
            V = f"[x{k}]"
            acc += dur(clips[k]) - XT
        n = len(clips)
        W, H = (1080, 1920) if fmt == "short" else (1920, 1080)
        post = V
        words = os.environ.get("WORDS_JSON")
        if words and os.path.exists(words):
            captions(json.load(open(words)), fmt, f"{work}/{fmt}.ass")
            fc += f"{post}subtitles={work}/{fmt}.ass[cap];"
            post = "[cap]"
        logo = os.environ.get("LOGO")
        if logo and os.path.exists(logo):
            lw = 150 if fmt == "short" else 130
            ins += ["-i", logo]
            lx, ly = (f"W-w-30", "H-h-430") if fmt == "short" else ("W-w-36", "H-h-36")
            fc += f"[{n}:v]scale={lw}:-1,format=rgba,colorchannelmixer=aa=0.85[lg];{post}[lg]overlay={lx}:{ly}[wm];"
            post = "[wm]"
            n += 1
        # Sound: the newer trailer's audio runs underneath (music + effects), voice ducks it.
        music = os.environ.get("MUSIC")
        if music and os.path.exists(music):
            # Your own song (looped if the video is longer than it), a bit softer under the voice.
            ins += ["-stream_loop", "-1", "-i", music]
            vol = 0.55 if os.environ.get("VOICE_WAV") else 0.8
        else:
            ins += ["-ss", f"{float(P.get('music_from', 0)):.2f}", "-i", vi]
            vol = 0.9
        mi = n
        n += 1
        fc += (f"[{mi}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=duration={acc:.3f},"
               f"afade=t=in:d=0.6,afade=t=out:st={max(0, acc - 2):.3f}:d=2,volume={vol}[bg];")
        voice = os.environ.get("VOICE_WAV")
        if voice and os.path.exists(voice):
            ins += ["-i", voice]
            fc += (f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,volume=1.6,asplit=2[vo][sc];"
                   f"[bg][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=350[duck];"
                   f"[duck][vo]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[aout]")
        else:
            fc += "[bg]anull[aout]"
        dest = f"{out}/compare_{fmt}.mp4"
        run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-stats", "-y", *ins, "-filter_complex", fc,
             "-map", post, "-map", "[aout]", "-t", f"{acc:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", dest])
        print(f"{fmt}: {dest} {dur(dest):.1f}s")


if __name__ == "__main__":
    if sys.argv[1] == "scan":
        scan(*sys.argv[2:5])
    elif sys.argv[1] == "lines":
        voice_lines(*sys.argv[2:6])
    else:
        render(*sys.argv[2:6])
