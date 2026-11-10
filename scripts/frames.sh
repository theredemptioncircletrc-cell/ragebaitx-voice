#!/usr/bin/env bash
# Makes one 3x3 grid of still frames spread across the clip, so the AI can see what happens.
# Inputs (env): CLIP_URL, OUT_DIR, WORK_DIR
set -euo pipefail
WORK="${WORK_DIR:-$(mktemp -d)}"
mkdir -p "$WORK" "$OUT_DIR"
source "$(dirname "$0")/download.sh"
download_clip "$CLIP_URL" "$WORK/in.mp4"

DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$WORK/in.mp4" | cut -d. -f1)
DUR=${DUR:-0}
[ "$DUR" -gt 0 ] || DUR=1
HAS_AUDIO=false
if ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$WORK/in.mp4" | grep -q .; then HAS_AUDIO=true; fi

# 9 frames, evenly spaced, each 360px wide, tiled 3x3 with the frame number and time stamped on.
FPS=$(awk -v d="$DUR" 'BEGIN { printf "%.5f", 9 / (d + 0.5) }')
ffmpeg -nostdin -hide_banner -loglevel error -y -i "$WORK/in.mp4" \
  -vf "fps=${FPS},scale=360:-2,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='%{eif\:t\:d}s':x=10:y=10:fontsize=28:fontcolor=yellow:box=1:boxcolor=black@0.6,tile=3x3" \
  -frames:v 1 -q:v 4 "$OUT_DIR/frames.jpg"
ls -lh "$OUT_DIR/frames.jpg"
echo "duration=$DUR" >> "$GITHUB_OUTPUT"
echo "has_audio=$HAS_AUDIO" >> "$GITHUB_OUTPUT"
