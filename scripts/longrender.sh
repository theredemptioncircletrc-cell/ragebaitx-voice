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
INTRO_ID=$(field intro_id ""); OUTRO_ID=$(field outro_id ""); MUSIC_ID=$(field music_id ""); WM_ID=$(field watermark_id "")
[ -n "$INTRO_ID" ] && drive_dl "$INTRO_ID" "$WORK/intro_raw" || INTRO_ID=""
[ -n "$OUTRO_ID" ] && drive_dl "$OUTRO_ID" "$WORK/outro_raw" || OUTRO_ID=""
[ -n "$MUSIC_ID" ] && drive_dl "$MUSIC_ID" "$WORK/music_raw" && ffmpeg -nostdin -loglevel error -y -i "$WORK/music_raw" -vn -ac 2 -ar 48000 "$WORK/music.wav" || MUSIC_ID=""
if [ -n "$WM_ID" ] && drive_dl "$WM_ID" "$WORK/logo_raw" && ffmpeg -nostdin -loglevel error -y -i "$WORK/logo_raw" -frames:v 1 "$WORK/logo.png"; then :; else WM_ID=""; fi
echo "::endgroup::"

echo "::group::Edit (cut to the best parts)"
# payload.segments = [[start, end], ...] in seconds of the original video, in order.
# Each part is cut, then they are joined with short varied transitions (fade, slide, dip to black).
SEG_JSON=$(printf '%s' "$PAYLOAD" | jq -c '[.segments // [] | .[] | select(length == 2) | map(tonumber)] | map(select(.[1] - .[0] >= 2))')
NSEG=$(jq length <<<"$SEG_JSON")
XT=0.5
if [ "$NSEG" -ge 1 ]; then
  CUTBASE="scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=${FPS},format=yuv420p,settb=AVTB"
  CUT_INS=(); i=0
  while [ "$i" -lt "$NSEG" ]; do
    SS=$(jq -r ".[$i][0]" <<<"$SEG_JSON"); EE=$(jq -r ".[$i][1]" <<<"$SEG_JSON")
    LEN=$(awk -v a="$SS" -v b="$EE" 'BEGIN { printf "%.3f", b - a }')
    if [ "$HAS_AUDIO" = "true" ]; then
      ffmpeg -nostdin -hide_banner -loglevel error -y -ss "$SS" -i "$WORK/in.mp4" -t "$LEN" -map 0:v:0 -map 0:a:0 \
        -vf "$CUTBASE" -af "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo" -c:v libx264 -preset veryfast -crf 17 -c:a pcm_s16le "$WORK/seg_$i.mkv"
    else
      ffmpeg -nostdin -hide_banner -loglevel error -y -ss "$SS" -i "$WORK/in.mp4" -f lavfi -i "anullsrc=r=48000:cl=stereo" -t "$LEN" -map 0:v:0 -map 1:a:0 \
        -vf "$CUTBASE" -c:v libx264 -preset veryfast -crf 17 -c:a pcm_s16le "$WORK/seg_$i.mkv"
    fi
    CUT_INS+=(-i "$WORK/seg_$i.mkv"); i=$((i+1))
  done
  if [ "$NSEG" -eq 1 ]; then
    ffmpeg -nostdin -hide_banner -loglevel error -y -i "$WORK/seg_0.mkv" -c:v copy -c:a aac -b:a 256k "$WORK/edited.mp4"
  else
    TRANS=(fade smoothleft fadeblack fade slideright dissolve fade smoothright)
    FCC=""; V="[0:v]"; A="[0:a]"; ACC=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$WORK/seg_0.mkv")
    i=1
    while [ "$i" -lt "$NSEG" ]; do
      OFF=$(awk -v a="$ACC" -v t="$XT" 'BEGIN { printf "%.3f", a - t }')
      TR=${TRANS[$(( (i-1) % ${#TRANS[@]} ))]}
      FCC+="${V}[$i:v]xfade=transition=${TR}:duration=${XT}:offset=${OFF}[cv$i];${A}[$i:a]acrossfade=d=${XT}:c1=tri:c2=tri[ca$i];"
      V="[cv$i]"; A="[ca$i]"
      L=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$WORK/seg_$i.mkv")
      ACC=$(awk -v a="$ACC" -v l="$L" -v t="$XT" 'BEGIN { printf "%.3f", a + l - t }')
      i=$((i+1))
    done
    ffmpeg -nostdin -hide_banner -loglevel error -stats -y "${CUT_INS[@]}" -filter_complex "${FCC%;}" -map "$V" -map "$A" \
      -c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p -c:a aac -b:a 256k "$WORK/edited.mp4"
  fi
  mv "$WORK/edited.mp4" "$WORK/in.mp4"; rm -f "$WORK"/seg_*.mkv
  DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$WORK/in.mp4")
  HAS_AUDIO=false
  if ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$WORK/in.mp4" | grep -q .; then HAS_AUDIO=true; fi
  echo "Edited down to ${NSEG} parts, new length ${DUR}s"
else
  echo "No edit list, keeping the full video."
fi
echo "::endgroup::"

echo "::group::Game sound"
ffmpeg -nostdin -hide_banner -loglevel error -y -i "$WORK/in.mp4" -vn -ac 2 -ar 44100 "$WORK/game.wav" 2>/dev/null || HAS_AUDIO=false
GAME_WAV="$WORK/game.wav"
if [ "$HAS_AUDIO" = "true" ]; then
  # A silent sound track (muted VOD) counts as no game sound: nothing to remove, nothing to mix.
  PEAK=$(ffmpeg -nostdin -hide_banner -i "$WORK/game.wav" -af volumedetect -f null - 2>&1 | sed -n 's/.*max_volume: \(-*[0-9.]*\) dB.*/\1/p' | tail -1)
  if [ -z "$PEAK" ] || awk -v p="$PEAK" 'BEGIN { exit !(p < -60) }'; then
    echo "::warning::The video's sound track is silent (max ${PEAK:-?} dB), so there is no game sound to keep."
    HAS_AUDIO=false
  fi
fi
SWAP=false
printf '%s' "$PAYLOAD" | jq -c '.lines // []' > "$WORK/lines.json"
if [ "$HAS_AUDIO" = "true" ] && [ "$(field sound "")" = "swap_music" ] && [ -x "${DEMUCS_PY:-}" ]; then
  # Keep your mic + the game effects, take the music out (your song goes in instead),
  # and drop AI lines that would talk over you.
  echo "Swapping the music out, keeping the talking and the game effects..."
  if "$TTS_PY" "$HERE/audio_swap.py" "$WORK/game.wav" "$WORK/swap" "$DEMUCS_PY" "$WORK/lines.json"; then
    GAME_WAV="$WORK/swap/game_nomusic.wav"; SWAP=true
  else
    echo "::warning::Could not take the music out, keeping the original sound."
  fi
elif [ "$HAS_AUDIO" = "true" ] && [ "$(field remove_voice false)" = "true" ] && [ -x "${DEMUCS_PY:-}" ]; then
  echo "Removing the original talking (this takes a while on long videos)..."
  if "$DEMUCS_PY" -m demucs --two-stems=vocals -n htdemucs -d cpu -o "$WORK/sep" "$WORK/game.wav" && [ -s "$WORK/sep/htdemucs/game/no_vocals.wav" ]; then
    GAME_WAV="$WORK/sep/htdemucs/game/no_vocals.wav"
  else
    echo "::warning::Could not remove the original talking, keeping the original game sound."
  fi
fi
echo "::endgroup::"

echo "::group::Voice the timed lines"
echo "$(jq length "$WORK/lines.json") lines"
ENGINE=kokoro; VID="am_puck"
if [ -n "${ELEVENLABS_API_KEY:-}" ] && [ -n "${ELEVENLABS_VOICE_ID:-}" ]; then ENGINE=eleven; VID="$ELEVENLABS_VOICE_ID"; fi
if [ "$(jq length "$WORK/lines.json")" -eq 0 ]; then
  echo "No AI lines left (you talk the whole way through), no AI voice."
  ffmpeg -nostdin -loglevel error -y -f lavfi -i "anullsrc=r=24000:cl=mono" -t "$DUR" "$WORK/voice.wav"
elif ! WORDS_OUT="$WORK/words.json" TTS_SPEED=1.05 "$TTS_PY" "$HERE/tts_timed.py" "$WORK/lines.json" "$DUR" "$WORK/voice.wav" "$WORK/captions.ass" "$ENGINE" "$VID" 0.2; then
  [ "$ENGINE" = "eleven" ] || exit 1
  echo "::warning::ElevenLabs failed, using the free voice."
  WORDS_OUT="$WORK/words.json" TTS_SPEED=1.05 "$TTS_PY" "$HERE/tts_timed.py" "$WORK/lines.json" "$DUR" "$WORK/voice.wav" "$WORK/captions.ass" kokoro am_puck 0.2
fi
echo "::endgroup::"


BASE="scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=${FPS},format=yuv420p,settb=AVTB"
AFMT="aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"

# Intro / outro: normalise to the same size, frame rate and sound format as the main video.
prep_clip() {  # prep_clip <in> <out>
  if ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$1" | grep -q .; then
    ffmpeg -nostdin -hide_banner -loglevel error -y -i "$1" -map 0:v:0 -map 0:a:0 -vf "$BASE" -af "$AFMT" \
      -c:v libx264 -preset veryfast -crf 18 -c:a pcm_s16le "$2"
  else
    ffmpeg -nostdin -hide_banner -loglevel error -y -i "$1" -f lavfi -i "anullsrc=r=48000:cl=stereo" -map 0:v:0 -map 1:a:0 -shortest \
      -vf "$BASE" -c:v libx264 -preset veryfast -crf 18 -c:a pcm_s16le "$2"
  fi
}
dur_of() { ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"; }
IDUR=0; ODUR=0
if [ -n "$INTRO_ID" ] && prep_clip "$WORK/intro_raw" "$WORK/intro.mkv"; then IDUR=$(dur_of "$WORK/intro.mkv"); else INTRO_ID=""; fi
if [ -n "$OUTRO_ID" ] && prep_clip "$WORK/outro_raw" "$WORK/outro.mkv"; then ODUR=$(dur_of "$WORK/outro.mkv"); else OUTRO_ID=""; fi
# Transition lengths (shorter if the intro/outro itself is very short).
TI=$(awk -v d="$IDUR" 'BEGIN { t = 0.7; if (d < 2) t = 0.3; printf "%.2f", t }')
TO=$(awk -v d="$ODUR" 'BEGIN { t = 1.0; if (d < 2.5) t = 0.4; printf "%.2f", t }')
echo "Intro ${IDUR}s, outro ${ODUR}s, music: ${MUSIC_ID:+yes}"
# Chapter times shift by how long the intro shows before the video starts.
INTRO_S=$(awk -v d="$IDUR" -v t="$TI" -v i="$INTRO_ID" 'BEGIN { printf "%.2f", (i != "" ? d - t : 0) }')

echo "::group::Subtitles and chapter cards"
printf '%s' "$PAYLOAD" > "$WORK/payload.json"
SUBS_VF=""
if [ -s "$WORK/words.json" ] && python3 "$HERE/long_subs.py" "$WORK/words.json" "$WORK/payload.json" "$WORK/long.ass" "$OUT_DIR/subs.srt" "$INTRO_S"; then
  SUBS_VF=",subtitles=$WORK/long.ass:fontsdir=/usr/share/fonts/truetype/dejavu"
else
  echo "::warning::Could not make subtitles, rendering without them."
fi
echo "::endgroup::"

echo "::group::Mix and render the full video (intro + video + outro in one pass)"
INS=(-i "$WORK/in.mp4" -i "$WORK/voice.wav"); N=2
GI=""; MI=""; II=""; OI=""
if [ "$HAS_AUDIO" = "true" ]; then INS+=(-i "$GAME_WAV"); GI=$N; N=$((N+1)); fi
if [ -n "$MUSIC_ID" ]; then INS+=(-stream_loop -1 -i "$WORK/music.wav"); MI=$N; N=$((N+1)); fi
VK=""
if [ "$SWAP" = "true" ]; then INS+=(-i "$WORK/swap/vocals.wav"); VK=$N; N=$((N+1)); fi
if [ -n "$INTRO_ID" ]; then INS+=(-i "$WORK/intro.mkv"); II=$N; N=$((N+1)); fi
if [ -n "$OUTRO_ID" ]; then INS+=(-i "$WORK/outro.mkv"); OI=$N; N=$((N+1)); fi

# --- main video: 16:9 + logo
if [ -n "$WM_ID" ]; then
  FC="[0:v]${BASE},trim=0:${DUR},setpts=PTS-STARTPTS[vb];movie=$WORK/logo.png,scale=w=200:h=110:force_original_aspect_ratio=decrease,format=rgba,colorchannelmixer=aa=0.75[wm];[vb][wm]overlay=W-w-40:36:eof_action=repeat${SUBS_VF},format=yuv420p[vm]"
else
  FC="[0:v]${BASE},trim=0:${DUR},setpts=PTS-STARTPTS${SUBS_VF}[vm]"
fi
# --- main sound: voice on top, game and music dip while you talk
FADE_OUT=$(awk -v d="$DUR" 'BEGIN { printf "%.2f", (d > 8 ? d - 5 : 0) }')
FC+=";[1:a]${AFMT},apad,atrim=0:${DUR},volume=1.2,asplit=3[sp1][sp2][sp3]"
MIX="[sp1]"; K=1
if [ -n "$GI" ]; then
  FC+=";[${GI}:a]${AFMT},apad,atrim=0:${DUR},volume=0.85[g];[g][sp2]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=500[gd]"
  MIX+="[gd]"; K=$((K+1))
else
  FC+=";[sp2]anullsink"
fi
if [ -n "$MI" ]; then
  # Calm music bed: quiet, fades in and out, ducks further under the voice.
  if [ -n "$VK" ]; then
    # Music swapped out: your song is the main music, so a bit louder, and it ducks under you AND the AI voice.
    FC+=";[${VK}:a]${AFMT},apad,atrim=0:${DUR}[vk];[sp3][vk]amix=inputs=2:normalize=0[key]"
    FC+=";[${MI}:a]${AFMT},atrim=0:${DUR},volume=0.22,afade=in:st=0:d=3,afade=out:st=${FADE_OUT}:d=5[m];[m][key]sidechaincompress=threshold=0.015:ratio=8:attack=20:release=700[md]"
  else
    FC+=";[${MI}:a]${AFMT},atrim=0:${DUR},volume=0.09,afade=in:st=0:d=3,afade=out:st=${FADE_OUT}:d=5[m];[m][sp3]sidechaincompress=threshold=0.01:ratio=10:attack=20:release=900[md]"
  fi
  MIX+="[md]"; K=$((K+1))
else
  FC+=";[sp3]anullsink"
fi
FC+=";${MIX}amix=inputs=${K}:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11,${AFMT}[am]"

# --- intro -> video: smooth slide; video -> outro: fade through black
V="[vm]"; A="[am]"; LEN="$DUR"
if [ -n "$II" ]; then
  OFF=$(awk -v d="$IDUR" -v t="$TI" 'BEGIN { printf "%.3f", d - t }')
  FC+=";[${II}:v]settb=AVTB[vi];[vi]${V}xfade=transition=smoothleft:duration=${TI}:offset=${OFF}[v1];[${II}:a]${AFMT}[ai];[ai]${A}acrossfade=d=${TI}:c1=tri:c2=tri[a1]"
  V="[v1]"; A="[a1]"; LEN=$(awk -v l="$LEN" -v d="$IDUR" -v t="$TI" 'BEGIN { printf "%.3f", l + d - t }')
fi
if [ -n "$OI" ]; then
  OFF=$(awk -v l="$LEN" -v t="$TO" 'BEGIN { printf "%.3f", l - t }')
  FC+=";[${OI}:v]settb=AVTB[vo];${V}[vo]xfade=transition=fadeblack:duration=${TO}:offset=${OFF}[v2x];[${OI}:a]${AFMT}[ao];${A}[ao]acrossfade=d=${TO}:c1=tri:c2=tri[a2x]"
  V="[v2x]"; A="[a2x]"
fi

GOP=$(awk -v f="$FPS" 'BEGIN { printf "%.0f", f * 2 }')
# 4K export: keep this step near-lossless, the 4K pass does the final compression.
if [ "$(field quality normal)" = "4k" ]; then FCRF=15; FMAX=30M; else FCRF=22; FMAX=8M; fi
ffmpeg -nostdin -hide_banner -loglevel error -stats -y "${INS[@]}" \
  -filter_complex "$FC" -map "$V" -map "$A" \
  -c:v libx264 -preset veryfast -crf "$FCRF" -maxrate "$FMAX" -bufsize 16M -g "$GOP" -pix_fmt yuv420p \
  -c:a aac -b:a 192k -ar 48000 -ac 2 -movflags +faststart "$WORK/final.mp4"
FINAL="$WORK/final.mp4"
echo "::endgroup::"
ls -lh "$FINAL"
if [ "$(field quality normal)" = "4k" ]; then
  echo "::group::4K export (clean-up + upscale + sharpen)"
  if bash "$HERE/enhance.sh" "$FINAL" "$WORK/final_4k.mp4"; then FINAL="$WORK/final_4k.mp4"; else echo "::warning::4K export failed, uploading the normal version."; fi
  echo "::endgroup::"
fi

echo "::group::Upload to Google Drive"
UPLOAD_URL=$(field upload_url "")
if [ -z "$UPLOAD_URL" ]; then echo "::error::No Drive upload link was sent."; exit 1; fi
# Upload in 64 MB pieces with automatic resume (big 4K files); shows Google's reason if it really refuses.
python3 "$HERE/drive_upload.py" "$FINAL" "$UPLOAD_URL" "$OUT_DIR/drive.json"
cat "$OUT_DIR/drive.json"; echo
jq -r '.id // empty' "$OUT_DIR/drive.json" > "$OUT_DIR/drive_id.txt"
[ -s "$OUT_DIR/drive_id.txt" ] || { echo "::error::Drive did not return a file id."; exit 1; }
echo "::endgroup::"
echo "drive_id=$(cat "$OUT_DIR/drive_id.txt")" >> "$GITHUB_OUTPUT"
echo "size_mb=$(du -m "$FINAL" | cut -f1)" >> "$GITHUB_OUTPUT"
echo "intro_s=${INTRO_S}" >> "$GITHUB_OUTPUT"
