# app-promo-reel

[![Bedtime Stories, a 16:9 hero loop made with this skill](https://github.com/hamen/app-promo-reel/releases/download/samples/bedtime-stories-hero.webp)](https://github.com/hamen/app-promo-reel/releases/download/samples/bedtime-stories-hero.mp4)

A [Claude Code](https://claude.com/claude-code) skill that makes beat-synced 30-second
promo reels for a mobile app, vertical (9:16) or for the feed (4:5), and a silent 16:9 loop for a
web hero (above: an 8-second loop for Bedtime Stories, made by the skill):

- music generated locally with ACE-Step 1.5 (or MusicGen), or your own track; ranked, and a
  beat grid locked to the kick;
- the app's real screens rebuilt as HTML from its store screenshots and its own strings;
- every cut, word and sound effect placed on a beat, rendered with
  [HyperFrames](https://hyperframes.heygen.com) (GSAP timeline in a headless browser);
- loudness normalised to -14 LUFS, audio/video sync checked, versioned MP4 output;
- a critique loop on the rendered frames: the agent scores its own video and fixes the worst
  problems, at most three rounds.

The 16:9 hero is a different product: 8 seconds, no music, no sound at all, and a seamless loop. The
last frame flows into the first, and `finish.py` measures that seam. Details:
[`references/hero.md`](skills/app-promo-reel/references/hero.md).

It **only generates video files.** It does not post, upload, schedule or send anything.

Contents: [Samples](#samples) · [How to use](#how-to-use) · [What happens, step by step](#what-happens-step-by-step) ·
[What you get](#what-you-get) · [Formats](#formats) · [Iterating](#iterating) ·
[Troubleshooting](#troubleshooting) · [Requirements](#requirements) · [Install](#install) ·
[Licences](#licences)

## Samples

Every sample is unedited: the MP4s are exactly what `finish.py` delivered. The previews below are
silent; click one to watch the MP4 (with sound, except the hero). All the files live in the
[`samples` release](https://github.com/hamen/app-promo-reel/releases/tag/samples), not in git
(`bin/ci` keeps media out of the repo).

### One app, three formats

The same app, Bedtime Stories, in the three formats. Each variant has its own hook, colour mood and
screens, and each reel has its own music seed: the skill never makes two variants with the same hook.

| 9:16 reel | 4:5 feed reel | 16:9 hero loop |
| :---: | :---: | :---: |
| [![Bedtime Stories 9:16 reel](https://github.com/hamen/app-promo-reel/releases/download/samples/bedtime-stories-reel.webp)](https://github.com/hamen/app-promo-reel/releases/download/samples/bedtime-stories-reel.mp4) | [![Bedtime Stories 4:5 feed reel](https://github.com/hamen/app-promo-reel/releases/download/samples/bedtime-stories-feed.webp)](https://github.com/hamen/app-promo-reel/releases/download/samples/bedtime-stories-feed.mp4) | [![Bedtime Stories 16:9 hero loop](https://github.com/hamen/app-promo-reel/releases/download/samples/bedtime-stories-hero.webp)](https://github.com/hamen/app-promo-reel/releases/download/samples/bedtime-stories-hero.mp4) |
| 1080×1920, 30 s. Night mood; hook "Your kid is the hero tonight"; the character step of the wizard, then a story page that is saved. MusicGen, 120 BPM | 1080×1350, 30 s. Day mood; hook "No book tonight? No problem."; the hero setup, then the world step. MusicGen, 122 BPM | 1920×1080, 8 s, no audio stream. A tap on a world opens a story, a tap on the back arrow returns; the seam measures 0.16 gray levels (limit 0.69) |

The live app is a wizard that its store screenshots do not show yet (they show an older one-page
form). The skill rebuilt the wizard from the app's source code and strings, read-only, and took the
story text word for word from a store screenshot.

### More reels

| 3 Things A Day (English) | Smart Pantry (Italian) | facecam-tui (open-source tool) |
| :---: | :---: | :---: |
| [![3 Things A Day reel](https://github.com/hamen/app-promo-reel/releases/download/samples/three-things.webp)](https://github.com/hamen/app-promo-reel/releases/download/samples/three-things.mp4) | [![Smart Pantry reel](https://github.com/hamen/app-promo-reel/releases/download/samples/smart-pantry.webp)](https://github.com/hamen/app-promo-reel/releases/download/samples/smart-pantry.mp4) | [![facecam-tui reel](https://github.com/hamen/app-promo-reel/releases/download/samples/facecam-tui.webp)](https://github.com/hamen/app-promo-reel/releases/download/samples/facecam-tui.mp4) |
| App Store + Google Play end card | Italian copy, App Store + Google Play end card | not a store app: ends on the GitHub link |

Each reel: H.264/AAC at -14 LUFS; every sound effect that `finish.py` checks for sync lands within
1 ms of its scheduled time; an AI-generation label, in the video's language, stays on screen for the
whole video (the hero too).

### The contact sheet

Next to each MP4, `finish.py` writes a contact sheet of frames taken from the real MP4, not from the
preview. This is the one for the 9:16 Bedtime Stories reel. The agent reads it, with stills around
every scene change, before it scores the video:

[![Contact sheet of the 9:16 Bedtime Stories reel](https://github.com/hamen/app-promo-reel/releases/download/samples/bedtime-stories-reel-sheet.jpg)](https://github.com/hamen/app-promo-reel/releases/download/samples/bedtime-stories-reel-sheet.jpg)

## How to use

After you [install](#install) the skill, ask Claude Code in plain words. Give it what it needs to
find the app; it asks for anything that is missing.

```text
Make promo reels for Bedtime Stories. App Store id6756010994, Google Play
com.ivanmorgillo.bedtimestories, site https://bedtimestories.click. English.
```

More examples:

```text
Two 9:16 reels and one 4:5 feed reel for Three Things A Day, copy in Italian, storefront it.

A 16:9 hero loop for the landing page of Smart Pantry. The source is in ~/code/pantry (read only).

Promo reels for my app, only on the App Store (id123456789). Use ~/Downloads/track.mp3 as the
music: it is "Sunny Day" from <the page you got it from>, licence <its licence>.

Gated run: promo reels for my app.
```

What you can give it:

| Input | Default | Notes |
| --- | --- | --- |
| App name, website URL | none | The site gives copy, colours and fonts. |
| App Store id and/or Google Play package | none | Only the stores the app is really on: the end card shows a badge for each store you give. |
| Storefront country | `us` | For the App Store listing and screenshots. |
| Language of the copy | `en` | Can differ from the storefront country. |
| Number of variants | 2 | Each variant is its own folder and renders on its own. |
| Format per variant | `9:16` | `9:16`, `4:5` or `16:9`; see [Formats](#formats). |
| Output folder | `~/app-promo-reels` | Never inside a git work tree. |
| App source repo | none | Optional, read-only: the agent reads the default branch with `git show`, never edits it. Real strings and screens make better reels. |
| Sound effects | none | Optional: a folder of your own files in `SFX_DIR`. |
| Brand notes | none | Optional: forbidden words, spelling, rules from your notes or memory system. |
| A reference video or image | none | Optional: sets the palette, type, pacing and motion only; no logo, text, music or claim comes from it. |

A **gated run** stops at four points and waits for you to say go: after the research (the asset
list), after the storyboard (`DESIGN.md` and `shotlist.md`), after the first render (contact sheet
and poster), and after the last critique round. Only the words "gated run" or "gated reel" turn it
on. Without them, the agent runs to the end without stopping, so an unattended job (a scheduled one,
for example) never waits on a person.

## What happens, step by step

The full workflow is in [`skills/app-promo-reel/SKILL.md`](skills/app-promo-reel/SKILL.md) and the
commands are in [`references/pipeline.md`](skills/app-promo-reel/references/pipeline.md). For each
variant, the agent:

1. **Scaffolds** a project folder (`new_project.py --app <slug> --variant a --format 9:16 --stores …`).
2. **Researches** the app: the store listings and screenshots (`store_assets.py`), the website, the
   app's own strings, and its real UI colours (`sample_colors.py`). Then it writes `DESIGN.md`: the
   angle, the sources, the colours, the type, and the list of allowed claims, each one with its
   source.
3. **Makes the music** (9:16 and 4:5 only): three seeds, ranked by `music_rank.py` (steady tempo, a
   lift where the drop goes); a beat grid locked to the kick (`beat_grid.py`); then the music bed
   (`make_bed.py`). A rejected seed is never used. It shows the licence note of the music source once,
   before the first generation.
4. **Storyboards on bars and builds the scenes.** It fills `CONFIG` at the top of `src.html.tmpl`
   (all text, colours and screens), rebuilds the app's screens as HTML, times every move with beat
   tokens (`D(bar, beat)`), and places the sound effects in `cues.json`. `shotlist.md` has one row
   for each scene: a scene with no reason to exist is cut.
5. **Builds, checks, renders and finishes.** `build.py` then `hyperframes check` until 0 errors:
   the check fails a page whose AI label is hidden, a text in the platform's UI zones, or two texts
   on top of each other. `read_check.py` times each caption against a reading rule. It renders the MP4,
   and `finish.py` normalises the loudness, checks the sync of every checked cue, and writes the
   versioned MP4, the contact sheet and the poster.
6. **Critiques the real frames**, at most three rounds. It scores seven things from 1 to 10 (hook,
   readability, motion, variety, composition, claims, and sound, or loop for the hero), writes the
   worst problems with a still as evidence in `reviews/critique-N.md`, fixes each one in the file
   that controls it, and renders again. It stops when every score is 8 or more.
7. **Delivers** a list of MP4 paths, with the angle, the music source and seed, the tempo, the sync
   result, the loudness, the scores and any problem still open. Nothing is uploaded or sent.

A critique round looks like this (round 1 of the 4:5 sample; round 2 had no defect):

```text
scores: hook=8 readability=8 motion=7 variety=8 composition=8 claims=9 sound=8

- t=1.2 evidence=reviews/still-1.2.jpg fix=src.html.tmpl: punch the hero chip on the pickup beat
  (D(-1, 3), 1.27 s); nothing moves from 0.73 s to 1.76 s
- t=21.9 evidence=reviews/still-21.9.jpg fix=src.html.tmpl: a slow push-in on the value camera;
  the value block holds still from 21.50 s to 22.37 s and from 23.47 s to 24.40 s
```

The skill has hard truthfulness rules: no invented ratings, numbers, people, quotes or features; AI
features framed as help, never as guaranteed; and an "AI-generated" label on screen for the whole
video. When an asset is missing (an icon, a screenshot, a font), it uses a clearly labelled
placeholder and tells you.

## What you get

One folder for each variant, `<output>/<app>-<variant>/`:

```text
bedtime-stories-a/
├── renders/
│   ├── bedtime-stories-a-v2.mp4          the video: one new version for each finish
│   ├── bedtime-stories-a-v2-sheet.jpg    contact sheet, frames from the real MP4
│   ├── bedtime-stories-a-v2-poster.jpg   poster frame (--poster-at <s> chooses it)
│   ├── bedtime-stories-a-v2-report.json  loudness, sync and frame checks (the seam, for a hero)
│   └── raw.mp4                           the last render, before finish.py
├── reviews/critique-1.md …               the scores and problems of each critique round
├── DESIGN.md                             angle, sources, colours, allowed claims
├── shotlist.md                           one row for each scene: purpose, entry, exit
├── src.html.tmpl                         the composition: CONFIG at the top, then scenes and timeline
├── cues.json                             sound effects, timed on beats
├── beats.json                            the beat grid of the chosen seed
├── project.json                          duration, fps, format, stores, language
├── assets/                               music bed, sound effects, fonts, icon
├── work/                                 store listing and screenshots, music seeds, logs
└── index.html                            built by build.py: never edit it by hand
```

## Formats

| Format | Size | Length | Sound | For |
| --- | --- | --- | --- | --- |
| `9:16` (default) | 1080×1920 | 30 s | music and sound effects | Reels, TikTok, Shorts, Stories |
| `4:5` | 1080×1350 | 30 s | music and sound effects | a feed post, which starts muted |
| `16:9` | 1920×1080 | 8 s | none: no audio stream at all | a web-hero loop behind a headline |

In 9:16 and 4:5, every text and tap stays inside the feed safe box at the format's minimum size, and
something moves at all times: nothing holds still for more than 0.8 s, except the end card. The 16:9
hero has no music, no beat grid and no cues; its contract is the loop, and `finish.py` fails a
clip whose last frame does not flow into its first. To use the hero on a page:

```html
<video autoplay loop muted playsinline src="hero.mp4"></video>
```

**Motion blur** is optional, for 9:16 and 4:5: the agent renders at 240 fps and `blur.py` blends the
frames into a 30 fps shutter (about 2.5 minutes for 30 s instead of about 25 s). It helps fast
moves; on very fast whips it can show separate copies instead of a smear, so the critique decides.
The Bedtime Stories samples have no blur for that reason.

## Iterating

Give the agent notes in the same session, in plain words: "the hook is too long", "use the green
of the site", "the second variant should open on the scanner screen". It changes the file that
controls the problem, renders again, and finishes a new version (`-v3.mp4`); the earlier versions
stay.

To change a reel yourself, edit `CONFIG` at the top of `src.html.tmpl` (texts, colours, screens), or
the scenes below it, and run the same steps:

```bash
S=~/code/app-promo-reel/skills/app-promo-reel/scripts
P=~/app-promo-reels/myapp-a
PY=~/code/app-promo-reel/.venv/bin/python

$PY $S/build.py $P                      # its last line is the check command: run it
cd $P && npx --yes hyperframes@0.8.78 check
npx --yes hyperframes@0.8.78 render -o renders/raw.mp4 -q delivery --quiet
$PY $S/finish.py $P renders/raw.mp4     # writes the next version
```

Never render a page whose check fails: the render does not stop on the error.

## Troubleshooting

| What you see | What to do |
| --- | --- |
| `hyperframes check` reports errors | Fix them before you render. A hidden or moving AI label, a text in a UI zone, two overlapping texts and a missing font face are all errors on purpose. |
| `font_family_without_font_face` | Copy the font file into `assets/fonts/` and declare it with `@font-face`. Emoji need a face too (for example Noto Color Emoji). |
| `music_gen_ace.py` exits 3 | The GPU ran out of memory: run the same command once with `--device cpu`. |
| All three seeds are rejected | The agent tries three new seeds, then a simpler prompt (steadier genre words), then stops and shows you the rank tables. |
| `beat_grid.py` stops: "the grid came out at X BPM" | That seed counts as rejected: the agent takes the next one. |
| `finish.py` exits 1 | A check failed: sync, loudness, frame size, frame rate, length or frame count, or the seam of a hero. The message names it. |
| `warning: still for 1.03 s from 0.73 s` | Nothing moves there for longer than 0.8 s: add a move on a beat. It never fails the run; the critique decides. |
| `warning: reading time:` from `read_check.py` | A caption leaves the screen before it can be read. Give it more time or fewer words. |
| A store badge for a store the app is not on | Scaffold with `--stores` set to the stores the app is really on. |
| `new_project.py` refuses the output folder | It never writes inside a git work tree (`--force` if you are sure) and never inside this repo. |

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

When `ACESTEP_DIR` is not set, the agent asks you once: install ACE-Step, use MusicGen, or give it a
track you downloaded yourself. It never downloads music itself.

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

Then ask Claude Code for "promo reels for <app>" ([How to use](#how-to-use)). Output goes to
`~/app-promo-reels/` by default.

## Licences

- The code in this repo is MIT (see LICENSE).
- ACE-Step 1.5, code and model weights, is published under the **MIT** licence. Its
  [model card](https://huggingface.co/ACE-Step/Ace-Step1.5) says: "You can strictly use the
  generated music for commercial purposes." This repo makes no legal claim about the generated
  music. Read the model card before you publish a video with it.
- The MusicGen model weights (`facebook/musicgen-small`) are published by Meta under
  **CC-BY-NC 4.0**. This repo makes no claim about what uses of the generated music that licence
  permits. Read the model licence before you publish a video with it; for any doubt (for example
  paid ads), use a licensed music track instead. The music of the Bedtime Stories samples was made
  with MusicGen.
- Your own track: its licence is yours to check. `music_import.py` never downloads anything, and
  many music sites forbid automated downloads.
- No sound effects, fonts, screenshots, icons or generated audio are distributed here.

## Credits

The critique loop and the frame checks (blank opening, pops) follow ideas from Raphaël Aubry's
[claude-motion-design](https://github.com/howseen-ai/claude-motion-design) (MIT). No code is copied.

The feed safe zones, the readable text minimums, the dead-hold rule and the motion-blur rules (a
shutter centred on the frame, no blur across a cut, one rounding of a float average) follow
[cinetic](https://github.com/Leonxlnx/cinetic) by Leonxlnx (MIT). No code is copied.

The motion ranges (an entrance in 0.3-0.6 s, an exit in 0.2-0.3 s, a stagger of 60-120 ms, 20-40 ms
between letters) and the idea of a reading-time check follow the guides of
[fframes](https://github.com/dmtrKovalenko/fframes) by dmtrKovalenko (MIT). The reading rule itself
(0.8 s, 0.3 s per word) is this skill's own. No code is copied.

## Development

```bash
git config core.hooksPath .githooks   # pre-push runs bin/ci
bin/ci                                 # deps check, hygiene scan, pytest (no GPU, no network)
APR_BROWSER_TESTS=1 bin/ci             # also runs the printed check command in a browser (npx, ~1 min)
```
