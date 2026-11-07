# RagebaitX voice job

Changes the voice on a gaming clip in the cloud, for free, using GitHub Actions.
It's started by the n8n workflow **RagebaitX – Clip Factory**, once per clip.

What one run does (`.github/workflows/voice.yml` → `scripts/process.sh`):

1. Downloads the clip from OpusClip.
2. Pulls out the audio with ffmpeg.
3. Splits the voice from the game sound with Demucs (so explosions and music stay clean).
4. Changes the voice with Applio, using the model in `models/`.
5. Mixes the new voice back with the game sound, levels the volume (-14 LUFS, the
   level YouTube/TikTok/Instagram normalise to), and puts it back on the original video
   without re-encoding the picture.
6. Uploads the finished MP4 as a run artifact (kept 1 day) and tells n8n, which saves it to
   Google Drive **01 – Ready to Upload**.

## Setup

1. Upload this folder's contents to a **private** repo.
2. Add your voice model to `models/` (see `models/README.md`).
3. In n8n, create a GitHub credential with a fine-grained token for this repo:
   - Repository access: only this repo
   - Permissions: **Actions: Read and write**, **Contents: Read-only**
4. Fill in the repo owner and name in the **Clip Factory Config** node in n8n.

## Test by hand

Actions tab → **Voice change clip** → **Run workflow** → paste a direct MP4 link in `clip_url`.
When it finishes, download the `voiced-…` artifact from the run page.

## Settings

| Input | Default | What it does |
|---|---|---|
| `separate_voice` | `true` | Split voice from game sound first. `false` runs Applio on the whole track. |
| `pitch` | `0` | Semitones up/down, same as Applio's Pitch slider. |
| `index_rate` | `0.3` | Same as Applio's Index Rate. |

## Cost

Free. Private repos get 2,000 Actions minutes a month; one clip takes about 3–6 minutes
(the first run is slower while it downloads models, later runs use the cache).
