# Storyboard — bars, scenes, variants

## Structure (30 s, ~120 bpm, 15 bars)

| Bars | Scene (template id) | Job |
|---|---|---|
| 0-1 | s1 hook | the full hook (4 words) is static and opaque from frame 0, with a beat punch on beats 0 of bars 0 and 1; one real app item card slides in |
| 2-5 | s2 the app | phone with two rebuilt screens; rows pop on beats; a tap on beat 3 |
| 6-7 | s3 the drop | the strongest real feature, slammed on the drop downbeat, flash + shake |
| 8-9 | s4 benefits | three short true benefits, one per half bar |
| 10-11 | s5 value | a two-part value word, a true one-line claim |
| 12-end | s6 end card | icon, name, tagline, CTA, only the stores the app is on, URL |

## Shot list

Each project has a `shotlist.md`: one row per scene, with the scene id (`s1`, not `s1 hook`), its
purpose, its entry state and its exit state. The Job column above is where the purposes start.
If you cannot say why a scene exists, it does not belong in the render. `build.py` fails when a
live scene has no row, when a row has no scene, or when a cell is empty or `TODO`. When you add,
remove or rename a scene, edit its row. Never delete `shotlist.md`: the check runs only while the
file exists.

| scene | purpose | entry state | exit state |
| --- | --- | --- | --- |
| s3 | The drop: the strongest real feature | The phone has left and the word is hidden | The word is settled after the flash |

Rules:
- Frame 0 already shows the hook text or UI: feeds use it as the thumbnail. No fade in from an
  empty background (finish.py warns "frame 0 is blank").
- Every change lands on a beat. Words slam on downbeats or beat 2. Scene cuts start ~0.3 s
  before a downbeat so the new scene is settled on it.
- 16:9 hero: no beats and no bars. Time the scenes in seconds with `{{calc DURATION*x}}`; see `hero.md`.
- 4:5 feed: a feed video starts muted. Every claim and every step is on screen as text; nothing
  depends on the sound (a sound effect can stress a word, never carry it).
- One idea per scene. Text a viewer must read stays on screen ≥ 0.8 s (a sentence: ~0.3 s per
  word).
- A different tempo means a different bar count: re-map the scenes, never squeeze text.
  The template's last lines (store badges, URL) enter on D(13, 3) and need 1.1 s to settle
  and be read: with a 30 s video that is about 116 bpm or faster (the first downbeat
  moves it a little). A slower seed fails the build with the re-map message.
  build.py fails when a scene would start less than 2 s before the end of the video.

## Drop placement

The drop bar is chosen in the storyboard first (template: bar 6). Then:
- If the chosen seed has a detected lift (`lift_at` in the rank table) on a downbeat in bars
  4-8, move the storyboard's drop to that bar.
- Otherwise build a synthetic lift: `make_bed.py --drop-bar <drop bar>`, so the full band hits
  on the drop downbeat. The riser tail comes from the `riser` cue in cues.json.

## Hook / angle menu (one per variant, never repeat)

1. **The problem, in the viewer's words** — "FORGOT IT / IN THE BACK / OF THE FRIDGE?"
2. **The moment of use** — the single screen people open the app for, from second one.
3. **Before → after** — the messy way, then the app's way (only if the app shows both).
4. **The one feature** — the most distinctive real feature as the hook.
5. **Question to the viewer** — "STILL DOING X BY HAND?"
6. **Speed** — how few taps the core action takes (count them in the real app).
7. **For who** — families / students / a hobby, if the listing names that audience.

Colour mood per variant: e.g. brand colour vs a light surface vs a warm accent — always from
DESIGN.md colours.

## SFX (cues.json)

Whoosh into each scene cut, impact on slams, pop on items, click on taps, chime on the value
line, a riser tail ending on the drop (`"align": "end"`), a big impact on the drop and the logo.
Keep volumes 0.25-0.85; the drop and the logo loudest.

A cue's `at` is when the sound is HEARD: build.py skips the leading silence of each file
(`"align": "attack"`, the default). Many stock SFX start with 50-400 ms of silence; without
this, a pop on the beat sounds a tenth of a second late.

finish.py checks every cue and fails on one it cannot find in the final audio ("masked").
A cue placed under a louder sound on purpose (a pop inside the drop's impact tail, a spark
under a whoosh) cannot be checked: mark it `"sync": false` with a `"why"` in cues.json. The
template's cues.json already marks the ones it layers.
