import json
import os
import re
import shutil
import subprocess
import sys
import tomllib

import pytest
from PIL import Image

import music_gen
import new_project
import sample_colors
from conftest import SCRIPTS, run_script, tone_file


@pytest.mark.parametrize(
    "a, b, same",
    [
        (30, "30/1", True),
        (29.97, "30000/1001", True),
        ("240000/1001", 29.97 * 8, True),
        (30, 30 * (1 + 0.9e-4), True),
        (30, 30 * (1 + 1.1e-4), False),
        (29.97, 30, False),
        (60, "60000/1001", False),
        (60, 30, False),
    ],
)
def test_same_rate_tells_ntsc_from_whole_rates(a, b, same):
    from common import same_rate

    assert same_rate(a, b) is same and same_rate(b, a) is same


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


def test_new_project_copies_the_bundled_sfx_then_sfx_dir_over_them(tmp_path):
    pack = sorted(f.name for f in new_project.SFX_PACK.glob("*.mp3"))
    assert "pop.mp3" in pack
    sfx = tmp_path / "sfx"
    sfx.mkdir()
    (sfx / "pop.mp3").write_bytes(b"the user's pop")
    tone_file(sfx / "extra.wav")
    (sfx / "notes.txt").write_text("x")
    env = {**os.environ, "SFX_DIR": str(sfx)}
    r = run_script("new_project.py", "--app", "x", "--variant", "a", "--out", tmp_path / "out", env=env)
    assert r.returncode == 0, r.stderr
    assert f"copied {len(pack)} bundled CC0 SFX files" in r.stdout
    assert "copied 2 SFX files from $SFX_DIR" in r.stdout
    audio = tmp_path / "out" / "x-a" / "assets" / "audio"
    assert sorted(f.name for f in audio.iterdir()) == sorted([*pack, "extra.wav"])
    assert (audio / "pop.mp3").read_bytes() == b"the user's pop"  # the same name: the user's file wins
    for name in pack:
        assert not (audio / name).is_symlink()
        if name != "pop.mp3":
            assert (audio / name).read_bytes() == (new_project.SFX_PACK / name).read_bytes()
    env.pop("SFX_DIR")
    r = run_script(
        "new_project.py", "--app", "x", "--variant", "b", "--out", tmp_path / "out", "--stores", "google_play", env=env
    )
    assert r.returncode == 0 and f"copied {len(pack)} bundled CC0 SFX files" in r.stdout
    assert "$SFX_DIR" not in r.stdout
    assert sorted(f.name for f in (tmp_path / "out" / "x-b" / "assets" / "audio").iterdir()) == pack
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
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, music_gen; from pathlib import Path; "
                f"music_gen.LOCK = Path({str(lock)!r}); "
                f"music_gen.main(['--prompt', 'x', '--duration', '30', '--seeds', '1', '--out', {str(tmp_path / 'o')!r}])",
            ],
            capture_output=True,
            text=True,
            cwd=str(music_gen.__file__.rsplit("/", 1)[0]),
        )
    assert r.returncode == 2 and "another music generator is running" in r.stderr


def test_repo_root_from_a_linked_worktree(tmp_path):
    main = tmp_path / "main"
    subprocess.run(["git", "init", "-q", str(main)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(main),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "x",
        ],
        check=True,
    )
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
    subprocess.run(
        [
            "git",
            "-C",
            str(main),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "x",
        ],
        check=True,
    )
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
    step1 = skill[skill.index("1. **Scaffold.**") : skill.index("2. **Research")]
    assert "--stores" in step1
    pipeline = (SCRIPTS.parent / "references" / "pipeline.md").read_text()
    assert "--stores <STORES>" in pipeline and "--stores app_store,google_play" not in pipeline


def fake_musicgen(
    monkeypatch, seconds_for_seed=lambda seed: 31.0, load_error=None, convert_error=None, seed_error=None
):
    """Stand-ins for torch and transformers: a 'model' whose output length depends on the seed."""
    import types
    import numpy as np

    state = {}
    torch = types.ModuleType("torch")
    torch.float16 = "fp16"
    torch.cuda = types.SimpleNamespace(
        is_available=lambda: True, OutOfMemoryError=type("OutOfMemoryError", (Exception,), {})
    )

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
    tf.AutoProcessor = types.SimpleNamespace(from_pretrained=lambda *a, **k: lambda **kw: Inputs())
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


@pytest.mark.parametrize(
    "fmt, size", [(None, [1080, 1920]), ("9:16", [1080, 1920]), ("4:5", [1080, 1350]), ("16:9", [1920, 1080])]
)
def test_new_project_writes_the_format(tmp_path, fmt, size):
    r = run_script(
        "new_project.py", "--app", "x", "--variant", "a", "--out", tmp_path / "out", *(["--format", fmt] if fmt else [])
    )
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
    assert "--format <9:16|4:5|16:9>" in skill[skill.index("1. **Scaffold.**") : skill.index("2. **Research")]
    assert "--format 9:16" in (SCRIPTS.parent / "references" / "pipeline.md").read_text()


@pytest.mark.parametrize("fmt", ["9:16", "4:5", "16:9"])
def test_every_design_md_keeps_the_reference_section_before_what_not_to_do(tmp_path, fmt):
    r = run_script("new_project.py", "--app", "x", "--variant", "a", "--out", tmp_path / "out", "--format", fmt)
    assert r.returncode == 0, r.stderr
    design = (tmp_path / "out" / "x-a" / "DESIGN.md").read_text()
    heads = [row for row in design.splitlines() if row.startswith("## ")]
    assert "## Reference" in heads and heads.index("## Reference") == heads.index("## What NOT to do") - 1
    ref = design[design.index("## Reference") : design.index("## What NOT to do")]
    for word in (
        "Palette",
        "Typography",
        "Composition",
        "Pacing",
        "Motion",
        "Texture",
        "Do not copy",
        "product screen",
        "estimated",
        "sample_colors.py",
    ):
        assert word in ref
    music = design[design.index("## Music") : design.index("## Reference")]
    assert ("16:9 is silent: no music." in music) == (fmt == "16:9")


def test_skill_step_2_points_at_the_reference_section():
    skill = " ".join((SCRIPTS.parent / "SKILL.md").read_text().split())
    step2 = skill[skill.index("2. **Research") : skill.index("3. **Music first")]
    assert "`## Reference`" in step2 and "sample_colors.py" in step2 and "estimated" in step2
    assert "no logo, text, music, claim or product screen comes from it" in step2


def test_gated_run_is_opt_in_and_names_its_triggers_and_four_stops():
    skill = " ".join((SCRIPTS.parent / "SKILL.md").read_text().split())
    assert "\n## Gated run (opt-in)" in (SCRIPTS.parent / "SKILL.md").read_text()
    sec = skill[skill.index("## Gated run (opt-in)") : skill.index("## Variants")]
    assert 'exact words "gated run" or "gated reel"' in sec and "in any letter case" in sec
    assert "No other wording turns it on" in sec and "without stopping" in sec
    assert "Never approve a gate yourself" in sec
    for stop in (
        "1. After step 2",
        "2. After the storyboard",
        "3. After the first `finish.py`",
        "4. After the last critique round",
    ):
        assert stop in sec
    for item in ("`## Reference`", "`shotlist.md`", "contact sheet", "poster", "final MP4"):
        assert item in sec
    # the default workflow above the section never mentions a gate
    assert "gate" not in skill[: skill.index("## Gated run (opt-in)")].lower()


def test_docs_pin_the_feed_safe_box_the_density_rule_and_the_punch_cap():
    import build
    import finish
    from common import FEED_BOXES

    def doc(*parts):
        return " ".join(SCRIPTS.parent.joinpath(*parts).read_text().split())

    story = doc("references", "storyboard.md")
    zones = story[story.index("## Feed safe zones") : story.index("## Density")]
    for fmt, (x0, y0, x1, y1) in FEED_BOXES.items():
        assert (
            f"| {fmt} |" in zones
            and f"x {x0}-{x1}, y {y0}-{y1} | {build.AI_LABEL_PLACES[fmt][1]} px or more |" in zones
        )
    assert "bottom 672, right 192" in zones and "lower 40%" in zones and "scaled 0.79" in zones
    density = story[story.index("## Density") : story.index("## Drop placement")]
    assert f"more than {finish.HOLD_MAX} s" in density and f"up to {finish.HOLD_END} s" in density
    assert "still for <length> s from <time> s: nothing on screen moves (look at it)" in density
    motion = doc("references", "motion.md")
    assert f"at most {build.PUNCH_CAP} shakes and {build.PUNCH_CAP} flashes per reel" in motion
    assert (
        "| `icon` | small objects that appear: icon, pop, CTA, chips, rows | spring, 10% overshoot | 0.32 s |" in motion
    )
    critique = doc("references", "critique.md")
    assert "caps readability at 6" in critique and "`still for …` warning" in critique
    # the agent runs the command build.py prints, not a plain check
    skill = doc("SKILL.md")
    step5 = skill[skill.index("5. **Build, check") : skill.index("6. **Critique")]
    assert "run the `check:` command it prints as its last line" in step5
    assert "The last line build.py prints is `check: <command>`. Run that command" in doc("references", "pipeline.md")


def test_docs_state_the_limits_of_the_seekability_check():
    motion = " ".join(SCRIPTS.parent.joinpath("references", "motion.md").read_text().split())
    sec = motion[motion.index("## Seekable frames") : motion.index("## Motion blur")]
    assert "A `<script>` inside an HTML comment is still read: delete it instead of commenting it out" in sec
    assert "The check is a guard, not a proof" in sec and "(also with `?.`)" in sec
    assert "write it as a constant (a seeded list in the file)" in sec


def test_docs_name_the_fps_token_and_the_blur_rates():
    pipeline = " ".join(SCRIPTS.parent.joinpath("references", "pipeline.md").read_text().split())
    tokens = pipeline[pipeline.index("- Template tokens:") : pipeline.index("- In the page script")]
    assert "`{{FPS}}` (the root's `data-fps`, from project.json)" in tokens
    # measured: HyperFrames 0.8.78 writes --fps 240000/1001 as 240/1, which blur.py refuses
    assert "(200 for 25 fps). Not for 23.976, 29.97 or 59.94 fps" in pipeline
    assert "`--fps 240000/1001` writes a video that ffprobe reads as 240/1" in pipeline
    assert "build.py writes the fps on the composition root as `data-fps`" in pipeline


def test_docs_pin_the_optional_motion_blur_step():
    import blur

    def doc(*parts):
        return " ".join(SCRIPTS.parent.joinpath(*parts).read_text().split())

    skill = doc("SKILL.md")
    step5 = skill[skill.index("5. **Build, check") : skill.index("6. **Critique")]
    step6 = skill[skill.index("6. **Critique") :]
    pipeline = doc("references", "pipeline.md")
    assert "render with `--fps 240` to `renders/sub240.mp4`" in step5
    assert "`scripts/blur.py <project> renders/sub240.mp4` writes `renders/raw.mp4`" in step5
    assert "render -o renders/sub240.mp4 -q delivery --fps 240 --quiet" in pipeline
    assert "$PY $S/blur.py $P renders/sub240.mp4 $PY $S/finish.py $P renders/raw.mp4" in pipeline
    assert "`fastest:`" in step6 and "from the final MP4" in step6
    motion = doc("references", "motion.md")
    blurred = motion[motion.index("## Motion blur") :]
    assert f"{2 * blur.reach(8) + 1} of 8 at 30 fps" in blurred and f"{2 * blur.reach(4) + 1} of 4 at 60 fps" in blurred
    assert "half-frame time, `(n + 0.5) / fps`" in blurred and "10 × K px per output frame" in blurred
    assert "`fastest:`" in doc("references", "critique.md")


def hyperframes_pins(root):
    # every "hyperframes@<version>", in any letter case, in the tracked files of root: {path: [(line, version), ...]}
    names = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split("\0")
    found = {}
    for name in filter(None, names):
        try:
            text = (root / name).read_text(encoding="utf-8")
        except (
            UnicodeDecodeError,
            IsADirectoryError,
            FileNotFoundError,
        ):  # not text, a submodule, deleted, a broken link
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for m in re.finditer(r"hyperframes@([\w.-]+)", line, re.IGNORECASE):
                found.setdefault(name, []).append((n, m.group(1).rstrip(".")))
    return found


def wrong_pins(found, want):
    return [f"{name}:{n}: hyperframes@{v}" for name, pins in found.items() for n, v in pins if v != want]


def test_every_hyperframes_pin_is_the_one_build_py_uses():
    import build

    want = build.HYPERFRAMES.split("@", 1)[1]
    found = hyperframes_pins(SCRIPTS.parents[2])
    # the scan reaches the files that run the CLI, so an empty scan cannot pass
    assert {
        "skills/app-promo-reel/scripts/build.py",
        "skills/app-promo-reel/SKILL.md",
        "skills/app-promo-reel/template/package.json",
        "README.md",
    } <= found.keys()
    wrong = wrong_pins(found, want)
    assert not wrong, f"pin these to {build.HYPERFRAMES}:\n" + "\n".join(wrong)


def test_the_pin_scan_finds_a_version_that_differs(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    pin = "hyperframes" + "@"  # split, so the scan of this repo does not find these lines
    (tmp_path / "a.md").write_text(f"Render with {pin}1.2.3.\n`{pin}1.2.4`\n")  # a sentence's dot is not the version's
    (tmp_path / "b.json").write_text(f'{{"check": "npx {pin}latest check"}}\n')
    (tmp_path / "untracked.md").write_text(f"{pin}9.9.9\n")
    (tmp_path / "c.dat").write_bytes(b"\xff\xfe" + f"{pin}8.8.8\n".encode())  # not UTF-8: skipped
    (tmp_path / "c.md").write_text(f"{pin.capitalize()}1.2.5 starts the sentence.\n")
    (tmp_path / "gone.md").write_text(f"{pin}7.7.7\n")
    subprocess.run(["git", "add", "a.md", "b.json", "c.dat", "c.md", "gone.md"], cwd=tmp_path, check=True)
    (tmp_path / "gone.md").unlink()  # tracked, deleted from disk: skipped
    subprocess.run(
        ["git", "update-index", "--add", "--cacheinfo", "160000," + "1" * 40 + ",sub"], cwd=tmp_path, check=True
    )
    (tmp_path / "sub").mkdir()  # a submodule's folder: skipped
    found = hyperframes_pins(tmp_path)
    assert found == {"a.md": [(1, "1.2.3"), (2, "1.2.4")], "b.json": [(1, "latest")], "c.md": [(1, "1.2.5")]}
    assert wrong_pins(found, "1.2.3") == [f"a.md:2: {pin}1.2.4", f"b.json:1: {pin}latest", f"c.md:1: {pin}1.2.5"]


def test_bin_ci_runs_the_pinned_ruff_before_the_tests():
    # a text test: running bin/ci here would run pytest again
    root = SCRIPTS.parents[2]
    live = "\n".join(s for s in (root / "bin" / "ci").read_text().splitlines() if not s.lstrip().startswith("#"))
    steps = [
        '"$PY" -m ruff check skills tests',
        '"$PY" -m ruff format --check skills tests',
        '"$PY" -m pytest -q tests',
    ]
    assert all(s in live for s in steps), steps
    assert [live.index(s) for s in steps] == sorted(live.index(s) for s in steps)
    assert "sed -n 's/^ruff==//p' requirements.txt" in live and '"$PY" -m ruff --version' in live
    pins = [s for s in (root / "requirements.txt").read_text().splitlines() if s.startswith("ruff==")]
    assert len(pins) == 1 and re.fullmatch(r"ruff==\d+\.\d+\.\d+", pins[0]), pins
    lint = tomllib.loads((root / "ruff.toml").read_text())["lint"]
    assert lint == {"select": ["E4", "E7", "E9", "F"]}, lint


@pytest.mark.parametrize("installed, found", [(None, "none"), ("0.16.0", "0.16.0"), ("pin", None)])
def test_bin_ci_stops_on_a_missing_or_different_ruff(tmp_path, installed, found):
    # a copy of bin/ci with a stand-in .venv/bin/python: the deps import passes, `-m ruff --version`
    # gives the version under test, and any other ruff call exits 3, so pytest never runs
    root = SCRIPTS.parents[2]
    want = re.search(r"^ruff==(\S+)$", (root / "requirements.txt").read_text(), re.M).group(1)
    have = want if installed == "pin" else installed
    (tmp_path / "bin").mkdir()
    shutil.copy(root / "bin" / "ci", tmp_path / "bin" / "ci")
    shutil.copy(root / "requirements.txt", tmp_path)
    py = tmp_path / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    version = f'echo "ruff {have}"' if have else "echo 'No module named ruff' >&2; exit 1"
    py.write_text(
        "#!/bin/sh\n"
        '[ "$1 $2" = "-m ruff" ] || exit 0\n'
        f'if [ "$3" = "--version" ]; then {version}; else echo "ruff $3 ran"; exit 3; fi\n'
    )
    py.chmod(0o755)
    r = subprocess.run(["bash", str(tmp_path / "bin" / "ci")], capture_output=True, text=True, timeout=60)
    if found is None:
        assert r.returncode == 3 and "ruff check ran" in r.stdout, (r.stdout, r.stderr)
    else:
        assert r.returncode == 1 and "ran" not in r.stdout, (r.stdout, r.stderr)
        assert f"bin/ci: ruff {want} missing for .venv/bin/python (found: {found})" in r.stderr, r.stderr


def test_new_project_scaffolds_and_warns_when_the_bundled_sfx_are_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(new_project, "SFX_PACK", tmp_path / "gone")
    monkeypatch.setattr(sys, "argv", ["new_project.py", "--app", "x", "--variant", "a", "--out", str(tmp_path / "out")])
    new_project.main()
    out = capsys.readouterr()
    assert "copied 0 bundled CC0 SFX files" in out.out
    assert "warning: no bundled SFX" in out.err and "skips every cue" in out.err
    assert (tmp_path / "out" / "x-a" / "assets" / "audio").is_dir()
    assert not any((tmp_path / "out" / "x-a" / "assets" / "audio").iterdir())
