"""The shot-list contract: <project>/shotlist.md must match the scenes of the page while it exists."""
import json
import re

import pytest

from conftest import run_script, steady_grid


def scaffold_and_build(tmp_path, fmt="9:16", edit=None, expect=0, edit_html=None):
    out = tmp_path / "out"
    r = run_script("new_project.py", "--app", "demo", "--variant", "a", "--out", out, "--force", "--format", fmt)
    assert r.returncode == 0, r.stderr
    p = out / "demo-a"
    if fmt != "16:9":
        (p / "beats.json").write_text(json.dumps(steady_grid(first=0.7, iv=0.5, n=64, phase=1)))
    if edit:
        (p / "shotlist.md").write_text(edit((p / "shotlist.md").read_text()))
    if edit_html:
        (p / "src.html.tmpl").write_text(edit_html((p / "src.html.tmpl").read_text()))
    r = run_script("build.py", p)
    assert r.returncode == expect, r.stderr
    return p, r


def row(text, scene):
    return next(line for line in text.splitlines() if line.startswith(f"| {scene} |"))


def ids(p):
    return [line.split("|")[1].strip() for line in (p / "shotlist.md").read_text().splitlines()
            if re.match(r"\| s\d+ \|", line)]


@pytest.mark.parametrize("fmt", ["9:16", "4:5", "16:9"])
def test_an_untouched_scaffold_builds_with_its_shotlist(tmp_path, fmt):
    p, _ = scaffold_and_build(tmp_path, fmt)
    assert (p / "shotlist.md").is_file() and (p / "index.html").is_file()


def test_each_format_ships_a_shotlist_for_its_own_scenes(tmp_path):
    p, _ = scaffold_and_build(tmp_path / "a")
    assert ids(p) == ["s1", "s2", "s3", "s4", "s5", "s6"]
    h, _ = scaffold_and_build(tmp_path / "b", "16:9")
    assert ids(h) == ["s1"]


def test_a_project_without_a_shotlist_builds_as_before(tmp_path):
    p, _ = scaffold_and_build(tmp_path, edit=None)
    (p / "shotlist.md").unlink()
    (p / "index.html").unlink()
    r = run_script("build.py", p)
    assert r.returncode == 0, r.stderr


def fails(tmp_path, edit, *needles, edit_html=None):
    p, r = scaffold_and_build(tmp_path, edit=edit, expect=2, edit_html=edit_html)
    for n in needles:
        assert n in r.stderr, r.stderr
    assert not (p / "index.html").exists(), "a failed check must leave no index.html"
    return r.stderr


def test_a_scene_with_no_row_stops_the_build(tmp_path):
    fails(tmp_path, lambda t: t.replace(row(t, "s3") + "\n", ""), "scene s3 has no row")


def test_a_row_for_a_scene_that_does_not_exist_stops_the_build(tmp_path):
    fails(tmp_path, lambda t: t.rstrip("\n") + "\n| s9 | a | b | c |\n", "row for s9")


def test_a_duplicate_row_stops_the_build(tmp_path):
    fails(tmp_path, lambda t: t.rstrip("\n") + "\n" + row(t, "s2") + "\n", "scene s2 has more than one row")


@pytest.mark.parametrize("cell", ["", "TODO", "todo"])
def test_an_empty_or_todo_cell_stops_the_build(tmp_path, cell):
    def edit(t):
        cells = row(t, "s4").split("|")
        cells[3] = f" {cell} "
        return t.replace(row(t, "s4"), "|".join(cells))
    fails(tmp_path, edit, "scene s4: the entry state is empty or TODO")


def test_a_sentence_that_contains_todo_is_not_a_todo_cell(tmp_path):
    def edit(t):
        cells = row(t, "s4").split("|")
        cells[2] = " Three benefits, nothing left TODO "
        return t.replace(row(t, "s4"), "|".join(cells))
    scaffold_and_build(tmp_path, edit=edit)


def test_a_scene_with_no_id_stops_the_build(tmp_path):
    fails(tmp_path, lambda t: t, "a scene has no id",
          edit_html=lambda h: h.replace('<section id="s2" ', "<section ", 1))


def test_every_problem_is_reported_in_one_message(tmp_path):
    def edit(t):
        return t.replace(row(t, "s3") + "\n", "").rstrip("\n") + "\n| s9 | a | b | c |\n"
    err = fails(tmp_path, edit, "scene s3 has no row", "row for s9")
    assert err.count("error:") == 1


def test_a_commented_out_scene_needs_no_row(tmp_path):
    scaffold_and_build(tmp_path, edit_html=lambda h: h.replace(
        '<section id="s6" ', '<!-- <section id="s9" data-start="1"></section> -->\n<section id="s6" ', 1))


def test_a_title_before_the_table_is_fine_but_no_table_or_two_fail(tmp_path):
    scaffold_and_build(tmp_path / "ok", edit=lambda t: "# Another title\n\nSome prose.\n\n" + t)
    fails(tmp_path / "none", lambda t: "# Shot list\n\nnothing here\n", "found 0")
    fails(tmp_path / "two", lambda t: t + "\n" + t, "found 2")


def test_a_row_with_the_wrong_cell_count_stops_the_build(tmp_path):
    fails(tmp_path, lambda t: t.replace(row(t, "s5"), "| s5 | only two |"), "has 2 cells")


def test_a_table_with_no_rows_stops_the_build(tmp_path):
    def edit(t):
        lines = t.splitlines()
        sep = next(i for i, x in enumerate(lines) if x.startswith("| --- "))
        return "\n".join(lines[:sep + 1]) + "\n"
    fails(tmp_path, edit, "no rows")


def test_the_docs_state_the_shotlist_rule():
    from conftest import SCRIPTS
    skill = (SCRIPTS.parent / "SKILL.md").read_text()
    story = (SCRIPTS.parent / "references" / "storyboard.md").read_text()
    for text in (" ".join(skill.split()), " ".join(story.split())):
        assert "If you cannot say why a scene exists, it does not belong in the render" in text
        assert "Never delete `shotlist.md`" in text
