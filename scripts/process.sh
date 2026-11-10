#!/usr/bin/env bash
# RagebaitX voice pipeline for one clip.
#   1. download the clip
#   2. pull the audio out (ffmpeg)
#   3. split voice from game sound (Demucs), optional
#   4. change the voice (Applio / RVC)
#   5. mix the new voice with the game sound, level the volume, and put it back
#      on the original video without re-encoding the picture (ffmpeg)
#
# Inputs come from environment variables (set by .github/workflows/voice.yml):
#   CLIP_URL, OUT_FILE, PTH_PATH, INDEX_PATH, SEPARATE_VOICE, PITCH, INDEX_RATE,
#   PROTECT, F0_METHOD, VOICE_VOLUME, GAME_VOLUME, APPLIO_DIR, APPLIO_PY, DEMUCS_PY
set -euo pipefail

WORK="${WORK_DIR:-$(mktemp -d)}"
mkdir -p "$WORK" "$(dirname "$OUT_FILE")"

SEPARATE_VOICE="${SEPARATE_VOICE:-true}"
PITCH="${PITCH:-0}"
INDEX_RATE="${INDEX_RATE:-0.3}"
PROTECT="${PROTECT:-0.33}"
F0_METHOD="${F0_METHOD:-rmvpe}"
VOICE_VOLUME="${VOICE_VOLUME:-1.0}"
GAME_VOLUME="${GAME_VOLUME:-0.8}"
# Playback speed for the finished clip (1.0 = unchanged). Speeds up picture and sound together,
# so the voice talks faster but stays in sync with the video. The pitch is not changed by this.
SPEED="${SPEED:-1.0}"
if ! awk -v s="$SPEED" 'BEGIN { exit !(s+0 >= 0.5 && s+0 <= 2) }'; then
  echo "::warning::SPEED '$SPEED' is not between 0.5 and 2, using 1.0"; SPEED=1.0
fi

log() { echo "::group::$*"; }
end() { echo "::endgroup::"; }

log "Download clip"
if [[ "$CLIP_URL" == release:* ]]; then
  # Test mode: "release:<tag>" downloads the first .mp4 attached to that release of this repo.
  TAG="${CLIP_URL#release:}"
  gh release download "$TAG" -R "$GITHUB_REPOSITORY" -p '*.mp4' -O "$WORK/in.mp4" --clobber
else
  URL="$CLIP_URL"
  # Turn a normal Google Drive share link into a direct download link.
  if [[ "$URL" =~ drive\.google\.com/file/d/([A-Za-z0-9_-]+) ]] || [[ "$URL" =~ drive\.google\.com/.*[?\&]id=([A-Za-z0-9_-]+) ]]; then
    URL="https://drive.usercontent.google.com/download?id=${BASH_REMATCH[1]}&export=download&confirm=t"
  fi
  curl -fsSL --retry 3 --retry-delay 5 -o "$WORK/in.mp4" "$URL"
fi
ls -lh "$WORK/in.mp4"
if ! ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$WORK/in.mp4" | grep -q .; then
  echo "::error::The clip has no audio track, nothing to voice-change."
  exit 1
fi
end

log "Extract audio"
ffmpeg -nostdin -hide_banner -loglevel error -y -i "$WORK/in.mp4" -vn -ac 2 -ar 44100 -c:a pcm_s16le "$WORK/audio.wav"
end

VOICE_IN="$WORK/audio.wav"
GAME=""
if [ "$SEPARATE_VOICE" = "true" ]; then
  log "Split voice from game sound (Demucs)"
  "$DEMUCS_PY" -m demucs --two-stems=vocals -n htdemucs -d cpu -o "$WORK/sep" "$WORK/audio.wav"
  VOICE_IN="$WORK/sep/htdemucs/audio/vocals.wav"
  GAME="$WORK/sep/htdemucs/audio/no_vocals.wav"
  ls -lh "$VOICE_IN" "$GAME"
  end
fi

log "Change voice (Applio)"
INDEX_ARGS=(--index-path "${INDEX_PATH:-}")
( cd "$APPLIO_DIR" && "$APPLIO_PY" core.py infer \
    --input-path "$VOICE_IN" \
    --output-path "$WORK/voice.wav" \
    --pth-path "$PTH_PATH" \
    "${INDEX_ARGS[@]}" \
    --pitch "$PITCH" \
    --index-rate "$INDEX_RATE" \
    --protect "$PROTECT" \
    --f0-method "$F0_METHOD" \
    --export-format WAV )
test -s "$WORK/voice.wav" || { echo "::error::Applio produced no audio."; exit 1; }
end

log "Mix and rebuild video"
# Re-encode to a social-media friendly size (about 5 Mbps, max 1080x1920) so files stay small
# enough for n8n to upload without running out of memory. Set VIDEO_REENCODE=false to keep the original.
SPEED_ON=$(awk -v s="$SPEED" 'BEGIN { print (s+0 == 1) ? "false" : "true" }')
if [ "${VIDEO_REENCODE:-true}" = "true" ] || [ "$SPEED_ON" = "true" ]; then
  VF="scale='min(1080,iw)':'min(1920,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"
  [ "$SPEED_ON" = "true" ] && VF="setpts=PTS/${SPEED},${VF}"
  VIDEO_ARGS=(-c:v libx264 -preset veryfast -crf 23 -maxrate "${VIDEO_MAXRATE:-5M}" -bufsize 10M -pix_fmt yuv420p -vf "$VF")
else
  VIDEO_ARGS=(-c:v copy)
fi
TEMPO=""
[ "$SPEED_ON" = "true" ] && TEMPO=",atempo=${SPEED}"
echo "Playback speed: ${SPEED}x"
if [ -n "$GAME" ]; then
  FILTER="[1:a]aresample=44100,volume=${VOICE_VOLUME}[v];[2:a]aresample=44100,volume=${GAME_VOLUME}[g];[v][g]amix=inputs=2:duration=longest:normalize=0${TEMPO},loudnorm=I=-14:TP=-1.5:LRA=11[a]"
  ffmpeg -nostdin -hide_banner -loglevel error -y \
    -i "$WORK/in.mp4" -i "$WORK/voice.wav" -i "$GAME" \
    -filter_complex "$FILTER" \
    -map 0:v:0 -map "[a]" "${VIDEO_ARGS[@]}" -c:a aac -b:a 192k -ar 48000 \
    -shortest -movflags +faststart "$OUT_FILE"
else
  FILTER="[1:a]aresample=44100,volume=${VOICE_VOLUME}${TEMPO},loudnorm=I=-14:TP=-1.5:LRA=11[a]"
  ffmpeg -nostdin -hide_banner -loglevel error -y \
    -i "$WORK/in.mp4" -i "$WORK/voice.wav" \
    -filter_complex "$FILTER" \
    -map 0:v:0 -map "[a]" "${VIDEO_ARGS[@]}" -c:a aac -b:a 192k -ar 48000 \
    -shortest -movflags +faststart "$OUT_FILE"
fi
ls -lh "$OUT_FILE"
end

echo "Done: $OUT_FILE"
