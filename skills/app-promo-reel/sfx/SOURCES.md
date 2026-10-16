# Bundled sound effects

`new_project.py` copies these 9 files into `assets/audio/` of every 9:16 and 4:5 project, so the
first reel has sound effects with no setup. They are the 9 file names that `template/cues.json`
uses. A file of the same name in `$SFX_DIR` replaces the bundled one in the project.

Every file is **CC0 1.0** (<https://creativecommons.org/publicdomain/zero/1.0/>): the author gave up
all rights, so no credit is required and commercial use is allowed. Each sound was found with the
Openverse audio search (<https://openverse.org>), and its licence was read on its Freesound page on
2026-10-16.

| File | Sound | Author | Page | Licence | Gain |
| --- | --- | --- | --- | --- | --- |
| `whoosh.mp3` | Space Swoosh - brighter | GameAudio | <https://freesound.org/people/GameAudio/sounds/220191/> | CC0 1.0 | +5 dB |
| `whoosh-short.mp3` | Short Woosh 01.wav | ironcross32 | <https://freesound.org/people/ironcross32/sounds/582892/> | CC0 1.0 | +3 dB |
| `impact-bass-1.mp3` | BOOM IMPACT 2 | XHALE303 | <https://freesound.org/people/XHALE303/sounds/535592/> | CC0 1.0 | +12 dB |
| `impact-bass-2.mp3` | BOOM IMPACT | XHALE303 | <https://freesound.org/people/XHALE303/sounds/535557/> | CC0 1.0 | +12 dB |
| `pop.mp3` | The Best Bubble Pop Sound For Game and UI | el_boss | <https://freesound.org/people/el_boss/sounds/669918/> | CC0 1.0 | -3 dB |
| `click.mp3` | UI Button Click | benzix2 | <https://freesound.org/people/benzix2/sounds/467951/> | CC0 1.0 | -9 dB |
| `chime.mp3` | [UI Sound] Approval - High Pitched Bell Synth | GabFitzgerald | <https://freesound.org/people/GabFitzgerald/sounds/625174/> | CC0 1.0 | -16 dB |
| `sparkle.mp3` | Fantasy_ui_Button_6.wav | ZenithInfinitiveStudios | <https://freesound.org/people/ZenithInfinitiveStudios/sounds/376748/> | CC0 1.0 | +4 dB |
| `riser-tail.mp3` | Riser | Rizzard | <https://freesound.org/people/Rizzard/sounds/561207/> | CC0 1.0 | 0 dB |

How each file was made from the Freesound MP3 preview: stereo at 44.1 kHz, peak set to -4 dBFS,
then the gain in the table, then a soft clip (tanh) at -3 dBFS, then cut where it is quieter than
-50 dBFS at the start and -60 dBFS at the end, then MP3 (LAME VBR quality 2). The gains put each
sound at about the loudness of the sounds that the volumes in `template/cues.json` were tuned on.
