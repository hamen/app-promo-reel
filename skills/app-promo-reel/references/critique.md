# Critique file — `reviews/critique-<N>.md`

Each critique round writes one file in the project folder, then runs
`critique_check.py <project>` before it fixes anything. Judge only the rendered frames. Do not
describe what you intended.

## Format

```
reviewer: fresh
scores: hook=8 readability=7 motion=8 variety=8 composition=8 claims=9 sound=8

- t=12.4 evidence=reviews/still-12.4.jpg fix=src.html.tmpl: hold the CTA 0.4 s longer
```

- One `reviewer:` line: `fresh` when a new subagent wrote the file (SKILL.md, step 6), `self` when
  the author of the reel wrote it because the host cannot start a subagent.
- One `scores:` line with seven `name=score` pairs. A score is a whole number from 1 to 10.
  The names are `hook`, `readability`, `motion`, `variety`, `composition`, `claims`, and a seventh:
  `sound` for a 9:16 or 4:5 reel, `loop` for a silent 16:9 hero.
- Then 0 to 3 defects, the worst ones, one line each: `- t=<seconds> evidence=<path> fix=<file>: <change>`.
  - `t` is a time in the video that has a frame: from 0 to `duration - 1/fps`.
  - `evidence` is one image file in the project folder that shows the defect (not a folder).
  - `fix` is the file that controls it, then a colon and the change. The file is in the project
    folder (`src.html.tmpl`, `cues.json`) or a script of the skill (`make_bed.py`).
- No defect is valid only when every score is 8 or more. That is the "stop" exit of the critique.
  A score below 8 needs at least one defect.
- Other lines (a heading, a note) are ignored. A line that starts with `-` must be a defect.
- A path may not leave the project folder by `..` or by a symlink.

## Reviewer brief

The author fills in the parts in `<>` and gives this text, and nothing more, to a new subagent. One
new subagent per round: a reviewer that saw round 1 judges round 2 against its own notes.

```
You review a promo reel that you did not make. Judge only what a viewer sees and hears.

Project folder: <project>
Round: <N>   Format: <9:16 | 4:5 | 16:9>   Duration: <s> s   fps: <fps>
Final MP4: <project>/renders/<app>-<variant>-v<M>.mp4
Contact sheet and poster: the -sheet.jpg and -poster.jpg next to it
Finish report: <project>/renders/<app>-<variant>-v<M>-report.json
Warnings of finish.py, read_check.py and blur.py (copied as printed):
<every warning: and fastest: line, or "none">
Scene start times (s): <t1, t2, ...>

Read <skill>/SKILL.md, step 6, and <skill>/references/critique.md. Do the steps of step 6 that
look at the reel, and score it. For the claims score, read the allowed claims under
"Copy rules" in <project>/DESIGN.md. Do not open src.html.tmpl, shotlist.md, cues.json or reviews/critique-*.md
of earlier rounds: you judge the frames, not the plan. Put your evidence stills in
<project>/reviews/. Write <project>/reviews/critique-<N>.md, with "reviewer: fresh", and run
critique_check.py <project> until it exits 0. Reply with the path of the file.
```

`<skill>` is the folder of SKILL.md. The `fix=` file of a defect still names the file that controls
it (`src.html.tmpl`, `cues.json`, `make_bed.py`): the reviewer knows that from step 6, without
reading the file.

## Scores with a fixed rule

- **readability**: a text or a tap outside the feed safe box on a settled frame (not the AI-generated
  label: build.py puts it at the frame's bottom-left corner), or a text under the
  format's minimum size (`references/storyboard.md`, "Feed safe zones"), caps readability at 6.
  Read the 270 px contact sheet first, then the stills at full size.
  Each `reading time:` warning from read_check.py that is not fixed is a readability defect. Its `t=`
  is the time after "from" in the warning (for a "(never)" warning, a time in the text's scene), and
  its evidence is a still from the render at that time (`references/storyboard.md`, "Reading time").
- **motion**: read each `still for …` warning from finish.py, as you read the pops. The check
  measures the whole frame, so a background pulse counts as motion: also look for a foreground
  that does not move.

## Evidence stills

A still from the real render, at time `t`, picks the frame by its number (the same way finish.py
does), so it is the frame the viewer gets:

```bash
mkdir -p reviews
ffmpeg -nostdin -v error -y -i renders/<app>-<variant>-v<N>.mp4 \
  -vf "select=eq(n\,$(python3 -c 'print(round(12.4*30))'))" -fps_mode passthrough -frames:v 1 reviews/still-12.4.jpg
```

Use the project fps in place of 30. The contact sheet (`…-sheet.jpg`) and the poster
(`…-poster.jpg`) in `renders/` are also valid evidence. A snapshot from `hyperframes snapshot` is
too, but it shows the preview, not the render: prefer the MP4.

On a blurred reel (`scripts/blur.py`), take a still at each `fastest:` time it printed. The line
names the frames with the most local change, one per move, not proven copies. Separate copies of
one object in a still are a **motion** defect: slow the move (`references/motion.md`, "Motion blur"),
or render without blur.

## What the check proves

`critique_check.py` checks form: the scores exist and are whole numbers, each defect has a time with
a frame, an image that exists and a file to fix. It does not judge whether the scores are right.
The scores come from looking at the frames.
