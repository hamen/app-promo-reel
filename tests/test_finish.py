import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

import finish
from conftest import click, run_script, write_project

SR = 48000
CLICKS = [0.5, 1.5, 2.5, 3.0]


def make_raw_mp4(tmp_path, seconds=4.0, fps=30, size="108x192", vf=None):
    # size: the project's frame size, which finish.py checks (see small_9x16 below)
    rng = np.random.default_rng(5)
    y = 0.01 * rng.standard_normal(int(seconds * SR))
    c = click(SR)
    for t in [t for t in CLICKS if t + 0.01 < seconds]:
        a = int(t * SR)
        y[a:a + len(c)] += c
    wav = tmp_path / "raw_audio.wav"
    sf.write(wav, np.stack([y, y], 1).astype(np.float32), SR)
    mp4 = tmp_path / "raw.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"color=c=blue:s={size}:r={fps}:d={seconds}", "-i", str(wav), "-map", "0:v", "-map", "1:a",
                    *(["-vf", vf] if vf else []),
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    str(mp4)], check=True)
    return mp4


@pytest.fixture(autouse=True)
def small_9x16(monkeypatch):
    """finish.py checks the video against the format's size; a 9:16 of 108x192 keeps the ~20 encodes
    of these tests fast. The real sizes are tested in test_build.py and test_template.py."""
    import common
    monkeypatch.setitem(common.FORMATS, "9:16", (108, 192))


@pytest.fixture
def proj(tmp_path):
    p = write_project(tmp_path, duration=4)
    (p / "renders").mkdir()
    return p


def realize(p, cues):
    audio = p / "assets" / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    sf.write(audio / "click.wav", click(SR), SR)  # the same sound the fixture mixes in
    (p / "cues.realized.json").write_text(json.dumps(
        [{"id": f"c{i}", "file": "assets/audio/click.wav", "time": t, "volume": 1, "track": 21, "align": "start",
          "sync": s}
         for i, (t, s) in enumerate(cues)]))


def test_sync_ok_versioned_and_never_overwritten(tmp_path, proj):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(t, True) for t in CLICKS] + [(3.6, False)])  # an unsynced cue is ignored
    assert finish.finish(proj, raw) == 0
    v1 = proj / "renders" / "demo-a-v1.mp4"
    report = json.loads((proj / "renders" / "demo-a-v1-report.json").read_text())
    assert all(abs(r["delta_ms"]) <= 1000 / 30 for r in report["sync"])
    assert len(report["sync"]) == len(CLICKS)
    assert abs(report["lag_ms"]) < 5
    assert report["video"] == finish.video_info(raw)
    assert (proj / "renders" / "demo-a-v1-sheet.jpg").is_file()
    before = v1.read_bytes()
    assert finish.finish(proj, raw) == 0
    assert (proj / "renders" / "demo-a-v2.mp4").is_file()
    assert v1.read_bytes() == before


def test_cue_100ms_off_is_flagged(tmp_path, proj):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(0.5, True), (1.6, True)])  # the click is at 1.5
    assert finish.finish(proj, raw) == 1
    report = json.loads((proj / "renders" / "demo-a-v1-report.json").read_text())
    bad = report["sync"][1]
    assert bad["flag"] == "off by more than one frame" and abs(bad["delta_ms"] + 100) < 5
    assert (proj / "renders" / "demo-a-v1-failed.mp4").is_file()
    assert finish.next_version_path(proj / "renders", "demo-a").name == "demo-a-v2.mp4"


def test_sound_missing_from_window_is_flagged(tmp_path, proj):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(2.0, True)])  # nothing within +-150 ms
    assert finish.finish(proj, raw) == 1
    report = json.loads((proj / "renders" / "demo-a-v1-report.json").read_text())
    assert report["sync"][0]["flag"] == "masked"
    assert any("not found in the final audio" in p for p in report["problems"])


def test_one_masked_cue_among_found_ones_fails(tmp_path, proj):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(t, True) for t in CLICKS] + [(2.0, True)])  # four found, one with no sound
    assert finish.finish(proj, raw) == 1


def test_cue_marked_unsynced_is_not_checked(tmp_path, proj):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(t, True) for t in CLICKS] + [(2.0, False)])
    assert finish.finish(proj, raw) == 0


def test_missing_realized_cues_exits_2(tmp_path, proj):
    raw = make_raw_mp4(tmp_path)
    with pytest.raises(SystemExit) as e:
        finish.finish(proj, raw)
    assert e.value.code == 2


def test_no_cues_passes(tmp_path, proj):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [])
    assert finish.finish(proj, raw) == 0


def test_wrong_duration_fails(tmp_path, proj):
    raw = make_raw_mp4(tmp_path, seconds=3.0)
    realize(proj, [])
    assert finish.finish(proj, raw) == 1


def test_a_video_of_another_size_fails(tmp_path, proj, capsys):
    raw = make_raw_mp4(tmp_path, size="1080x1350")
    realize(proj, [])
    assert finish.finish(proj, raw) == 1
    assert "video is 1080x1350, project.json says 108x192 (format 9:16)" in capsys.readouterr().err


def test_a_4x5_project_passes_with_a_4x5_video(tmp_path, proj):
    doc = json.loads((proj / "project.json").read_text())
    (proj / "project.json").write_text(json.dumps({**doc, "format": "4:5"}))
    raw = make_raw_mp4(tmp_path, size="1080x1350")
    realize(proj, [])
    assert finish.finish(proj, raw) == 0


def test_matched_filter_finds_sfx_under_louder_music():
    rng = np.random.default_rng(7)
    t = np.arange(4 * SR) / SR
    music = 0.3 * np.sin(2 * np.pi * 110 * t) + 0.1 * rng.standard_normal(len(t))
    for k in np.arange(0.5, 4, 0.25):  # loud transients every 250 ms, like hats and kicks
        a = int(k * SR)
        music[a:a + 400] += 0.8 * rng.standard_normal(400)
    sfx = click(SR, dur=0.03, freq=1800, amp=0.25)
    at = 1.9  # 100 ms from the nearest music transients at 1.75 and 2.0
    y = music.copy()
    y[int(at * SR):int(at * SR) + len(sfx)] += sfx
    found, score = finish.locate(y, sfx, at + 0.02)
    assert abs(found - at) < 0.001 and score > finish.MIN_MATCH


def test_leading_silence_in_sfx_is_measured_from_the_attack(tmp_path, proj, capsys):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(t - 0.2, True) for t in CLICKS])  # cue times 200 ms before each click ...
    audio = proj / "assets" / "audio"
    sf.write(audio / "click.wav", np.concatenate([np.zeros(int(0.2 * SR)), click(SR)]), SR)  # ... after 200 ms of silence
    assert finish.finish(proj, raw) == 0
    report = json.loads((proj / "renders" / "demo-a-v1-report.json").read_text())
    assert all(abs(r["delta_ms"]) < 2 and r["lead_ms"] == 200.0 for r in report["sync"])
    assert "starts with 200 ms of silence" in capsys.readouterr().err


def test_lag_detects_a_shift():
    rng = np.random.default_rng(6)
    a = rng.standard_normal(SR)
    b = np.concatenate([np.zeros(480), a[:-480]])  # 10 ms late
    assert abs(finish.lag_seconds(a, b) - 0.010) < 1e-4
    assert finish.lag_seconds(a, a) == 0


def test_loudnorm_that_moves_audio_fails(tmp_path, proj, monkeypatch):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [])
    real = finish.loudnorm

    def shifted(src, dst):
        meas = real(src, dst)
        y, sr = sf.read(dst)
        sf.write(dst, np.concatenate([np.zeros((480, y.shape[1])), y[:-480]]), sr, subtype="PCM_16")
        return meas
    monkeypatch.setattr(finish, "loudnorm", shifted)
    assert finish.finish(proj, raw) == 1
    report = json.loads((proj / "renders" / "demo-a-v1-report.json").read_text())
    assert any("loudnorm moved audio" in x for x in report["problems"])


def test_loudness_gate():
    assert finish.loudness_problems({"input_i": "-14.21", "input_tp": "-1.58"}) == []
    assert finish.loudness_problems({"input_i": "-15.2", "input_tp": "-2.0"})
    assert finish.loudness_problems({"input_i": "-12.9", "input_tp": "-2.0"})
    assert finish.loudness_problems({"input_i": "-14.0", "input_tp": "-0.9"})


def test_loudness_miss_fails_the_run(tmp_path, proj, monkeypatch):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(t, True) for t in CLICKS])
    monkeypatch.setattr(finish, "MAX_FINAL_TP", -40.0)  # no real file can meet this ceiling
    assert finish.finish(proj, raw) == 1
    report = json.loads((proj / "renders" / "demo-a-v1-report.json").read_text())
    assert any("true peak" in p for p in report["problems"])
    assert report["sheet"].endswith("demo-a-v1-failed-sheet.jpg") and Path(report["sheet"]).is_file()
    assert not (proj / "renders" / "demo-a-v1-sheet.jpg").exists()


def test_realized_cues_that_are_not_a_list_exit_2(tmp_path, proj):
    raw = make_raw_mp4(tmp_path)
    (proj / "cues.realized.json").write_text("{}")
    with pytest.raises(SystemExit) as e:
        finish.finish(proj, raw)
    assert e.value.code == 2


def test_realized_entries_are_checked(tmp_path, proj):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(1.0, True)])  # the cue file exists: only the entry shape can fail
    for bad in ("[{}]", '[{"id": "c", "file": "assets/audio/click.wav"}]',
                '[{"id": "c", "file": "assets/audio/click.wav", "time": "1.0"}]', '["c"]'):
        (proj / "cues.realized.json").write_text(bad)
        with pytest.raises(SystemExit) as e:
            finish.finish(proj, raw)
        assert e.value.code == 2, bad


def test_negative_frames_exit_2_before_any_output(tmp_path, proj):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(t, True) for t in CLICKS])
    r = subprocess.run([sys.executable, str(finish.__file__), str(proj), str(raw), "--frames", "1,-2"],
                       capture_output=True, text=True)
    assert r.returncode == 2 and not list((proj / "renders").glob("*.mp4"))


def test_success_leaves_final_names_and_no_checking_file(tmp_path, proj):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(t, True) for t in CLICKS])
    assert finish.finish(proj, raw) == 0
    r = proj / "renders"
    report = json.loads((r / "demo-a-v1-report.json").read_text())
    assert report["output"] == str(r / "demo-a-v1.mp4") and report["sheet"] == str(r / "demo-a-v1-sheet.jpg")
    assert Path(report["output"]).is_file() and Path(report["sheet"]).is_file()
    assert not list(r.glob("*checking*")) and not list(r.glob(".*partial*"))


def test_error_after_the_mux_leaves_only_a_failed_file(tmp_path, proj, monkeypatch):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(t, True) for t in CLICKS])

    r = proj / "renders"
    during = []

    def broken_sheet(*a, **k):
        during.extend(p.name for p in r.iterdir())  # what a reader sees while the checks run
        raise RuntimeError("disk full")
    monkeypatch.setattr(finish, "contact_sheet", broken_sheet)
    with pytest.raises(RuntimeError):
        finish.finish(proj, raw)
    assert during == ["demo-a-v1.checking.mp4"]
    assert (r / "demo-a-v1-failed.mp4").is_file()
    assert not (r / "demo-a-v1.mp4").exists() and not list(r.glob("*checking*"))
    assert not (r / "demo-a-v1-report.json").exists()


def test_leftover_checking_file_reserves_its_version(proj):
    (proj / "renders" / "demo-a-v3.checking.mp4").write_bytes(b"killed run")
    assert finish.next_version_path(proj / "renders", "demo-a").name == "demo-a-v4.mp4"


def test_failed_report_write_leaves_no_report(tmp_path, proj, monkeypatch):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(t, True) for t in CLICKS])
    real_write = Path.write_text

    def half_write(self, text, *a, **k):
        if "-report.json" in self.name:  # the report write dies half way, whatever its name
            real_write(self, text[:20])
            raise OSError("disk full")
        return real_write(self, text, *a, **k)
    monkeypatch.setattr(Path, "write_text", half_write)
    with pytest.raises(OSError):
        finish.finish(proj, raw)
    r = proj / "renders"
    assert not (r / "demo-a-v1-report.json").exists() and not list(r.glob(".*partial*"))
    # the run did not complete, so nothing keeps a delivery name
    assert (r / "demo-a-v1-failed.mp4").is_file() and not (r / "demo-a-v1.mp4").exists()
    assert not (r / "demo-a-v1-sheet.jpg").exists()


@pytest.mark.parametrize("doc, expect", [
    ({"streams": [], "format": {"duration": "4.0"}}, "no video stream"),
    ({"streams": [{"codec_name": "h264", "width": 1, "height": 1, "nb_read_packets": "120"}], "format": {}},
     "no duration"),
])
def test_video_info_without_stream_or_duration_exits_2(monkeypatch, capsys, doc, expect):
    monkeypatch.setattr(finish, "run", lambda cmd: subprocess.CompletedProcess(cmd, 0, json.dumps(doc), ""))
    with pytest.raises(SystemExit) as e:
        finish.video_info("x.mp4")
    assert e.value.code == 2 and expect in capsys.readouterr().err


def test_video_info_falls_back_to_the_format_duration(monkeypatch):
    doc = {"streams": [{"codec_name": "h264", "width": 1, "height": 1, "nb_read_packets": "120"}],
           "format": {"duration": "4.000"}}
    monkeypatch.setattr(finish, "run", lambda cmd: subprocess.CompletedProcess(cmd, 0, json.dumps(doc), ""))
    assert finish.video_info("x.mp4")["duration"] == 4.0
    for bad in ("N/A", "nan", "inf"):  # "N/A" is what ffprobe writes when the stream has none
        doc["streams"][0]["duration"] = bad
        assert finish.video_info("x.mp4")["duration"] == 4.0, bad


def test_realized_time_true_is_refused(tmp_path, proj, capsys):
    raw = make_raw_mp4(tmp_path)
    (proj / "cues.realized.json").write_text(json.dumps([{"id": "c", "file": "assets/audio/c.wav", "time": True}]))
    with pytest.raises(SystemExit) as e:
        finish.finish(proj, raw)
    assert e.value.code == 2 and "every entry needs id, file and time" in capsys.readouterr().err


def test_lead_silence_warning_covers_unsynced_cues(tmp_path, proj, capsys):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(3.6, False)])  # align "start", not checked for sync
    audio = proj / "assets" / "audio"
    sf.write(audio / "click.wav", np.concatenate([np.zeros(int(0.2 * SR)), click(SR)]), SR)
    finish.finish(proj, raw)
    assert "starts with 200 ms of silence" in capsys.readouterr().err


def test_window_energy_matches_the_direct_sum():
    rng = np.random.default_rng(3)
    seg, n = rng.standard_normal(5000), 400
    assert np.allclose(finish.window_energy(seg, n), np.convolve(seg ** 2, np.ones(n), mode="valid"))
    y = np.zeros(SR)
    tmpl = click(SR)
    y[int(0.5 * SR):int(0.5 * SR) + len(tmpl)] += tmpl
    found, score = finish.locate(y, tmpl, 0.52)
    assert abs(found - 0.5) < 1e-3 and score > 0.99


def test_error_in_the_warning_step_leaves_no_file(tmp_path, proj, monkeypatch):
    # late_starts reads only the cue sounds, so it runs before the mux
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(t, True) for t in CLICKS])

    def broken(*a, **k):
        raise RuntimeError("cannot decode")
    monkeypatch.setattr(finish, "late_starts", broken)
    with pytest.raises(RuntimeError, match="cannot decode"):
        finish.finish(proj, raw)
    r = proj / "renders"
    assert not r.exists() or list(r.iterdir()) == []


# --- frame checks: blank opening and pops -------------------------------------------------------

def gray_clip(tmp_path, frames, rate="30", name="clip.mp4"):
    """An MP4 whose luma is exactly `frames` (uint8, n x h x w): x264 at qp 0."""
    n, h, w = frames.shape
    mp4 = tmp_path / name
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}",
                    "-framerate", rate, "-i", "-", "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p", str(mp4)],
                   input=frames.astype(np.uint8).tobytes(), check=True)
    return mp4


def texture(seed, n, h=192, w=108):
    return np.repeat(np.random.default_rng(seed).integers(0, 256, (1, h, w)), n, axis=0)


def marks(p, scenes=(0.0,), beats=()):
    (p / "index.html").write_text("".join(f'<section id="s{i}" data-start="{t}"></section>' for i, t in enumerate(scenes)))
    (p / "beats.json").write_text(json.dumps({"beats": list(beats), "downbeat_phase": 0}))


def checks(tmp_path, frames, rate="30"):
    mp4 = gray_clip(tmp_path, frames, rate)
    return finish.frame_checks(tmp_path, mp4, finish.video_info(mp4))


# the still-clip fixtures hold their first picture for 1 s, then change: a dead hold (finish.HOLD_MAX)
STILL_1S = "still for 1.00 s from 0.00 s: nothing on screen moves (look at it)"


def test_blank_opening_is_reported_with_the_first_readable_time(tmp_path):
    marks(tmp_path, (0.0, 1.5))  # the texture arrives with a scene: a planned cut, no pop warning
    f = texture(1, 60)
    f[:45] = 30  # 1.5 s of flat colour, then a textured frame
    r = checks(tmp_path, f)
    assert r["frame0_blank"] is True and r["first_detail_time"] == pytest.approx(1.5, abs=0.002)
    assert r["warnings"] == [
        "frame 0 is blank, and feeds show frame 0 as the thumbnail: start on the hook text or UI",
        "nothing to read until 1.50 s: the hook must show within 1 s",
        "still for 1.50 s from 0.00 s: nothing on screen moves (look at it)"]


def test_an_empty_video_gives_only_the_empty_warning(tmp_path):
    marks(tmp_path)
    r = checks(tmp_path, np.full((30, 192, 108), 30))
    assert r["frame0_blank"] is True and r["first_detail_time"] is None and r["events"] == []
    assert r["warnings"] == ["no frame has anything to read on it: the video looks empty"]


def test_a_steady_picture_gives_nothing(tmp_path):
    marks(tmp_path)
    r = checks(tmp_path, texture(1, 60))
    assert r["frame0_blank"] is False and r["first_detail_time"] == 0.0
    assert r["events"] == [] and r["warnings"] == [] and r["notes"] == []


def test_one_odd_frame_is_one_flash(tmp_path):
    marks(tmp_path)
    f = texture(1, 60)
    f[30] = 255
    r = checks(tmp_path, f)
    assert r["events"] == [{"type": "flash", "time": 1.0, "frames": 1}]
    assert r["warnings"] == ["one-frame flash at 1.00 s: a glitch frame (look at it)", STILL_1S]


@pytest.mark.parametrize("scenes, beats", [((0.0, 1.0), ()), ((0.0,), (1.1,))])
def test_a_cut_on_a_scene_start_or_just_before_a_beat_is_planned(tmp_path, scenes, beats):
    marks(tmp_path, scenes, beats)
    f = np.concatenate([texture(1, 30), texture(2, 30)])  # hard switch at 1.0 s
    r = checks(tmp_path, f)
    assert [(e["type"], e["time"], e["planned"]) for e in r["events"]] == [("cut", 1.0, True)]
    assert r["warnings"] == [STILL_1S]


def test_a_cut_near_no_beat_and_no_scene_is_a_warning(tmp_path):
    marks(tmp_path, (0.0,), (0.5, 1.5))
    f = np.concatenate([texture(1, 30), texture(2, 30)])
    r = checks(tmp_path, f)
    assert [(e["type"], e["planned"]) for e in r["events"]] == [("cut", False)]
    assert r["warnings"] == ["sudden change at 1.00 s near no beat and no scene start (look at it)", STILL_1S]


def test_spikes_a_few_frames_apart_are_one_move(tmp_path):
    marks(tmp_path, (0.0,), (1.2,))
    f = np.concatenate([texture(1, 30), texture(2, 2), texture(3, 2), texture(4, 26)])  # 3 jumps in 4 frames
    r = checks(tmp_path, f)
    assert [(e["type"], e["time"], e["frames"], e["planned"]) for e in r["events"]] == [("cut", 1.0, 5, True)]
    assert r["warnings"] == [STILL_1S]


def test_other_sizes_and_rates_are_timed_right(tmp_path):
    marks(tmp_path, (0.0,), (0.5,))
    # 4:5; the cut at frame 300 is 10.010 s at 29.97 fps and 10.000 s if the rate were taken as 30
    f = np.concatenate([texture(1, 300, 150, 120), texture(2, 30, 150, 120)])
    mp4 = gray_clip(tmp_path, f, rate="30000/1001")
    assert len(finish.decode_gray(mp4, 120, 150)) == 330
    r = finish.frame_checks(tmp_path, mp4, finish.video_info(mp4))
    assert len(r["events"]) == 1 and r["events"][0]["time"] == pytest.approx(300 / 29.97, abs=0.002)
    assert r["events"][0]["planned"] is False


def test_unreadable_marks_are_notes_not_failures(tmp_path):
    (tmp_path / "beats.json").write_text("{not json")
    r = checks(tmp_path, texture(1, 30))
    assert r["warnings"] == [] and len(r["notes"]) == 2
    assert r["notes"][0].startswith("index.html not read") and r["notes"][1].startswith("beats.json not read")


def test_frame_checks_never_fail_the_reel(tmp_path, proj, monkeypatch, capsys):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(t, True) for t in CLICKS])
    (proj / "beats.json").write_text("{not json")  # read_json would die() here: SystemExit
    assert finish.finish(proj, raw) == 0
    report = json.loads((proj / "renders" / "demo-a-v1-report.json").read_text())
    assert any(n.startswith("beats.json not read") for n in report["frames"]["notes"])

    real_decode, calls = finish.decode_gray, []

    def broken(*a, **k):
        calls.append(1)
        if len(calls) == 1:  # the frame checks run first; the poster decodes again and needs it
            raise RuntimeError("decoder gone")
        return real_decode(*a, **k)
    monkeypatch.setattr(finish, "decode_gray", broken)
    assert finish.finish(proj, raw) == 0
    report = json.loads((proj / "renders" / "demo-a-v2-report.json").read_text())
    assert report["frames"]["notes"] == ["frame checks did not run: RuntimeError('decoder gone')"]
    assert report["frames"]["error"] == "RuntimeError('decoder gone')"
    assert report["frames"]["holds"] == [] and report["frames"]["warnings"] == []
    assert (proj / "renders" / "demo-a-v2.mp4").is_file()
    assert "note: frame checks did not run" in capsys.readouterr().err


def test_a_small_settle_is_not_a_pop(tmp_path):
    # a headline settling after its slam changes a few gray levels in one frame: not a pop
    # the settle comes at 0.67 s: whether the codec's rounding makes the +8 step a change for the hold
    # check or not, there is no hold (0.67 s, then a 1.33 s end card; or one 2.0 s end card)
    marks(tmp_path, (0.0,), (0.5,))
    base = texture(1, 60)
    f = np.concatenate([base[:20], np.clip(base[20:] + 8, 0, 255)])
    r = checks(tmp_path, f)
    assert r["events"] == [] and r["warnings"] == []


def test_a_flash_next_to_a_cut_is_still_a_flash(tmp_path):
    marks(tmp_path, (0.0, 1.0))
    f = np.concatenate([texture(1, 30), texture(2, 30)])  # planned cut at 1.0 s
    f[32] = 255  # a glitch frame two frames later
    r = checks(tmp_path, f)
    assert [(e["type"], e["time"]) for e in r["events"]] == [("cut", 1.0), ("flash", pytest.approx(32 / 30, abs=0.002))]
    assert r["warnings"] == ["one-frame flash at 1.07 s: a glitch frame (look at it)", STILL_1S]


def test_a_spike_on_the_last_frame_is_a_cut(tmp_path):
    marks(tmp_path, (0.0,), (0.5,))
    f = texture(1, 30)
    f[29] = 255  # nothing after it to come back to: a cut, not a flash
    r = checks(tmp_path, f)
    assert [(e["type"], e["frames"], e["planned"]) for e in r["events"]] == [("cut", 1, False)]


def test_audio_longer_than_the_video_does_not_stretch_frame_times(tmp_path):
    marks(tmp_path, (0.0,), (0.5,))
    video = gray_clip(tmp_path, np.concatenate([texture(1, 60), texture(2, 30)]))  # cut at 2.0 s of 3.0 s
    mp4 = tmp_path / "long-audio.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-f", "lavfi", "-i",
                    "anullsrc=r=48000:cl=stereo", "-t", "4.0", "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", str(mp4)], check=True)
    vi = finish.video_info(mp4)
    assert vi["duration"] == pytest.approx(3.0, abs=0.01)
    r = finish.frame_checks(tmp_path, mp4, vi)
    assert [e["time"] for e in r["events"]] == [pytest.approx(2.0, abs=0.002)]


def test_a_blank_frame_0_with_an_early_hook_gives_only_the_thumbnail_warning(tmp_path):
    # what the three delivered reels do: an empty first frame, text by 0.5 s
    marks(tmp_path, (0.0, 0.5))
    f = texture(1, 60)
    f[:15] = 30
    r = checks(tmp_path, f)
    assert r["frame0_blank"] is True and r["first_detail_time"] == 0.5
    assert r["warnings"] == ["frame 0 is blank, and feeds show frame 0 as the thumbnail: start on the hook text or UI"]


def test_a_commented_out_scene_is_not_a_planned_cut(tmp_path):
    (tmp_path / "index.html").write_text('<section data-start="0"></section><!-- <section data-start="1.0"></section> -->')
    (tmp_path / "beats.json").write_text(json.dumps({"beats": [0.5], "downbeat_phase": 0}))
    assert finish.scene_starts((tmp_path / "index.html").read_text()) == ([0.0], [])
    r = checks(tmp_path, np.concatenate([texture(1, 30), texture(2, 30)]))
    assert [e["planned"] for e in r["events"]] == [False]


@pytest.mark.parametrize("frames_before, planned", [(1, True), (2, True), (3, False)])
def test_a_beat_up_to_two_frames_before_a_cut_plans_it(tmp_path, frames_before, planned):
    mp4 = gray_clip(tmp_path, np.concatenate([texture(1, 30), texture(2, 30)]))  # hard switch at frame 30
    vi = finish.video_info(mp4)
    dt = vi["duration"] / 60  # the same frame time frame_checks uses
    marks(tmp_path, (0.0,), (30 * dt - frames_before * dt,))
    r = finish.frame_checks(tmp_path, mp4, vi)
    assert [(e["type"], e["time"], e["planned"]) for e in r["events"]] == [("cut", 1.0, planned)]


def test_a_bad_data_start_skips_only_its_own_scene(tmp_path):
    marks(tmp_path, (0.0, "x", "1e999", 1.0))
    assert finish.scene_starts((tmp_path / "index.html").read_text()) == ([0.0, 1.0], [
        "index.html: data-start 'x' is not a number: that scene start is not compared with cuts",
        "index.html: data-start '1e999' is not a number: that scene start is not compared with cuts"])
    r = checks(tmp_path, np.concatenate([texture(1, 30), texture(2, 30)]))
    assert [(e["type"], e["time"], e["planned"]) for e in r["events"]] == [("cut", 1.0, True)]
    assert r["warnings"] == [STILL_1S]
    assert r["notes"] == [
        "index.html: data-start 'x' is not a number: that scene start is not compared with cuts",
        "index.html: data-start '1e999' is not a number: that scene start is not compared with cuts"]


def test_frame_warnings_reach_stderr(tmp_path, proj, capsys):
    raw = make_raw_mp4(tmp_path)  # a flat blue picture: nothing to read on it
    realize(proj, [(t, True) for t in CLICKS])
    assert finish.finish(proj, raw) == 0
    err = capsys.readouterr().err
    assert "warning: no frame has anything to read on it: the video looks empty" in err


def test_cuts_far_apart_are_separate_events(tmp_path):
    marks(tmp_path, (0.0, 1.0), ())
    # 1.0 s on a scene, 1.2 s on nothing: 6 frames apart, inside POP_MOVE_MAX, beyond POP_GROUP
    f = np.concatenate([texture(1, 30), texture(2, 6), texture(3, 24)])
    r = checks(tmp_path, f)
    assert [(e["time"], e["frames"], e["planned"]) for e in r["events"]] == [(1.0, 1, True), (1.2, 1, False)]
    assert r["warnings"] == ["sudden change at 1.20 s near no beat and no scene start (look at it)", STILL_1S]


def test_a_long_chain_of_cuts_is_not_one_planned_move(tmp_path):
    # spikes every 3 frames from 0.1 s to 1.0 s: a beat at 0.1 s must not cover the later ones
    marks(tmp_path, (0.0,), (0.1,))
    f = np.concatenate([texture(i, 3) for i in range(1, 12)] + [texture(99, 27)])[:60]
    r = checks(tmp_path, f)
    assert r["events"][0]["planned"] is True and r["events"][0]["time"] == pytest.approx(0.1, abs=0.002)
    assert all(e["end"] - e["time"] <= finish.POP_MOVE_MAX + 1e-6 for e in r["events"])
    assert len(r["events"]) >= 3 and all(not e["planned"] for e in r["events"][1:])
    assert len(r["warnings"]) == len(r["events"]) - 1



# --- poster frame --------------------------------------------------------------------------------

def html_of(*scenes):
    return "".join(f'<section id="s{i + 1}" class="clip scene" data-start="{a}" data-duration="{b}"></section>'
                   for i, (a, b) in enumerate(scenes))


def test_scene_spans_reads_live_sections_sorted_without_repeats():
    html = ('<section id="b" data-start="5" data-duration="3"></section>'
            '<!-- <section id="old" data-start="1" data-duration="9"></section> -->'
            '<section id="a" data-start="0" data-duration="5.3"></section>'
            '<section id="dup" data-start="5" data-duration="1"></section>'
            '<section id="bad" data-start="x" data-duration="1"></section>'
            "<section id='q' data-start='9'></section>")
    assert finish.scene_spans(html) == [(0.0, 5.3), (5.0, 3.0), (9.0, None)]


def test_poster_candidates_sit_a_beat_after_each_scene_start():
    # overlapping scenes, as the template has them: the window of a scene starts when the one before ends
    spans = [(0.0, 5.3), (5.0, 5.3), (10.0, 20.0)]
    assert finish.poster_candidates(spans, 30.0) == [1.1, 6.1, 29.5]


def test_poster_candidate_moves_back_inside_a_short_window():
    # the next scene starts at 0.8, before the 1.1 s mark of the first: it moves to 0.05 s before it
    assert finish.poster_candidates([(0.0, 2.0), (0.8, 4.0)], 4.0) == [0.75, 3.5]


def test_a_scene_with_no_clean_window_gives_no_candidate():
    # scene 2 ends (2.0) before scene 1 does (3.0): it is hidden for its whole life
    assert finish.poster_candidates([(0.0, 3.0), (1.0, 1.0), (2.0, 5.0)], 6.0) == [0.95, 5.5]


def test_a_scene_hidden_under_the_one_before_gives_no_candidate_at_its_own_start():
    # scene 2 starts at 1 but scene 1 stays on top until 4: 1 + 1.1 is not clean, and no later time is tried
    assert finish.poster_candidates([(0.0, 4.0), (1.0, 5.0), (6.0, 2.0)], 8.0) == [0.95, 7.5]


def test_a_candidate_before_its_window_gives_none():
    # the last scene starts at 3.8; 0.5 s before the end (3.5) is before it
    assert finish.poster_candidates([(0.0, 2.0), (3.8, 1.0)], 4.0) == [1.1]


def test_poster_candidates_never_include_frame_zero_or_the_last_frame():
    assert finish.poster_candidates([(0.0, 0.3)], 0.5) == []
    assert finish.poster_candidates([(0.0, 0.0504)], 4.0) == []  # 0.0004 s rounds to 0.0: that is frame 0
    assert finish.poster_candidates([(0.0, None)], 0.5) == []


def test_poster_candidates_keep_a_zero_duration_as_a_real_end():
    # data-duration="0": the first scene ends where it starts, so it has no window; the later scene keeps its own
    assert finish.poster_candidates([(0.0, 0.0), (1.0, None)], 4.0) == [3.5]


def test_poster_never_picks_frame_zero_for_a_candidate_that_rounds_to_it():
    # one scene in a 0.516 s clip: the last-scene candidate is 0.016 s, and round(0.016 * 30) is frame 0
    assert finish.poster_candidates([(0.0, None)], 0.516) == [0.016]
    frames = with_detail(flat_frames(), 0, 1)
    i, info = finish.pick_poster(frames, 30, [(0.0, None)], 0.516)
    assert i == 60 and info["t"] == 2.0


def flat_frames(n=120, h=64, w=36):
    return np.zeros((n, h, w), np.float32)


def with_detail(frames, index, seed):
    frames[index] = np.random.default_rng(seed).integers(0, 256, frames[index].shape)
    return frames


def test_poster_is_the_candidate_with_most_detail():
    frames = with_detail(flat_frames(), 33, 1)  # 1.1 s: full noise
    frames[105, ::4] = 255  # 3.5 s: a few lines, less detail
    i, info = finish.pick_poster(frames, 30, [(0.0, 2.1), (2.0, 2.0)], 4.0)
    assert (i, info["t"]) == (33, 1.1)
    assert [c["t"] for c in info["candidates"]] == [1.1, 3.5]
    assert info["candidates"][0]["score"] > info["candidates"][1]["score"] > 0
    assert info["score"] == info["candidates"][0]["score"]


def test_poster_tie_goes_to_the_later_time():
    i, info = finish.pick_poster(flat_frames(), 30, [(0.0, 2.1), (2.0, 2.0)], 4.0)
    assert (i, info["t"]) == (105, 3.5)


def test_poster_score_and_frame_share_one_index():
    # t * fps does not land on a whole frame: both the score and the JPEG use round(t * fps)
    frames = with_detail(flat_frames(60), 9, 4)  # 0.29 s * 30 = 8.7
    i, info = finish.pick_poster(frames, 30, [], 2.0, forced_t=0.29)
    assert i == 9 and info["score"] > 0 and info["t"] == 0.29


def test_poster_with_no_scene_markup_uses_the_middle_frame():
    i, info = finish.pick_poster(flat_frames(), 30, [], 4.0)
    assert (i, info["t"]) == (60, 2.0)


def test_a_silent_hero_uses_the_middle_frame_but_a_silent_project_with_sections_does_not():
    one = [(0.0, 4.0)]
    assert finish.pick_poster(flat_frames(), 30, one, 4.0, silent=True)[0] == 60
    several = [(0.0, 2.1), (2.0, 2.0)]
    assert finish.pick_poster(flat_frames(), 30, several, 4.0, silent=True)[0] == 105


def test_a_single_scene_reel_uses_the_per_scene_rule():
    # the same one section, not silent: the last-scene rule applies (0.5 s before the end)
    assert finish.pick_poster(flat_frames(), 30, [(0.0, 4.0)], 4.0)[0] == 105


MARKER_FRAME = 105  # 3.5 s at 30 fps: the settled frame of the second scene


def label_clip(tmp_path):
    """Blue 108x192, a white 40x12 'label' box at the bottom the whole time, and a busier picture
    from 2 s on, so the poster is chosen in the second scene."""
    boxes = ",".join(f"drawbox=x={10 + 14 * k}:y=20:w=8:h=60:color=white:t=fill:enable='gte(t,2)'" for k in range(6))
    marker = f"drawbox=x=90:y=100:w=10:h=10:color=red:t=fill:enable='eq(n,{MARKER_FRAME})'"  # one frame only
    return make_raw_mp4(tmp_path, vf="drawbox=x=10:y=170:w=40:h=12:color=white:t=fill," + boxes + "," + marker)


def test_finish_writes_a_full_size_poster_with_the_label_and_reports_it(tmp_path, proj):
    from PIL import Image
    raw = label_clip(tmp_path)
    (proj / "index.html").write_text(html_of((0.0, 2.1), (2.0, 2.0)))
    realize(proj, [(t, True) for t in CLICKS])
    assert finish.finish(proj, raw) == 0
    r = proj / "renders"
    report = json.loads((r / "demo-a-v1-report.json").read_text())
    assert report["poster"]["path"] == str(r / "demo-a-v1-poster.jpg")
    assert report["poster"]["t"] == 3.5
    assert [c["t"] for c in report["poster"]["candidates"]] == [1.1, 3.5]
    assert report["poster"]["score"] == report["poster"]["candidates"][1]["score"]
    img = Image.open(r / "demo-a-v1-poster.jpg")
    assert img.format == "JPEG" and img.size == (108, 192)
    label = np.asarray(img.convert("RGB"))[172:180, 14:46]  # inside the label box
    assert label.min() > 200
    px = np.asarray(img.convert("RGB"))
    assert px[30:70, 12:16].min() > 200  # a box that exists only from 2 s on: not the first scene's frame
    marker = px[102:108, 92:98]  # red in frame 105 only: the JPEG is that frame, not its neighbour
    assert marker[..., 0].min() > 200 and marker[..., 1].max() < 80
    assert not list(r.glob("*checking*"))


def test_the_poster_is_a_second_encode_of_the_scored_frame_at_quality_90(tmp_path, proj):
    from PIL import Image
    raw = label_clip(tmp_path)
    (proj / "index.html").write_text(html_of((0.0, 2.1), (2.0, 2.0)))
    realize(proj, [(t, True) for t in CLICKS])
    assert finish.finish(proj, raw) == 0
    r = proj / "renders"
    png = tmp_path / "again.png"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(r / "demo-a-v1.mp4"),
                    "-vf", f"select=eq(n\\,{MARKER_FRAME})", "-fps_mode", "passthrough", "-frames:v", "1", str(png)],
                   check=True)
    again = tmp_path / "again.jpg"
    Image.open(png).convert("RGB").save(again, quality=90)
    assert (r / "demo-a-v1-poster.jpg").read_bytes() == again.read_bytes()


def test_a_failed_check_leaves_no_poster_and_no_poster_entry(tmp_path, proj):
    raw = make_raw_mp4(tmp_path, seconds=4.5)  # the project says 4 s
    realize(proj, [(t, True) for t in CLICKS])
    assert finish.finish(proj, raw) == 1
    r = proj / "renders"
    assert not list(r.glob("*poster*"))
    assert json.loads((r / "demo-a-v1-report.json").read_text())["poster"] is None


def test_a_poster_that_cannot_be_written_fails_the_run_without_a_report(tmp_path, proj, monkeypatch):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(t, True) for t in CLICKS])

    def half(mp4, index, dest):
        Path(dest).write_bytes(b"half a jpeg")
        raise RuntimeError("disk full")
    monkeypatch.setattr(finish, "write_poster", half)
    with pytest.raises(RuntimeError):
        finish.finish(proj, raw)
    r = proj / "renders"
    assert (r / "demo-a-v1-failed.mp4").is_file() and not (r / "demo-a-v1.mp4").exists()
    assert not list(r.glob("*report*")) and not list(r.glob("*poster*")) and not list(r.glob("*checking*"))


def test_poster_at_names_the_frame(tmp_path, proj):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(t, True) for t in CLICKS])
    assert finish.finish(proj, raw, poster_at=1.0) == 0
    report = json.loads((proj / "renders" / "demo-a-v1-report.json").read_text())
    assert report["poster"]["t"] == 1.0 and len(report["poster"]["candidates"]) == 1
    assert finish.finish(proj, raw, poster_at=0) == 0  # frame 0 is allowed when asked for
    assert json.loads((proj / "renders" / "demo-a-v2-report.json").read_text())["poster"]["t"] == 0.0


def test_poster_at_accepts_the_last_frame(tmp_path, proj):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(t, True) for t in CLICKS])
    assert finish.finish(proj, raw, poster_at=3.96) == 0
    assert json.loads((proj / "renders" / "demo-a-v1-report.json").read_text())["poster"]["t"] == 3.96
    assert (proj / "renders" / "demo-a-v1-poster.jpg").is_file()


@pytest.mark.parametrize("t", [-0.1, -0.01, 4.0, 100, float("nan"), float("inf")])
def test_a_poster_at_outside_the_video_exits_2_before_any_file(tmp_path, proj, t):
    raw = make_raw_mp4(tmp_path)  # 120 frames: the last is at 3.967 s
    realize(proj, [(t, True) for t in CLICKS])
    with pytest.raises(SystemExit) as e:
        finish.finish(proj, raw, poster_at=t)
    assert e.value.code == 2
    assert list((proj / "renders").iterdir()) == []


@pytest.mark.parametrize("arg", ["-1", "nan", "inf"])
def test_poster_at_on_the_command_line_must_be_a_time(tmp_path, arg):
    r = run_script("finish.py", tmp_path, tmp_path / "raw.mp4", f"--poster-at={arg}")
    assert r.returncode == 2 and "--poster-at" in r.stderr


# --- dead holds (references/storyboard.md, "Density"), on the 54 px gray frames the check reads ----
# (whole gray levels, as decode_gray gives them)

DT = 1 / 30


def still(n, seed=3):
    return np.repeat(np.random.default_rng(seed).integers(40, 200, (1, 96, 54)).astype(np.float32), n, axis=0)


def moving(n, seed=4):
    return np.random.default_rng(seed).integers(40, 200, (n, 96, 54)).astype(np.float32)


@pytest.mark.parametrize("frames, holds", [(30, [{"time": 0.0, "length": 1.0}]), (21, [])])
def test_a_still_second_is_a_dead_hold_and_0_7_s_is_not(frames, holds):
    assert finish.dead_holds(np.concatenate([still(frames), moving(60)]), DT) == holds


def test_a_hold_is_reported_where_it_starts():
    f = np.concatenate([moving(45), still(45), moving(30)])
    assert finish.dead_holds(f, DT) == [{"time": 1.5, "length": 1.5}]


def test_a_slow_creep_is_motion():
    # each frame one gray level up: no two neighbours differ by more than HOLD_PIX, but the run's
    # first frame and its ninth do
    f = still(90) + np.arange(90, dtype=np.float32)[:, None, None]
    assert max(end - first for first, end in finish.still_runs(f)) == finish.HOLD_PIX + 1
    assert finish.dead_holds(np.concatenate([f, moving(30)]), DT) == []
    # a dark bar that moves 1 px every 3 frames
    bar = still(90)
    for i in range(90):
        bar[i, :, 10 + i // 3:16 + i // 3] = 0
    assert max(end - first for first, end in finish.still_runs(bar)) == 3
    assert finish.dead_holds(np.concatenate([bar, moving(30)]), DT) == []


@pytest.mark.parametrize("seconds, holds", [(2.0, []), (3.0, [{"time": 3.0, "length": 3.0}])])
def test_the_end_card_may_hold_up_to_2_5_s(seconds, holds):
    assert finish.dead_holds(np.concatenate([moving(90), still(round(seconds * 30))]), DT) == holds


@pytest.mark.parametrize("tail, holds", [(1, []), (2, []), (3, [{"time": 3.0, "length": 2.0}])])
def test_an_end_card_that_stops_a_frame_or_two_early_is_still_the_end_card(tail, holds):
    assert finish.dead_holds(np.concatenate([moving(90), still(60), moving(tail)]), DT) == holds


@pytest.mark.parametrize("pixels, level, holds", [
    (10, 50, [{"time": 0.0, "length": 2.0}]),  # 10 of 5184 pixels: within HOLD_SHARE, still
    (11, 50, []),                              # 11: over it, motion
    (40, 8, [{"time": 0.0, "length": 2.0}]),   # a change of exactly HOLD_PIX is no change
    (40, 9, []),
])
def test_a_patch_moves_the_frame_only_over_both_thresholds(pixels, level, holds):
    f = still(60)
    f[1::2].reshape(30, -1)[:, :pixels] += level  # the patch blinks on every other frame
    assert finish.dead_holds(np.concatenate([f, moving(30)]), DT) == holds


def test_a_silent_project_gets_no_hold_warning(tmp_path):
    marks(tmp_path)
    mp4 = gray_clip(tmp_path, np.concatenate([texture(1, 30), texture(2, 30)]))
    loud = finish.frame_checks(tmp_path, mp4, finish.video_info(mp4))
    quiet = finish.frame_checks(tmp_path, mp4, finish.video_info(mp4), silent=True)
    assert loud["holds"] == [{"time": 0.0, "length": 1.0}] and STILL_1S in loud["warnings"]
    assert quiet["holds"] == [] and STILL_1S not in quiet["warnings"]
