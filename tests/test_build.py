import json

import pytest

from build import CalcError, calc, sfx_tags, substitute
from common import Grid
from conftest import run_script, tone_file

AI_LABEL = '<div id="ai-label" data-cfg="aiLabel"></div><script>const CONFIG = {"aiLabel": "AI"};\nassertAiLabel();\n</script>\n'
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
    (project / "src.html.tmpl").write_text("<div data-duration='{{DURATION}}'>{{D 1}}</div>\n<!--SFX-->\n" + AI_LABEL)
    (project / "cues.json").write_text(json.dumps({"sfx": {"a": "a.mp3"}, "cues": [{"id": "x", "sfx": "a", "at": "D(0)"}]}))
    r = run_script("build.py", project)
    assert r.returncode == 0, r.stderr
    assert "skipping cue 'x'" in r.stderr
    assert json.loads((project / "cues.realized.json").read_text()) == []
    assert "{{" not in (project / "index.html").read_text()


def test_bad_cue_id_exits_2(tmp_path):
    audio = tmp_path / "assets" / "audio"
    audio.mkdir(parents=True)
    tone_file(audio / "a.wav")
    with pytest.raises(SystemExit) as e:
        sfx_tags(tmp_path, {"sfx": {"a": "a.wav"}, "cues": [{"id": 'x" onload="y', "sfx": "a", "at": "D(0)"}]},
                 GRID, 30.0)
    assert e.value.code == 2


def test_division_by_zero_in_calc_is_a_calc_error():
    with pytest.raises(CalcError):
        calc("D(1)/0", GRID, 30.0)


def test_beat_outside_the_bar_is_refused():
    with pytest.raises(CalcError):
        calc("D(2, 5)", GRID, 30.0)
    with pytest.raises(ValueError):
        GRID.D(2, -1)


def test_check_scenes_sees_either_attribute_order():
    from build import check_scenes
    check_scenes('<section id="a" data-start="1.0"></section><section id="z" data-start="28.0">', 30.0)
    for tag in ('<section data-start="31.0" id="late">', '<section id="short" data-start="28.1">', '<section class="x" data-start="-1" id="neg">',
                '<section id="bad" data-start="x">'):
        with pytest.raises(SystemExit):
            check_scenes(tag, 30.0)


def test_bad_cues_json_exits_2(tmp_path):
    for doc in ({"sfx": [], "cues": []}, {"sfx": {}, "cues": {}}, {"sfx": {"a": "a.wav"}, "cues": [{"id": "x"}]},
                {"sfx": {"a": "a.wav"}, "cues": ["x"]}):
        with pytest.raises(SystemExit) as e:
            sfx_tags(tmp_path, doc, GRID, 30.0)
        assert e.value.code == 2, doc


def test_build_refuses_broken_json_files(tmp_path):
    import json as _json
    from conftest import run_script, steady_grid, write_project
    p = write_project(tmp_path)
    (p / "src.html.tmpl").write_text("<html><!--SFX--></html>")
    (p / "beats.json").write_text(_json.dumps(steady_grid()))
    (p / "cues.json").write_text("{not json")
    r = run_script("build.py", p)
    assert r.returncode == 2 and "cues.json" in r.stderr and "Traceback" not in r.stderr
    (p / "cues.json").unlink()
    (p / "beats.json").write_text('{"beats": [1, 2]}')
    r = run_script("build.py", p)
    assert r.returncode == 2 and "beat grid" in r.stderr and "Traceback" not in r.stderr
    (p / "beats.json").write_text(_json.dumps(steady_grid()))
    (p / "project.json").write_text('{"app": "x", "variant": "a", "duration": "long"}')
    r = run_script("build.py", p)
    assert r.returncode == 2 and "must be numbers" in r.stderr and "Traceback" not in r.stderr


def test_missing_sfx_marker_with_cues_exits_2(tmp_path):
    import json as _json
    from conftest import run_script, steady_grid, write_project
    p = write_project(tmp_path)
    audio = p / "assets" / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    tone_file(audio / "a.wav")
    (p / "src.html.tmpl").write_text("<html></html>")
    (p / "beats.json").write_text(_json.dumps(steady_grid()))
    (p / "cues.json").write_text(_json.dumps({"sfx": {"a": "a.wav"}, "cues": [{"id": "c", "sfx": "a", "at": "D(1)"}]}))
    r = run_script("build.py", p)
    assert r.returncode == 2 and "<!--SFX-->" in r.stderr


def test_before_end_token_renders_nothing_or_fails():
    project = {"duration": 30.0, "stores": ["app_store"]}
    assert substitute("a{{BEFORE_END 1.1 D(2)}}b", GRID, project) == "ab"
    assert substitute("{{BEFORE_END 1.1 D(7)}}", GRID, {**project, "duration": 16.6}) == ""  # D(7) = 15.5 s
    with pytest.raises(SystemExit):
        substitute("{{BEFORE_END 1.1 D(7)}}", GRID, {**project, "duration": 16.595})  # 5 ms short


def test_cue_fields_are_checked(tmp_path):
    audio = tmp_path / "assets" / "audio"
    audio.mkdir(parents=True)
    tone_file(audio / "a.wav")
    base = {"id": "c", "sfx": "a", "at": "D(1)"}
    lines, realized = sfx_tags(tmp_path, {"sfx": {"a": "a.wav"}, "cues": [{**base, "at": 5}]}, GRID, 30.0)
    assert realized[0]["time"] <= 5.0  # a plain number is a time in seconds
    for bad in ([base, base], [{**base, "volume": None}], [{**base, "offset": "x"}]):
        with pytest.raises(SystemExit) as e:
            sfx_tags(tmp_path, {"sfx": {"a": "a.wav"}, "cues": bad}, GRID, 30.0)
        assert e.value.code == 2, bad


def test_failed_build_removes_the_previous_build(tmp_path):
    import json as _json
    from conftest import steady_grid, write_project
    p = write_project(tmp_path)
    (p / "src.html.tmpl").write_text("<html>{{NOPE}}</html>")
    (p / "beats.json").write_text(_json.dumps(steady_grid()))
    (p / "index.html").write_text("old build")
    (p / "cues.realized.json").write_text("[]")
    assert run_script("build.py", p).returncode == 2
    assert not (p / "index.html").exists() and not (p / "cues.realized.json").exists()


def test_stores_that_are_not_a_list_exit_2(tmp_path):
    from conftest import write_project
    p = write_project(tmp_path)
    for stores in ("null", "7", '"app_store"'):
        (p / "project.json").write_text('{"app": "x", "variant": "a", "stores": %s}' % stores)
        r = run_script("build.py", p)
        assert r.returncode == 2 and "non-empty subset" in r.stderr and "Traceback" not in r.stderr, stores
