#!/usr/bin/env bash
# Shared helper: download_clip <url> <out.mp4>
# Accepts a direct MP4 link, a Google Drive share link, or release:<tag> (first .mp4 on that release).
#
# Google Drive limits how often a big file can be downloaded (the same stream gets downloaded for the
# Shorts scan, the long-video scan and the long-video render). So the first time a Drive video is
# downloaded, a copy is kept on a private GitHub release ("src-<file id>", split into <2 GB parts) and
# every later job takes it from there. Copies older than 4 days are cleaned up automatically.

_drive_get() {
  # _drive_get <id> <out>: download from Drive, handling the "can't scan for viruses" page; explains refusals.
  local id="$1" out="$2" page form uuid
  curl -fsSL --retry 3 --retry-delay 5 -o "$out" "https://drive.usercontent.google.com/download?id=${id}&export=download&confirm=t" || true
  if [ -s "$out" ] && [ "$(stat -c %s "$out")" -gt 200000 ]; then return 0; fi
  page=$(cat "$out" 2>/dev/null | head -c 20000)
  uuid=$(printf '%s' "$page" | grep -o 'name="uuid" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"$//')
  if [ -n "$uuid" ]; then
    curl -fsSL --retry 3 --retry-delay 5 -o "$out" \
      "https://drive.usercontent.google.com/download?id=${id}&export=download&confirm=t&uuid=${uuid}" || true
    if [ -s "$out" ] && [ "$(stat -c %s "$out")" -gt 200000 ]; then return 0; fi
    page=$(cat "$out" 2>/dev/null | head -c 20000)
  fi
  local why
  why=$(printf '%s' "$page" | sed -e 's/<[^>]*>/ /g' | tr -s ' \n' ' ' | grep -oiE "(too many users[^.]*\.|quota[^.]*\.|you need access[^.]*\.|not found[^.]*\.|sorry[^.]*\.)" | head -2 | tr '\n' ' ')
  echo "::error::Google Drive did not give the video. ${why:-It may not be shared as 'anyone with the link', or Drive limited downloads of this file for now.}"
  return 1
}

_src_cleanup() {
  gh release list -R "$GITHUB_REPOSITORY" --limit 100 --json tagName,createdAt \
    -q '.[] | select(.tagName | startswith("src-")) | select((now - (.createdAt | fromdateiso8601)) > 345600) | .tagName' 2>/dev/null |
    while read -r t; do gh release delete "$t" -R "$GITHUB_REPOSITORY" --yes --cleanup-tag >/dev/null 2>&1 || true; done
}

download_clip() {
  local url="$1" out="$2"
  if [[ "$url" == release:*/* ]]; then
    # release:<tag>/<file name> = that one file on the release (used by the highlight moments)
    local rel="${url#release:}"
    gh release download "${rel%%/*}" -R "$GITHUB_REPOSITORY" -p "${rel#*/}" -O "$out" --clobber
  elif [[ "$url" == release:* ]]; then
    gh release download "${url#release:}" -R "$GITHUB_REPOSITORY" -p '*.mp4' -O "$out" --clobber
  elif [[ "$url" =~ drive\.google\.com/file/d/([A-Za-z0-9_-]+) ]] || [[ "$url" =~ drive\.google\.com/.*[?\&]id=([A-Za-z0-9_-]+) ]]; then
    local id="${BASH_REMATCH[1]}" tag="src-${BASH_REMATCH[1]}" d
    d=$(mktemp -d)
    if gh release download "$tag" -R "$GITHUB_REPOSITORY" -p 'part_*' -D "$d" >/dev/null 2>&1 && ls "$d"/part_* >/dev/null 2>&1; then
      cat "$d"/part_* > "$out"; rm -rf "$d"
      echo "Using the saved copy of this video (no Drive download needed)."
    else
      rm -rf "$d"
      _drive_get "$id" "$out" || return 1
      # Keep a copy for the next jobs on this video (best effort; never fails the job).
      (
        set +e
        p=$(mktemp -d); split -b 1900m -d -a 2 "$out" "$p/part_"
        gh release create "$tag" -R "$GITHUB_REPOSITORY" --title "Source copy $id" --notes "Auto copy of a Drive video, deleted after 4 days." --prerelease "$p"/part_* >/dev/null 2>&1 \
          && echo "Saved a copy for the next jobs on this video."
        rm -rf "$p"; _src_cleanup
      ) || true
    fi
  else
    curl -fsSL --retry 3 --retry-delay 5 -o "$out" "$url"
  fi
  ls -lh "$out"
}
