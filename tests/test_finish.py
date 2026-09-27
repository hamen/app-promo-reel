import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

import finish
from conftest import click, write_project

SR = 48000
CLICKS = [0.5, 1.5, 2.5, 3.0]


def make_raw_mp4(tmp_path, seconds=4.0, fps=30):
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
                    f"color=c=blue:s=108x192:r={fps}:d={seconds}", "-i", str(wav), "-map", "0:v", "-map", "1:a",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(mp4)], check=True)
    return mp4


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
