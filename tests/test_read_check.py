"""read_check.py without a browser: the rule, the runs, the throw-away folder, the parsing of the check's
JSON and the output. A fake `npx` replays a real `hyperframes check --json` result of 0.8.78
(fixtures/read_check.json: the stock template, 9:16, 120 BPM, with the pass's lines; the run token is
`__TOKEN__` there and is put back by the fake). The pass itself runs in a browser only:
test_read_check_browser.py (opt-in)."""
import json
import os
import re
import stat
import sys
from pathlib import Path

import pytest

import build
import read_check as rc
from conftest import FIXTURES, TEMPLATE, run_script, write_project

FAKE_NPX = r'''#!{python}
"""Fake npx: records the call and what the folder holds, then prints the scenario file with the
token of the page it was given."""
import json, os, re, sys, time
from pathlib import Path
args = sys.argv[1:]
folder = Path(args[args.index("check") + 1])
page = (folder / "index.html").read_text()
m = re.search(r'const TOKEN = "([0-9a-f]+)"', page)
entries = {{e.name: (os.readlink(e) if e.is_symlink() else None) for e in folder.iterdir()}}
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({{"args": args, "entries": entries, "page": page}}) + "\n")
time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
out = Path(os.environ["FAKE_CHECK"]).read_text()
print(out.replace("__TOKEN__", m.group(1)) if m else out)
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
'''

PAGE = """<!doctype html><html><body>
<!-- an old </body> in a comment -->
<div id="root" data-composition-id="main" data-start="0" data-duration="30">
<section data-start="0" data-duration="30"><div id="cap" data-read></div></section></div>
<script>window.__timelines = {main: gsap.timeline({paused: true})};</script>
</body></html>
"""


def fixture():
    return json.loads((FIXTURES / "read_check.json").read_text())


def runtime(doc):
    return doc["runtime"]["findings"]


def line(body, token="__TOKEN__"):
    return {"code": "console_warning", "severity": "warning", "message": f"{token} {json.dumps(body)}"}


def set_caption(doc, name, **changes):
    """Change the pass line of caption `name` in the fixture."""
    for f in runtime(doc):
        body = json.loads(f["message"].split(" ", 1)[1])
        if body.get("caption") == name:
            body.update(changes)
            f["message"] = f"__TOKEN__ {json.dumps(body)}"
            return
    raise AssertionError(name)


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """A project with an index.html, a fake npx on PATH, and a scenario to replay (the fixture)."""
    p = write_project(tmp_path)
    (p / "index.html").write_text(PAGE)
    (p / "assets").mkdir()
    (p / "renders").mkdir()
    (p / "src.html.tmpl").write_text("x")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    npx = bin_dir / "npx"
    npx.write_text(FAKE_NPX.format(python=sys.executable))
    npx.chmod(npx.stat().st_mode | stat.S_IEXEC)
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps(fixture()))
    temp = tmp_path / "temp"
    temp.mkdir()
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_LOG": str(tmp_path / "log"),
           "FAKE_CHECK": str(scenario), "TMPDIR": str(temp)}
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    class Fake:
        project, log, check, tmp = p, tmp_path / "log", scenario, temp

        def write(self, doc):
            scenario.write_text(json.dumps(doc) if not isinstance(doc, str) else doc)

        def calls(self):
            return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []

        def run(self, **extra):
            return run_script("read_check.py", p, env={**env, **extra})
    return Fake()


# 1. the rule

@pytest.mark.parametrize("words,seconds", [(1, 0.8), (2, 0.8), (3, 0.9), (4, 1.2), (6, 1.8)])
def test_the_rule_has_a_floor_and_a_slope(words, seconds):
    assert rc.need(words) == pytest.approx(seconds)


@pytest.mark.parametrize("fps", [30, 60])
@pytest.mark.parametrize("words", [1, 3, 6])
def test_a_run_of_exactly_the_need_is_enough_and_one_frame_less_is_short(fps, words):
    n = rc.need_frames(words, fps)
    assert n == round(rc.need(words) * fps)
    listed = {"done": True, "captions": [["#a", words]]}

    def out(frames):
        return rc.report([{"i": 0, "caption": "#a", "text": "x", "words": words, "runs": [[10, 10 + frames]]}, listed], fps)
    assert out(n) == ["read_check: 1 caption, 0 short"]
    assert out(n - 1)[0].startswith("warning: reading time: #a ")


# 2. runs

def test_the_longest_run_wins_and_a_tie_goes_to_the_earlier_one():
    assert rc.longest_run([[0, 5], [10, 20], [30, 40]]) == (10, 10)
    assert rc.longest_run([[3, 4]]) == (1, 3)
    assert rc.longest_run([]) == (0, None)


# 3. the folder

def test_the_pass_goes_before_the_last_body_and_nothing_else_changes():
    page = rc.with_pass(PAGE, "abc", 30, 30.0)
    script = page[page.index("<script data-read-check>"):page.index("</script>", page.index("<script data-read-check>")) + 10]
    end = PAGE.rfind("</body>")
    assert end > PAGE.index("an old </body>")
    assert page == PAGE[:end] + script + PAGE[end:]
    assert 'const TOKEN = "abc", FPS = 30.0, DURATION = 30.0' in script
    assert rc.with_pass("<html>no body end</html>", "abc", 30, 30.0) is None


def test_the_folder_links_every_entry_but_the_left_out_ones(fake):
    r = fake.run()
    assert r.returncode == 0, r.stderr
    (call,) = fake.calls()
    p = fake.project
    assert call["entries"].pop("index.html") is None  # a copy, not a link
    assert call["entries"] == {e.name: str(e.resolve()) for e in p.iterdir() if e.name not in ("index.html", "renders")}
    assert call["page"] == rc.with_pass(PAGE, re.search(r'TOKEN = "(\w+)"', call["page"]).group(1), 30, 30.0)
    assert (p / "index.html").read_text() == PAGE
    assert list(fake.tmp.iterdir()) == []


def test_a_project_without_renders_works(fake):
    (fake.project / "renders").rmdir()
    assert fake.run().returncode == 0


def test_the_folder_is_removed_after_an_error_and_after_ctrl_c(fake, monkeypatch, capsys):
    fake.write("not json")
    assert fake.run().returncode == 2
    assert list(fake.tmp.iterdir()) == []

    def interrupted(folder):
        assert Path(folder).is_dir() and (Path(folder) / "index.html").is_file()
        raise KeyboardInterrupt
    monkeypatch.setattr(rc, "run_check", interrupted)
    monkeypatch.setattr(rc.tempfile, "tempdir", str(fake.tmp))
    with pytest.raises(KeyboardInterrupt):
        rc.read_check(fake.project)
    assert list(fake.tmp.iterdir()) == []


# 4. the pass and the command

def test_the_pass_uses_no_clock_and_no_random_value():
    page = rc.with_pass(PAGE, "abc", 30, 30.0)
    build.check_seekable(page)  # dies (SystemExit) on a banned name
    code = build.blank_js(rc.PASS)
    for name, rx in build.SEEKABLE_BANNED:
        assert not re.search(rx, code), name


def test_the_check_runs_the_pinned_hyperframes_with_json_and_no_contrast(fake):
    assert fake.run().returncode == 0
    (call,) = fake.calls()
    folder = call["args"][3]
    assert call["args"] == ["--yes", build.HYPERFRAMES, "check", folder, "--json", "--no-contrast"]
    assert Path(folder).name.startswith("reel-read-")


# 5. parsing

def test_the_real_result_reads_as_seventeen_captions_none_short(fake):
    r = fake.run()
    assert r.returncode == 0, r.stderr
    assert r.stdout == "read_check: 17 captions, 0 short\n"


def test_lines_with_another_token_or_no_token_are_ignored(fake):
    doc = fixture()
    short = {"i": 2, "caption": "#cap-b", "text": "Step two", "words": 2, "runs": []}
    runtime(doc).append(line(short, token="0123456789abcdef"))
    runtime(doc).append({"code": "console_warning", "severity": "warning", "message": json.dumps(short)})
    fake.write(doc)
    r = fake.run()
    assert (r.returncode, r.stdout) == (0, "read_check: 17 captions, 0 short\n")


def test_a_check_that_exits_1_with_json_is_still_read(fake):
    r = fake.run(FAKE_EXIT="1")
    assert (r.returncode, r.stdout) == (0, "read_check: 17 captions, 0 short\n")


def drop(doc, pred):
    doc["runtime"]["findings"] = [f for f in runtime(doc) if not pred(f["message"])]
    return doc


@pytest.mark.parametrize("scenario,reason", [
    (lambda d: "garbage", "gave no JSON"),
    (lambda d: drop(d, lambda m: '"done"' in m), "did not report"),
    (lambda d: drop(d, lambda m: '"done"' in m) | {"x": [line({"done": False, "error": "no timeline"})]},
     "pass failed: no timeline"),
    (lambda d: drop(d, lambda m: '"#fl-2"' in m and '"runs"' in m), "no result for #fl-2"),
    (lambda d: {**d, "x": [{"code": "console_warning", "severity": "warning", "message": "__TOKEN__ {broken"}]},
     "does not parse"),
])
def test_each_failure_of_the_pass_exits_2_with_its_reason(fake, scenario, reason):
    doc = scenario(fixture())
    fake.write(doc)
    r = fake.run()
    assert r.returncode == 2 and reason in r.stderr, r.stderr
    assert r.stdout == ""


def test_a_missing_index_or_body_end_exits_2_and_runs_no_check(fake):
    (fake.project / "index.html").write_text("<html>no end</html>")
    r = fake.run()
    assert r.returncode == 2 and "has no </body>" in r.stderr
    (fake.project / "index.html").unlink()
    r = fake.run()
    assert r.returncode == 2 and "run build.py first" in r.stderr
    assert fake.calls() == []


def test_no_npx_exits_2(fake):
    r = fake.run(PATH=os.path.dirname(sys.executable))
    assert r.returncode == 2 and "npx is not installed" in r.stderr


def test_a_check_that_hangs_exits_2(fake, monkeypatch, capsys):
    monkeypatch.setattr(rc, "CHECK_TIMEOUT", 1)
    monkeypatch.setenv("FAKE_SLEEP", "5")
    monkeypatch.setattr(rc.tempfile, "tempdir", str(fake.tmp))
    with pytest.raises(SystemExit) as e:
        rc.read_check(fake.project)
    assert e.value.code == 2 and "did not finish in 1 s" in capsys.readouterr().err
    assert list(fake.tmp.iterdir()) == []


# 6. output

def test_short_captions_are_warned_in_time_order_with_their_numbers(fake):
    doc = fixture()
    set_caption(doc, "#val-sub", runs=[[695, 720]])           # 25 frames, needs 36
    set_caption(doc, "#cap-b", runs=[[278, 290], [300, 310]])  # 12 frames, needs 24
    set_caption(doc, "#fl-2", runs=[])                         # never readable
    fake.write(doc)
    r = fake.run()
    assert r.returncode == 0
    assert r.stdout.splitlines() == [
        'warning: reading time: #cap-b "Step two" (2 words) is readable for 0.4 s from 9.3 s; it needs 0.8 s',
        'warning: reading time: #val-sub "A true closing claim" (4 words) is readable for 0.8 s from 23.2 s; '
        "it needs 1.2 s",
        'warning: reading time: #fl-2 "A third one" (3 words) is readable for 0.0 s (never); it needs 0.9 s',
        "read_check: 17 captions, 3 short",
    ]


def test_a_caption_with_no_words_is_listed_and_not_timed(fake):
    doc = drop(fixture(), lambda m: '"caption":"#cta"' in m)
    for f in runtime(doc):
        if '"done"' in f["message"]:
            body = json.loads(f["message"].split(" ", 1)[1])
            body["captions"][-1] = ["#cta", 0]
            f["message"] = f"__TOKEN__ {json.dumps(body)}"
    fake.write(doc)
    r = fake.run()
    assert r.stdout.splitlines() == ["read_check: #cta has no words, not timed", "read_check: 16 captions, 0 short"]


def test_a_page_with_no_marked_text_says_so(fake):
    doc = drop(fixture(), lambda m: m.startswith("__TOKEN__"))
    runtime(doc).append(line({"done": True, "captions": []}))
    fake.write(doc)
    r = fake.run()
    assert (r.returncode, r.stdout) == (0, "warning: reading time: no text is marked data-read; nothing was timed\n")


def test_a_16_9_loop_is_not_checked(fake):
    pj = fake.project / "project.json"
    pj.write_text(json.dumps({**json.loads(pj.read_text()), "format": "16:9", "width": 1920, "height": 1080}))
    r = fake.run()
    assert (r.returncode, r.stdout) == (0, "read_check: 16:9 is a silent loop, not checked\n")
    assert fake.calls() == []


# 7. the template

READ = ["hook-words", "cap-a", "cap-b", "feat-title", "fl-0", "fl-1", "fl-2", "ben-0", "ben-1", "ben-2", "ben-line",
        "val-a", "val-b", "val-sub", "wordmark", "tagline", "cta"]


def test_the_template_marks_exactly_the_texts_to_read_each_inside_a_scene():
    src = (TEMPLATE / "src.html.tmpl").read_text()
    marked = re.findall(r'<[a-z0-9]+\b[^>]*\bdata-read\b[^>]*>', src)
    assert [re.search(r'\bid="([^"]+)"', tag).group(1) for tag in marked] == READ
    for name in READ:
        at = src.index(f'id="{name}"')
        assert src.rfind("<section", 0, at) > src.rfind("</section>", 0, at), name

