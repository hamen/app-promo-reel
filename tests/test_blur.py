"""blur.py: the window, cut and average rules, and end-to-end runs on small synthetic clips."""
import json
import subprocess
import sys
from fractions import Fraction

import numpy as np
import pytest

from conftest import SCRIPTS
import blur

W, H = 256, 320  # the 4:5 size the child process patches in (a real 4:5 is 1080 x 1350)
RED, BLUE, WHITE = (255, 0, 0), (0, 0, 255), (255, 255, 255)
CUT_AT = 40      # input frame of the hard cut: c of output frame 5

# blur.py runs in a child Python (a hang fails the test instead of stopping bin/ci); the child shrinks
# the 4:5 format first, as test_finish.py does in-process for 9:16
CHILD = """
import sys
sys.path.insert(0, {scripts!r})
import common
common.FORMATS["4:5"] = ({w}, {h})
import blur
{patch}
blur.main({argv!r})
"""


def run_blur(proj, src, patch="", timeout=120):
    code = CHILD.format(scripts=str(SCRIPTS), w=W, h=H, patch=patch, argv=[str(proj), str(src)])
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=timeout)


def write_proj(tmp_path, fmt="4:5", fps=30, duration=4):
    p = tmp_path / "proj"
    p.mkdir(exist_ok=True)
    (p / "project.json").write_text(json.dumps({"app": "demo", "variant": "a", "duration": duration, "fps": fps,
                                                "format": fmt, "beats_per_bar": 4, "stores": ["app_store"]}))
    return p


def fixture_frames(n=64):
    """0-15: a white box at rest on red; 16-39: the box moves 8 px per frame; 40-: a blue field.
    8 px, a multiple of blur.STRIDE: a 6 px move reads every 4th pixel as steps that alternate in size,
    and the start of the move then looks like a cut (one frame less blur, a cost blur.py accepts)."""
    out = []
    for i in range(n):
        f = np.empty((H, W, 3), np.uint8)
        if i < CUT_AT:
            f[:] = RED
            x = 8 + 8 * max(0, i - 15)
            f[100:160, x:x + 40] = WHITE
        else:
            f[:] = BLUE
        out.append(f)
    return out


def make_clip(path, frames, rate="240", audio=True):
    """A lossless H.264 clip, yuv420p with bt709 tags (as a HyperFrames render has), plus a tone."""
    h, w = frames[0].shape[:2]
    seconds = len(frames) / float(Fraction(rate))
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-framerate", rate, "-i", "-"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}"]
    cmd += ["-map", "0:v"] + (["-map", "1:a", "-c:a", "aac"] if audio else [])
    cmd += ["-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p", "-c:v", "libx264", "-qp", "0",
            "-preset", "ultrafast", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-color_range", "tv", "-movflags", "+faststart", str(path)]
    subprocess.run(cmd, input=b"".join(f.tobytes() for f in frames), check=True)
    return path


def decode(path, pix_fmt="rgb24"):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "rawvideo",
                          "-pix_fmt", pix_fmt, "-"], capture_output=True, check=True).stdout
    per = W * H * 3 if pix_fmt == "rgb24" else W * H * 3 // 2
    return np.frombuffer(raw, np.uint8).reshape(-1, per)


def luma(path):
    return decode(path, "yuv420p")[:, :W * H].astype(np.float32)


def video_tags(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=r_frame_rate,color_range,color_space,color_primaries,color_transfer", "-of", "json",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)["streams"][0]


def audio_md5(path):
    return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-c:a", "copy", "-f", "framemd5",
                           "-"], capture_output=True, text=True, check=True).stdout


def line(stdout, name):
    return next(l for l in stdout.splitlines() if l.startswith(name + ":")).split(":", 1)[1].split()


# ---------------------------------------------------------------- the rules, as pure functions

@pytest.mark.parametrize("k, r", [(4, 1), (5, 1), (6, 2), (8, 2), (10, 3)])
def test_the_window_reaches_a_third_of_a_frame_each_side(k, r):
    assert blur.reach(k) == r
    c = 5 * k
    assert blur.window(c, 100 * k, r, lambda i: False) == (c - r, c + r)


def test_the_window_is_clamped_to_the_clip():
    assert blur.window(0, 64, 2, lambda i: False) == (0, 2)
    assert blur.window(63, 64, 2, lambda i: False) == (61, 63)


def test_a_cut_keeps_the_side_of_the_frame_time():
    c = 40
    assert blur.window(c, 64, 2, lambda i: i == c + 1) == (c - 2, c + 1)  # cut between c+1 and c+2
    assert blur.window(c, 64, 2, lambda i: i == c - 1) == (c, c + 2)      # cut just before c
    assert blur.window(c, 64, 2, lambda i: i in (c - 2, c)) == (c - 1, c)


@pytest.mark.parametrize("k", range(4, 11))
def test_windows_never_touch_and_the_half_frame_is_in_no_window(k):
    r = blur.reach(k)
    assert 2 * r + 1 < k
    for off in (k // 2, -(-k // 2)):  # both frames next to the half-frame time when k is odd
        assert off > r and k - off > r  # outside the window of c and of c + k


@pytest.mark.parametrize("rate, fps, k", [
    (240, 30, 8), (240, 60, 4), (200, 25, 8), (Fraction(240000, 1001), Fraction(30000, 1001), 8),
    (Fraction(240000, 1001), 29.97, 8),
    (240, 25, None), (240, 29.97, None), (30, 30, None), (90, 30, None)])
def test_the_rate_must_be_a_whole_multiple_of_four_or_more(rate, fps, k):
    assert blur.factor(rate, fps) == k


def steps_of(*values, at=10):
    return {at + i: v for i, v in enumerate(values)}


def test_a_spike_is_a_cut():
    assert blur.is_cut(steps_of(0.1, 0.1, 6, 0.1, 0.1), 12)


def test_smooth_motion_is_not_a_cut():
    ramp = steps_of(*[2 * 1.3 ** i for i in range(5)])
    assert not any(blur.is_cut(ramp, i) for i in ramp)


def test_a_start_from_rest_is_not_a_cut():
    start = steps_of(0, 0, 0, 0.4, 0.8)  # above 3 x its still neighbours, but under the floor
    assert not any(blur.is_cut(start, i) for i in start)


def test_a_fast_fade_is_not_a_cut():
    fade = steps_of(17, 19, 25, 21, 18)
    assert not any(blur.is_cut(fade, i) for i in fade)


def test_an_unknown_step_is_not_a_cut():
    assert not blur.is_cut(steps_of(0.1, 6), 30)


def test_the_average_rounds_once():
    f = lambda v: np.full(6, v, np.uint8)  # noqa: E731
    assert blur.average([f(10), f(11), f(11)]).tolist() == [11] * 6
    assert blur.average([f(10), f(10), f(11)]).tolist() == [10] * 6
    same = np.arange(6, dtype=np.uint8)
    assert blur.average([same] * 5).tobytes() == same.tobytes()


def test_the_local_score_sees_a_small_object_the_mean_does_not():
    a = np.zeros((64, 64), np.float32)
    b = a.copy()
    b[:16, :16] = 80  # one cell of 16 changes
    whole, local = blur.step_scores(a, b)
    assert local == 80 and whole == 5
    c = np.zeros((40, 40), np.float32)  # only full cells count: the 8 px margin is left out
    d = c.copy()
    d[32:, 32:] = 80
    assert blur.step_scores(c, d)[1] == 0


def test_fastest_takes_one_frame_per_move():
    scores = [0] * 60
    scores[10:14] = [5, 9, 7, 3]    # one move: frame 11 is its best
    scores[40] = 12                 # another, 1 s later, and the best: still printed second
    scores[50] = 1.5                # below FAST_MIN
    assert blur.pick_fastest(scores, 30) == [11, 40]


def test_fastest_keeps_at_most_six_in_time_order():
    scores = [float(i % 7) for i in range(400)]
    picked = blur.pick_fastest(scores, 30)
    assert len(picked) == blur.FAST_MAX and picked == sorted(picked)
    assert all(b - a >= 15 for a, b in zip(picked, picked[1:]))


def test_fastest_names_nothing_in_a_still_reel():
    assert blur.pick_fastest([0.0, 1.0, 1.9], 30) == []


# ---------------------------------------------------------------- end to end

@pytest.fixture
def clip(tmp_path):
    return make_clip(tmp_path / "sub240.mp4", fixture_frames())


def test_blur_end_to_end(tmp_path, clip):
    proj = write_proj(tmp_path)  # no renders/ folder: blur.py makes it
    r = run_blur(proj, clip)
    assert r.returncode == 0, r.stderr
    out = proj / "renders" / "raw.mp4"
    assert not (proj / "renders" / "raw.partial.mp4").exists()

    tags = video_tags(out)
    assert tags == {**video_tags(clip), "r_frame_rate": "30/1"}
    src_rgb, out_rgb = decode(clip).astype(np.float32), decode(out).astype(np.float32)
    assert len(out_rgb) == 8
    # the cut stays sharp: frame 5 is the blue side only, frame 4 the red side only
    assert np.abs(out_rgb[5] - src_rgb[CUT_AT]).mean() < 3
    assert np.abs(out_rgb[4] - src_rgb[30:35].mean(0)).mean() < 3
    # the moving box smears: levels between the field and the box along its edges
    src_y, out_y = luma(clip), luma(out)
    field, box = np.median(src_y[0]), src_y[0].max()
    between = lambda y: int(((y > field + 20) & (y < box - 20)).sum())  # noqa: E731
    assert between(src_y[24]) == 0 and between(out_y[3]) > 500
    # the colour matrix is unchanged: a still red frame keeps its level
    assert abs(out_y[0].mean() - src_y[0].mean()) < 1
    assert audio_md5(out) == audio_md5(clip)

    assert line(r.stdout, "blur") == ["K=8,", "5", "of", "8", "input", "frames", "per", "output", "frame", "(about",
                                      "225", "degrees),", "8", "frames,", "1", "windows", "cut", "short"]
    assert line(r.stdout, "cuts") == ["0.167"]
    fastest = line(r.stdout, "fastest")
    assert len(fastest) == 1 and fastest[0] in ("0.067", "0.100", "0.133")


def test_blur_replaces_an_old_output(tmp_path, clip):
    proj = write_proj(tmp_path)
    (proj / "renders").mkdir()
    (proj / "renders" / "raw.mp4").write_bytes(b"old render")
    assert run_blur(proj, clip).returncode == 0
    assert len(decode(proj / "renders" / "raw.mp4")) == 8


def nothing_written(proj, old=b"old render"):
    renders = proj / "renders"
    return sorted(p.name for p in renders.iterdir()) == ["raw.mp4"] and (renders / "raw.mp4").read_bytes() == old


def old_output(proj):
    (proj / "renders").mkdir(exist_ok=True)
    (proj / "renders" / "raw.mp4").write_bytes(b"old render")


def late_start(tmp_path, clip):
    late = tmp_path / "late.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-itsoffset", "0.1", "-i", str(clip), "-i", str(clip),
                    "-map", "0:v", "-map", "1:a", "-c", "copy", str(late)], check=True)
    return late


@pytest.mark.parametrize("case, rule", [
    ("16:9", "blur is for 9:16 and 4:5"),
    ("missing", "not found"),
    ("30 fps input", "whole multiple (4 or more) of the project fps"),
    ("25 fps project", "whole multiple (4 or more) of the project fps"),
    ("29.97 fps project", "whole multiple (4 or more) of the project fps"),
    ("65 frames", "not a whole number of output frames"),
    ("size", "is 256x320, but a 9:16 project is 1080x1920"),
    ("no audio", "has no audio stream"),
    ("late start", "not a constant-rate video that starts at 0"),
])
def test_a_bad_input_exits_2_and_writes_nothing(tmp_path, case, rule):
    fmt, fps = {"16:9": ("16:9", 30), "25 fps project": ("4:5", 25), "29.97 fps project": ("4:5", 29.97),
                "size": ("9:16", 30)}.get(case, ("4:5", 30))
    proj = write_proj(tmp_path, fmt=fmt, fps=fps, duration=8)
    old_output(proj)
    frames = fixture_frames(65 if case == "65 frames" else 64)
    src = make_clip(tmp_path / "in.mp4", frames, rate="30" if case == "30 fps input" else "240",
                    audio=case != "no audio")
    if case == "missing":
        src = tmp_path / "nope.mp4"
    elif case == "late start":
        src = late_start(tmp_path, src)
    r = run_blur(proj, src)
    assert r.returncode == 2 and rule in r.stderr, r.stderr
    assert nothing_written(proj)


def test_a_failure_while_blurring_removes_the_partial_file(tmp_path, clip):
    proj = write_proj(tmp_path)
    old_output(proj)
    patch = """
real, calls = blur.average, []
def average(frames):
    calls.append(1)
    if len(calls) > 3:
        raise RuntimeError("boom")
    return real(frames)
blur.average = average
"""
    r = run_blur(proj, clip, patch=patch)
    assert r.returncode != 0 and "boom" in r.stderr
    assert nothing_written(proj)


def test_a_decoder_that_stops_early_is_an_error(tmp_path, clip):
    proj = write_proj(tmp_path)
    old_output(proj)
    patch = """
real = blur.decoder_cmd
blur.decoder_cmd = lambda src: real(src)[:-1] + ["-frames:v", "32", "-"]
"""
    r = run_blur(proj, clip, patch=patch)
    assert r.returncode == 2 and "the decoder stopped after 32 of 64 frames" in r.stderr, r.stderr
    assert nothing_written(proj)
