#!/usr/bin/env bash
# Clip Polisher render: turns one of your own clipped Shorts into a finished, edited Short (no AI voice).
#   landscape clips -> vertical, following the action, facecam hidden; vertical clips keep your framing
#   + captions of what is said, bold hook at the top, smooth zoom + callout on the key moments,
#   your background song under the game sound, your logo, end card with the question, 4K export,
#   then uploads it to Drive (06 - Highlights Review) through the upload link made by n8n.
# Env: VIDEO_URL, PAYLOAD (JSON), OUT_DIR, WORK_DIR
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="${WORK_DIR:-$(mktemp -d)}"; mkdir -p "$WORK" "$OUT_DIR"
field() { printf '%s' "$PAYLOAD" | jq -r --arg k "$1" --arg d "$2" '.[$k] // $d | tostring'; }
gdl() { curl -fsSL --retry 3 -o "$2" "https://drive.usercontent.google.com/download?id=$1&export=download&confirm=t"; }
source "$HERE/download.sh"
printf '%s' "$PAYLOAD" > "$WORK/payload.json"

echo "::group::Download"
download_clip "$VIDEO_URL" "$WORK/in.mp4"
IFS=, read -r VW VH < <(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$WORK/in.mp4")
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$WORK/in.mp4")
HAS_AUDIO=false; ffprobe -v error -select_streams a:0 -show_entries stream=index -of csv=p=0 "$WORK/in.mp4" | grep -q . && HAS_AUDIO=true
echo "Clip: ${VW}x${VH}, ${DUR}s, audio: $HAS_AUDIO"
echo "::endgroup::"

echo "::group::Captions and words"
# The words were transcribed in the scan step and come back in the payload.
mkdir -p "$WORK/scan"; printf '%s' "$PAYLOAD" | jq '{words: (.words // [])}' > "$WORK/scan/scan.json"
OUTRO=0; [ -n "$(field outro_text "")" ] && OUTRO=3.4
python3 "$HERE/polish.py" ass "$WORK/payload.json" "$WORK/scan/scan.json" "$DUR" "$OUTRO" "$WORK/overlay.ass"
echo "::endgroup::"

echo "::group::Frame, overlay, music, logo"
FOCUS=$(printf '%s' "$PAYLOAD" | jq -c '.focus // []')
if [ "$VW" -gt "$VH" ]; then
  MAXR=""
  if [ "$(field hide_cam true)" = "true" ]; then MAXR=$(awk -v w="$VW" 'BEGIN { printf "%d", w * 0.786 - 4 }'); fi
  # Follow the action but stay inside the real picture (photo / selfie / menu boxes have blurred sides),
  # and find the scene changes for the transition effects.
  if python3 "$HERE/framing.py" "$WORK/in.mp4" "$FOCUS" "$MAXR" "$WORK/focus.json" "$WORK/cuts.json"; then
    CROP=$(CROP_NOSMOOTH=1 python3 "$HERE/cropexpr.py" "$VW" "$VH" "$(cat "$WORK/focus.json")" "" "")
  else
    echo "::warning::Smart framing failed, using the AI focus points only."; echo '[]' > "$WORK/cuts.json"
    CROP=$(python3 "$HERE/cropexpr.py" "$VW" "$VH" "$FOCUS" "" "$MAXR")
  fi
  FRAME="${CROP},scale=1080:1920:flags=lanczos"
else
  FRAME="scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:1920"
  python3 "$HERE/framing.py" "$WORK/in.mp4" "[]" "" "$WORK/focus.json" "$WORK/cuts.json" || echo '[]' > "$WORK/cuts.json"
fi
# Transitions at the scene changes (skipped when the form says no effects).
if [ "$(field transitions true)" = "true" ]; then
  PAYLOAD=$(printf '%s' "$PAYLOAD" | jq -c --slurpfile c "$WORK/cuts.json" '.fx = ((.fx // []) + [$c[0][] | {type: "punch", t: .}])')
fi
FREEZE=""; DARK=""
if [ "$OUTRO" != "0" ]; then
  FREEZE="tpad=stop_mode=clone:stop_duration=${OUTRO},"
  DARK="eq=brightness=-0.22:saturation=0.6:enable='gte(t\\,${DUR})',"
fi
TOTAL=$(awk -v d="$DUR" -v o="$OUTRO" 'BEGIN { printf "%.2f", d + o }')
INS=(-i "$WORK/in.mp4"); N=1
VCH="[0:v]${FREEZE}${FRAME},setsar=1,${DARK}subtitles=$WORK/overlay.ass:fontsdir=/usr/share/fonts/truetype/dejavu[vb]"
LOGO_ID="$(field watermark_id "")"
if [ -n "$LOGO_ID" ] && gdl "$LOGO_ID" "$WORK/logo_raw" && ffmpeg -nostdin -loglevel error -y -i "$WORK/logo_raw" -frames:v 1 "$WORK/logo.png"; then
  INS+=(-loop 1 -i "$WORK/logo.png"); LI=$N; N=$((N+1))
  VCH+=";[${LI}:v]scale=w=200:h=110:force_original_aspect_ratio=decrease,format=rgba,colorchannelmixer=aa=0.8[lg];[vb][lg]overlay=(W-w)/2:40:shortest=1[v]"
else
  VCH+=";[vb]null[v]"
fi
AF="aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
if [ "$HAS_AUDIO" = "true" ]; then ACH="[0:a]${AF},apad,atrim=0:${TOTAL}[game]"; else
  INS+=(-f lavfi -t "$TOTAL" -i anullsrc=r=48000:cl=stereo); ACH="[${N}:a]${AF}[game]"; N=$((N+1)); fi
MUSIC_ID="$(field music_id "")"
if [ -n "$MUSIC_ID" ] && gdl "$MUSIC_ID" "$WORK/music_raw" && ffmpeg -nostdin -loglevel error -y -i "$WORK/music_raw" -vn -ac 2 -ar 48000 "$WORK/music.wav"; then
  INS+=(-stream_loop -1 -i "$WORK/music.wav"); MI=$N; N=$((N+1))
  FO=$(awk -v t="$TOTAL" 'BEGIN { printf "%.2f", (t > 3 ? t - 2.5 : 0) }')
  ACH+=";[game]asplit[g1][g2];[${MI}:a]${AF},atrim=0:${TOTAL},volume=${MUSIC_VOL:-0.16},afade=in:d=0.8,afade=out:st=${FO}:d=2.5[m];[m][g2]sidechaincompress=threshold=0.05:ratio=3:attack=30:release=500[md];[g1][md]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.97[a]"
  echo "Background song added"
else
  ACH+=";[game]alimiter=limit=0.97[a]"
fi
ffmpeg -nostdin -hide_banner -loglevel error -y "${INS[@]}" -filter_complex "${VCH};${ACH}" -map "[v]" -map "[a]" \
  -t "$TOTAL" -r 30 -c:v libx264 -preset veryfast -crf 16 -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart "$WORK/base.mp4"
echo "::endgroup::"

FINAL="$WORK/base.mp4"
if [ "$(printf '%s' "$PAYLOAD" | jq '[.fx // [] | .[] | select(.type == "spotlight" or .type == "punch" or .type == "meme")] | length')" -gt 0 ]; then
  echo "::group::Zoom + callouts + transitions + memes"
  printf '%s' "$PAYLOAD" | jq -c '[.fx[] | select(.type == "spotlight" or .type == "punch")]' > "$WORK/fx.json"
  # Memes the AI picked: download the sound / image from Drive and add them with local paths.
  mkdir -p "$WORK/meme"; K=0
  printf '%s' "$PAYLOAD" | jq -c '.fx[] | select(.type == "meme")' | while read -r M; do
    K=$((K+1)); T=$(printf '%s' "$M" | jq -r '.t'); SID=$(printf '%s' "$M" | jq -r '.sound_id // ""'); IID=$(printf '%s' "$M" | jq -r '.image_id // ""')
    SP=""; IP=""
    if [ -n "$SID" ] && gdl "$SID" "$WORK/meme/s$K.raw" && ffmpeg -nostdin -loglevel error -y -i "$WORK/meme/s$K.raw" -vn -ac 2 -ar 48000 "$WORK/meme/s$K.wav"; then SP="$WORK/meme/s$K.wav"; fi
    if [ -n "$IID" ] && gdl "$IID" "$WORK/meme/i$K.raw" && ffmpeg -nostdin -loglevel error -y -i "$WORK/meme/i$K.raw" -frames:v 1 "$WORK/meme/i$K.png"; then IP="$WORK/meme/i$K.png"; fi
    jq -nc --argjson t "$T" --arg s "$SP" --arg i "$IP" '{type: "meme", t: $t, sound: $s, image: $i}' >> "$WORK/meme/list.jsonl"
    echo "Meme at ${T}s: $(printf '%s' "$M" | jq -r '(.sound_name // "") + " " + (.image_name // "")')"
  done
  if [ -s "$WORK/meme/list.jsonl" ]; then jq -s --slurpfile f "$WORK/fx.json" '$f[0] + .' "$WORK/meme/list.jsonl" > "$WORK/fx2.json" && mv "$WORK/fx2.json" "$WORK/fx.json"; fi
  mkdir -p "$WORK/sfx"
  printf '%s' "$PAYLOAD" | jq -r '.sfx // [] | .[] | "\(.id)\t\(.name)"' | while IFS=$'\t' read -r SID SNAME; do
    [ -n "$SID" ] && gdl "$SID" "$WORK/sfx/$(printf '%s' "$SNAME" | tr -c 'A-Za-z0-9._-' '_')" || true
  done
  if CALL_SIZE=66 GOOFY_CRF=16 GOOFY_MAX=25M python3 "$HERE/goofy.py" "$FINAL" "$WORK/fx.json" "$WORK/fx.mp4" "$DUR" "$WORK/sfx"; then FINAL="$WORK/fx.mp4"; else echo "::warning::Callouts failed, keeping the clean version."; fi
  echo "::endgroup::"
fi
if [ "$(field quality 4k)" = "4k" ]; then
  echo "::group::4K export"
  if bash "$HERE/enhance.sh" "$FINAL" "$WORK/final_4k.mp4" vertical; then FINAL="$WORK/final_4k.mp4"; fi
  echo "::endgroup::"
fi
ls -lh "$FINAL"

echo "::group::Upload to Drive (06 - Highlights Review)"
UPLOAD_URL=$(field upload_url "")
[ -n "$UPLOAD_URL" ] || { echo "::error::No Drive upload link was sent."; exit 1; }
python3 "$HERE/drive_upload.py" "$FINAL" "$UPLOAD_URL" "$OUT_DIR/drive.json"
DRIVE_ID=$(jq -r '.id // empty' "$OUT_DIR/drive.json")
[ -n "$DRIVE_ID" ] || { echo "::error::Drive did not return a file id."; exit 1; }
echo "drive_id=$DRIVE_ID" >> "$GITHUB_OUTPUT"
echo "::endgroup::"
