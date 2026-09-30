---
name: app-promo-reel
description: Generate beat-synced 30 s vertical (9:16) promo reels for a mobile app — music from ACE-Step 1.5, MusicGen or the user's own track, a kick-locked beat grid, the app's real UI rebuilt as HTML, HyperFrames render, loudness and sync checks. Use when the user asks for promo / social / showreel videos of an app. Generation only; it never posts or uploads anything.
---

# app-promo-reel

Input: an app. Output: N rendered MP4 reels, one folder per variant. Nothing is uploaded,
posted or sent anywhere — the skill ends with a list of file paths.

`<skill>` below is the folder that holds this SKILL.md. Run the scripts with a Python that has
`requirements.txt` installed (the repo's `.venv` if present).

## CRITICAL — truthfulness

These rules win over any creative idea:

1. Every claim in the video comes from the app's website, its store listing, or the app's own
   strings. Write the source next to each claim in DESIGN.md.
2. No invented ratings, reviews, download counts, percentages, money saved, or "#1" claims.
3. No invented people, testimonials, quotes, user names or faces.
4. No feature the app does not have. Show only screens the app really has.
5. AI features are framed as help ("helps you …"), never as guaranteed or always right.
6. Respect what the listings say: e.g. if the Play listing says "Contains ads", never claim
   "no ads".
7. The AI-generated label (`CONFIG.aiLabel`, in the video's language) stays on screen for the
   whole video. Never remove it. build.py's script at the end of the page creates the label
   from `CONFIG.aiLabel` and stops `hyperframes check` and the render when it is empty or
   something (display, opacity, filter, clip-path, position) keeps it from being seen.
8. When an asset is missing (icon, screenshot, font), use a clearly labelled placeholder and
   tell the user. Never fake it.

Detail: `references/copy-rules.md`.

## Inputs (ask for what is missing)

- App name; website URL; App Store id and/or Google Play package; storefront country.
- Language of the copy (can differ from the storefront country).
- N variants (default 2); output folder (default `~/app-promo-reels`).
- Optional: a local path to the app's source repo (read-only), a folder of SFX (`$SFX_DIR`),
  and the user's own brand notes / memory system for app-specific rules.

## Workflow

Commands for every step: `references/pipeline.md`.

1. **Scaffold.** `new_project.py --app <slug> --variant <a|b|…> --stores <stores>` once per
   variant. `--stores` lists only the stores the app is really on (`app_store`, `google_play`
   or both): the default is both, which puts a false badge on a single-store app's end card.
   Each variant is its own folder and renders on its own.
2. **Research, then DESIGN.md — before any copy.**
   - `store_assets.py` (screenshots, listing text, Play labels).
   - The website: copy, CSS colours, fonts.
   - App strings in the target language from the app repo, if given — read-only, from the
     default branch (`git fetch origin`, `git symbolic-ref refs/remotes/origin/HEAD`,
     `git show origin/<branch>:<path>`). Never edit that repo.
   - `sample_colors.py` on the screenshots for the app's real UI colours.
   - Search the user's notes/memory for rules about this app (forbidden words, spelling).
   - Fill `DESIGN.md` from the template: angle, sources, colours, type, copy rules.
3. **Music first, per variant.** Commands in `references/pipeline.md`.
   - Choose the source once per session:
     1. ACE-Step 1.5 (`music_gen_ace.py`, run with `$ACESTEP_DIR/.venv/bin/python`) when
        `ACESTEP_DIR` is set and `$ACESTEP_DIR/.venv` exists. This is the default.
     2. Otherwise ask the user once: install ACE-Step (README, about 17 GB), use MusicGen
        (`music_gen.py`, needs an NVIDIA GPU), or give a track they downloaded themselves.
     3. A track from the user: `music_import.py` with `--source` (where it came from). Never
        download music yourself.
   - Show the licence note of that source once, before the first generation, then continue:
     ACE-Step: *"ACE-Step 1.5 is MIT; its model card says the generated music can be used for
     commercial purposes. Read the model card before you publish."* MusicGen: *"The music model
     (musicgen-small) is published under CC-BY-NC 4.0. Read that licence before you publish;
     for any doubt, use a licensed track."* Own track: *"The licence of this track is yours to
     check."*
   - 3 seeds → `music_rank.py`. Pick the best accepted seed. `music_gen_ace.py` exit 3 = the
     GPU ran out of memory: run the same command once with `--device cpu`.
   - If all 3 are rejected: one more batch of 3 new seeds. If that batch is rejected too, simplify
     the prompt once (steadier genre words) and try a last batch. Then stop and show the rank
     tables to the user. Never use a rejected seed. A seed that `beat_grid.py` stops on counts as
     rejected.
   - Own track rejected: show the rank table and ask for another `--start` or another track.
   - `beat_grid.py --bpm <tempo>` → `beats.json`. The tempo: the `--bpm` asked of ACE-Step, else
     the `tempo` column of the rank table. If beat_grid stops ("the grid came out at X BPM"),
     never run make_bed on that seed: take the next one. Place the drop (rule in
     `references/storyboard.md`), then `make_bed.py` (with `--drop-bar` for a synthetic lift
     when the seed has no lift there).
4. **Storyboard on bars, then build the scenes.** Fill `CONFIG` at the top of `src.html.tmpl`
   (all text, colours, screens) and edit the scenes. Rebuild the app's real screens as HTML
   components from the screenshots and strings — no pasted screenshots. Timing uses beat tokens
   only. Put the SFX cues in `cues.json`. See `references/storyboard.md` and
   `references/hyperframes-gotchas.md`.
5. **Build, check, look, render, finish.**
   - `build.py <project>` → `npx --yes hyperframes@0.8.78 check` until 0 errors.
   - Snapshots at every scene and every transition; look at them; fix; repeat.
   - `npx --yes hyperframes@0.8.78 render -o renders/raw.mp4 -q delivery --quiet`.
   - `finish.py <project> renders/raw.mp4` → loudness, A/V check, sync report, versioned file
     `renders/<app>-<variant>-v<N>.mp4`, contact sheet, frame warnings (blank opening, pops).
     Exit 1 = a check failed: fix and finish again. Frame warnings never fail the run; the
     critique below decides.
6. **Critique, at most 3 rounds.** Be a harsh motion director, not a proud author.
   - Look at the contact sheet (frames from the real MP4, not the preview) and read every
     `warning:` line from finish.py.
   - Stills around every scene change: for each scene start t, every 0.1 s from t-0.2 to t+0.5
     (this covers the overlap of two scenes and the downbeat it lands on). Always add 0.0; clamp
     every time to [0, duration-0.05]:
     `npx --yes hyperframes@0.8.78 snapshot --at <times> --describe false --no-end -o snapshots/c<round>`
     (a new folder per round).
   - Score 1-10, one line each: **hook** (something readable in the first 1 s, frame 0 not
     empty); **readability** (at the 270 px size of the contact sheet); **motion** (no two texts
     on top of each other, nothing crossing another element by accident, no dead second);
     **variety** (something new every 2-4 s); **composition**; **claims** (each one is in the
     DESIGN.md allowed list); **sound** (sync report, and what the storyboard asked for).
   - Write the 3 worst problems with their timestamps. Fix each one in the file that controls
     it: scenes, text and motion in `src.html.tmpl`; sound effects in `cues.json`; the music bed
     with `make_bed.py` (or a new seed, step 3). Then build, check, render and finish again.
   - Stop when every score is 8 or more, or after 3 critique rounds. Never loop without the cap.
7. **Deliver.** List each final MP4 path with a one-line summary (angle, music source and seed,
   tempo, sync result, loudness), its seven scores and any problem still open. Repeat the music
   licence note; for the user's own track, give the contents of `bgm_user.source.txt`.
   **Nothing is uploaded or sent.**

## Variants

Variants differ by hook/angle (menu in `references/storyboard.md`), music seed or prompt, and
colour mood. Never two variants with the same hook.
