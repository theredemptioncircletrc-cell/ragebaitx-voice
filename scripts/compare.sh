#!/usr/bin/env bash
# Comparison maker (GTA V vs GTA VI style).
#   STAGE=scan   : download both trailers, frame grids for the AI -> $OUT_DIR/grids
#   STAGE=render : voice lines (optional), build the Short and/or the long version, upload to Drive
# Inputs (env): STAGE, VIDEO_URL (older game), PAYLOAD (JSON: new_url, pairs, formats, upload_short,
#               upload_long, watermark_id, narration), OUT_DIR, WORK_DIR, TTS_PY, ELEVENLABS_*
set -euo pipefail
WORK="${WORK_DIR:-$(mktemp -d)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$WORK" "$OUT_DIR"
source "$HERE/download.sh"
field() { printf '%s' "$PAYLOAD" | jq -r --arg k "$1" --arg d "$2" '.[$k] // $d | tostring'; }

echo "::group::Download both trailers"
download_clip "$VIDEO_URL" "$WORK/old.mp4"
download_clip "$(field new_url "")" "$WORK/new.mp4"
echo "::endgroup::"

if [ "$STAGE" = "scan" ]; then
  python3 "$HERE/compare.py" scan "$WORK/old.mp4" "$WORK/new.mp4" "$OUT_DIR/grids"
  echo "old_s=$(jq .v "$OUT_DIR/grids/info.json")" >> "$GITHUB_OUTPUT"
  echo "new_s=$(jq .vi "$OUT_DIR/grids/info.json")" >> "$GITHUB_OUTPUT"
  exit 0
fi

printf '%s' "$PAYLOAD" > "$WORK/payload.json"
WM_ID=$(field watermark_id "")
if [ -n "$WM_ID" ] && curl -fsSL --retry 3 -o "$WORK/logo_raw" "https://drive.usercontent.google.com/download?id=$WM_ID&export=download&confirm=t" \
   && ffmpeg -nostdin -loglevel error -y -i "$WORK/logo_raw" -frames:v 1 "$WORK/logo.png"; then export LOGO="$WORK/logo.png"; fi

if [ "$(printf '%s' "$PAYLOAD" | jq -r 'if .narration == false then "false" else "true" end')" = "true" ]; then
  echo "::group::Voice"
  python3 "$HERE/compare.py" lines "$WORK/old.mp4" "$WORK/new.mp4" "$WORK/payload.json" "$WORK/lines.json"
  TOTAL=$(cat "$WORK/lines.json.total")
  ENGINE=kokoro; VID="am_puck"
  if [ -n "${ELEVENLABS_API_KEY:-}" ] && [ -n "${ELEVENLABS_VOICE_ID:-}" ]; then ENGINE=eleven; VID="$ELEVENLABS_VOICE_ID"; fi
  if [ "$(jq length "$WORK/lines.json")" -gt 0 ]; then
    if ! WORDS_OUT="$WORK/words.json" "$TTS_PY" "$HERE/tts_timed.py" "$WORK/lines.json" "$TOTAL" "$WORK/voice.wav" "$WORK/unused.ass" "$ENGINE" "$VID" 0; then
      [ "$ENGINE" = "eleven" ] && WORDS_OUT="$WORK/words.json" "$TTS_PY" "$HERE/tts_timed.py" "$WORK/lines.json" "$TOTAL" "$WORK/voice.wav" "$WORK/unused.ass" kokoro am_puck 0 || true
    fi
    [ -s "$WORK/voice.wav" ] && export VOICE_WAV="$WORK/voice.wav" WORDS_JSON="$WORK/words.json"
  fi
  echo "::endgroup::"
fi

echo "::group::Render"
python3 "$HERE/compare.py" render "$WORK/old.mp4" "$WORK/new.mp4" "$WORK/payload.json" "$WORK/out"
echo "::endgroup::"

echo "::group::Upload to Drive"
for fmt in short long; do
  URL=$(field "upload_$fmt" "")
  F="$WORK/out/compare_$fmt.mp4"
  if [ -n "$URL" ] && [ -s "$F" ]; then
    curl -fsS --retry 3 --retry-delay 10 -X PUT -H "Content-Type: video/mp4" --upload-file "$F" "$URL" -o "$WORK/$fmt.json"
    echo "${fmt}_id=$(jq -r .id "$WORK/$fmt.json")" >> "$GITHUB_OUTPUT"
    ls -lh "$F"
  fi
done
echo "::endgroup::"
