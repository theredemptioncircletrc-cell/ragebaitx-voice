"""Download meme images + sounds from Drive and describe them (sheet of images, sound stats + transcript)."""
import json, os, subprocess, sys, urllib.request

def get(fid, out):
    url = f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t"
    urllib.request.urlretrieve(url, out)

src, rep = sys.argv[1], sys.argv[2]
os.makedirs(rep, exist_ok=True); os.makedirs("dl", exist_ok=True)
L = json.load(open(src))
font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
tiles = []
for k, (fid, name) in enumerate(L["images"]):
    p = f"dl/img{k}"
    try:
        get(fid, p)
        t = f"{rep}/i{k:02d}.jpg"
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", p, "-frames:v", "1", "-vf",
                        f"scale=400:400:force_original_aspect_ratio=decrease,pad=400:440:(ow-iw)/2:0:color=gray,"
                        f"drawtext=fontfile={font}:text='{k} {name[:28].replace(chr(39), '')}':x=4:y=412:fontsize=16:fontcolor=white", t], check=True)
        tiles.append(t)
    except Exception as e:
        print("image fail", name, e)
if tiles:
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-pattern_type", "glob", "-i", f"{rep}/i*.jpg",
                    "-vf", "tile=5x4", "-frames:v", "1", f"{rep}/images.jpg"], check=True)
    for t in tiles: os.remove(t)
from faster_whisper import WhisperModel
model = WhisperModel("small", device="cpu", compute_type="int8")
rows = []
for k, (fid, name) in enumerate(L["sounds"]):
    p = f"dl/snd{k}.mp3"
    try:
        get(fid, p)
        d = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]))
        vol = subprocess.run(["ffmpeg", "-nostdin", "-i", p, "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
        mean = [l.split(":")[1].strip() for l in vol.splitlines() if "mean_volume" in l]
        peak = [l.split(":")[1].strip() for l in vol.splitlines() if "max_volume" in l]
        segs, _ = model.transcribe(p, vad_filter=False)
        words = " ".join(s.text.strip() for s in segs)
        # loudness over time (0.25 s steps) to see where the hit is
        env = subprocess.run(["ffmpeg", "-nostdin", "-i", p, "-af", "astats=metadata=1:reset=11025,ametadata=print:key=lavfi.astats.Overall.RMS_level", "-ar", "44100", "-f", "null", "-"], capture_output=True, text=True).stderr
        lv = [l.split("=")[1] for l in env.splitlines() if "RMS_level=" in l][:24]
        rows.append({"k": k, "name": name, "dur": round(d, 2), "mean": mean[:1], "peak": peak[:1], "words": words, "rms_quarter_s": [round(float(x)) if x not in ("-inf", "inf") else -99 for x in lv]})
        sp = f"{rep}/s{k:02d}.png"
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", p, "-lavfi", "showspectrumpic=s=600x200:legend=0", sp])
    except Exception as e:
        rows.append({"k": k, "name": name, "error": str(e)})
json.dump(rows, open(f"{rep}/sounds.json", "w"), indent=1)
print(json.dumps(rows, indent=1))
