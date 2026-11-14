#!/usr/bin/env bash
# Long video, stage 2: builds the finished YouTube video.
#   1. download the long video (+ your intro and logo)
#   2. optionally remove the original talking (Demucs), keep the game sound
#   3. voice the AI's timed lines (ElevenLabs, else free Kokoro), each on its own moment
#   4. mix: game sound dips while the voice talks
#   5. 1080p 16:9, logo in the top-right corner, intro in front
#   6. upload straight into Google Drive (resumable upload link made by n8n)
# Inputs (env): VIDEO_URL, PAYLOAD (JSON: lines, intro_id, watermark_id, remove_voice, upload_url),
#               OUT_DIR, WORK_DIR, TTS_PY, DEMUCS_PY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID
set -euo pipefail
WORK="${WORK_DIR:-$(mktemp -d)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$WORK" "$OUT_DIR"
source "$HERE/download.sh"
field() { printf '%s' "$PAYLOAD" | jq -r --arg k "$1" --arg d "$2" '.[$k] // $d | tostring'; }
drive_dl() { curl -fsSL --retry 3 -o "$2" "https://drive.usercontent.google.com/download?id=$1&export=download&confirm=t"; }

echo "::group::Download"
download_clip "$VIDEO_URL" "$WORK/in.mp4"
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$WORK/in.mp4")
FPS=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of csv=p=0 "$WORK/in.mp4")
FPS=$(awk -F/ '{ f = ($2 ? $1 / $2 : $1); if (f > 60 || f < 20) f = 30; printf "%.3f", f }' <<<"$FPS")
HAS_AUDIO=false
if ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$WORK/in.mp4" | grep -q .; then HAS_AUDIO=true; fi
echo "Duration ${DUR}s, ${FPS} fps, game audio: $HAS_AUDIO"
INTRO_ID=$(field intro_id ""); WM_ID=$(field watermark_id "")
[ -n "$INTRO_ID" ] && drive_dl "$INTRO_ID" "$WORK/intro_raw" || INTRO_ID=""
if [ -n "$WM_ID" ] && drive_dl "$WM_ID" "$WORK/logo_raw" && ffmpeg -nostdin -loglevel error -y -i "$WORK/logo_raw" -frames:v 1 "$WORK/logo.png"; then :; else WM_ID=""; fi
echo "::endgroup::"

echo "::group::Game sound"
ffmpeg -nostdin -hide_banner -loglevel error -y -i "$WORK/in.mp4" -vn -ac 2 -ar 44100 "$WORK/game.wav" 2>/dev/null || HAS_AUDIO=false
GAME_WAV="$WORK/game.wav"
if [ "$HAS_AUDIO" = "true" ] && [ "$(field remove_voice false)" = "true" ] && [ -x "${DEMUCS_PY:-}" ]; then
  echo "Removing the original talking (this takes a while on long videos)..."
  "$DEMUCS_PY" -m demucs --two-stems=vocals -n htdemucs -d cpu --segment 7 -o "$WORK/sep" "$WORK/game.wav"
  [ -s "$WORK/sep/htdemucs/game/no_vocals.wav" ] && GAME_WAV="$WORK/sep/htdemucs/game/no_vocals.wav"
fi
echo "::endgroup::"

echo "::group::Voice the timed lines"
printf '%s' "$PAYLOAD" | jq -c '.lines // []' > "$WORK/lines.json"
echo "$(jq length "$WORK/lines.json") lines"
ENGINE=kokoro; VID="am_puck"
if [ -n "${ELEVENLABS_API_KEY:-}" ] && [ -n "${ELEVENLABS_VOICE_ID:-}" ]; then ENGINE=eleven; VID="$ELEVENLABS_VOICE_ID"; fi
if ! TTS_SPEED=1.05 "$TTS_PY" "$HERE/tts_timed.py" "$WORK/lines.json" "$DUR" "$WORK/voice.wav" "$WORK/captions.ass" "$ENGINE" "$VID" 0.2; then
  [ "$ENGINE" = "eleven" ] || exit 1
  echo "::warning::ElevenLabs failed, using the free voice."
  TTS_SPEED=1.05 "$TTS_PY" "$HERE/tts_timed.py" "$WORK/lines.json" "$DUR" "$WORK/voice.wav" "$WORK/captions.ass" kokoro am_puck 0.2
fi
echo "::endgroup::"

echo "::group::Mix and render the main video"
VOICE_CHAIN="[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad,volume=1.2"
if [ "$HAS_AUDIO" = "true" ]; then
  AF="${VOICE_CHAIN},asplit=2[v1][v2];[2:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume=0.85[g];[g][v2]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=500[gd];[gd][v1]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]"
  AUDIO_IN=(-i "$WORK/voice.wav" -i "$GAME_WAV")
else
  AF="${VOICE_CHAIN},loudnorm=I=-14:TP=-1.5:LRA=11[a]"
  AUDIO_IN=(-i "$WORK/voice.wav")
fi
BASE="scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=${FPS}"
if [ -n "$WM_ID" ]; then
  VCHAIN="[0:v]${BASE}[vb];movie=$WORK/logo.png,scale=w=200:h=110:force_original_aspect_ratio=decrease,format=rgba,colorchannelmixer=aa=0.75[wm];[vb][wm]overlay=W-w-40:36:eof_action=repeat,format=yuv420p[v]"
else
  VCHAIN="[0:v]${BASE},format=yuv420p[v]"
fi
ffmpeg -nostdin -hide_banner -loglevel error -stats -y -i "$WORK/in.mp4" "${AUDIO_IN[@]}" \
  -filter_complex "${VCHAIN};${AF}" -map "[v]" -map "[a]" \
  -c:v libx264 -preset veryfast -crf 22 -maxrate 8M -bufsize 16M -g "$(printf '%.0f' "$(awk -v f="$FPS" 'BEGIN{print f*2}')")" \
  -c:a aac -b:a 192k -ar 48000 -ac 2 -t "$DUR" -movflags +faststart "$WORK/main.mp4"
echo "::endgroup::"

FINAL="$WORK/main.mp4"
if [ -n "$INTRO_ID" ]; then
  echo "::group::Put the intro in front"
  if ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$WORK/intro_raw" | grep -q .; then
    IA=(-map 0:a:0); IAF="aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
  else
    IA=(-map 1:a:0); IAF="anull"
  fi
  ffmpeg -nostdin -hide_banner -loglevel error -y -i "$WORK/intro_raw" -f lavfi -i "anullsrc=r=48000:cl=stereo" \
    -map 0:v:0 "${IA[@]}" -vf "${BASE},format=yuv420p" -af "$IAF" -shortest \
    -c:v libx264 -preset veryfast -crf 20 -c:a aac -b:a 192k -ar 48000 -ac 2 "$WORK/intro.mp4"
  printf "file '%s'\nfile '%s'\n" "$WORK/intro.mp4" "$WORK/main.mp4" > "$WORK/list.txt"
  ffmpeg -nostdin -hide_banner -loglevel error -y -f concat -safe 0 -i "$WORK/list.txt" -c copy -movflags +faststart "$WORK/final.mp4"
  FINAL="$WORK/final.mp4"
  echo "::endgroup::"
fi
ls -lh "$FINAL"

echo "::group::Upload to Google Drive"
UPLOAD_URL=$(field upload_url "")
if [ -z "$UPLOAD_URL" ]; then echo "::error::No Drive upload link was sent."; exit 1; fi
curl -fsS --retry 3 --retry-delay 10 -X PUT -H "Content-Type: video/mp4" --upload-file "$FINAL" "$UPLOAD_URL" -o "$OUT_DIR/drive.json"
cat "$OUT_DIR/drive.json"; echo
jq -r '.id // empty' "$OUT_DIR/drive.json" > "$OUT_DIR/drive_id.txt"
[ -s "$OUT_DIR/drive_id.txt" ] || { echo "::error::Drive did not return a file id."; exit 1; }
echo "::endgroup::"
echo "drive_id=$(cat "$OUT_DIR/drive_id.txt")" >> "$GITHUB_OUTPUT"
echo "size_mb=$(du -m "$FINAL" | cut -f1)" >> "$GITHUB_OUTPUT"
