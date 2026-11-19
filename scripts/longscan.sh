#!/usr/bin/env bash
# Long video, stage 1: lets the AI "watch" the whole video.
#   - 8 frame grids (6x5 = 30 frames each) spread evenly over the video, every frame
#     stamped with its time in seconds from the start of the video
#   - the loudest moments (hype list) from highlights.py
# Inputs (env): VIDEO_URL, OUT_DIR, WORK_DIR
set -euo pipefail
WORK="${WORK_DIR:-$(mktemp -d)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$WORK" "$OUT_DIR/grids"
source "$HERE/download.sh"

echo "::group::Download the long video"
download_clip "$VIDEO_URL" "$WORK/long.mp4"
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$WORK/long.mp4" | cut -d. -f1)
if [ -z "$DUR" ] || [ "$DUR" -lt 30 ]; then echo "::error::Could not read the video (or it is under 30 seconds)."; exit 1; fi
echo "Duration: ${DUR}s"
echo "::endgroup::"

echo "::group::Loudest moments"
python3 "$HERE/highlights.py" "$WORK/long.mp4" "$WORK" 15 || echo '{"candidates":[]}' > "$WORK/candidates.json"
jq -c '[.candidates[] | .peak] | sort' "$WORK/candidates.json" > "$OUT_DIR/grids/peaks.json"
cat "$OUT_DIR/grids/peaks.json"
# Radio-aware: stretches where the in-game radio / music plays (the edit avoids them when it can).
python3 "$HERE/radio_detect.py" "$WORK/long.mp4" "$OUT_DIR/grids/radio.json" || echo '{"radio":[]}' > "$OUT_DIR/grids/radio.json"
cat "$OUT_DIR/grids/radio.json"
echo "::endgroup::"

echo "::group::Frame grids"
FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
SEG=$(awk -v d="$DUR" 'BEGIN { printf "%.3f", d / 8 }')
for i in 0 1 2 3 4 5 6 7; do
  START=$(awk -v s="$SEG" -v i="$i" 'BEGIN { printf "%.3f", s * i }')
  FPS=$(awk -v s="$SEG" 'BEGIN { printf "%.5f", 30 / s }')
  ffmpeg -nostdin -hide_banner -loglevel error -y -ss "$START" -i "$WORK/long.mp4" -t "$SEG" \
    -vf "fps=${FPS},scale=300:-2,drawtext=fontfile=${FONT}:text='%{eif\:t+${START}\:d}s':x=6:y=6:fontsize=24:fontcolor=yellow:box=1:boxcolor=black@0.65,tile=6x5" \
    -frames:v 1 -q:v 5 "$OUT_DIR/grids/grid_${i}.jpg"
done
ls -lh "$OUT_DIR/grids"
echo "::endgroup::"
echo "duration=$DUR" >> "$GITHUB_OUTPUT"
