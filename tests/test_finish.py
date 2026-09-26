import json
import subprocess

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
    (p / "cues.realized.json").write_text(json.dumps(
        [{"id": f"c{i}", "file": "x", "time": t, "volume": 1, "track": 21, "sync": s} for i, (t, s) in enumerate(cues)]))


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


def test_no_onset_in_window_is_flagged(tmp_path, proj):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [(2.0, True)])  # nothing within +-150 ms
    assert finish.finish(proj, raw) == 1
    report = json.loads((proj / "renders" / "demo-a-v1-report.json").read_text())
    assert report["sync"][0]["flag"] == "no onset"


def test_no_cues_passes(tmp_path, proj):
    raw = make_raw_mp4(tmp_path)
    realize(proj, [])
    assert finish.finish(proj, raw) == 0


def test_wrong_duration_fails(tmp_path, proj):
    raw = make_raw_mp4(tmp_path, seconds=3.0)
    realize(proj, [])
    assert finish.finish(proj, raw) == 1


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
