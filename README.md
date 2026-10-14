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

Contents: [What's new](#whats-new) · [Samples](#samples) · [How to use](#how-to-use) ·
[What happens, step by step](#what-happens-step-by-step) · [What you get](#what-you-get) ·
[Formats](#formats) · [Iterating](#iterating) · [Troubleshooting](#troubleshooting) ·
[Requirements](#requirements) · [Install](#install) · [Licences](#licences)

## What's new

The skill shipped on 2026-09-27 as a 9:16 reel maker. Every merged pull request is listed here, newest
first, in merge order:

- 2026-10-14: this README, `SKILL.md` and the version test have the fixes that the reviews of #26
  and #27 recorded ([#28](https://github.com/hamen/app-promo-reel/pull/28)). A test fails when a copy of
  the HyperFrames version in the docs, the template or the tests differs from the one in `build.py`
  ([#27](https://github.com/hamen/app-promo-reel/pull/27)).
  `SKILL.md`, this README and a template comment have the fixes that the reviews of #20, #21 and #25
  recorded ([#26](https://github.com/hamen/app-promo-reel/pull/26)). The template comments and two
  guard tests give the label's place since #21, the bottom-left corner of the frame
  ([#25](https://github.com/hamen/app-promo-reel/pull/25)).
- 2026-10-13: sample reels for Ebooks Gratis and Blackjack Trainer
  ([#24](https://github.com/hamen/app-promo-reel/pull/24)), the 9:16 and 4:5 samples rendered again
  with the label in the corner ([#23](https://github.com/hamen/app-promo-reel/pull/23)), this list
  ([#22](https://github.com/hamen/app-promo-reel/pull/22)), and the AI-generated label of 9:16 and
  4:5 reels back in a corner of the frame, at the bottom-left, below the feed safe box
  ([#21](https://github.com/hamen/app-promo-reel/pull/21)). Inside the box, it read as the middle of
  the video on a player with no overlay, such as Telegram. To move the label of an older reel, build,
  check, render and finish it again. Earlier the same day: this README, with samples in all three
  formats ([#20](https://github.com/hamen/app-promo-reel/pull/20)).
- 2026-10-12: 21 docs, comments and messages now say what the code does
  ([#19](https://github.com/hamen/app-promo-reel/pull/19)), and seven checks that could pass a page
  or a render they exist to refuse now refuse it ([#18](https://github.com/hamen/app-promo-reel/pull/18)).
- 2026-10-11: the frame rate in `project.json` reaches the render, and `finish.py` checks the rate
  of the MP4 ([#17](https://github.com/hamen/app-promo-reel/pull/17)).
- 2026-10-10: the AI-label guard reads the timeline. A fade, a clip or a move of the whole reel can
  no longer hide the label ([#16](https://github.com/hamen/app-promo-reel/pull/16)).
- 2026-10-09: `read_check.py` times each caption against a reading rule, max(0.8 s, 0.3 s per word)
  ([#15](https://github.com/hamen/app-promo-reel/pull/15)).
- 2026-10-08: optional motion blur that stops at cuts: render at 240 fps, and `blur.py` blends the
  frames into a 30 fps shutter ([#14](https://github.com/hamen/app-promo-reel/pull/14)).
- 2026-10-07: a feed-safe layout. Text and taps stay out of the platforms' UI zones, at a readable
  size, and `finish.py` warns when nothing moves for more than 0.8 s
  ([#13](https://github.com/hamen/app-promo-reel/pull/13)).
- 2026-10-06: a shot list, a poster frame, a critique file for each round, an optional reference
  look, and the gated run ([#12](https://github.com/hamen/app-promo-reel/pull/12)).
- 2026-10-05: a motion language, with one ease for each class of object. The build refuses a page
  script that reads the clock or a random number, so a seek always gives the same frame
  ([#11](https://github.com/hamen/app-promo-reel/pull/11)).
- 2026-10-03: the silent 16:9 hero loop, with a seam check
  ([#10](https://github.com/hamen/app-promo-reel/pull/10)).
- 2026-10-01: the first samples in this README ([#4](https://github.com/hamen/app-promo-reel/pull/4)),
  and the 4:5 feed format ([#9](https://github.com/hamen/app-promo-reel/pull/9)).
- 2026-09-30: ACE-Step 1.5 is the default music source, and you can bring your own track
  ([#6](https://github.com/hamen/app-promo-reel/pull/6)). The hook is readable from frame 0
  ([#8](https://github.com/hamen/app-promo-reel/pull/8),
  [#7](https://github.com/hamen/app-promo-reel/pull/7)).
- 2026-09-29: the critique loop and the frame checks
  ([#5](https://github.com/hamen/app-promo-reel/pull/5)), and the fixes from the closing review of
  #2 ([#3](https://github.com/hamen/app-promo-reel/pull/3)).
- 2026-09-27: fixes from the review of the first release
  ([#2](https://github.com/hamen/app-promo-reel/pull/2)), and the first release, beat-synced 9:16
  reels ([#1](https://github.com/hamen/app-promo-reel/pull/1)).

## Samples

Every sample is unedited: the MP4s are exactly what `finish.py` delivered. The previews below are
silent; click one to watch the MP4 (with sound, except the hero). All the files are in the
[`samples` release](https://github.com/hamen/app-promo-reel/releases/tag/samples), not in git
(`bin/ci` keeps media out of the repo). The 9:16 and 4:5 samples were built, checked, rendered and
finished again after [#21](https://github.com/hamen/app-promo-reel/pull/21), with no edits, so their
AI-generated label is at the frame's bottom-left corner. The 16:9 hero keeps its label at the
bottom-right corner.

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

| Ebooks Gratis | Blackjack Trainer | app-promo-reel (this skill) |
| :---: | :---: | :---: |
| [![Ebooks Gratis reel](https://github.com/hamen/app-promo-reel/releases/download/samples/kindle-gratis.webp)](https://github.com/hamen/app-promo-reel/releases/download/samples/kindle-gratis.mp4) | [![Blackjack Trainer reel](https://github.com/hamen/app-promo-reel/releases/download/samples/blackjack-trainer.webp)](https://github.com/hamen/app-promo-reel/releases/download/samples/blackjack-trainer.mp4) | [![app-promo-reel reel](https://github.com/hamen/app-promo-reel/releases/download/samples/app-promo-reel.webp)](https://github.com/hamen/app-promo-reel/releases/download/samples/app-promo-reel.mp4) |
| 1080×1920, 30 s. Hook "Free Kindle books, daily."; the categories screen, then the Amazon store picker. The app is on Google Play only, so the end card has one store badge. MusicGen, 120 BPM | 1080×1920, 30 s. Hook "The house has a system. Do you?"; the trainer screen, then the statistics screen. MusicGen, 122 BPM | 1080×1920, 30 s. Hook "21 pull requests in 17 days"; the skill is on no store, so the end card shows the GitHub link. MusicGen, 122 BPM |

These three reels are H.264/AAC at -14.2 to -14.3 LUFS, and in each one the 22 sound effects that
`finish.py` checks for sync land within 14 ms of their scheduled times. Every sample, the silent hero included, keeps an AI-generated
label, in the video's language, on screen for the whole video.

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
| Output folder | `~/app-promo-reels` | Not inside a git work tree (`new_project.py` refuses a folder inside one unless you pass `--force`), and never inside this repo, even with `--force`. |
| App source repo | none | Optional, read-only: the agent reads the default branch with `git show`, never edits it. |
| Sound effects | none | Optional: a folder of your own files in `SFX_DIR`. |
| Brand notes | none | Optional: forbidden words, spelling, rules from your notes or memory system. |
| A reference video or image | none | Optional: sets the palette, type, pacing and motion only; no logo, text, music or claim comes from it. |

A **gated run** stops at four points and waits for you to say go: after the research (the asset
list), after the storyboard (`DESIGN.md` and `shotlist.md`), after the first render (contact sheet
and poster), and after the last critique round. Only the words "gated run" or "gated reel" turn it
on. Without them, the agent does not stop between steps. It still asks for an input that is missing,
and once for the music source when `ACESTEP_DIR` is not set (ACE-Step, MusicGen or your own track).
For an unattended job (a scheduled one, for example), give the inputs and the music source in the
request, so that it never waits on a person.

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
5. **Builds, checks, renders and finishes.** `build.py`, then the check command it prints, until 0 errors:
   the check fails a page whose AI label is hidden, a text in the platform's UI zones, a font with no
   `@font-face`, or two texts that stay on top of each other for 0.5 s or more (a shorter overlap is
   only an `info` line, so the agent also looks at the frames). `read_check.py` times each caption
   against a reading rule. It renders the MP4, and `finish.py` normalises the loudness, checks the
   sync of every checked cue, and writes the next version of the MP4 (one more than the highest in
   `renders/`), the contact sheet and the poster (`--poster-at <s>` chooses its time). For a 16:9
   hero, `read_check.py` times nothing, and `finish.py` checks the seam and the frame count instead
   of the loudness and the sync.
6. **Critiques the real frames**, at most three rounds. It scores seven things from 1 to 10 (hook,
   readability, motion, variety, composition, claims, and sound, or loop for the hero), writes the
   worst problems with a still as evidence in `reviews/critique-N.md`, fixes each one in the file
   that controls it, and renders again. It stops when every score is 8 or more.
7. **Delivers** a list of MP4 paths, with the angle, the scores and any problem still open; for a
   reel also the music source and seed, the tempo, the sync result and the loudness. Nothing is
   uploaded or sent.

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

One folder for each variant, `<output>/<app>-<variant>/` (a 16:9 hero has no `cues.json`, no
`beats.json` and no audio):

```text
bedtime-stories-a/
├── renders/
│   ├── bedtime-stories-a-v2.mp4          the video: each finish adds a version, the earlier ones stay
│   ├── bedtime-stories-a-v2-sheet.jpg    contact sheet, frames from the real MP4
│   ├── bedtime-stories-a-v2-poster.jpg   poster frame (--poster-at <s> chooses it)
│   ├── bedtime-stories-a-v2-report.json  loudness, sync and frame checks (the seam, for a hero)
│   └── raw.mp4                           the last render, before finish.py
├── reviews/critique-1.md …               the scores and problems of each critique round
├── reviews/still-1.2.jpg …               the stills from the MP4 that a critique names as evidence
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

In 9:16 and 4:5, every text and tap stays inside the
[feed safe box](skills/app-promo-reel/references/storyboard.md#feed-safe-zones) at the format's
minimum size, 32 px in 9:16 and 30 px in 4:5 (the AI-generated label sits below the box, at the
frame's bottom-left corner), and something moves at all times: nothing holds still for more than
0.8 s, except the end card. The 0.8 s is a target for the critique: `finish.py` warns, and never
fails a reel for it. The 16:9
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

$PY $S/build.py $P                      # its last line is "check: <command>"
```

Run the command after `check:` exactly as `build.py` prints it, until it reports 0 errors. Do not
replace it with a plain `hyperframes check`: for 9:16 and 4:5 the printed command also carries the
feed safe box (`--caption-zone`). Never render a page whose check fails: the render does not stop
on the error. Then, in the same shell (the first block sets `S`, `P` and `PY`):

```bash
$PY $S/read_check.py $P                 # 9:16 and 4:5: the reading time of each caption
cd $P && npx --yes hyperframes@0.8.78 render -o renders/raw.mp4 -q delivery --quiet &&
  $PY $S/finish.py $P $P/renders/raw.mp4  # only after a render that succeeded: the next version
```

## Troubleshooting

| What you see | What to do |
| --- | --- |
| `hyperframes check` reports errors | Fix them before you render. A hidden or moving AI label, a text in a UI zone, two texts that overlap for 0.5 s or more and a missing font face are all errors on purpose. A shorter overlap is only an `info` line: look at the frames. |
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
  paid ads), use a licensed music track instead. The music of every sample in this README was made
  with MusicGen. The sample videos show what the skill makes; they are not offered for reuse.
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
