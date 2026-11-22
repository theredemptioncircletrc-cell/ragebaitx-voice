#!/usr/bin/env bash
# Adds your intro (slides in) and outro (fades in through black) to an already finished long video,
# without touching the voice or the edit. Used to fix videos that were made without them.
#   usage: wrap.sh MAIN.mp4 INTRO_ID OUTRO_ID OUT.mp4
set -euo pipefail
MAIN="$1"; INTRO_ID="$2"; OUTRO_ID="$3"; OUT="$4"
T=$(mktemp -d)
dl() { [ -f "$1" ] && { cp "$1" "$2"; return 0; }; curl -fsSL --retry 3 -o "$2" "https://drive.usercontent.google.com/download?id=$1&export=download&confirm=t" && ffprobe -v error "$2" >/dev/null 2>&1; }
IFS=, read -r W H < <(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$MAIN")
FPS=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of csv=p=0 "$MAIN")
FPS=$(awk -F/ '{ f = ($2 ? $1 / $2 : $1); if (f > 60 || f < 20) f = 30; printf "%.3f", f }' <<<"$FPS")
NORM="scale=${W}:${H}:force_original_aspect_ratio=decrease:flags=lanczos,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=${FPS},format=yuv420p,settb=AVTB"
AFMT="aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
dur() { ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"; }
INS=(-i "$MAIN"); FC="[0:v]${NORM}[vm];[0:a]${AFMT}[am]"; V="[vm]"; A="[am]"; N=1
LEN=$(dur "$MAIN")
if [ -n "$INTRO_ID" ] && dl "$INTRO_ID" "$T/intro"; then
  ID=$(dur "$T/intro"); TI=0.7
  if ! ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$T/intro" | grep -q .; then
    ffmpeg -nostdin -loglevel error -y -i "$T/intro" -f lavfi -i anullsrc=r=48000:cl=stereo -shortest -c:v copy -c:a aac "$T/intro.mp4"; mv "$T/intro.mp4" "$T/intro"
  fi
  INS+=(-i "$T/intro"); OFF=$(awk -v d="$ID" -v t="$TI" 'BEGIN { printf "%.3f", d - t }')
  FC+=";[$N:v]${NORM}[vi];[vi]${V}xfade=transition=smoothleft:duration=${TI}:offset=${OFF}[v1];[$N:a]${AFMT}[ai];[ai]${A}acrossfade=d=${TI}:c1=tri:c2=tri[a1]"
  V="[v1]"; A="[a1]"; N=$((N+1)); LEN=$(awk -v l="$LEN" -v d="$ID" -v t="$TI" 'BEGIN { printf "%.3f", l + d - t }')
  echo "Intro added: ${ID}s"
fi
if [ -n "$OUTRO_ID" ] && dl "$OUTRO_ID" "$T/outro"; then
  TO=1.0
  if ! ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$T/outro" | grep -q .; then
    ffmpeg -nostdin -loglevel error -y -i "$T/outro" -f lavfi -i anullsrc=r=48000:cl=stereo -shortest -c:v copy -c:a aac "$T/outro.mp4"; mv "$T/outro.mp4" "$T/outro"
  fi
  INS+=(-i "$T/outro"); OFF=$(awk -v l="$LEN" -v t="$TO" 'BEGIN { printf "%.3f", l - t }')
  FC+=";[$N:v]${NORM}[vo];${V}[vo]xfade=transition=fadeblack:duration=${TO}:offset=${OFF}[v2];[$N:a]${AFMT}[ao];${A}[ao]acrossfade=d=${TO}:c1=tri:c2=tri[a2]"
  V="[v2]"; A="[a2]"
  echo "Outro added: $(dur "$T/outro")s"
fi
GOP=$(awk -v f="$FPS" 'BEGIN { printf "%.0f", f * 2 }')
ffmpeg -nostdin -hide_banner -loglevel error -stats -y "${INS[@]}" -filter_complex "$FC" -map "$V" -map "$A" \
  -c:v libx264 -preset superfast -crf 19 -maxrate 35M -bufsize 70M -g "$GOP" -pix_fmt yuv420p \
  -c:a aac -b:a 192k -ar 48000 -ac 2 -movflags +faststart "$OUT"
ls -lh "$OUT"
