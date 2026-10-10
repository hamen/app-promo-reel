import json
import shutil
import subprocess

import pytest

from build import CalcError, calc, sfx_tags, substitute
from common import Grid
from conftest import run_script, tone_file

AI_LABEL = '<script>const CONFIG = {"aiLabel": "AI"};</script></body>\n'
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


@pytest.mark.parametrize("src", ["{{D}}", "{{NOPE 1}}", "{{D 1 2 3}}", "{{calc os.system}}", "{{DURATION 3}}",
                                 "{{WIDTH 3}}", "{{FRAME_SCALE 1}}"])
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
    assert r.returncode == 2 and "downbeat_phase must be" in r.stderr and "Traceback" not in r.stderr
    (p / "beats.json").write_text(_json.dumps(steady_grid()))
    (p / "project.json").write_text('{"app": "x", "variant": "a", "duration": "long"}')
    r = run_script("build.py", p)
    assert r.returncode == 2 and "must be JSON numbers" in r.stderr and "Traceback" not in r.stderr
    # a 400-digit integer does not fit a float: math.isfinite raised OverflowError on it
    (p / "project.json").write_text('{"app": "x", "variant": "a", "duration": 1' + "0" * 400 + '}')
    r = run_script("build.py", p)
    assert r.returncode == 2 and "must be JSON numbers" in r.stderr and "Traceback" not in r.stderr


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
    lines, realized = sfx_tags(tmp_path, {"sfx": {"a": "a.wav"}, "cues": [{**base, "at": 5, "align": "start"}]},
                               GRID, 30.0)
    assert realized[0]["time"] == 5.0  # a plain number is a time in seconds
    for bad in ([base, base], [{**base, "volume": None}], [{**base, "offset": "x"}], [{**base, "offset": "0.1"}],
                [{**base, "volume": True}], [{**base, "volume": -0.5}], [{**base, "sync": "false"}],
                [{**base, "sync": 0}], [{**base, "sync": None}]):
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


def test_a_bad_project_json_also_removes_the_previous_build(tmp_path):
    from conftest import write_project
    p = write_project(tmp_path)
    (p / "index.html").write_text("old build")
    (p / "project.json").write_text("{not json")
    assert run_script("build.py", p).returncode == 2
    assert not (p / "index.html").exists()


def test_template_that_is_not_utf8_exits_2(tmp_path):
    import json as _json
    from conftest import steady_grid, write_project
    p = write_project(tmp_path)
    (p / "beats.json").write_text(_json.dumps(steady_grid()))
    (p / "src.html.tmpl").write_bytes("<html>caf\u00e9</html>".encode("latin-1"))
    r = run_script("build.py", p)
    assert r.returncode == 2 and "UTF-8" in r.stderr and "Traceback" not in r.stderr


def test_media_duration_without_a_duration_exits_2(monkeypatch):
    import subprocess as sp
    import common
    monkeypatch.setattr(common.subprocess, "run", lambda *a, **k: sp.CompletedProcess(a, 0, '{"format": {}}', ""))
    with pytest.raises(SystemExit) as e:
        common.media_duration("x.wav")
    assert e.value.code == 2


def test_sync_false_is_kept_and_default_follows_align(tmp_path):
    audio = tmp_path / "assets" / "audio"
    audio.mkdir(parents=True)
    tone_file(audio / "a.wav")
    cues = [{"id": "a", "sfx": "a", "at": 5, "sync": False}, {"id": "b", "sfx": "a", "at": 8},
            {"id": "c", "sfx": "a", "at": 12, "align": "end"}]
    _, realized = sfx_tags(tmp_path, {"sfx": {"a": "a.wav"}, "cues": cues}, GRID, 30.0)
    assert [r["sync"] for r in realized] == [False, True, False]


def test_sfx_map_values_must_be_file_names(tmp_path):
    with pytest.raises(SystemExit) as e:
        sfx_tags(tmp_path, {"sfx": {"a": 7}, "cues": []}, GRID, 30.0)
    assert e.value.code == 2


def test_to_end_and_len_refuse_negative_lengths():
    short = {**PROJECT, "duration": 10.0}
    assert substitute("{{TO_END 4}}", GRID, short) == "0.500"  # D(4) = 9.5 s
    for src in ("{{TO_END 5}}", "{{LEN 3 1}}"):  # D(5) = 11.5 s, inside the grid but past the end
        with pytest.raises(SystemExit):
            substitute(src, GRID, short)
    assert substitute("{{LEN 1 1}}", GRID, PROJECT) == "0.000"


def test_unclosed_token_fails_the_build():
    with pytest.raises(SystemExit):
        substitute("<div>{{D 1</div>", GRID, PROJECT)


def test_two_sfx_markers_fail_the_build(tmp_path):
    import json as _json
    from conftest import steady_grid, write_project
    p = write_project(tmp_path)
    (p / "beats.json").write_text(_json.dumps(steady_grid()))
    (p / "src.html.tmpl").write_text("<html><!--SFX--><!--SFX-->" + AI_LABEL)
    r = run_script("build.py", p)
    assert r.returncode == 2 and "more than one <!--SFX-->" in r.stderr


def test_check_scenes_reads_single_quotes_and_skips_comments():
    from build import check_scenes
    check_scenes("<!-- <section id='old' data-start='31'> --><section id='a' data-start='1.0'>", 30.0)
    for tag in ("<section id='late' data-start='29.5'>", "<section id = 'late' data-start = '29.5'>",
                '<section data-start ="29.5">'):
        with pytest.raises(SystemExit):
            check_scenes(tag, 30.0)


@pytest.mark.parametrize("page, ok", [
    ('<!-- "aiLabel": "" --><script>const CONFIG = {"aiLabel": "AI"};</script>', True),
    ('<script>/* e.g. "aiLabel": "" */ const CONFIG = {"aiLabel": "AI"};</script>', True),
    ('<script>\n  // "aiLabel": ""\nconst CONFIG = {"aiLabel": "AI"};</script>', True),
    ('<!-- "aiLabel": "AI" --><script>const CONFIG = {"aiLabel": ""};</script>', False),
    ('<script>const CONFIG = {"aiLabel": 123};</script>', False),
    ('<script>const CONFIG = {"aiLabel": "\u3164\u2800"};</script>', False),
    ('<script>const CONFIG = {"aiLabel": "\\u3164"};</script>', False),
    ('<script>const CONFIG = {};</script>', False),
])
def test_ai_label_static_check(page, ok):
    from build import check_ai_label
    if ok:
        check_ai_label(page)
    else:
        with pytest.raises(SystemExit):
            check_ai_label(page)


@pytest.mark.parametrize("fields, msg", [
    ({"duration": "30"}, "JSON numbers"), ({"fps": True}, "JSON numbers"), ({"beats_per_bar": 4.5}, "whole number"),
])
def test_project_json_numbers_are_not_coerced(tmp_path, fields, msg):
    from conftest import write_project
    p = write_project(tmp_path)
    doc = {**json.loads((p / "project.json").read_text()), **fields}
    (p / "project.json").write_text(json.dumps(doc))
    r = run_script("build.py", p)
    assert r.returncode == 2 and msg in r.stderr, r.stderr


def test_fractional_fps_is_kept(tmp_path):
    from common import load_project
    (tmp_path / "project.json").write_text(json.dumps({"app": "x", "variant": "a", "fps": 29.97}))
    assert load_project(tmp_path)["fps"] == 29.97


def test_project_json_nan_and_infinity_are_refused(tmp_path):
    from conftest import write_project
    p = write_project(tmp_path)
    for text in ('"duration": NaN', '"duration": Infinity', '"fps": -Infinity'):
        (p / "project.json").write_text('{"app": "x", "variant": "a", %s}' % text)
        r = run_script("build.py", p)
        assert r.returncode == 2 and "JSON numbers" in r.stderr and "Traceback" not in r.stderr, text


def test_is_number_rejects_an_int_too_large_for_a_float():
    from common import is_number
    assert is_number(3) and is_number(29.97)
    assert not is_number(10 ** 400) and not is_number(float("inf")) and not is_number(True)


@pytest.mark.parametrize("doc, size", [
    ({}, (1080, 1920)),  # every project made before formats: no format, 9:16
    ({"format": "9:16", "width": 1080, "height": 1920}, (1080, 1920)),
    ({"format": "4:5"}, (1080, 1350)),  # no width/height in the file: the 9:16 defaults must not win
    ({"format": "4:5", "width": 1080, "height": 1350}, (1080, 1350)),
])
def test_the_size_comes_from_the_format(tmp_path, doc, size):
    from common import load_project
    (tmp_path / "project.json").write_text(json.dumps({"app": "x", "variant": "a", **doc}))
    p = load_project(tmp_path)
    assert (p["format"], p["width"], p["height"]) == (doc.get("format", "9:16"), *size)


@pytest.mark.parametrize("doc, msg", [
    ({"format": "1:1"}, "format must be one of 9:16, 4:5, 16:9, got '1:1'\n"),
    ({"format": "16:9", "duration": 3}, "a 16:9 loop needs a duration of at least 4 s"),
    ({"format": "16:9", "width": 1080}, "format 16:9 is 1920x1080, but the file says width 1080"),
    ({"format": ["4:5"]}, "format must be one of"),
    ({"format": {"4:5": 1}}, "format must be one of"),
    ({"format": "4:5", "height": 1920}, "format 4:5 is 1080x1350, but the file says height 1920"),
    ({"width": 1350}, "format 9:16 is 1080x1920, but the file says width 1350"),
])
def test_a_bad_format_or_a_size_against_it_exits_2(tmp_path, doc, msg):
    from conftest import write_project
    p = write_project(tmp_path)
    (p / "project.json").write_text(json.dumps({**json.loads((p / "project.json").read_text()), **doc}))
    r = run_script("build.py", p)
    assert r.returncode == 2 and msg in r.stderr and "Traceback" not in r.stderr, r.stderr


@pytest.mark.parametrize("fmt, want", [("9:16", "1080 1920 9:16 1"), ("4:5", "1080 1350 4:5 0.703125"), ("16:9", "1920 1080 16:9 0.5625")])
def test_size_tokens_come_from_the_format(tmp_path, fmt, want):
    from common import load_project
    (tmp_path / "project.json").write_text(json.dumps({"app": "x", "variant": "a", "format": fmt}))
    assert substitute("{{WIDTH}} {{HEIGHT}} {{FORMAT}} {{FRAME_SCALE}}", GRID, load_project(tmp_path)) == want


# --- the seekability check and the {{MOTION}} token (the motion language) ---------------------

def page(js, attrs=""):
    return f"<html><body><script{attrs}>\n{js}\n</script></body></html>"


def seekable_error(html, capsys):
    from build import check_seekable
    with pytest.raises(SystemExit) as e:
        check_seekable(html)
    assert e.value.code == 2
    return capsys.readouterr().err


@pytest.mark.parametrize("name, line", [
    ("Math.random", "const r = Math.random();"),
    ("Math.random", "const r = Math . random();"),
    ("Date.now", "const t = Date.now();"),
    ("new Date", "const d = new Date;"),
    ("Date(", "const d = Date();"),
    ("Date(", "const d = new Date(0);"),
    ("Date(", "const d = window.Date();"),
    ("Date(", "const d = globalThis.Date();"),
    ("performance.now", "const t = performance.now();"),
    ("setTimeout", "setTimeout(() => {}, 10);"),
    ("setInterval", "window.setInterval(f, 10);"),
    ("requestAnimationFrame", "requestAnimationFrame(tick);"),
    ("crypto.getRandomValues", "crypto.getRandomValues(a);"),
    ("crypto.randomUUID", "const id = crypto.randomUUID();"),
])
def test_a_hidden_clock_or_random_value_exits_2_and_quotes_its_line(capsys, name, line):
    err = seekable_error(page(f"const a = 1;\n    {line}\nconst b = 2;"), capsys)
    assert name in err and f"`{line}`" in err and "depend only on t" in err


@pytest.mark.parametrize("js", [
    "// Math.random() would break the seek",
    "/* Date.now() */ const a = 1;",
    "const a = 1; // setTimeout later",
    'const s = "Math.random()";',
    "const s = 'Date.now()';",
    "const s = `Math.random() is banned`;",
    "const s = `\\${Math.random()}`;",
    "const a = Date.UTC(2020, 0, 1);",
    "const a = Math.sin(1); gsap.to(x, { repeat: -1 });",
    "const mathRandom = 1, mydate = 2, setTimeoutLater = 3;",
])
def test_a_name_in_a_comment_a_string_or_a_longer_name_does_not_fail(js):
    from build import check_seekable
    check_seekable(page(js))


def test_a_script_with_a_src_or_a_json_script_is_not_read():
    from build import check_seekable
    check_seekable(page("Math.random()", ' src="x.js"'))
    check_seekable(page("Math.random()", ' type="application/json"'))


@pytest.mark.parametrize("attrs", [' data-src="x"', ' ng-src="x"', ' data-type="application/json"', ' data-type="text/plain"'])
def test_a_data_attribute_does_not_hide_a_script_from_the_check(capsys, attrs):
    assert "Math.random" in seekable_error(page("Math.random()", attrs), capsys)


@pytest.mark.parametrize("attrs", [
    ' id="src=x"', " id='src=x'", ' id="type=application/json"', ' data-note="a > b" id="src=x"',
    ' title="type=text/plain"', ' id=a"src=x"',
])
def test_text_inside_an_attribute_value_does_not_hide_a_script_from_the_check(capsys, attrs):
    assert "Math.random" in seekable_error(page("Math.random()", attrs), capsys)


@pytest.mark.parametrize("attrs", [' type="module"', ' type="text/javascript"', ' type="application/javascript"',
                                   " type=module", ' TYPE="Module"', ' type=""', ' type',
                                   ' type="module" type="application/json"',
                                   ' type="text/javascript; charset=UTF-8"', ' type="text/javascript;charset=utf-8"',
                                   ' type=" text/javascript "', ' type="\tmodule\n"'])
def test_a_script_that_runs_is_scanned(capsys, attrs):
    assert "Math.random" in seekable_error(page("Math.random()", attrs), capsys)


@pytest.mark.parametrize("attrs", [' src="x.js"', " src='x.js'", " src=x.js", ' type="application/json"',
                                   ' type="text/template"', ' data-x="1" src="x.js"',
                                   ' data-note="a > b" src="x.js"', " data-note='a > b' type='application/json'",
                                   ' type="application/json" type="module"',
                                   ' type="application/json; charset=utf-8"', ' type=" application/json "'])
def test_a_script_that_does_not_run_inline_is_not_scanned(attrs):
    from build import check_seekable
    check_seekable(page("Math.random()", attrs))


def test_every_hit_in_every_inline_script_gets_its_own_line(capsys):
    html = ("<html><body><script>\nMath.random();\nconst t = Date.now();\n</script>"
            "<script>\nrequestAnimationFrame(tick);\n</script></body></html>")
    err = seekable_error(html, capsys)
    assert [n for n in ("Math.random", "Date.now", "requestAnimationFrame") if f"remove {n} in" in err] == [
        "Math.random", "Date.now", "requestAnimationFrame"]
    assert err.count("remove ") == 3


@pytest.mark.parametrize("js", [
    "const s = `${Math.random()}`;",
    'const s = "//"; Math.random();',
    "const s = `a ${ `b ${Math.random()}` } c`;",
    "const s = '\\''; Math.random();",
    "/* a */ Math.random(); /* b */",
])
def test_code_next_to_a_comment_or_a_string_is_still_read(capsys, js):
    assert "Math.random" in seekable_error(page(js), capsys)


def test_a_clean_page_passes():
    from build import check_seekable
    check_seekable(page("const tl = gsap.timeline({ paused: true });\ntl.to('#a', { x: 1 }, 0);"))


def test_the_motion_token_is_replaced_by_the_file_text_literally():
    motion = "const spring = (os) => (p) => p; // $1 \\1 \\g<0>"
    assert substitute("a\n{{MOTION}}\nb", GRID, PROJECT, motion) == f"a\n{motion}\nb"


def test_the_motion_token_without_a_file_exits_2(capsys):
    with pytest.raises(SystemExit) as e:
        substitute("{{MOTION}}", GRID, PROJECT)
    assert e.value.code == 2 and "no motion.js" in capsys.readouterr().err


@pytest.mark.parametrize("motion", ["const a = {{}};", "x = {{ y }}"])
def test_a_double_brace_in_motion_js_exits_2(capsys, motion):
    with pytest.raises(SystemExit) as e:
        substitute("{{MOTION}}", GRID, PROJECT, motion)
    assert e.value.code == 2 and "double brace" in capsys.readouterr().err


def test_a_page_without_the_token_builds_without_motion_js(tmp_path):
    from conftest import write_project
    p = write_project(tmp_path)
    (p / "beats.json").write_text(json.dumps({"beats": [0.5 + 0.5 * i for i in range(70)], "downbeat_phase": 0}))
    (p / "src.html.tmpl").write_text(f"<html><body>{AI_LABEL}")
    r = run_script("build.py", p)
    assert r.returncode == 0, r.stderr
    assert not (p / "motion.js").exists()


def test_the_motion_token_without_motion_js_exits_2_with_one_line(tmp_path):
    from conftest import write_project
    p = write_project(tmp_path)
    (p / "beats.json").write_text(json.dumps({"beats": [0.5 + 0.5 * i for i in range(70)], "downbeat_phase": 0}))
    (p / "src.html.tmpl").write_text(f"<html><body><script>{{{{MOTION}}}}</script>{AI_LABEL}")
    r = run_script("build.py", p)
    assert r.returncode == 2 and "no motion.js" in r.stderr and "Traceback" not in r.stderr
    assert len(r.stderr.strip().splitlines()) == 1
    assert not (p / "index.html").exists()


# --- the feed formats: the AI label's place, the bottom-zone gate, the punch cap ------------------

@pytest.mark.parametrize("fmt, place, size, box", [
    ("9:16", 'left: "64px", bottom: "428px"', 32, "[64, 270, 960, 1500]"),
    ("4:5", 'left: "64px", bottom: "104px"', 30, "[64, 96, 1016, 1254]"),
    ("16:9", 'right: "44px", bottom: "40px"', 24, "null"),
])
def test_the_label_sits_in_the_feed_safe_box_at_the_format_minimum(fmt, place, size, box):
    from build import add_ai_label_guard
    html = add_ai_label_guard(AI_LABEL, fmt)
    assert "__AI_LABEL" not in html
    assert f'position: "absolute", {place}, "z-index"' in html
    # the size it draws is the size it checks
    assert f"font: 700 {size}px/1.25 sans-serif" in html and f'own.fontSize !== "{size}px"' in html
    assert f"const safe = {box};" in html


# the guard run in node with a stub DOM: its bounds checks get exact label boxes, so the result does not
# depend on a browser or on the machine's sans-serif width. The root sits in body and html; a case's
# setup (the first %s) runs before the guard: it can give a node computed-style values (`cs`) or CSS
# animations (`anims`), move the root (`root.shift`), register the page's own document.fonts.ready
# callbacks, and build a fake GSAP. The fonts.ready callbacks run, in order, after the guard.
GUARD_RUN = r"""
const [w, h, px, l, t, r, b] = process.argv.slice(1).map(Number);
const rect = (l, t, r, b) => ({ left: l, top: t, right: r, bottom: b, width: r - l, height: b - t });
const moved = (x) => rect(x.left + (root.shift || 0), x.top, x.right + (root.shift || 0), x.bottom);
const pill = rect(l, t, r, b), ink = rect(l + 23, t + 11, r - 23, b - 11);
const node = (tag) => ({ tagName: tag, kids: [], anims: [], cs: {}, style: { setProperty() {} }, parentElement: null,
  attachShadow: () => ({ append() {} }), appendChild(c) { c.parentElement = this; this.kids.push(c); },
  getAnimations() { return this.anims; }, getBoundingClientRect() { return moved(this === root ? rect(0, 0, w, h) : pill); } });
const html = node("HTML"), body = node("BODY"), root = node("DIV");
html.appendChild(body);
body.appendChild(root);
const label = () => root.kids[root.kids.length - 1];  // the guard appends it last
const later = [];
globalThis.window = globalThis;
globalThis.innerWidth = w;
globalThis.innerHeight = h;
globalThis.CONFIG = { aiLabel: "AI-generated" };
globalThis.document = { querySelector: () => root, createElement: (tag) => node(tag.toUpperCase()),
  createRange: () => ({ selectNodeContents() {}, getBoundingClientRect: () => moved(ink) }),
  fonts: { ready: { then(f) { later.push(f); } } } };
globalThis.getComputedStyle = (n, pseudo) => pseudo ? { content: "none" } : { color: "rgb(255, 255, 255)",
  webkitTextFillColor: "rgb(255, 255, 255)", fontSize: px + "px", display: "block", clipPath: "none",
  maskImage: "none", webkitMaskImage: "none", filter: "none", mixBlendMode: "normal", opacity: "1",
  transform: "none", translate: "none", rotate: "none", scale: "none", zoom: "1", ...n.cs };
// a fake GSAP: getChildren(nested, tweens, timelines) reads its three flags as GSAP does
const tween = (...targets) => ({ targets: () => targets });
const timeline = (...kids) => ({ kids, getChildren(nested, tweens, timelines) {
  return this.kids.flatMap((c) => {
    const line = typeof c.getChildren === "function";
    return [...((line ? timelines : tweens) ? [c] : []), ...(line && nested ? c.getChildren(nested, tweens, timelines) : [])];
  });
} });
%s
try { new Function(%s)(); for (const f of later) f(); console.log("ok"); } catch (e) { console.log(e.message); }
"""
BOX_FAIL = "the AI-generated label is not fully inside the feed safe box (references/storyboard.md): it must stay on screen"
FRAME_FAIL = "the AI-generated label is not fully inside the frame: it must stay on screen"


def run_guard(fmt, pill, setup="", mutate=None):
    from build import AI_LABEL_PLACES, add_ai_label_guard
    from common import FORMATS
    html = add_ai_label_guard(AI_LABEL, fmt)
    guard = html.split("<script data-ai-label-guard>", 1)[1].split("</script>", 1)[0]
    if mutate:
        guard = mutate(guard)
    w, h = FORMATS[fmt]
    r = subprocess.run(["node", "-e", GUARD_RUN % (setup, json.dumps(guard)), "--",
                        *map(str, (w, h, AI_LABEL_PLACES[fmt][1], *pill))], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
@pytest.mark.parametrize("fmt, pill, result", [
    ("9:16", (64, 1430, 300, 1492), "ok"),        # where build.py puts it
    ("9:16", (64, 1430, 960, 1492), "ok"),        # on the box's right edge
    ("9:16", (64, 1430, 961, 1492), BOX_FAIL),    # 1 px past it, far inside the frame
    ("9:16", (64, 1439, 300, 1501), BOX_FAIL),    # past the bottom edge (y 1500)
    ("9:16", (63, 1430, 300, 1492), BOX_FAIL),
    ("9:16", (64, 269, 300, 331), BOX_FAIL),      # above the top edge (y 270)
    ("4:5", (64, 1186.5, 1016, 1246), "ok"),
    ("4:5", (64, 1186.5, 1017, 1246), BOX_FAIL),
    ("4:5", (64, 1196, 300, 1255), BOX_FAIL),
    ("16:9", (1600, 1000, 1876, 1040), "ok"),     # no box: the frame is the bound
    ("16:9", (1600, 1000, 1921, 1040), FRAME_FAIL),
])
def test_the_guard_keeps_the_label_inside_the_feed_safe_box(fmt, pill, result):
    assert run_guard(fmt, pill) == result


TWEEN_FAIL = "by a GSAP tween: animate a child of the composition root instead: it must stay on screen"
CSS_FAIL = "by a CSS animation or transition: it must stay on screen"


ANIMATED = [
    ("", "ok"),                                                       # no GSAP on the page
    ("const s1 = node('SECTION'); root.appendChild(s1);"
     " globalThis.gsap = { globalTimeline: timeline(timeline(tween(s1), tween({}))) };", "ok"),  # a scene, a plain object
    ("globalThis.gsap = { globalTimeline: timeline(tween(root)) };", "sits in the composition root, which is animated " + TWEEN_FAIL),
    ("globalThis.gsap = { globalTimeline: timeline(tween(body)) };", "sits in body, which is animated " + TWEEN_FAIL),
    ("globalThis.gsap = { globalTimeline: timeline(tween(html)) };", "sits in html, which is animated " + TWEEN_FAIL),
    # a timeline built in the page's own fonts.ready callback, after the label exists: "#root > *" holds it
    ("const main = timeline(); globalThis.gsap = { globalTimeline: timeline(main) };"
     " document.fonts.ready.then(() => main.kids.push(tween(label())));", "is animated " + TWEEN_FAIL),
    ("globalThis.gsap = { globalTimeline: timeline(timeline(timeline(tween(root)))) };",
     "sits in the composition root, which is animated " + TWEEN_FAIL),                         # nested
    ("globalThis.gsap = { globalTimeline: timeline() }; window.__timelines = { main: timeline(tween(root)) };",
     "sits in the composition root, which is animated " + TWEEN_FAIL),                         # only in __timelines
    ("const main = timeline(); globalThis.gsap = { globalTimeline: timeline(main) };"
     " document.fonts.ready.then(() => main.kids.push(tween(root)));",
     "sits in the composition root, which is animated " + TWEEN_FAIL),                         # added in fonts.ready
    ("document.fonts.ready.then(() => { root.cs = { opacity: '0.3' }; });",
     "is faded out (opacity of the label and its ancestors): it must stay on screen"),        # set in fonts.ready
    ("root.cs = { transform: 'matrix(1, 0, 0, 1, 4000, 0)' };", "sits in a transformed element: it must stay on screen"),
    # the separate transform properties: a scale keeps the label inside the frame, smaller
    ("root.cs = { scale: '0.5' };", "sits in a transformed element: it must stay on screen"),
    ("body.cs = { rotate: '180deg' };", "sits in a transformed element: it must stay on screen"),
    ("root.cs = { translate: '4000px' };", "sits in a transformed element: it must stay on screen"),  # boxes not moved
    # zoom shrinks the label without a transform: in 16:9, anchored right, it stays inside the frame
    ("root.cs = { zoom: '0.8' };", "sits in a zoomed element: it must stay on screen"),
    ("document.fonts.ready.then(() => { label().cs = { zoom: '0.5' }; });", "is zoomed: it must stay on screen"),
    ("root.shift = 4000;", FRAME_FAIL[len("the AI-generated label "):]),                        # moved with its label
    ("root.anims = [{}];", "sits in the composition root, which is animated " + CSS_FAIL),
    ("document.fonts.ready.then(() => { label().anims = [{}]; });", "is animated " + CSS_FAIL),
]


def expected(result):
    return result if result == "ok" else "the AI-generated label " + result


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
@pytest.mark.parametrize("setup, result", ANIMATED)
def test_the_guard_fails_on_anything_that_animates_the_label_or_its_ancestors(setup, result):
    assert run_guard("9:16", (64, 1430, 300, 1492), setup) == expected(result)  # where build.py puts the label


# control mutations: each part of the guard is needed, so removing it changes the result of a case above
GUARD_MUTATIONS = {
    "no ancestor watched": [("    for (let n = el.parentElement; n; n = n.parentElement) watched.push(n);\n", "")],
    "label not watched": [("    const watched = [el];", "    const watched = [];")],
    "global timeline only": [('    if (window.__timelines && typeof window.__timelines === "object") '
                              'lines.push(...Object.values(window.__timelines));\n', "")],
    "not nested": [("line.getChildren(true, true, false)", "line.getChildren(false, true, false)")],
    "no second read": [("  document.fonts.ready.then(inspect);\n", "")],
    "second read of the tween scan only": [
        ("  const inspect = () => {\n", "  let reads = 0;\n  const inspect = () => {\n    if (!reads++) {\n"),
        ("    // the checks above read the page at one moment;", "    }\n    // the checks above read the page at one moment;")],
    "no CSS animation read": [("    for (const n of watched) if (n.getAnimations().length) "
                               "fail(`${who(n)} by a CSS animation or transition`);\n", "")],
    "transform only": [("[cs.transform, cs.translate, cs.rotate, cs.scale]", "[cs.transform]")],
    "no translate read": [("[cs.transform, cs.translate, cs.rotate, cs.scale]", "[cs.transform, cs.rotate, cs.scale]")],
    "no zoom read": [('      if (!["1", "normal"].includes(cs.zoom)) fail(n === el ? "is zoomed" : "sits in a zoomed element");\n', "")],
    "no transform read": [("[cs.transform, cs.translate, cs.rotate, cs.scale]", "[]")],
    "no viewport read": [("      if (box.left < 0 || box.top < 0 || box.right > innerWidth || box.bottom > innerHeight) "
                          'fail("is not fully inside the frame");\n', "")],
}


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
@pytest.mark.parametrize("name", GUARD_MUTATIONS)
def test_each_part_of_the_guard_is_needed(name):
    def mutate(guard):
        for old, new in GUARD_MUTATIONS[name]:
            assert guard.count(old) == 1, (name, old)
            guard = guard.replace(old, new, 1)
        return guard
    changed = [setup for setup, result in ANIMATED
               if run_guard("9:16", (64, 1430, 300, 1492), setup, mutate) != expected(result)]
    assert changed, f"no case sees the mutation: {name}"


@pytest.mark.parametrize("spans, duration, times", [
    ([(0.0, 5.0), (5.0, 5.0)], 10.0, [1.1, 4.5, 6.1, 9.5]),  # 1.1 s in, and 0.5 s before each window ends
    ([(0.0, 7.0), (5.0, 5.0)], 10.0, [1.1, 4.5, 9.5]),       # an overlap: scene 2's window starts at 7
    ([(0.0, None)], 10.0, [1.1, 9.5]),                       # no duration: it runs to the end
    ([(0.0, 1.6)], 1.6, [1.1]),                              # the same time twice is one time
    ([(0.0, 1.0)], 1.0, [0.5]),                              # 1.1 s is past the window
    ([(0.0, 0.3)], 0.3, []),
])
def test_settled_times_are_two_per_scene_window(spans, duration, times):
    from build import settled_times
    assert settled_times(spans, duration) == times


TWO_SCENES = '<section data-start="0" data-duration="15"></section><section data-start="15" data-duration="15"></section>'


@pytest.mark.parametrize("fmt, y0", [("9:16", "0.78125"), ("4:5", "0.92889")])
def test_a_feed_format_checks_the_bottom_of_its_safe_box_at_settled_times(fmt, y0):
    from build import check_command
    # 1.1, 14.5, 16.1 and 29.5 s of 30 s
    assert check_command("/p/my reel", TWO_SCENES, {"format": fmt, "duration": 30.0}) == (
        "npx --yes hyperframes@0.8.78 check '/p/my reel' --caption-zone "
        f'"x0=0;y0={y0};x1=1;y1=1;severity=error;seek=0.0367,0.4833,0.5367,0.9833"')


@pytest.mark.parametrize("fmt, html", [("16:9", TWO_SCENES), ("9:16", f"<!-- {TWO_SCENES} -->")])
def test_no_feed_box_or_no_live_scene_gives_the_plain_check(fmt, html):
    from build import check_command
    assert check_command("/p/r", html, {"format": fmt, "duration": 30.0}) == "npx --yes hyperframes@0.8.78 check /p/r"


@pytest.mark.parametrize("js, warned", [
    ('shake("#a", 1, 18); flash(1, 0.3, 0.25); shake("#b", 9, 18); flash(9, 0.3, 0.25);', []),
    ('shake("#a", 1); shake("#a", 2); shake ("#a", 3);', ["shake"]),
    ("flash(1); flash(2); flash(3); shake(1); shake(2); shake(3);", ["shake", "flash"]),
    # a definition, a comment, a string, a method and a longer name are not calls
    ('function shake(t) {} function flash(t) {} shake(1); shake(2); flash(1); flash(2); // shake(3) flash(3)\n'
     'const s = "shake(4) flash(4)"; /* shake(5) */ cam.shake(6); cam.flash(6); myflash(7); shake_it(8);', []),
])
def test_more_than_two_shakes_or_flashes_is_a_warning(js, warned):
    from build import punch_warnings
    got = punch_warnings(f"<script>{js}</script>")
    assert [w.split()[1] for w in got] == [f"{n}()" for n in warned]
    assert all(w.startswith("3 ") and "(at most 2, on the drop and the end card: references/motion.md)" in w for w in got)
