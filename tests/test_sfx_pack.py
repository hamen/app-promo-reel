"""The bundled CC0 sound pack (skills/app-promo-reel/sfx/): one file for each sound the template
names, each one a CC0 row in SOURCES.md, small, and ready to land on a beat. bin/ci tracks no other
media file."""

import json
import re
import subprocess

import numpy as np
import pytest

from common import decode_audio
from conftest import SCRIPTS, TEMPLATE

PACK = SCRIPTS.parent / "sfx"
CI = SCRIPTS.parents[2] / "bin" / "ci"
ROW = re.compile(
    r"^\| `([^`]+)` \| [^|]+ \| [^|]+ \| <(https://freesound\.org/people/[^/]+/sounds/\d+/)> \| CC0 1\.0 \| [+-]?\d+ dB \|$",
    re.M,
)
MAX_PACK_BYTES = 400_000  # the 9 files are about 240 KB; a WAV or a long file would pass this
SOUNDS = sorted(f.name for f in PACK.glob("*.mp3"))


def test_the_pack_has_one_file_for_each_sound_the_template_names():
    names = set(json.loads((TEMPLATE / "cues.json").read_text())["sfx"].values())
    assert sorted(f.name for f in PACK.iterdir()) == sorted(names | {"SOURCES.md"})


def test_sources_lists_every_file_once_as_cc0():
    text = (PACK / "SOURCES.md").read_text()
    rows = ROW.findall(text)
    # a file row in another form (another licence, no page) matches no ROW and fails here
    assert len(rows) == len(re.findall(r"^\| `", text, re.M))
    assert sorted(f for f, _ in rows) == SOUNDS
    assert len({page for _, page in rows}) == len(rows)


def test_the_pack_stays_small():
    assert sum(f.stat().st_size for f in PACK.iterdir()) <= MAX_PACK_BYTES


@pytest.mark.parametrize("name", SOUNDS)
def test_each_sound_starts_at_once_and_never_clips(name):
    sr = 48000
    assert 0.05 <= len(decode_audio(PACK / name, sr)) / sr <= 3.0
    stereo = np.abs(decode_audio(PACK / name, sr, mono=False))  # L, R, L, R, ...
    assert stereo.max() <= 1.0
    # SOURCES.md: cut where both channels are quieter than -50 dBFS at the start
    assert np.argmax(stereo > 10 ** (-50 / 20)) / 2 / sr <= 0.01


def media_scan(paths):
    """The media= line of bin/ci, run on `paths` in place of `git ls-files`."""
    m = re.search(r"^media=\$\(git ls-files (.*?) \|\| true\)$", CI.read_text(), re.S | re.M)
    assert m, "bin/ci has no media= scan"
    script = f"set -euo pipefail; media=$(printf '%s\\n' \"$@\" {m.group(1)} || true); printf '%s' \"$media\""
    return subprocess.run(
        ["bash", "-c", script, "scan", *paths], capture_output=True, text=True, check=True
    ).stdout.split()


def test_bin_ci_lets_through_only_the_mp3_files_of_the_pack():
    passed = ["skills/app-promo-reel/sfx/pop.mp3", "skills/app-promo-reel/sfx/SOURCES.md", "README.md"]
    stopped = [
        "skills/app-promo-reel/sfx/pop.wav",
        "skills/app-promo-reel/sfx/POP.MP3",
        "skills/app-promo-reel/sfx/more/pop.mp3",
        "skills/app-promo-reel/template/pop.mp3",
        "tests/fixtures/pop.mp3",
        "renders/demo.mp4",
    ]
    assert media_scan(passed + stopped) == stopped
