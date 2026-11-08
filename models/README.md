# Voice model

Put your Applio voice model here:

- `your-voice.pth` (required)
- `your-voice.index` (optional, improves likeness)

Any file name works; the job uses the first `.pth` and `.index` it finds.

The GitHub website only accepts files up to 25 MB. Voice models are usually bigger, so
the easiest way is a **Release**: Releases → Draft a new release → tag `voice-model` →
attach the files → Publish. The job downloads them from there automatically.
