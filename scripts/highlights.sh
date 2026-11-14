#!/usr/bin/env bash
# Finds hype moments in a long video and prepares them for the AI.
#   1. download the long video
#   2. listen for loudness spikes (highlights.py) -> candidates.json
#   3. cut each candidate window to its own MP4 (full quality, kept on a GitHub release)
#   4. make a 4x3 frame grid of each window, stamped with seconds from the window start
# Inputs (env): VIDEO_URL, MAX_CANDIDATES, OUT_DIR, WORK_DIR
set -euo pipefail
WORK="${WORK_DIR:-$(mktemp -d)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$WORK" "$OUT_DIR/grids" "$OUT_DIR/clips"
source "$HERE/download.sh"

echo "::group::Download the long video"
download_clip "$VIDEO_URL" "$WORK/long.mp4"
if ! ffprobe -v error -show_entries format=duration -of csv=p=0 "$WORK/long.mp4" | grep -q '[0-9]'; then
  echo "::error::That file is not a video I can read. If it is a Google Drive link, make sure the file is a video and shared."
  exit 1
fi
echo "::endgroup::"

echo "::group::Listen for hype moments"
python3 "$HERE/highlights.py" "$WORK/long.mp4" "$OUT_DIR" "${MAX_CANDIDATES:-10}"
echo "::endgroup::"

FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
echo "::group::Cut the moments and make frame grids"
jq -c '.candidates[]' "$OUT_DIR/candidates.json" | while read -r c; do
  ID=$(jq -r .id <<<"$c"); START=$(jq -r .start <<<"$c"); LEN=$(jq -r .length <<<"$c"); FILE=$(jq -r .file <<<"$c")
  ffmpeg -nostdin -hide_banner -loglevel error -y -ss "$START" -i "$WORK/long.mp4" -t "$LEN" \
    -map 0:v:0 -map '0:a:0?' -c:v libx264 -preset veryfast -crf 19 -pix_fmt yuv420p \
    -c:a aac -b:a 192k -movflags +faststart "$OUT_DIR/clips/$FILE"
  FPS=$(awk -v d="$LEN" 'BEGIN { printf "%.5f", 12 / (d + 0.5) }')
  ffmpeg -nostdin -hide_banner -loglevel error -y -i "$OUT_DIR/clips/$FILE" \
    -vf "fps=${FPS},scale=400:-2,drawtext=fontfile=${FONT}:text='%{eif\:t\:d}s':x=10:y=10:fontsize=30:fontcolor=yellow:box=1:boxcolor=black@0.6,tile=4x3" \
    -frames:v 1 -q:v 4 "$OUT_DIR/grids/grid_${ID}.jpg"
  echo "$ID ok"
done
cp "$OUT_DIR/candidates.json" "$OUT_DIR/grids/candidates.json"
ls -lh "$OUT_DIR/clips" "$OUT_DIR/grids"
echo "::endgroup::"

echo "count=$(jq '.candidates | length' "$OUT_DIR/candidates.json")" >> "$GITHUB_OUTPUT"
echo "duration=$(jq '.duration' "$OUT_DIR/candidates.json")" >> "$GITHUB_OUTPUT"
