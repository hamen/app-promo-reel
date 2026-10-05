import json
import os
import shutil
import subprocess
import sys

import pytest
from PIL import Image

import music_gen
import new_project
import sample_colors
from conftest import SCRIPTS, run_script, tone_file


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


def test_new_project_ignores_a_callers_git_dir(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path / "other")], check=True)
    env = {**os.environ, "GIT_DIR": str(tmp_path / "other" / ".git")}  # as inside a git hook
    r = run_script("new_project.py", "--app", "x", "--variant", "a", "--out", tmp_path / "plain", env=env)
    assert r.returncode == 0, r.stderr


def test_new_project_always_refuses_its_own_repo():
    inside = new_project.SKILL_DIR / "reels-test-should-not-exist"
    if new_project.repo_root(new_project.SKILL_DIR) is None:
        pytest.skip("skill is not inside a git checkout")
    try:
        r = run_script("new_project.py", "--app", "x", "--variant", "a", "--out", inside, "--force")
        assert r.returncode == 2 and "app-promo-reel repo" in r.stderr
        assert not inside.exists()
    finally:
        shutil.rmtree(inside, ignore_errors=True)


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


def test_music_gen_refuses_long_duration_before_import(tmp_path, monkeypatch):
    monkeypatch.setattr(music_gen, "LOCK", tmp_path / "lock")  # never the real lock
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


def test_sample_colors_cli_rejects_absolute_coords(tmp_path):
    img = tmp_path / "i.png"
    Image.new("RGB", (100, 200), "#123456").save(img)
    pts = tmp_path / "p.json"
    pts.write_text('{"x": [50, 20]}')
    r = run_script("sample_colors.py", img, pts)
    assert r.returncode == 2 and "0-1" in r.stderr and "Traceback" not in r.stderr


def test_music_gen_removes_stale_seed_files_on_failure(tmp_path, monkeypatch):
    out = tmp_path / "o"
    out.mkdir()
    (out / "bgm_1.wav").write_bytes(b"old")
    (out / "bgm_9.wav").write_bytes(b"other seed")
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setattr(music_gen, "LOCK", tmp_path / "lock")
    with pytest.raises(SystemExit):
        music_gen.main(["--prompt", "x", "--duration", "30", "--seeds", "1", "--out", str(out)])
    assert not (out / "bgm_1.wav").exists() and (out / "bgm_9.wav").exists()


def test_music_gen_second_process_exits_2(tmp_path, monkeypatch):
    import fcntl
    lock = tmp_path / "lock"
    monkeypatch.setattr(music_gen, "LOCK", lock)
    with open(lock, "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = subprocess.run([sys.executable, "-c",
                            "import sys, music_gen; from pathlib import Path; "
                            f"music_gen.LOCK = Path({str(lock)!r}); "
                            f"music_gen.main(['--prompt', 'x', '--duration', '30', '--seeds', '1', '--out', {str(tmp_path / 'o')!r}])"],
                           capture_output=True, text=True, cwd=str(music_gen.__file__.rsplit('/', 1)[0]))
    assert r.returncode == 2 and "another music_gen.py is running" in r.stderr


def test_repo_root_from_a_linked_worktree(tmp_path):
    main = tmp_path / "main"
    subprocess.run(["git", "init", "-q", str(main)], check=True)
    subprocess.run(["git", "-C", str(main), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                    "--allow-empty", "-m", "x"], check=True)
    wt = main / ".claude" / "worktrees" / "w"
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", str(wt)], check=True)
    assert new_project.repo_root(wt) == main.resolve()
    assert new_project.is_inside(main / "reels", new_project.repo_root(wt))


def test_sample_colors_cli_bad_files_exit_2(tmp_path):
    img = tmp_path / "i.png"
    Image.new("RGB", (100, 200), "#123456").save(img)
    pts = tmp_path / "p.json"
    pts.write_text('{"x": [0.5, 0.5]}')
    junk = tmp_path / "junk.png"
    junk.write_bytes(b"not an image")
    lst = tmp_path / "l.json"
    lst.write_text("[1, 2]")
    for args in ((tmp_path / "missing.png", pts), (junk, pts), (img, tmp_path / "missing.json"), (img, lst)):
        r = run_script("sample_colors.py", *args)
        assert r.returncode == 2 and "Traceback" not in r.stderr, (args, r.stderr)


def test_music_gen_bad_duration_still_removes_stale_files(tmp_path, monkeypatch):
    out = tmp_path / "o"
    out.mkdir()
    (out / "bgm_1.wav").write_bytes(b"old")
    monkeypatch.setattr(music_gen, "LOCK", tmp_path / "lock")
    with pytest.raises(SystemExit) as e:
        music_gen.main(["--prompt", "x", "--duration", "90", "--seeds", "1", "--out", str(out)])
    assert e.value.code == 2 and not (out / "bgm_1.wav").exists()
    with pytest.raises(SystemExit) as e:
        music_gen.main(["--prompt", "x", "--duration", "30", "--seeds", "a,b", "--out", str(out)])
    assert e.value.code == 2


def test_linked_worktree_of_this_repo_is_refused_even_with_force(tmp_path, monkeypatch):
    main = tmp_path / "main"
    subprocess.run(["git", "init", "-q", str(main)], check=True)
    subprocess.run(["git", "-C", str(main), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                    "--allow-empty", "-m", "x"], check=True)
    skill = main / "skills" / "app-promo-reel"
    skill.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", str(elsewhere)], check=True)
    monkeypatch.setattr(new_project, "SKILL_DIR", skill)
    with pytest.raises(SystemExit):
        new_project.check_out_dir(elsewhere / "reels", force=True)
    other = tmp_path / "other"
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    new_project.check_out_dir(other / "reels", force=True)  # another repo: allowed with --force


def test_sample_colors_point_that_is_not_a_pair_exits_2(tmp_path):
    img = tmp_path / "i.png"
    Image.new("RGB", (100, 200), "#123456").save(img)
    for bad in ('{"a": 1}', '{"a": [0.5]}', '{"a": ["x", 0.5]}', '{"a": [true, 0.5]}'):
        pts = tmp_path / "p.json"
        pts.write_text(bad)
        r = run_script("sample_colors.py", img, pts)
        assert r.returncode == 2 and "Traceback" not in r.stderr, (bad, r.stderr)


def test_music_gen_second_process_leaves_the_first_ones_files(tmp_path, monkeypatch):
    import fcntl
    lock = tmp_path / "lock"
    out = tmp_path / "o"
    out.mkdir()
    (out / "bgm_1.wav").write_bytes(b"made by the running process")
    monkeypatch.setattr(music_gen, "LOCK", lock)
    with open(lock, "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)  # the first process is running
        with pytest.raises(SystemExit) as e:
            music_gen.main(["--prompt", "x", "--duration", "30", "--seeds", "1", "--out", str(out)])
    assert e.value.code == 2 and (out / "bgm_1.wav").read_bytes() == b"made by the running process"


def test_new_project_refuses_a_short_duration(tmp_path):
    with pytest.raises(SystemExit):
        new_project.scaffold("x", "a", tmp_path / "out", duration=0)


def test_partial_music_file_is_outside_the_rank_glob(tmp_path):
    import fnmatch
    assert not fnmatch.fnmatch(music_gen.partial_path(tmp_path, 5).name, "bgm_*.wav")
    assert music_gen.partial_path(tmp_path, 5).parent == tmp_path


def test_docs_scaffold_step_names_the_real_stores():
    # tripwire: the scaffold commands must make the agent choose the stores (the default, both,
    # puts a false badge on a single-store app's end card)
    skill = (SCRIPTS.parent / "SKILL.md").read_text()
    step1 = skill[skill.index("1. **Scaffold.**"):skill.index("2. **Research")]
    assert "--stores" in step1
    pipeline = (SCRIPTS.parent / "references" / "pipeline.md").read_text()
    assert "--stores <STORES>" in pipeline and "--stores app_store,google_play" not in pipeline


def fake_musicgen(monkeypatch, seconds_for_seed=lambda seed: 31.0, load_error=None, convert_error=None,
                  seed_error=None):
    """Stand-ins for torch and transformers: a 'model' whose output length depends on the seed."""
    import types
    import numpy as np
    state = {}
    torch = types.ModuleType("torch")
    torch.float16 = "fp16"
    torch.cuda = types.SimpleNamespace(is_available=lambda: True,
                                       OutOfMemoryError=type("OutOfMemoryError", (Exception,), {}))
    def manual_seed(seed):
        if seed_error:
            raise seed_error
        state.update(seed=seed)
    torch.manual_seed = manual_seed

    class Tensor:
        def __init__(self, a):
            self.a = a

        def __getitem__(self, k):
            return Tensor(self.a[k])

        def float(self):
            if convert_error:
                raise convert_error
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self.a

    class Inputs(dict):
        def to(self, device):
            return self

    class Model:
        config = types.SimpleNamespace(audio_encoder=types.SimpleNamespace(sampling_rate=8000))

        @classmethod
        def from_pretrained(cls, *a, **k):
            if load_error:
                raise load_error
            return cls()

        def to(self, device):
            return self

        def generate(self, **k):
            n = int(seconds_for_seed(state["seed"]) * 8000)
            return Tensor(np.zeros((1, 1, n), dtype=np.float32))

    tf = types.ModuleType("transformers")
    tf.AutoProcessor = types.SimpleNamespace(from_pretrained=lambda *a, **k: (lambda **kw: Inputs()))
    tf.MusicgenForConditionalGeneration = Model
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", tf)


def test_music_gen_short_seed_is_skipped_and_the_rest_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(music_gen, "LOCK", tmp_path / "lock")
    fake_musicgen(monkeypatch, seconds_for_seed=lambda seed: 20.0 if seed == 2 else 31.0)
    out = tmp_path / "o"
    with pytest.raises(SystemExit) as e:
        music_gen.main(["--prompt", "x", "--duration", "30", "--seeds", "1,2,3", "--out", str(out)])
    assert e.value.code == 2 and "seed(s) 2 came out shorter" in capsys.readouterr().err
    assert sorted(p.name for p in out.iterdir()) == ["bgm_1.wav", "bgm_3.wav"]


def test_music_gen_model_load_error_exits_2_without_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(music_gen, "LOCK", tmp_path / "lock")
    fake_musicgen(monkeypatch, load_error=ConnectionError("hub unreachable"))
    with pytest.raises(SystemExit) as e:
        music_gen.main(["--prompt", "x", "--duration", "30", "--seeds", "1", "--out", str(tmp_path / "o")])
    assert e.value.code == 2 and "hub unreachable" in capsys.readouterr().err


def test_music_gen_write_error_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(music_gen, "LOCK", tmp_path / "lock")
    fake_musicgen(monkeypatch)
    import soundfile

    def no_space(*a, **k):
        raise TypeError("no space left on device")  # any error type, not only OSError
    monkeypatch.setattr(soundfile, "write", no_space)
    with pytest.raises(SystemExit) as e:
        music_gen.main(["--prompt", "x", "--duration", "30", "--seeds", "1", "--out", str(tmp_path / "o")])
    assert e.value.code == 2 and "no space left" in capsys.readouterr().err
    assert not list((tmp_path / "o").iterdir())


def test_sample_colors_box_must_be_a_fraction(tmp_path):
    img = tmp_path / "i.png"
    Image.new("RGB", (100, 200), "#123456").save(img)
    pts = tmp_path / "p.json"
    pts.write_text('{"x": [0.5, 0.5]}')
    for box in ("0", "-0.1", "0.5", "3"):
        r = run_script("sample_colors.py", img, pts, "--box", box)
        assert r.returncode == 2 and "--box" in r.stderr, box
    assert run_script("sample_colors.py", img, pts, "--box", "0.01").returncode == 0


def test_music_gen_conversion_error_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(music_gen, "LOCK", tmp_path / "lock")
    fake_musicgen(monkeypatch, convert_error=RuntimeError("CUDA error: device-side assert"))
    with pytest.raises(SystemExit) as e:
        music_gen.main(["--prompt", "x", "--duration", "30", "--seeds", "1", "--out", str(tmp_path / "o")])
    assert e.value.code == 2 and "device-side assert" in capsys.readouterr().err


def test_music_gen_seeding_error_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(music_gen, "LOCK", tmp_path / "lock")
    fake_musicgen(monkeypatch, seed_error=RuntimeError("CUDA driver initialization failed"))
    with pytest.raises(SystemExit) as e:
        music_gen.main(["--prompt", "x", "--duration", "30", "--seeds", "1", "--out", str(tmp_path / "o")])
    assert e.value.code == 2 and "driver initialization failed" in capsys.readouterr().err


@pytest.mark.parametrize("fmt, size", [(None, [1080, 1920]), ("9:16", [1080, 1920]), ("4:5", [1080, 1350]), ("16:9", [1920, 1080])])
def test_new_project_writes_the_format(tmp_path, fmt, size):
    r = run_script("new_project.py", "--app", "x", "--variant", "a", "--out", tmp_path / "out",
                   *(["--format", fmt] if fmt else []))
    assert r.returncode == 0, r.stderr
    dest = tmp_path / "out" / "x-a"
    doc = json.loads((dest / "project.json").read_text())
    assert [doc["format"], doc["width"], doc["height"]] == [fmt or "9:16", *size]
    design = (dest / "DESIGN.md").read_text()
    assert f"(<language>, {fmt or '9:16'}, variant <x>)" in design.splitlines()[0] and "<format>" not in design


def test_new_project_refuses_an_unknown_format(tmp_path):
    r = run_script("new_project.py", "--app", "x", "--variant", "a", "--out", tmp_path / "out", "--format", "1:1")
    assert r.returncode == 2 and "invalid choice" in r.stderr and not (tmp_path / "out").exists()
    with pytest.raises(SystemExit):
        new_project.scaffold("x", "a", tmp_path / "out", fmt="1:1")
    assert not (tmp_path / "out").exists()


def test_docs_scaffold_step_names_the_format():
    # tripwire: a feed variant scaffolded without --format renders at 9:16
    skill = (SCRIPTS.parent / "SKILL.md").read_text()
    assert "--format <9:16|4:5|16:9>" in skill[skill.index("1. **Scaffold.**"):skill.index("2. **Research")]
    assert "--format 9:16" in (SCRIPTS.parent / "references" / "pipeline.md").read_text()


@pytest.mark.parametrize("fmt", ["9:16", "4:5", "16:9"])
def test_every_design_md_keeps_the_reference_section_before_what_not_to_do(tmp_path, fmt):
    r = run_script("new_project.py", "--app", "x", "--variant", "a", "--out", tmp_path / "out", "--format", fmt)
    assert r.returncode == 0, r.stderr
    design = (tmp_path / "out" / "x-a" / "DESIGN.md").read_text()
    heads = [l for l in design.splitlines() if l.startswith("## ")]
    assert "## Reference" in heads and heads.index("## Reference") == heads.index("## What NOT to do") - 1
    ref = design[design.index("## Reference"):design.index("## What NOT to do")]
    for word in ("Palette", "Typography", "Composition", "Pacing", "Motion", "Texture", "Do not copy", "estimated", "sample_colors.py"):
        assert word in ref
    music = design[design.index("## Music"):design.index("## Reference")]
    assert ("16:9 is silent: no music." in music) == (fmt == "16:9")


def test_skill_step_2_points_at_the_reference_section():
    skill = " ".join((SCRIPTS.parent / "SKILL.md").read_text().split())
    step2 = skill[skill.index("2. **Research"):skill.index("3. **Music first")]
    assert "`## Reference`" in step2 and "sample_colors.py" in step2 and "estimated" in step2


def test_gated_run_is_opt_in_and_names_its_triggers_and_four_stops():
    skill = " ".join((SCRIPTS.parent / "SKILL.md").read_text().split())
    assert "\n## Gated run (opt-in)" in (SCRIPTS.parent / "SKILL.md").read_text()
    sec = skill[skill.index("## Gated run (opt-in)"):skill.index("## Variants")]
    assert 'exact words "gated run" or "gated reel"' in sec and "in any letter case" in sec
    assert "No other wording turns it on" in sec and "without stopping" in sec
    assert "Never approve a gate yourself" in sec
    for stop in ("1. After step 2", "2. After the storyboard", "3. After the first `finish.py`", "4. After the last critique round"):
        assert stop in sec
    for item in ("`## Reference`", "`shotlist.md`", "contact sheet", "poster", "final MP4"):
        assert item in sec
    # the default workflow above the section never mentions a gate
    assert "gate" not in skill[:skill.index("## Gated run (opt-in)")].lower()
