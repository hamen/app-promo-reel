# app-promo-reel

A [Claude Code](https://claude.com/claude-code) skill that makes beat-synced 30-second
promo reels for a mobile app, vertical (9:16) or for the feed (4:5):

- music generated locally with ACE-Step 1.5 (or MusicGen), or your own track; ranked, and a
  beat grid locked to the kick;
- the app's real screens rebuilt as HTML from its store screenshots and its own strings;
- every cut, word and sound effect placed on a beat, rendered with
  [HyperFrames](https://hyperframes.heygen.com) (GSAP timeline in a headless browser);
- loudness normalised to -14 LUFS, audio/video sync checked, versioned MP4 output.

It **only generates video files.** It does not post, upload, schedule or send anything.

## Samples

Three reels made with this skill, unedited: the MP4s are exactly what `finish.py` delivered.
The previews below are silent; click one to watch the MP4 with sound. All six files live in
the [`samples` release](https://github.com/hamen/app-promo-reel/releases/tag/samples), not in git
(`bin/ci` keeps media out of the repo).

| 3 Things A Day (English) | Smart Pantry (Italian) | facecam-tui (open-source tool) |
| :---: | :---: | :---: |
| [![3 Things A Day reel](https://github.com/hamen/app-promo-reel/releases/download/samples/three-things.webp)](https://github.com/hamen/app-promo-reel/releases/download/samples/three-things.mp4) | [![Smart Pantry reel](https://github.com/hamen/app-promo-reel/releases/download/samples/smart-pantry.webp)](https://github.com/hamen/app-promo-reel/releases/download/samples/smart-pantry.mp4) | [![facecam-tui reel](https://github.com/hamen/app-promo-reel/releases/download/samples/facecam-tui.webp)](https://github.com/hamen/app-promo-reel/releases/download/samples/facecam-tui.mp4) |
| App Store + Google Play end card | Italian copy, App Store + Google Play end card | not a store app: ends on the GitHub link |

Each one: 30 s, 1080×1920, H.264/AAC at -14 LUFS; every sound effect that `finish.py` checks for
sync lands within 1 ms of its scheduled time; an AI-generation label, in the video's language, stays
on screen for the whole video.

## What the agent does

See [`skills/app-promo-reel/SKILL.md`](skills/app-promo-reel/SKILL.md). In short: scaffold one
project per variant, in its format (9:16 or 4:5) → research the app (site, stores, app strings)
→ write a design spec with the allowed claims → generate (or
import) and rank music → beat grid → storyboard on bars → build, check, snapshot, render → finish and verify.
The skill has hard truthfulness rules: no invented ratings, numbers, people or features, and an
"AI-generated" label on screen for the whole video.

## Requirements

- Python 3.11+, `ffmpeg` and `ffprobe`, `git`.
- Node 20+ with `npx` and a Chrome/Chromium for HyperFrames (render and check).
- Music, one of:
  - **ACE-Step 1.5** (the default): its own clone and environment, about 17 GB on disk (a 7.6 GB
    environment, and 9.4 GB of model files downloaded on the first run). It runs on an NVIDIA GPU
    or on the CPU. Measured here on the CPU: about 85 s per seed on 32 threads, with 15 GB of RAM.
    The GPU path was not measured here (the model card says less than 4 GB of VRAM).
  - **MusicGen** (`facebook/musicgen-small`): an NVIDIA GPU with a CUDA build of PyTorch.
  - **Your own track**: nothing to install; `music_import.py` takes a file you downloaded.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt            # analysis, build, finish, tests

# ACE-Step 1.5 (needs uv, https://docs.astral.sh/uv/)
git clone https://github.com/ace-step/ACE-Step-1.5 ~/ACE-Step-1.5
git -C ~/ACE-Step-1.5 checkout ca1e85f                # the version this skill was tested with
(cd ~/ACE-Step-1.5 && uv sync)
export ACESTEP_DIR=~/ACE-Step-1.5                     # the skill uses ACE-Step when this is set

# MusicGen: install torch for your CUDA version first, see https://pytorch.org
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
- ACE-Step 1.5, code and model weights, is published under the **MIT** licence. Its
  [model card](https://huggingface.co/ACE-Step/Ace-Step1.5) says: "You can strictly use the
  generated music for commercial purposes." This repo makes no legal claim about the generated
  music. Read the model card before you publish a video with it.
- The MusicGen model weights (`facebook/musicgen-small`) are published by Meta under
  **CC-BY-NC 4.0**. This repo makes no claim about what uses of the generated music that licence
  permits. Read the model licence before you publish a video with it; for any doubt (for example
  paid ads), use a licensed music track instead.
- Your own track: its licence is yours to check. `music_import.py` never downloads anything, and
  many music sites forbid automated downloads.
- No sound effects, fonts, screenshots, icons or generated audio are distributed here.

## Credits

The critique loop and the frame checks (blank opening, pops) follow ideas from Raphaël Aubry's
[claude-motion-design](https://github.com/howseen-ai/claude-motion-design) (MIT). No code is copied.

## Development

```bash
git config core.hooksPath .githooks   # pre-push runs bin/ci
bin/ci                                 # deps check, hygiene scan, pytest (no GPU, no network)
```
