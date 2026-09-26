import json

import pytest

from build import CalcError, calc, sfx_tags, substitute
from common import Grid
from conftest import run_script, tone_file

GRID = Grid([0.5 + 0.5 * i for i in range(40)], 2, 4)  # first downbeat at 1.5 s
PROJECT = {"duration": 30.0, "stores": ["google_play"]}


def test_D_E_addressing():
    assert GRID.D(0) == 1.5
    assert GRID.D(1, 2) == 1.5 + 6 * 0.5
    assert GRID.D(-1, 2) == 0.5          # pickup beat before the first downbeat
    assert GRID.E(0, 1) == 2.25
    with pytest.raises(ValueError):
        GRID.D(-1, 0)


def test_tokens_substituted_and_css_untouched():
    src = ("@font-face { font-family: X; } @media (x) {} @keyframes k {}\n"
           "{{D 2}} {{D 1 3}} {{E 0}} {{LEN 1 3}} {{TO_END 2}} {{calc D(2)-0.3}} {{calc -(D(1)+E(0,1))/2}}\n"
           "{{BEATS_PER_BAR}} {{DOWNBEAT_INDEX}} {{DURATION}} {{STORES}} {{calc DURATION-D(2)}}")
    out = substitute(src, GRID, PROJECT)
    assert out.startswith("@font-face { font-family: X; } @media (x) {} @keyframes k {}")
    assert out.splitlines()[1].split() == ["5.500", "5.000", "1.750", "4.000", "24.500", "5.200", "-2.875"]
    assert out.splitlines()[2] == '4 2 30 ["google_play"] 24.500'
    assert json.loads(substitute("{{BEATS}}", GRID, PROJECT))[:2] == [0.5, 1.0]


@pytest.mark.parametrize("expr", ["__import__('os')", "D.__class__", "open(1)", "D(1, x=2)", "2**8",
                                  "D(1.5)", "[1][0]", "E", "abs(-1)"])
def test_calc_rejects_anything_but_arithmetic(expr):
    with pytest.raises(CalcError):
        calc(expr, GRID, 30.0)


@pytest.mark.parametrize("src", ["{{D}}", "{{NOPE 1}}", "{{D 1 2 3}}", "{{calc os.system}}", "{{DURATION 3}}"])
def test_bad_or_leftover_token_exits_2(src):
    with pytest.raises(SystemExit) as e:
        substitute(src, GRID, PROJECT)
    assert e.value.code == 2


def test_sfx_tracks_never_overlap_and_missing_file_is_skipped(tmp_path, capsys):
    audio = tmp_path / "assets" / "audio"
    audio.mkdir(parents=True)
    tone_file(audio / "a.wav", 0.3)
    tone_file(audio / "r.wav", 1.0)
    doc = {"sfx": {"a": "a.wav", "r": "r.wav", "gone": "missing.mp3"},
           "cues": [{"id": "c1", "sfx": "a", "at": "D(0)"},
                    {"id": "c2", "sfx": "a", "at": "D(0)", "offset": 0.1},
                    {"id": "c3", "sfx": "a", "at": "D(1)"},
                    {"id": "c4", "sfx": "gone", "at": "D(0)"},
                    {"id": "c5", "sfx": "r", "at": "D(2)", "align": "end"}]}
    lines, realized = sfx_tags(tmp_path, doc, GRID, 30.0)
    assert "c4" in capsys.readouterr().err
    by_id = {r["id"]: r for r in realized}
    assert set(by_id) == {"c1", "c2", "c3", "c5"}
    assert by_id["c1"]["track"] == 21 and by_id["c2"]["track"] == 22 and by_id["c3"]["track"] == 21
    assert abs(by_id["c5"]["time"] - (GRID.D(2) - 1.0)) < 0.01 and by_id["c5"]["sync"] is False
    ends = {}
    for r in sorted(realized, key=lambda r: r["time"]):
        assert ends.get(r["track"], -1) <= r["time"]
        ends[r["track"]] = r["time"] + (1.0 if r["id"] == "c5" else 0.3)
    assert len(lines) == 4


def test_attack_alignment_skips_leading_silence(tmp_path):
    import numpy as np
    import soundfile as sf
    audio = tmp_path / "assets" / "audio"
    audio.mkdir(parents=True)
    sr = 48000
    snd = np.concatenate([np.zeros(int(0.1 * sr)), 0.5 * np.ones(int(0.2 * sr))])
    sf.write(audio / "late.wav", snd, sr)
    doc = {"sfx": {"late": "late.wav"}, "cues": [{"id": "att", "sfx": "late", "at": "D(1)"},
                                                 {"id": "raw", "sfx": "late", "at": "D(2)", "align": "start"}]}
    _, realized = sfx_tags(tmp_path, doc, GRID, 30.0)
    by_id = {r["id"]: r for r in realized}
    assert abs(by_id["att"]["time"] - (GRID.D(1) - 0.1)) < 0.001 and by_id["att"]["align"] == "attack"
    assert by_id["raw"]["time"] == GRID.D(2)


def test_build_without_sfx_succeeds_and_realizes_nothing(project):
    (project / "src.html.tmpl").write_text("<div data-duration='{{DURATION}}'>{{D 1}}</div>\n<!--SFX-->\n")
    (project / "cues.json").write_text(json.dumps({"sfx": {"a": "a.mp3"}, "cues": [{"id": "x", "sfx": "a", "at": "D(0)"}]}))
    r = run_script("build.py", project)
    assert r.returncode == 0, r.stderr
    assert "skipping cue 'x'" in r.stderr
    assert json.loads((project / "cues.realized.json").read_text()) == []
    assert "{{" not in (project / "index.html").read_text()
