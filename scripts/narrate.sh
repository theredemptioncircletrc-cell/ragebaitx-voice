#!/usr/bin/env bash
# RagebaitX AI commentary for one clip with no voice-over.
#   1. download the clip
#   2. read the AI script with Kokoro (free TTS) and make timed captions
#   3. turn the TTS voice into your voice with Applio (if a voice model is set up)
#   4. mix it over the game sound (game ducks while the voice talks), burn in captions
# Inputs (env, set by .github/workflows/narrate.yml):
#   CLIP_URL, PAYLOAD (JSON: script, pitch, index_rate, voice, game_volume), OUT_FILE, WORK_DIR,
#   PTH_PATH, INDEX_PATH, APPLIO_DIR, APPLIO_PY, TTS_PY
set -euo pipefail
WORK="${WORK_DIR:-$(mktemp -d)}"
mkdir -p "$WORK" "$(dirname "$OUT_FILE")"
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/download.sh"

field() { printf '%s' "$PAYLOAD" | jq -r --arg k "$1" --arg d "$2" '.[$k] // $d | tostring'; }
PITCH=$(field pitch 0)
INDEX_RATE=$(field index_rate 0.3)
VOICE=$(field voice am_michael)
GAME_VOLUME=$(field game_volume 0.9)
OFFSET=0.3
printf '%s' "$PAYLOAD" | jq -r '.script // ""' > "$WORK/script.txt"
if [ ! -s "$WORK/script.txt" ]; then echo "::error::No commentary script was sent."; exit 1; fi
echo "Script:"; cat "$WORK/script.txt"; echo

echo "::group::Download clip"
download_clip "$CLIP_URL" "$WORK/in.mp4"
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$WORK/in.mp4")
HAS_AUDIO=false
if ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$WORK/in.mp4" | grep -q .; then HAS_AUDIO=true; fi
echo "Duration ${DUR}s, game audio: $HAS_AUDIO"
echo "::endgroup::"

echo "::group::Read the script (Kokoro)"
"$TTS_PY" "$HERE/tts.py" "$WORK/script.txt" "$DUR" "$WORK/tts.wav" "$WORK/captions.ass" "$VOICE" "$OFFSET"
echo "::endgroup::"

VOICE_WAV="$WORK/tts.wav"
if [ -n "${PTH_PATH:-}" ] && [ -f "$PTH_PATH" ]; then
  echo "::group::Turn it into your voice (Applio)"
  ( cd "$APPLIO_DIR" && "$APPLIO_PY" core.py infer \
      --input-path "$WORK/tts.wav" --output-path "$WORK/voice.wav" \
      --pth-path "$PTH_PATH" --index-path "${INDEX_PATH:-}" \
      --pitch "$PITCH" --index-rate "$INDEX_RATE" --protect 0.33 --f0-method rmvpe --export-format WAV )
  test -s "$WORK/voice.wav" && VOICE_WAV="$WORK/voice.wav"
  echo "::endgroup::"
else
  echo "No voice model found, using the plain AI voice."
fi

echo "::group::Mix and add captions"
VF="scale='min(1080,iw)':'min(1920,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,subtitles=$WORK/captions.ass:fontsdir=/usr/share/fonts/truetype/dejavu"
DELAY_MS=$(awk -v o="$OFFSET" 'BEGIN { printf "%d", o * 1000 }')
VOICE_CHAIN="[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,adelay=${DELAY_MS}|${DELAY_MS},apad,volume=1.15"
if [ "$HAS_AUDIO" = "true" ]; then
  FILTER="${VOICE_CHAIN},asplit=2[v1][v2];[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume=${GAME_VOLUME}[g];[g][v2]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=400[gd];[gd][v1]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]"
else
  FILTER="${VOICE_CHAIN},loudnorm=I=-14:TP=-1.5:LRA=11[a]"
fi
ffmpeg -nostdin -hide_banner -loglevel error -y \
  -i "$WORK/in.mp4" -i "$VOICE_WAV" \
  -filter_complex "$FILTER" -map 0:v:0 -map "[a]" -vf "$VF" \
  -c:v libx264 -preset veryfast -crf 23 -maxrate 5M -bufsize 10M -pix_fmt yuv420p \
  -c:a aac -b:a 192k -ar 48000 -t "$DUR" -movflags +faststart "$OUT_FILE"
ls -lh "$OUT_FILE"
echo "::endgroup::"
echo "Done: $OUT_FILE"
