# app-promo-reel

A [Claude Code](https://claude.com/claude-code) skill that makes beat-synced 30-second
vertical (9:16) promo reels for a mobile app:

- music generated locally with MusicGen, seeds ranked, and a beat grid locked to the kick;
- the app's real screens rebuilt as HTML from its store screenshots and its own strings;
- every cut, word and sound effect placed on a beat, rendered with
  [HyperFrames](https://hyperframes.heygen.com) (GSAP timeline in a headless browser);
- loudness normalised to -14 LUFS, audio/video sync checked, versioned MP4 output.

It **only generates video files.** It does not post, upload, schedule or send anything.

## What the agent does

See [`skills/app-promo-reel/SKILL.md`](skills/app-promo-reel/SKILL.md). In short: research the
app (site, stores, app strings) → write a design spec with the allowed claims → generate and
rank music → beat grid → storyboard on bars → build, check, snapshot, render → finish and verify.
The skill has hard truthfulness rules: no invented ratings, numbers, people or features, and an
"AI-generated" label on screen for the whole video.

## Requirements

- Python 3.11+, `ffmpeg` and `ffprobe`, `git`.
- Node 20+ with `npx` and a Chrome/Chromium for HyperFrames (render and check).
- For music generation only: an NVIDIA GPU with a CUDA build of PyTorch.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt            # analysis, build, finish, tests
# music generation: install torch for your CUDA version first, see https://pytorch.org
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cu128
.venv/bin/pip install -r requirements-gen.txt
```

Sound effects are optional and not included (most SFX licences forbid redistribution). Put your
own files in a folder and set `SFX_DIR`; `new_project.py` copies them into each project. The
example `skills/app-promo-reel/template/cues.json` names the files it expects (`whoosh.mp3`, `pop.mp3`,
`impact-bass-1.mp3`, …); rename the map to match your files. Without `SFX_DIR` the reel builds
with music only.

## Install

```bash
git clone https://github.com/hamen/app-promo-reel ~/code/app-promo-reel
ln -s ~/code/app-promo-reel/skills/app-promo-reel ~/.claude/skills/app-promo-reel
```

Then ask Claude Code for "promo reels for <app>". Output goes to `~/app-promo-reels/` by default.

## Licences

- The code in this repo is MIT (see LICENSE).
- The MusicGen model weights (`facebook/musicgen-small`) are published by Meta under
  **CC-BY-NC 4.0**. This repo makes no claim about what uses of the generated music that licence
  permits. Read the model licence before you publish a video with it; for any doubt (for example
  paid ads), use a licensed music track instead.
- No sound effects, fonts, screenshots, icons or generated audio are distributed here.

## Credits

The critique loop and the frame checks (blank opening, pops) follow ideas from Raphaël Aubry's
[claude-motion-design](https://github.com/howseen-ai/claude-motion-design) (MIT). No code is copied.

## Development

```bash
git config core.hooksPath .githooks   # pre-push runs bin/ci
bin/ci                                 # deps check, hygiene scan, pytest (no GPU, no network)
```
