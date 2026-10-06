import json
import os
from pathlib import Path

import pytest

from conftest import SCRIPTS, run_script, write_project

SCORES = "scores: hook=8 readability=7 motion=8 variety=8 composition=8 claims=9 sound=8"
DEFECT = "- t=1.2 evidence=reviews/still-1.2.jpg fix=src.html.tmpl: hold the CTA 0.4 s longer"


@pytest.fixture
def proj(tmp_path):
    p = write_project(tmp_path, duration=4)
    (p / "reviews").mkdir()
    (p / "reviews" / "still-1.2.jpg").write_bytes(b"jpg")
    (p / "src.html.tmpl").write_text("<html></html>")
    return p


def write(p, text, n=1):
    (p / "reviews" / f"critique-{n}.md").write_text(text)


def check(p, *args):
    return run_script("critique_check.py", p, *args)


def test_a_valid_file_passes(proj):
    write(proj, f"# round 1\n\n{SCORES}\n\n{DEFECT}\n")
    r = check(proj)
    assert r.returncode == 0, r.stderr
    assert "critique-1.md: 7 scores, 1 defects" in r.stdout


def test_a_zero_defect_file_needs_every_score_at_8(proj):
    write(proj, "scores: hook=8 readability=9 motion=8 variety=8 composition=10 claims=9 sound=8\n")
    assert check(proj).returncode == 0
    write(proj, SCORES + "\n")  # readability 7
    r = check(proj)
    assert r.returncode == 1 and "no defects, but readability below 8" in r.stderr


def test_a_skill_script_is_a_valid_fix_file(proj):
    write(proj, SCORES + "\n- t=0 evidence=reviews/still-1.2.jpg fix=make_bed.py: lower the drop by 3 dB\n")
    assert (SCRIPTS / "make_bed.py").is_file()
    assert check(proj).returncode == 0


def test_the_default_round_is_the_highest(proj):
    write(proj, "nothing useful\n", 1)
    write(proj, f"{SCORES}\n{DEFECT}\n", 2)
    assert check(proj).returncode == 0
    r = check(proj, "--round", "1")
    assert r.returncode == 1 and "no scores: line" in r.stderr


def test_a_missing_round_exits_1(proj):
    r = check(proj)
    assert r.returncode == 1 and "critique-N.md" in r.stderr
    write(proj, f"{SCORES}\n{DEFECT}\n", 1)
    r = check(proj, "--round", "3")
    assert r.returncode == 1 and "critique-3.md" in r.stderr


def test_a_silent_project_scores_loop_not_sound(tmp_path):
    p = tmp_path / "hero"
    p.mkdir()
    (p / "project.json").write_text(json.dumps({"app": "demo", "variant": "a", "format": "16:9"}))
    (p / "reviews").mkdir()
    loop = "scores: hook=8 readability=8 motion=8 variety=8 composition=8 claims=8 loop=8\n"
    write(p, loop)
    assert check(p).returncode == 0
    write(p, loop.replace("loop=", "sound="))
    r = check(p)
    assert r.returncode == 1 and "unknown score 'sound' (a silent 16:9 project scores loop" in r.stderr
    assert "missing score: loop" in r.stderr


def test_a_9x16_file_with_loop_fails(proj):
    write(proj, SCORES.replace("sound=", "loop=") + "\n" + DEFECT + "\n")
    r = check(proj)
    assert r.returncode == 1 and "unknown score 'loop' (this project scores sound" in r.stderr
    assert "missing score: sound" in r.stderr


@pytest.mark.parametrize("line, msg", [
    ("scores: hook=8 readability=7 motion=8 variety=8 composition=8 claims=9", "missing score: sound"),
    (SCORES.replace("hook=8", "hook=0"), "hook: the score must be a whole number from 1 to 10, got '0'"),
    (SCORES.replace("hook=8", "hook=11"), "hook: the score must be a whole number from 1 to 10, got '11'"),
    (SCORES.replace("hook=8", "hook=8.5"), "got '8.5'"),
    (SCORES.replace("hook=8", "hook=eight"), "got 'eight'"),
    (SCORES + " hook=9", "'hook=9' is not a new name=score pair"),
])
def test_bad_scores_are_reported(proj, line, msg):
    write(proj, line + "\n" + DEFECT + "\n")
    r = check(proj)
    assert r.returncode == 1 and msg in r.stderr


def test_a_second_scores_line_fails(proj):
    write(proj, f"{SCORES}\n{SCORES}\n{DEFECT}\n")
    assert "line 2: a second scores: line" in check(proj).stderr


def test_four_defects_fail(proj):
    write(proj, SCORES + "\n" + (DEFECT + "\n") * 4)
    r = check(proj)
    assert r.returncode == 1 and "4 defects: at most 3" in r.stderr
    write(proj, SCORES + "\n" + (DEFECT + "\n") * 3)
    assert check(proj).returncode == 0


@pytest.mark.parametrize("t, ok", [("0", True), ("3.96", True), ("3.9666", True), ("4", False), ("3.97", False),
                                   ("-0.1", False), ("abc", False), ("nan", False), ("inf", False)])
def test_t_must_have_a_frame(proj, t, ok):
    write(proj, SCORES + "\n" + DEFECT.replace("t=1.2", f"t={t}") + "\n")
    r = check(proj)
    assert (r.returncode == 0) == ok, r.stderr
    if not ok:
        assert f"t={t}: must be a time from 0 to 3.967 s" in r.stderr


def test_missing_evidence_fails(proj):
    write(proj, SCORES + "\n" + DEFECT.replace("still-1.2", "still-9.9") + "\n")
    r = check(proj)
    assert r.returncode == 1 and "evidence reviews/still-9.9.jpg is not a file in the project" in r.stderr


def test_evidence_is_a_file_not_a_folder(proj):
    write(proj, SCORES + "\n" + DEFECT.replace("reviews/still-1.2.jpg", "reviews") + "\n")
    assert "is not a file" in check(proj).stderr


def test_evidence_and_fix_cannot_leave_the_project(proj, tmp_path):
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"x")
    write(proj, SCORES + "\n" + DEFECT.replace("reviews/still-1.2.jpg", "../outside.jpg") + "\n")
    assert "evidence ../outside.jpg leaves the project folder" in check(proj).stderr
    link = proj / "reviews" / "link.jpg"
    os.symlink(outside, link)
    write(proj, SCORES + "\n" + DEFECT.replace("still-1.2", "link") + "\n")
    assert "leaves the project folder" in check(proj).stderr
    write(proj, SCORES + "\n" + DEFECT.replace("fix=src.html.tmpl", "fix=../outside.jpg") + "\n")
    assert "fix file ../outside.jpg is neither" in check(proj).stderr
    assert (SCRIPTS.parent / "SKILL.md").is_file()
    write(proj, SCORES + "\n" + DEFECT.replace("fix=src.html.tmpl", "fix=../SKILL.md") + "\n")
    assert "fix file ../SKILL.md is neither" in check(proj).stderr


def test_a_fix_file_that_does_not_exist_fails(proj):
    write(proj, SCORES + "\n" + DEFECT.replace("src.html.tmpl", "nothing.html") + "\n")
    assert "fix file nothing.html is neither a file in the project nor a script of the skill" in check(proj).stderr


def test_a_malformed_defect_names_its_line(proj):
    write(proj, SCORES + "\n- the hook is weak\n")
    r = check(proj)
    assert r.returncode == 1 and "line 2: a defect reads: - t=<seconds>" in r.stderr
    write(proj, SCORES + "\n" + DEFECT.replace("fix=src.html.tmpl:", "fix=src.html.tmpl") + "\n")
    assert "line 2: a defect reads" in check(proj).stderr


def test_skill_step_6_runs_the_checker_and_the_format_doc_matches_it():
    skill = " ".join((SCRIPTS.parent / "SKILL.md").read_text().split())
    step6 = skill[skill.index("6. **Critique"):skill.index("7. **Deliver")]
    assert "critique_check.py" in step6 and "reviews/critique-<N>.md" in step6 and "references/critique.md" in step6
    assert "Judge only the rendered frames" in step6
    doc = (SCRIPTS.parent / "references" / "critique.md").read_text()
    # the example in the doc is a file the checker accepts
    assert SCORES in doc and "fix=src.html.tmpl: hold the CTA 0.4 s longer" in doc
    for name in ("hook", "readability", "motion", "variety", "composition", "claims", "sound", "loop"):
        assert f"`{name}`" in doc
