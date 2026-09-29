# Pipeline — commands per stage

`S=<skill>/scripts`, `P=<out>/<app>-<variant>` (the project folder). `PY` = a Python with
`requirements.txt` (and, for step 3, `requirements-gen.txt` + CUDA torch).

## Beat addressing (used everywhere)

`D(bar, beat=0)`: `bar` is 0-based from the first downbeat of `beats.json` (negative bars are
pickup beats before it); `beat` is 0-based inside the bar; `beats_per_bar` is in project.json
(default 4). `E(bar, beat)` is the "and": halfway to the next beat.

- Template tokens: `{{D 3}}`, `{{D 3 2}}`, `{{E 3 1}}`, `{{LEN 2 6}}` (= D(6) − D(2)),
  `{{TO_END 12}}`, `{{calc D(2)-0.3}}` (numbers, + − * /, parentheses, D, E, DURATION only),
  `{{BEFORE_END 1.1 D(13, 3)}}` (renders nothing; the build fails when the time is less than
  1.1 s before the end),
  `{{BEATS}}`, `{{DOWNBEAT_INDEX}}`, `{{BEATS_PER_BAR}}`, `{{DURATION}}`, `{{STORES}}`.
- In the page script the same `D()` / `E()` exist in JavaScript.
- `cues.json` `"at"` fields and `make_bed.py --drop-bar k` use the same `D()`.

## 1. Scaffold

```bash
SFX_DIR=~/my-sfx $PY $S/new_project.py --app myapp --variant a --lang en --stores <STORES>
```
`<STORES>` is the stores the app is really on: `app_store`, `google_play`, or
`app_store,google_play`. The default (both) is wrong for a single-store app: its end card
would show a badge for a store the app is not in.
Default out folder `~/app-promo-reels`. Refuses a folder inside a git work tree (use `--force`
if you are sure) and always refuses the app-promo-reel repo itself. project.json is the one
place for duration, fps, size, beats per bar and stores.

## 2. Research

```bash
$PY $S/store_assets.py --out $P/work/store --app-store-id 123456789 --play com.example.app --country us --lang en
$PY $S/sample_colors.py $P/work/store/screens/01.png points.json   # relative coords 0-1
git -C <app-repo> fetch origin
git -C <app-repo> symbolic-ref refs/remotes/origin/HEAD            # -> origin/<branch>
git -C <app-repo> show origin/<branch>:<path/to/strings>
```
store_assets.py first removes an old metadata.json and screens/NN.png from `--out`. Exit 2 = no App Store data: ask the user for screenshots, or build from the
website only. Play facts are best-effort and never guessed.

## 3. Music

```bash
$PY $S/music_gen.py --duration 30 --seeds 5,17,23 --out $P/work/music \
  --prompt "upbeat indie pop, punchy four on the floor kick, crisp handclaps on the backbeat, 118 bpm, clear steady beat, energetic from the first bar"
$PY $S/music_rank.py --duration 30 --json $P/work/music/rank.json $P/work/music/bgm_*.wav
$PY $S/beat_grid.py $P/work/music/bgm_5.wav $P
$PY $S/make_bed.py $P/work/music/bgm_5.wav $P --drop-bar 6
```
- One music_gen.py at a time (GPU memory); exit 2 = a hard failure, no file written.
- Prompt: name the tempo (118-128 bpm; the 30 s template needs about 116 bpm or more, see
  storyboard.md), a steady kick, and "clear steady beat". At ~120 bpm a
  30 s video has 15 bars — the template's scenes assume bars 0-14.
- Seeds with a real lift: note `lift_at` from the rank table (drop rule: storyboard.md).
- Run `make_bed.py` after `beat_grid.py` (the lift window needs beats.json).
- The template's cues.json already ends a riser tail on the drop. Use `make_bed.py --riser`
  only when you remove that cue, or the riser plays twice.

## 4. Build

```bash
$PY $S/build.py $P      # src.html.tmpl -> index.html, cues.json -> cues.realized.json
cd $P && npx --yes hyperframes@0.8.78 check
npx --yes hyperframes@0.8.78 snapshot --at 1.0,2.4,4.6,... --describe false --no-end -o snapshots/r1
```
- Always edit `src.html.tmpl`, never index.html (it is overwritten).
- build.py adds the AI-generated label itself (text from `CONFIG.aiLabel`) with the last script
  of index.html: never add a label element or CSS for it to the template. A `page_error` about
  the AI-generated label in `hyperframes check` means it is empty or something hides it.
- Leftover or unknown `{{…}}` → exit 2.
- A cue whose SFX file is missing is skipped with a warning; the build still succeeds.
- Snapshots: pick every scene middle and every transition ±0.1 s. Write each round to a new
  `-o snapshots/rN` folder.

## 5. Render and finish

```bash
cd $P && npx --yes hyperframes@0.8.78 render -o renders/raw.mp4 -q delivery --quiet
$PY $S/finish.py $P renders/raw.mp4
```
finish.py: two-pass loudnorm to -14 LUFS / -2 dBTP (linear; the final AAC file must measure
within 1 LU of -14 and at most -1 dBTP), A/V lag check on the PCM before
AAC (< 5 ms), video stream copied and compared, sync report (each cue's own sound located by a
matched filter within ±150 ms on the audio minus the bed; fail on a cue > 1 frame off, or on
any checked cue not found — mark a cue that sits under a louder sound `"sync": false` in
cues.json), contact sheet, versioned output that never overwrites. While the checks run the file
is `…-v<N>.checking.mp4`; it becomes `…-v<N>.mp4` only when every check passed. Exit 1 → output
and contact sheet named `…-v<N>-failed.mp4` and the report lists the problems; an error or
Ctrl-C during the checks also leaves `-failed` (no report). A `.checking` file left behind was
never checked: do not deliver it.
Frame checks on the final MP4 print `warning:` lines and never fail the run: frame 0 blank (the
feed thumbnail), nothing readable by 1 s, a one-frame flash, or a sudden change near no beat and
no scene start. They are in the report under `"frames"`; the critique step of SKILL.md reads them.
