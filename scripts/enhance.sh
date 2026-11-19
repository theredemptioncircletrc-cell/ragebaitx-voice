#!/usr/bin/env bash
# Clean "4K export": makes the finished video look as sharp and clean as possible on YouTube.
#   usage: enhance.sh IN.mp4 OUT.mp4 [vertical]
#   1. light clean-up of PS5 compression (soft denoise + de-banding of skies and dark areas)
#   2. careful upscale to 4K (3840x2160, or 2160x3840 for Shorts) with lanczos
#   3. smart sharpening (contrast-adaptive, so edges pop without halos) and a touch of colour
#   4. high-bitrate export, so YouTube gives the video its 4K treatment (better codec + bitrate for every viewer)
# Already 4K footage is not upscaled, only cleaned and sharpened. The sound is copied untouched.
set -euo pipefail
IN="$1"; OUT="$2"; VERT="${3:-}"
if [ "$VERT" = "vertical" ]; then W=2160; H=3840; else W=3840; H=2160; fi
# Very long videos (over 25 min) go to 1440p instead: YouTube still gives them the better codec, and the
# render stays well inside GitHub's time limit.
LEN=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$IN" | cut -d. -f1)
if [ "${LEN:-0}" -gt 1500 ] && [ "$VERT" != "vertical" ]; then W=2560; H=1440; fi
FPS=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of csv=p=0 "$IN")
GOP=$(awk -F/ '{ f = ($2 ? $1 / $2 : $1); if (f > 60 || f < 20) f = 30; printf "%.0f", f * 2 }' <<<"$FPS")
VF="hqdn3d=1.2:1.0:2.5:2.5,gradfun=0.8:12,cas=0.5,eq=contrast=1.03:saturation=1.07,scale=${W}:${H}:force_original_aspect_ratio=decrease:flags=lanczos+accurate_rnd+full_chroma_int,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
echo "Quality export: ${W}x${H}, cleaned + sharpened"
ffmpeg -nostdin -hide_banner -loglevel error -stats -y -i "$IN" -map 0:v:0 -map '0:a?' -vf "$VF" \
  -c:v libx264 -preset "${PRESET:-superfast}" -crf 18 -maxrate 45M -bufsize 90M -g "$GOP" -pix_fmt yuv420p \
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 \
  -c:a copy -movflags +faststart "$OUT"
ls -lh "$OUT"
