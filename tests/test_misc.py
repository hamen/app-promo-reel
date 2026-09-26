import json
import os
import subprocess
import sys

import pytest
from PIL import Image

import music_gen
import new_project
import sample_colors
from conftest import run_script, tone_file


def test_sample_colors_relative_coords():
    img = Image.new("RGB", (1290, 2796), "#112233")
    img.paste((250, 240, 10), (0, 1398, 645, 2796))  # bottom-left quarter
    got = sample_colors.sample(img, {"top": [0.5, 0.1], "bl": [0.25, 0.75]})
    assert got == {"top": "#112233", "bl": "#FAF00A"}
    small = img.resize((129, 280))
    assert sample_colors.sample(small, {"bl": [0.25, 0.75]}) == {"bl": "#FAF00A"}
    with pytest.raises(ValueError):
        sample_colors.sample(img, {"bad": [300, 20]})


def test_new_project_refuses_git_tree_without_force(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path / "repo")], check=True)
    r = run_script("new_project.py", "--app", "x", "--variant", "a", "--out", tmp_path / "repo" / "reels")
    assert r.returncode == 2 and "git work tree" in r.stderr
    r = run_script("new_project.py", "--app", "x", "--variant", "a", "--out", tmp_path / "repo" / "reels", "--force")
    assert r.returncode == 0, r.stderr


def test_new_project_always_refuses_its_own_repo():
    inside = new_project.SKILL_DIR / "reels-test-should-not-exist"
    if new_project.git_toplevel(new_project.SKILL_DIR) is None:
        pytest.skip("skill is not inside a git checkout")
    r = run_script("new_project.py", "--app", "x", "--variant", "a", "--out", inside, "--force")
    assert r.returncode == 2 and "app-promo-reel repo" in r.stderr
    assert not inside.exists()


def test_new_project_copies_sfx_and_works_without(tmp_path):
    sfx = tmp_path / "sfx"
    sfx.mkdir()
    tone_file(sfx / "pop.wav")
    (sfx / "notes.txt").write_text("x")
    env = {**os.environ, "SFX_DIR": str(sfx)}
    r = run_script("new_project.py", "--app", "x", "--variant", "a", "--out", tmp_path / "out", env=env)
    assert r.returncode == 0, r.stderr
    dest = tmp_path / "out" / "x-a"
    copied = dest / "assets" / "audio" / "pop.wav"
    assert copied.is_file() and not copied.is_symlink()
    assert not (dest / "assets" / "audio" / "notes.txt").exists()
    env.pop("SFX_DIR")
    r = run_script("new_project.py", "--app", "x", "--variant", "b", "--out", tmp_path / "out",
                   "--stores", "google_play", env=env)
    assert r.returncode == 0 and "no $SFX_DIR" in r.stdout
    assert json.loads((tmp_path / "out" / "x-b" / "project.json").read_text())["stores"] == ["google_play"]
    r = run_script("new_project.py", "--app", "x", "--variant", "b", "--out", tmp_path / "out", env=env)
    assert r.returncode == 2 and "already exists" in r.stderr


def test_music_gen_refuses_long_duration_before_import(tmp_path):
    with pytest.raises(SystemExit) as e:
        music_gen.main(["--prompt", "x", "--duration", "45", "--seeds", "1", "--out", str(tmp_path)])
    assert e.value.code == 2


def test_music_gen_without_torch_exits_2(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setattr(music_gen, "LOCK", tmp_path / "lock")
    with pytest.raises(SystemExit) as e:
        music_gen.main(["--prompt", "x", "--duration", "30", "--seeds", "1", "--out", str(tmp_path / "o")])
    assert e.value.code == 2
    assert not list((tmp_path / "o").glob("*.wav"))
