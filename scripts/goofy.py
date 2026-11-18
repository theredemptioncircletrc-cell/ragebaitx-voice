"""Goofy edits on a finished vertical Short (1080x1920): the chaos layer.

usage: python goofy.py IN_MP4 FX_JSON OUT_MP4 CLIP_SECONDS [SFX_DIR]
  FX_JSON: [{"type": "zoom" | "replay" | "freeze" | "guess", "t": seconds into the clip, "text": "..."}]
    zoom   : punch-in + screen shake + flash + boom on the impact
    replay : "<< REWIND" back a few seconds, then the moment again in deep-voiced slow motion with a REPLAY badge
    freeze : freeze frame, record scratch, a goofy caption ("YEP. THAT'S ME."), then it carries on
    guess  : "PAUSE. WHAT HAPPENS NEXT?" with a ticking clock, then the payoff
  CLIP_SECONDS: length of the clip before the end card (effects only happen inside it)
  SFX_DIR: optional folder with your own sound effects; file names decide what they are used for
           (boom/impact/hit, scratch/record, rewind/tape, tick/clock/timer, whoosh/swoosh, bruh/fail/bonk).
           Anything missing is made on the fly, so it always works.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap

W, H, FPS = 1080, 1920, 30
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
TMP = tempfile.mkdtemp()

SYNTH = {
    "boom": "aevalsrc='0.95*sin(2*PI*(45+90*exp(-9*t))*t)*exp(-3.2*t)':s=48000:d=1.3",
    "scratch": "aevalsrc='0.55*sin(2*PI*(500+420*sin(2*PI*11*t))*t)*exp(-2.5*t)+0.25*(random(0)-0.5)*exp(-6*t)':s=48000:d=0.55",
    "rewind": "aevalsrc='0.35*sin(2*PI*(2200-1700*t)*t)*(0.6+0.4*sin(2*PI*28*t))':s=48000:d=1.0",
    "tick": "aevalsrc='0.6*sin(2*PI*1900*t)*exp(-70*mod(t\\,0.45))':s=48000:d=1.9",
    "whoosh": "anoisesrc=c=pink:r=48000:a=0.8:d=0.6,highpass=f=500,lowpass=f=5000,afade=in:d=0.2,afade=out:st=0.2:d=0.4",
    "fail": "aevalsrc='0.5*sin(2*PI*(330-140*t)*t)*exp(-1.6*t)':s=48000:d=1.1",
    "crowd": "anoisesrc=c=pink:r=48000:a=0.9:d=2.6,bandpass=f=900:width_type=o:w=2.5,volume='min(1\\,t*2.5)*if(gt(t\\,1.6)\\,1-(t-1.6)\\,1)':eval=frame",
}
KEYS = {
    "boom": r"boom|impact|hit|bass|punch",
    "scratch": r"scratch|record|vinyl",
    "rewind": r"rewind|tape|reverse",
    "tick": r"tick|clock|timer|count",
    "whoosh": r"whoosh|swoosh|swish|woosh",
    "fail": r"bruh|fail|bonk|sad|oof",
    "crowd": r"crowd|roar|cheer|stadium",
}


def ff(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]).strip())


def sfx(kind, sfx_dir):
    """A wav for this kind of sound: your file if you have one, else a made one."""
    out = os.path.join(TMP, f"sfx_{kind}.wav")
    if os.path.exists(out):
        return out
    if sfx_dir and os.path.isdir(sfx_dir):
        for f in sorted(os.listdir(sfx_dir)):
            if re.search(KEYS[kind], f, re.I):
                try:
                    ff("-i", os.path.join(sfx_dir, f), "-t", "3", "-ac", "2", "-ar", "48000", "-af", "loudnorm=I=-16:TP=-2", out)
                    print(f"  {kind}: your file {f}")
                    return out
                except subprocess.CalledProcessError:
                    pass
    ff("-f", "lavfi", "-i", SYNTH[kind], "-ac", "2", "-ar", "48000", out)
    return out


def ass_text(lines, path, dur_s, size=88, color="&H00FFFFFF", y=900, pop=True):
    """Big centered goofy text (wrapped), popping in."""
    def ts(s):
        return f"0:00:{s:05.2f}"
    ev = []
    for k, (txt, col, sz, dy) in enumerate(lines):
        wrapped = "\\N".join(textwrap.wrap(txt.upper(), 16)) or " "
        fx = r"{\fscx20\fscy20\t(0,120,\fscx115\fscy115)\t(120,200,\fscx100\fscy100)\frz-4}" if pop else ""
        ev.append(f"Dialogue: 0,{ts(0.05 + k * 0.15)},{ts(dur_s)},T,,0,0,0,,{{\\pos(540,{y + dy})\\c{col}\\fs{sz}}}{fx}{wrapped}")
    open(path, "w").write(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: T,DejaVu Sans,{size},{color},&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,9,5,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(ev) + "\n")


ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
       "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"]


def piece(src, a, b, out):
    ff("-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", src, "-vf", f"fps={FPS},setsar=1", "-af", "aresample=48000", *ENC, out)


def frame_at(src, t, out):
    ff("-ss", f"{max(0, t - 0.02):.3f}", "-i", src, "-frames:v", "1", out)


def freeze(src, t, text, out, sfx_dir):
    L = 1.5
    png = os.path.join(TMP, f"fr_{t}.png"); frame_at(src, t, png)
    ass = os.path.join(TMP, f"fr_{t}.ass")
    ass_text([(text or "YEP. THAT'S ME.", "&H0000E5FF", 92, 0)], ass, L)
    ff("-loop", "1", "-t", f"{L}", "-i", png, "-i", sfx("scratch", sfx_dir),
       "-filter_complex",
       f"[0:v]scale={W}:{H},zoompan=z='1+0.05*on/{int(L * FPS)}':d={int(L * FPS)}:s={W}x{H}:fps={FPS},hue=s=0.35,eq=contrast=1.15,vignette=PI/4,"
       f"subtitles={ass}[v];[1:a]apad,atrim=duration={L}[a]", "-map", "[v]", "-map", "[a]", "-t", f"{L}", *ENC, out)


def guess(src, t, text, out, sfx_dir):
    L = 1.9
    png = os.path.join(TMP, f"gs_{t}.png"); frame_at(src, t, png)
    ass = os.path.join(TMP, f"gs_{t}.ass")
    ass_text([("PAUSE.", "&H00FFFFFF", 120, -170), (text or "WHAT HAPPENS NEXT?", "&H0000E5FF", 84, 40),
              ("COMMENT FAST", "&H00A43FFF", 56, 260)], ass, L)
    ff("-loop", "1", "-t", f"{L}", "-i", png, "-i", sfx("tick", sfx_dir),
       "-filter_complex",
       f"[0:v]scale={W}:{H},boxblur=6:1,eq=brightness=-0.3:saturation=0.7,"
       f"drawbox=x=470:y=520:w=48:h=150:color=white@0.95:t=fill,drawbox=x=562:y=520:w=48:h=150:color=white@0.95:t=fill,"
       f"subtitles={ass},fps={FPS}[v];[1:a]apad,atrim=duration={L}[a]", "-map", "[v]", "-map", "[a]", "-t", f"{L}", *ENC, out)


def replay(src, t, sfx_dir):
    L = min(2.0, max(1.2, t - 0.3))
    a = t - L
    seg = os.path.join(TMP, f"rp_seg_{t}.mkv"); piece(src, a, t, seg)
    rew = os.path.join(TMP, f"rp_rew_{t}.mkv")
    # Rewind: backwards at 3x speed, VHS-ish tint and noise, tape whirr.
    ff("-i", seg, "-i", sfx("rewind", sfx_dir), "-filter_complex",
       f"[0:v]reverse,setpts=PTS/3,noise=alls=28:allf=t,hue=s=0.5,eq=contrast=1.2,"
       f"drawtext=fontfile={FONT}:text='<< REWIND':x=50:y=260:fontsize=82:fontcolor=white:borderw=7:bordercolor=black,fps={FPS}[v];"
       f"[1:a]atrim=duration={L / 3:.3f}[a]", "-map", "[v]", "-map", "[a]", "-t", f"{L / 3:.3f}", *ENC, rew)
    slo = os.path.join(TMP, f"rp_slo_{t}.mkv")
    S = 1.8  # slow-motion factor
    # Slow-mo with a blinking REPLAY badge and the classic deep slowed-down sound, boom on the moment.
    ff("-i", seg, "-i", sfx("boom", sfx_dir), "-filter_complex",
       f"[0:v]setpts=PTS*{S},minterpolate=fps={FPS}:mi_mode=blend,"
       f"drawbox=x=40:y=240:w=330:h=110:color=0xE11D2E@0.95:t=fill:enable='lt(mod(t\\,0.8)\\,0.55)',"
       f"drawtext=fontfile={FONT}:text='REPLAY':x=62:y=258:fontsize=72:fontcolor=white:enable='lt(mod(t\\,0.8)\\,0.55)'[v];"
       f"[0:a]asetrate=48000*0.72,aresample=48000,atempo={1 / (0.72 * S):.4f},volume=1.1[sa];"
       f"[1:a]adelay={int((L * S - 0.9) * 1000)}:all=1[bm];[sa][bm]amix=inputs=2:duration=first:normalize=0[a]",
       "-map", "[v]", "-map", "[a]", "-t", f"{L * S:.3f}", *ENC, slo)
    return [rew, slo]


def teaser(src, at, text, sfx_dir):
    """Cold open: the peak moment first (muffled, with the hook question), then "N SECONDS EARLIER..." back to the start."""
    a, b = max(0.0, at - 0.9), at + 0.8
    L = b - a
    seg = os.path.join(TMP, "teaser_seg.mkv"); piece(src, a, b, seg)
    ass = os.path.join(TMP, "teaser.ass")
    ass_text([(text or "HOW DID WE GET HERE?", "&H0000E5FF", 96, 0)], ass, L)
    hot = os.path.join(TMP, "teaser_hot.mkv")
    ff("-i", seg, "-i", sfx("whoosh", sfx_dir), "-filter_complex",
       f"[0:v]eq=contrast=1.15:saturation=1.35,fade=in:st=0:d=0.12:color=white,subtitles={ass}[v];"
       f"[0:a]lowpass=f=1100,volume=0.9[g];[1:a]atrim=duration={L:.3f},volume=0.8[w];[g][w]amix=inputs=2:duration=first:normalize=0[a]",
       "-map", "[v]", "-map", "[a]", "-t", f"{L:.3f}", *ENC, hot)
    png = os.path.join(TMP, "teaser_start.png"); frame_at(src, 0.05, png)
    ass2 = os.path.join(TMP, "teaser_card.ass")
    ass_text([(f"{max(1, round(at))} SECONDS EARLIER...", "&H00FFFFFF", 84, 0)], ass2, 0.85, pop=False)
    card = os.path.join(TMP, "teaser_card.mkv")
    ff("-loop", "1", "-t", "0.85", "-i", png, "-i", sfx("rewind", sfx_dir), "-filter_complex",
       f"[0:v]scale={W}:{H},hue=s=0.2,eq=brightness=-0.15,noise=alls=24:allf=t,subtitles={ass2},fps={FPS}[v];"
       f"[1:a]apad,atrim=duration=0.85,afade=out:st=0.6:d=0.25[a]", "-map", "[v]", "-map", "[a]", "-t", "0.85", *ENC, card)
    return [hot, card]


def stamps_ass(stamps, path):
    """Big moments drawn over the video: FIFA goal banner, GTA stamp (WANTED / SENT IT / NO SHOT)."""
    def ts(x):
        x = max(0, x)
        return f"0:{int(x // 60):02d}:{x % 60:05.2f}"
    ev = []
    for st in stamps:
        t, txt, sub, style = st["t"], st["text"].upper()[:22], st.get("sub", "").upper()[:28], st.get("style", "gta")
        if style == "fifa":
            ev.append(f"Dialogue: 3,{ts(t)},{ts(t + 1.9)},Banner,,0,0,0,,{{\\move(-700,820,540,820,0,180)\\t(180,300,\\fscx108\\fscy108)\\t(300,380,\\fscx100\\fscy100)}}{txt}")
            if sub:
                ev.append(f"Dialogue: 3,{ts(t + 0.15)},{ts(t + 1.9)},BannerSub,,0,0,0,,{{\\move(1700,960,540,960,0,200)}}{sub}")
        else:
            ev.append(f"Dialogue: 3,{ts(t)},{ts(t + 1.6)},Stamp,,0,0,0,,{{\\pos(540,880)\\frz-7\\fscx320\\fscy320\\t(0,110,\\fscx100\\fscy100)\\t(1300,1600,\\alpha&HFF&)}}{txt}")
            if sub:
                ev.append(f"Dialogue: 3,{ts(t + 0.12)},{ts(t + 1.6)},StampSub,,0,0,0,,{{\\pos(540,1010)\\frz-7\\t(1300,1600,\\alpha&HFF&)}}{sub}")
    open(path, "w").write(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Banner,DejaVu Sans,130,&H0000E5FF,&H00FFFFFF,&H00228B22,&H96000000,-1,1,0,0,100,100,2,0,3,22,0,5,0,0,0,1
Style: BannerSub,DejaVu Sans,58,&H00FFFFFF,&H00FFFFFF,&H00141414,&H96000000,-1,0,0,0,100,100,1,0,3,16,0,5,0,0,0,1
Style: Stamp,DejaVu Sans,120,&H0000E5FF,&H00FFFFFF,&H00000000,&HB4000000,-1,0,0,0,100,100,3,0,1,12,8,5,0,0,0,1
Style: StampSub,DejaVu Sans,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&HB4000000,-1,0,0,0,100,100,2,0,1,8,5,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(ev) + "\n")


def var_check(src, t, verdict, out, sfx_dir):
    """FIFA: freeze, VAR CHECKING... with a scanning line, then the verdict lands with a boom."""
    L, V = 2.5, 1.7
    png = os.path.join(TMP, f"var_{t}.png"); frame_at(src, t, png)
    good = not re.search(r"NO |OFF|ROBBED|DISALLOWED", verdict.upper())
    col = "&H0044DD44" if good else "&H004040FF"
    ass = os.path.join(TMP, f"var_{t}.ass")
    open(ass, "w").write(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Var,DejaVu Sans,78,&H00FFFFFF,&H00FFFFFF,&H00301E0A,&H96000000,-1,0,0,0,100,100,3,0,3,20,0,5,0,0,0,1
Style: Verdict,DejaVu Sans,118,{col},&H00FFFFFF,&H00000000,&HB4000000,-1,0,0,0,100,100,2,0,1,12,6,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:{V:05.2f},Var,,0,0,0,,{{\\pos(540,760)\\t(0,400,\\alpha&H30&)\\t(400,800,\\alpha&H00&)\\t(800,1200,\\alpha&H30&)\\t(1200,1600,\\alpha&H00&)}}VAR CHECKING...
Dialogue: 1,0:00:{V:05.2f},0:00:{L:05.2f},Verdict,,0,0,0,,{{\\pos(540,900)\\fscx260\\fscy260\\t(0,120,\\fscx100\\fscy100)}}{verdict.upper()[:20]}
""")
    ff("-loop", "1", "-t", f"{L}", "-i", png, "-i", sfx("tick", sfx_dir), "-i", sfx("boom", sfx_dir), "-filter_complex",
       f"[0:v]scale={W}:{H},hue=s=0.4,eq=brightness=-0.22,"
       f"drawbox=x='mod(t*900\\,{W})':y=0:w=10:h={H}:color=0x00E5FF@0.85:t=fill:enable='lt(t\\,{V})',"
       f"drawgrid=w=120:h=120:t=1:c=white@0.12,subtitles={ass},fps={FPS}[v];"
       f"[1:a]atrim=duration={V},apad[tk];[2:a]adelay={int(V * 1000)}:all=1[bm];[tk][bm]amix=inputs=2:duration=longest:normalize=0,atrim=duration={L}[a]",
       "-map", "[v]", "-map", "[a]", "-t", f"{L}", *ENC, out)


def zooms_pass(src, out, zs, sfx_dir, total, ass=None, extra=()):
    """Punch-in + shake + flash on every zoom time, with a boom; plus the big-moment overlays and their sounds."""
    if not zs:
        zs = [-5.0]   # nothing to punch, but still draw the overlays
    env = "+".join(f"if(between(t\\,{z:.2f}\\,{z + 0.65:.2f})\\,if(lt(t-{z:.2f}\\,0.07)\\,(t-{z:.2f})/0.07\\,1-(t-{z:.2f}-0.07)/0.58)\\,0)" for z in zs)
    flash = "+".join(f"between(t\\,{z:.2f}\\,{z + 0.07:.2f})" for z in zs)
    vf = (f"scale=w='trunc({W}*(1+0.3*({env}))/2)*2':h=-2:eval=frame,"
          f"crop={W}:{H}:x='(iw-ow)/2+(iw-ow)/2*0.85*sin(t*73)':y='(ih-oh)/2+(ih-oh)/2*0.85*cos(t*61)',"
          f"eq=brightness=0.35:saturation=1.4:enable='{flash}',setsar=1" + (f",subtitles={ass}" if ass else ""))
    ins, fa = ["-i", src], "[0:a]aresample=48000[base];"
    mix = "[base]"
    sounds = [(z, "boom") for z in zs if z >= 0] + list(extra)
    for k, (z, kind) in enumerate(sounds):
        ins += ["-i", sfx(kind, sfx_dir)]
        fa += f"[{k + 1}:a]adelay={int(z * 1000)}:all=1,volume=0.9[b{k}];"
        mix += f"[b{k}]"
    fa += f"{mix}amix=inputs={len(sounds) + 1}:duration=first:normalize=0,alimiter=limit=0.97[a]"
    ff(*ins, "-filter_complex", f"[0:v]{vf}[v];{fa}", "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}", *ENC, out)


def main():
    src, fx_path, out, clip_s = sys.argv[1:5]
    sfx_dir = sys.argv[5] if len(sys.argv) > 5 else ""
    clip_s = float(clip_s)
    total = dur(src)
    fx = [f for f in json.load(open(fx_path)) if isinstance(f, dict) and f.get("type") in ("zoom", "replay", "freeze", "guess", "teaser", "stamp", "var")]
    stamps = [f for f in fx if f["type"] == "stamp" and str(f.get("text", "")).strip()]
    fx = [f for f in fx if f["type"] != "stamp"]
    tz = next((f for f in fx if f["type"] == "teaser"), None)
    fx = [f for f in fx if f["type"] != "teaser"]
    for f in fx:
        f["t"] = round(min(max(1.0, float(f.get("t", 0) or 0)), clip_s - 0.4), 2)
    zs = sorted({f["t"] for f in fx if f["type"] == "zoom"})[:3]
    inserts, seen, last = [], set(), -9
    for f in sorted([f for f in fx if f["type"] != "zoom"], key=lambda f: f["t"]):
        if f["type"] in seen or f["t"] - last < 2.0:
            continue
        seen.add(f["type"]); inserts.append(f); last = f["t"]
    print(f"Goofy edits: teaser {tz}, zooms {zs}, inserts {[(f['type'], f['t']) for f in inserts]}")
    base = os.path.join(TMP, "base.mkv")
    for st in stamps:
        st["t"] = round(min(max(0.5, float(st.get("t", 0) or 0)), clip_s - 0.5), 2)
    ass = None
    if stamps:
        ass = os.path.join(TMP, "stamps.ass"); stamps_ass(stamps, ass)
    extra = [(st["t"], "crowd") for st in stamps if st.get("style") == "fifa" and st.get("crowd", True)]
    if zs or stamps:
        zooms_pass(src, base, zs, sfx_dir, total, ass, extra)
    else:
        piece(src, 0, total, base)
    parts, cur = [], 0.0
    if tz and 3.0 <= float(tz.get("t", 0) or 0) <= clip_s - 0.5:
        parts += teaser(base, float(tz["t"]), str(tz.get("text", "")).strip()[:50], sfx_dir)
    for f in inserts:
        t = f["t"]
        if t - cur > 0.05:
            p = os.path.join(TMP, f"main_{len(parts)}.mkv"); piece(base, cur, t, p); parts.append(p)
        ins = os.path.join(TMP, f"ins_{len(parts)}.mkv")
        if f["type"] == "freeze":
            freeze(base, t, str(f.get("text", "")).strip()[:60], ins, sfx_dir); parts.append(ins)
        elif f["type"] == "var":
            var_check(base, t, str(f.get("text", "")).strip() or "GOAL STANDS", ins, sfx_dir); parts.append(ins)
        elif f["type"] == "guess":
            guess(base, t, str(f.get("text", "")).strip()[:50], ins, sfx_dir); parts.append(ins)
        else:
            parts += replay(base, t, sfx_dir)
        cur = t
    p = os.path.join(TMP, "main_end.mkv"); piece(base, cur, total, p); parts.append(p)
    ins = []
    for p in parts:
        ins += ["-i", p]
    cat = "".join(f"[{k}:v][{k}:a]" for k in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=1[v][a]"
    ff(*ins, "-filter_complex", cat, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
       "-maxrate", "6M", "-bufsize", "12M", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out)
    print(f"Goofy Short: {dur(out):.1f}s (was {total:.1f}s)")


if __name__ == "__main__":
    main()
