# Voice model

Put your Applio voice model here:

- `your-voice.pth` (required)
- `your-voice.index` (optional, improves likeness)

Any file name works; the job uses the first `.pth` and `.index` it finds.

GitHub refuses single files over 100 MB in the website uploader. If your `.index` (or `.pth`) is
bigger than that, create a **Release** instead: Releases → Draft a new release → tag `voice-model` →
attach the files → Publish. The job downloads them from there automatically.
