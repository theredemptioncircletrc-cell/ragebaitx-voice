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
# Optional trim (highlight moments): payload start/end are seconds inside the downloaded clip.
CUT_START=$(field start "")
CUT_END=$(field end "")
if [ -n "$CUT_START" ] && [ -n "$CUT_END" ] && awk -v s="$CUT_START" -v e="$CUT_END" 'BEGIN { exit !(e - s >= 3) }'; then
  CUT_LEN=$(awk -v s="$CUT_START" -v e="$CUT_END" 'BEGIN { printf "%.2f", e - s }')
  echo "Trimming to ${CUT_START}s - ${CUT_END}s (${CUT_LEN}s)"
  ffmpeg -nostdin -hide_banner -loglevel error -y -ss "$CUT_START" -i "$WORK/in.mp4" -t "$CUT_LEN" \
    -map 0:v:0 -map '0:a:0?' -c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p -c:a aac -b:a 192k "$WORK/cut.mp4"
  mv "$WORK/cut.mp4" "$WORK/in.mp4"
fi
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
# Optional hook headline at the top of the screen for the whole clip.
HOOK=$(printf '%s' "$PAYLOAD" | jq -r '.hook_text // ""' | tr '\n' ' ' | sed 's/[{}\\]//g' | cut -c1-90)
if [ -n "$HOOK" ]; then
  HOOK_END=$(awk -v d="$DUR" 'BEGIN { h=int(d/3600); m=int((d%3600)/60); s=d-h*3600-m*60; printf "%d:%02d:%05.2f", h, m, s }')
  sed -i '/^Style: Cap,/a Style: Hook,DejaVu Sans,74,\&H0000E5FF,\&H00FFFFFF,\&H00000000,\&H96000000,-1,0,0,0,100,100,0,0,1,7,3,8,70,70,190,1' "$WORK/captions.ass"
  printf 'Dialogue: 1,0:00:00.00,%s,Hook,,0,0,0,,%s\n' "$HOOK_END" "$HOOK" >> "$WORK/captions.ass"
fi
SUBS="subtitles=$WORK/captions.ass:fontsdir=/usr/share/fonts/truetype/dejavu"
VW=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 "$WORK/in.mp4")
VH=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 "$WORK/in.mp4")
if [ "$(field vertical false)" = "true" ] && [ "${VW:-0}" -gt "${VH:-0}" ]; then
  # Landscape gameplay -> 9:16 Short: blurred copy fills the screen, the game sits a little
  # zoomed in the middle, hook text above it, captions below it.
  VF="split[m][b];[b]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:3,eq=brightness=-0.12[bg];[m]scale=1296:-2,crop=1080:ih[fg];[bg][fg]overlay=(W-w)/2:520,setsar=1,$SUBS"
else
  VF="scale='min(1080,iw)':'min(1920,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,$SUBS"
fi
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
