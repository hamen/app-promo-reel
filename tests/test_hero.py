"""The 16:9 hero: a silent, seamless loop. Scaffold, build, template and finish (seam check)."""
import json
import re
import subprocess

import numpy as np
import pytest

import common
import finish
from conftest import run_script

DEMO_HTML = "<section id=\"s1\" data-start=\"0\"></section>"


def scaffold(tmp_path, *extra):
    out = tmp_path / "out"
    r = run_script("new_project.py", "--app", "demo", "--variant", "a", "--out", out, "--force", "--format", "16:9",
                   *extra)
    return r, out / "demo-a"


def built(tmp_path, edit=None, expect=0, *extra):
    r, p = scaffold(tmp_path, *extra)
    assert r.returncode == 0, r.stderr
    if edit:
        edit(p)
    r = run_script("build.py", p)
    assert r.returncode == expect, r.stderr
    return p, r


# --- scaffold -------------------------------------------------------------------------------

def test_a_16x9_scaffold_has_no_sound_files(tmp_path):
    r, p = scaffold(tmp_path)
    assert r.returncode == 0, r.stderr
    doc = json.loads((p / "project.json").read_text())
    assert (doc["format"], doc["width"], doc["height"], doc["duration"]) == ("16:9", 1920, 1080, 8.0)
    assert not (p / "cues.json").exists() and not (p / "assets" / "audio").exists()
    assert not (p / "beats.json").exists()
    assert 'id="hero-card"' in (p / "src.html.tmpl").read_text()
    assert "16:9 is silent: no music." in (p / "DESIGN.md").read_text()


def test_a_16x9_scaffold_takes_a_duration_of_four_seconds_or_more(tmp_path):
    r, p = scaffold(tmp_path, "--duration", "6")
    assert r.returncode == 0 and json.loads((p / "project.json").read_text())["duration"] == 6
    r, _ = scaffold(tmp_path / "short", "--duration", "3")
    assert r.returncode == 2 and "at least 4" in r.stderr and not (tmp_path / "short" / "out").exists()


def test_a_9x16_scaffold_is_unchanged_by_the_hero(tmp_path):
    r = run_script("new_project.py", "--app", "demo", "--variant", "a", "--out", tmp_path / "out")
    assert r.returncode == 0, r.stderr
    p = tmp_path / "out" / "demo-a"
    assert (p / "cues.json").exists() and (p / "assets" / "audio").is_dir()
    assert 'id="hero-card"' not in (p / "src.html.tmpl").read_text()


def test_a_16x9_project_without_a_duration_gets_eight_seconds(tmp_path):
    (tmp_path / "project.json").write_text(json.dumps({"app": "x", "variant": "a", "format": "16:9"}))
    assert common.load_project(tmp_path)["duration"] == 8.0
    (tmp_path / "project.json").write_text(json.dumps({"app": "x", "variant": "a"}))
    assert common.load_project(tmp_path)["duration"] == 30.0


def test_a_16x9_project_file_with_a_duration_under_four_seconds_is_refused(tmp_path):
    (tmp_path / "project.json").write_text(json.dumps({"app": "x", "variant": "a", "format": "16:9", "duration": 3}))
    with pytest.raises(SystemExit):
        common.load_project(tmp_path)
    (tmp_path / "project.json").write_text(json.dumps({"app": "x", "variant": "a", "format": "16:9", "duration": 4}))
    assert common.load_project(tmp_path)["duration"] == 4.0


# --- build ----------------------------------------------------------------------------------

def test_a_16x9_build_needs_no_beats_and_writes_no_sound(tmp_path):
    p, r = built(tmp_path)
    html = (p / "index.html").read_text()
    assert "silent 16:9 loop, 8 s" in r.stdout
    assert json.loads((p / "cues.realized.json").read_text()) == []
    assert "<audio" not in html and "<video" not in html
    assert not re.search(r"\{\{", html)
    assert re.search(r'id="root"[^>]*data-width="1920" data-height="1080" data-format="16:9"', html)
    # the AI label survives: it is the EU AI Act disclosure
    assert '"aiLabel"' in html and "aiLabel" in html.split("</script>", 1)[1] + html


@pytest.mark.parametrize("token", ["{{D 1}}", "{{E 0}}", "{{LEN 1 2}}", "{{TO_END 1}}", "{{BEFORE_END 1 2}}", "{{BEATS}}",
                                   "{{BEATS_PER_BAR}}", "{{DOWNBEAT_INDEX}}", "{{calc D(1)+1}}", "{{calc E(0,1)}}"])
def test_a_beat_token_in_a_silent_page_exits_2(tmp_path, token):
    def edit(p):
        t = p / "src.html.tmpl"
        t.write_text(t.read_text().replace("<body>", f"<body><!-- x --><p>{token}</p>", 1))
    p, r = built(tmp_path, edit, expect=2)
    assert "silent and has no beat grid" in r.stderr and "Traceback" not in r.stderr
    assert not (p / "index.html").exists()


def test_cues_in_a_silent_project_exit_2(tmp_path):
    def edit(p):
        (p / "cues.json").write_text(json.dumps({"sfx": {"a": "a.wav"}, "cues": [{"id": "c", "sfx": "a", "at": "1"}]}))
    p, r = built(tmp_path, edit, expect=2)
    assert "silent: cues.json has cues" in r.stderr and not (p / "index.html").exists()


@pytest.mark.parametrize("tag", ['<audio src="a.wav" data-start="0"></audio>', '<VIDEO src="a.mp4"></VIDEO>'])
def test_an_audio_or_video_tag_in_a_silent_page_exits_2(tmp_path, tag):
    def edit(p):
        t = p / "src.html.tmpl"
        t.write_text(t.read_text().replace("</body>", f"{tag}</body>", 1))
    p, r = built(tmp_path, edit, expect=2)
    assert "is silent: the page has a <" in r.stderr and not (p / "index.html").exists()


def test_a_commented_out_audio_tag_is_not_a_sound(tmp_path):
    def edit(p):
        t = p / "src.html.tmpl"
        t.write_text(t.read_text().replace("</body>", '<!-- <audio src="a.wav"></audio> --></body>', 1))
    built(tmp_path, edit)


def test_a_9x16_build_still_needs_beats(tmp_path):
    r = run_script("new_project.py", "--app", "demo", "--variant", "a", "--out", tmp_path / "out")
    assert r.returncode == 0
    r = run_script("build.py", tmp_path / "out" / "demo-a")
    assert r.returncode == 2 and "beats.json not found" in r.stderr


# --- the template ---------------------------------------------------------------------------

@pytest.mark.parametrize("duration", [4, 8, 20])
def test_the_hero_slides_end_before_the_rest_window(tmp_path, duration):
    p, _ = built(tmp_path, None, 0, "--duration", str(duration))
    html = (p / "index.html").read_text()
    to_a = float(re.search(r"const toA = ([\d.]+);", html).group(1))
    to_b = float(re.search(r"const toB = ([\d.]+);", html).group(1))
    rest = min(0.4, duration * 0.05)
    assert 0 < to_b < to_a and to_a + 0.45 <= duration - rest
    assert f"data-duration=\"{duration}\"" in html or f'data-duration="{float(duration):g}"' in html


def test_every_hero_from_pose_that_differs_from_rest_is_not_painted_at_t0():
    html = (common.Path(__file__).resolve().parent.parent / "skills" / "app-promo-reel" / "template"
            / "hero.html.tmpl").read_text()
    script = html.split("<script>")[-1]
    for line in script.splitlines():
        if "tl.fromTo(" in line:
            assert "immediateRender: false" in line, line


def test_the_hero_hides_a_screen_that_is_off_the_page():
    # `hyperframes check` measures the text of a clipped, off-page screen against the page behind
    # it, and fails the contrast gate: an off-page screen must have opacity 0
    html = (common.Path(__file__).resolve().parent.parent / "skills" / "app-promo-reel" / "template"
            / "hero.html.tmpl").read_text()
    assert 'gsap.set("#scr-b", { x: 760, opacity: 0 })' in html
    assert 'tl.to("#scr-a", { opacity: 0' in html and 'tl.to("#scr-b", { opacity: 0' in html


# --- finish: silent loop --------------------------------------------------------------------

W, H, N = 192, 108, 120  # a 4 s loop at 30 fps, small so that the encodes are fast


@pytest.fixture(autouse=True)
def small_16x9(monkeypatch):
    monkeypatch.setitem(common.FORMATS, "16:9", (W, H))


def loop_frames(pose):
    """N gray frames: a textured background and a bright square whose x is pose(i), 0 <= i < N."""
    rng = np.random.default_rng(3)
    bg = rng.integers(20, 60, (H, W)).astype(np.uint8)
    out = np.repeat(bg[None], N, axis=0)
    for i in range(N):
        x = int(round(pose(i)))
        out[i, 30:70, 20 + x:60 + x] = 255
    return out


def eased(i):  # 0 at both ends of the loop, with zero speed there
    return 30 * np.sin(np.pi * i / N) ** 2


def encode(path, frames, audio=False):
    n, h, w = frames.shape
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-framerate", "30",
           "-i", "-"]
    if audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, input=frames.astype(np.uint8).tobytes(), check=True)
    return path


@pytest.fixture
def hero(tmp_path):
    p = tmp_path / "hero"
    (p / "renders").mkdir(parents=True)
    (p / "project.json").write_text(json.dumps({"app": "demo", "variant": "a", "format": "16:9", "duration": 4}))
    (p / "index.html").write_text(DEMO_HTML)
    return p


def outputs(p):
    return sorted(f.name for f in (p / "renders").iterdir())


def test_a_clean_loop_passes_and_the_report_has_the_seam(tmp_path, hero):
    raw = encode(tmp_path / "raw.mp4", loop_frames(eased))
    assert finish.finish(hero, raw) == 0
    assert "demo-a-v1.mp4" in outputs(hero)
    rep = json.loads((hero / "renders" / "demo-a-v1-report.json").read_text())
    assert rep["silent"] is True and rep["problems"] == []
    assert rep["seam"]["ok"] and rep["seam"]["frames"] == N == rep["seam"]["frames_expected"]


def test_a_loop_that_ends_off_its_start_pose_fails_the_seam(tmp_path, hero, capsys):
    raw = encode(tmp_path / "raw.mp4", loop_frames(lambda i: 30 * i / N))
    assert finish.finish(hero, raw) == 1
    assert "demo-a-v1-failed.mp4" in outputs(hero)
    assert "seam: the loop jumps from its last frame to its first" in capsys.readouterr().err


@pytest.mark.parametrize("px", [2, 1])
def test_a_loop_that_ends_a_few_pixels_off_fails_the_seam(tmp_path, hero, px):
    # px at 192 px wide: the check decodes at 480 px, so the shift is 2.5x as large there
    raw = encode(tmp_path / "raw.mp4", loop_frames(lambda i: eased(i) + px * (i / N) ** 6))
    assert finish.finish(hero, raw) == 1


def test_the_final_file_of_a_silent_loop_has_no_audio_even_if_the_render_had_some(tmp_path, hero):
    raw = encode(tmp_path / "raw.mp4", loop_frames(eased), audio=True)
    assert finish.has_audio_stream(raw)
    assert finish.finish(hero, raw) == 0
    assert not finish.has_audio_stream(hero / "renders" / "demo-a-v1.mp4")


def test_an_audio_stream_in_the_checked_file_is_a_problem(tmp_path, hero, monkeypatch, capsys):
    # the copy step maps the video stream only, so this is the second line of defence
    monkeypatch.setattr(finish, "has_audio_stream", lambda path: True)
    raw = encode(tmp_path / "raw.mp4", loop_frames(eased))
    assert finish.finish(hero, raw) == 1
    assert "the output has an audio stream" in capsys.readouterr().err


def test_a_loop_of_the_wrong_frame_count_fails(tmp_path, hero, capsys):
    raw = encode(tmp_path / "raw.mp4", loop_frames(eased)[:-1])
    assert finish.finish(hero, raw) == 1
    assert "119 frames, a 4 s loop at 30 fps is 120" in capsys.readouterr().err


def test_a_silent_finish_does_not_read_or_need_cues_or_audio(tmp_path, hero):
    assert not (hero / "cues.realized.json").exists()
    raw = encode(tmp_path / "raw.mp4", loop_frames(eased))
    assert finish.finish(hero, raw) == 0


# --- seam_check -----------------------------------------------------------------------------

def test_seam_check_refuses_a_clip_it_cannot_measure():
    r = finish.seam_check(np.zeros((finish.SEAM_MIN_FRAMES - 1, 8, 8), np.uint8))
    assert r["ok"] is False and "error" in r


def test_a_decode_failure_is_a_problem_not_a_pass(tmp_path):
    problems, seam = finish.silent_loop_problems(tmp_path / "missing.mp4",
                                                 {"duration": 4, "fps": 30}, {"width": W, "height": H})
    assert seam["ok"] is False and len(problems) == 1 and problems[0].startswith("seam: could not be checked")


def test_a_still_clip_has_a_clean_seam():
    r = finish.seam_check(np.full((30, 16, 16), 90, np.uint8))
    assert r["ok"] and r["mad"] == 0 and r["moved"] == 0


def test_the_seam_limit_follows_the_steps_beside_the_seam():
    # a fast loop: every step is large, so a seam of the same size is not a jump
    frames = np.zeros((30, 16, 16), np.uint8)
    for i in range(30):
        frames[i] = (i % 2) * 40
    assert finish.seam_check(frames)["ok"]
    frames[15:] += 100  # the second half sits at another level: a jump at the seam, not a fast step
    assert not finish.seam_check(frames)["ok"]


def test_a_small_bright_change_at_the_seam_fails_on_the_share_of_pixels():
    # 64 of 10000 pixels jump by 60 levels: the mean change is 0.38, under its floor of 0.6, so
    # only the `moved` term sees it
    frames = np.zeros((30, 100, 100), np.uint8)
    frames[15:, :8, :8] = 60
    r = finish.seam_check(frames)
    assert r["mad"] < finish.SEAM_MIN_MAD and r["moved"] > finish.SEAM_MIN_MOVED and not r["ok"]


@pytest.mark.parametrize("fps, duration, frames, ok", [(30, 8, 240, True), (30, 8, 239, False), (30, 8, 241, False),
                                                       (29.97, 8, 240, True), (29.97, 8, 239, True),
                                                       (29.97, 8, 238, False)])
def test_the_expected_frame_count(fps, duration, frames, ok):
    want, tol = finish.expected_frames({"fps": fps, "duration": duration})
    assert (abs(frames - want) <= tol) is ok
