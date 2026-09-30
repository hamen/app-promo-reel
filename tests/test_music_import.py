import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

import music_import


def mp3(tmp_path, seconds=10.0, click_at=None, name="track.mp3"):
    """An mp3 made by ffmpeg: a quiet tone, and one loud click at `click_at` seconds."""
    sr = 44100
    t = np.arange(int(seconds * sr)) / sr
    y = 0.05 * np.sin(2 * np.pi * 220 * t)
    if click_at is not None:
        a = int(click_at * sr)
        y[a:a + 40] = 0.9
    wav = tmp_path / "src.wav"
    sf.write(wav, y, sr)
    out = tmp_path / name
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "192k",
                    str(out)], check=True)
    return out


def run(*args):
    with pytest.raises(SystemExit) as e:
        music_import.main([str(a) for a in args])
    return e.value.code


def test_a_track_becomes_a_48k_stereo_wav_with_its_source(tmp_path):
    src, out = mp3(tmp_path), tmp_path / "work"
    music_import.main([str(src), "--out", str(out), "--source", "https://example.com/track  "])
    y, sr = sf.read(out / "bgm_user.wav")
    assert sr == 48000 and y.shape[1] == 2 and abs(len(y) / sr - 10.0) < 0.06
    assert (out / "bgm_user.source.txt").read_text() == \
        "file: track.mp3\nsource: https://example.com/track\nstart: 0 s\n"
    assert sorted(p.name for p in out.iterdir()) == ["bgm_user.source.txt", "bgm_user.wav"]


def test_start_cuts_the_track_to_the_sample(tmp_path):
    src, out = mp3(tmp_path, click_at=5.0), tmp_path / "work"
    music_import.main([str(src), "--out", str(out), "--source", "x", "--start", "5"])
    y, sr = sf.read(out / "bgm_user.wav")
    assert abs(len(y) / sr - 5.0) < 0.06
    # the mp3 encoder's delay is compensated by the decoder; the click must be at 0 within 1 ms
    assert np.argmax(np.abs(y[:, 0])) / sr < 0.001
    assert (out / "bgm_user.source.txt").read_text().endswith("start: 5 s\n")


@pytest.mark.parametrize("what", ["url", "dir", "missing"])
def test_only_a_local_file_is_taken(tmp_path, capsys, what):
    arg = {"url": "https://mixkit.co/free-stock-music/some-track/", "dir": tmp_path,
           "missing": tmp_path / "nope.mp3"}[what]
    assert run(arg, "--out", tmp_path / "work", "--source", "x") == 2
    err = capsys.readouterr().err
    assert ("never downloads music" if what == "url" else "is not a file") in err
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize("start", ["-1", "nan", "inf"])
def test_start_must_be_a_time_in_the_track(tmp_path, start):
    assert run(mp3(tmp_path), "--out", tmp_path / "work", "--source", "x", "--start", start) == 2
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize("source", ["", "   "])
def test_source_must_say_something(tmp_path, source):
    assert run(mp3(tmp_path), "--out", tmp_path / "work", "--source", source) == 2


def test_source_is_required(tmp_path):
    assert run(mp3(tmp_path), "--out", tmp_path / "work") == 2


def old_import(out):
    out.mkdir()
    (out / "bgm_user.wav").write_bytes(b"the previous track")
    (out / "bgm_user.source.txt").write_text("file: old.mp3\n")


def test_a_start_past_the_end_fails_and_leaves_no_track(tmp_path, capsys):
    out = tmp_path / "work"
    old_import(out)
    assert run(mp3(tmp_path), "--out", out, "--source", "x", "--start", "20") == 2
    assert "nothing left" in capsys.readouterr().err
    assert list(out.iterdir()) == []


def test_a_file_ffmpeg_cannot_decode_fails_and_leaves_no_track(tmp_path, capsys):
    out, junk = tmp_path / "work", tmp_path / "junk.mp3"
    junk.write_bytes(b"not audio at all")
    old_import(out)
    assert run(junk, "--out", out, "--source", "x") == 2
    assert "could not decode" in capsys.readouterr().err
    assert list(out.iterdir()) == []


def test_no_source_record_means_no_track(tmp_path, monkeypatch):
    src, out = mp3(tmp_path), tmp_path / "work"

    def refuse(self, *a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(Path, "write_text", refuse)
    assert run(src, "--out", out, "--source", "x") == 2
    assert list(out.iterdir()) == []


def test_ffmpeg_failing_mid_write_leaves_no_partial_file(tmp_path, monkeypatch):
    src, out = mp3(tmp_path), tmp_path / "work"

    def half_written(cmd, **kw):
        Path(cmd[-1]).write_bytes(b"RIFF half a file")
        return subprocess.CompletedProcess(cmd, 1, "", "error while writing")
    monkeypatch.setattr(music_import.subprocess, "run", half_written)
    assert run(src, "--out", out, "--source", "x") == 2
    assert list(out.iterdir()) == []
