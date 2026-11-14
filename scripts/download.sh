#!/usr/bin/env bash
# Shared helper: download_clip <url> <out.mp4>
# Accepts a direct MP4 link, a Google Drive share link, or release:<tag> (first .mp4 on that release).
download_clip() {
  local url="$1" out="$2"
  if [[ "$url" == release:*/* ]]; then
    # release:<tag>/<file name> = that one file on the release (used by the highlight moments)
    local rel="${url#release:}"
    gh release download "${rel%%/*}" -R "$GITHUB_REPOSITORY" -p "${rel#*/}" -O "$out" --clobber
  elif [[ "$url" == release:* ]]; then
    gh release download "${url#release:}" -R "$GITHUB_REPOSITORY" -p '*.mp4' -O "$out" --clobber
  else
    if [[ "$url" =~ drive\.google\.com/file/d/([A-Za-z0-9_-]+) ]] || [[ "$url" =~ drive\.google\.com/.*[?\&]id=([A-Za-z0-9_-]+) ]]; then
      url="https://drive.usercontent.google.com/download?id=${BASH_REMATCH[1]}&export=download&confirm=t"
    fi
    curl -fsSL --retry 3 --retry-delay 5 -o "$out" "$url"
  fi
  ls -lh "$out"
}
