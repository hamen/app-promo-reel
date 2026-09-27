import json
from pathlib import Path

import numpy as np
import soundfile as sf

import beat_grid as bg
import make_bed as mb
import music_rank as mr
from common import Grid
from conftest import run_script, steady_grid, write_project

SR = 32000


def thump(sr=SR, dur=0.12, freq=60.0, amp=0.9):
    t = np.arange(int(dur * sr)) / sr
    return amp * np.sin(2 * np.pi * freq * t) * np.exp(-t / 0.03)


def kick_track(times, seconds, accent_every=4, sr=SR, seed=0):
    rng = np.random.default_rng(seed)
    y = 0.01 * rng.standard_normal(int(seconds * sr))
    k = thump(sr)
    for i, t in enumerate(times):
        a = int(t * sr)
        amp = 1.0 if i % accent_every == 0 else 0.45
        y[a:a + len(k)] += amp * k[:len(y) - a]
    return y.astype(np.float32)


def gauss_env(times, t_env, width=0.006):
    env = np.zeros_like(t_env)
    for t in times:
        env += np.exp(-0.5 * ((t_env - t) / width) ** 2)
    return env


# ---------------- beat_grid ----------------

def test_offbeat_kick_shifts_half_beat():
    t_env = np.arange(0, 20, 0.008)
    kicks = np.arange(0.5, 19.5, 0.5)
    kick = gauss_env(kicks, t_env)
    beats = kicks[:-1] + 0.25  # the tracker locked onto the off-beat
    shifted, did, _ = bg.phase_check(beats, kick, t_env)
    assert did
    assert np.max(np.abs(shifted - kicks[1:])) < 0.01


def test_onbeat_kick_is_not_shifted():
    t_env = np.arange(0, 20, 0.008)
    kicks = np.arange(0.5, 19.5, 0.5)
    _, did, _ = bg.phase_check(kicks, gauss_env(kicks, t_env), t_env)
    assert not did


def test_steady_click_track_refines_to_sub_2ms_and_finds_accent():
    true = np.arange(0.5, 20.0, 0.5)
    y = kick_track(true, 21.0)
    kick, t_env = bg.band_envelope(y, SR, 40, 160)
    hi, _ = bg.band_envelope(y, SR, 2500)
    rng = np.random.default_rng(1)
    jittered = true + rng.uniform(-0.02, 0.02, len(true))  # a rough tracker result
    on = np.mean([bg.peak_near(kick, t_env, b) for b in jittered])
    beats = bg.smooth(bg.refine(jittered, kick, hi, t_env, on))
    iv = np.diff(beats)
    assert iv.std() < 0.002
    # onset strength peaks a constant few ms after the thump starts; the grid is steady
    offset = np.median(beats - true)
    assert abs(offset) < 0.025 and np.max(np.abs(beats - true - offset)) < 0.004
    strengths = [bg.peak_near(kick, t_env, b) for b in beats]
    assert bg.downbeat_phase(strengths, 4) == 0


def test_refine_never_moves_more_than_the_window():
    t_env = np.arange(0, 10, 0.004)
    kick = gauss_env([2.06], t_env)  # 60 ms away from the beat at 2.0
    out = bg.refine([2.0], kick, np.zeros_like(kick), t_env, on_strength=1.0)
    assert out[0] == 2.0
    out = bg.refine([2.0], np.zeros_like(kick), np.zeros_like(kick), t_env, on_strength=1.0)
    assert out[0] == 2.0


def test_extend_covers_duration_plus_extra_beats():
    beats = bg.extend(np.arange(1.0, 10.0, 0.5), 30.0, beats_past_end=16)
    assert beats[0] <= 0.7 and beats[-1] >= 30.0 + 16 * 0.5
    assert np.allclose(np.diff(beats), 0.5)


# ---------------- music_rank ----------------

def test_silent_second_is_a_dropout(tmp_path):
    true = np.arange(0.5, 30.0, 0.5)
    y = kick_track(true, 31.0)
    y[12 * SR:13 * SR] = 0
    assert mr.dropouts(y, SR) == [12]
    f = tmp_path / "s.wav"
    sf.write(f, y, SR)
    r = mr.rank_file(f, 30)
    assert r["rejected"] and "drop-out" in r["reasons"][0]


def test_short_file_rejected(tmp_path):
    f = tmp_path / "short.wav"
    sf.write(f, kick_track(np.arange(0.5, 20, 0.5), 20.0), SR)
    r = mr.rank_file(f, 30)
    assert r["rejected"] and any("too short" in x for x in r["reasons"])


def test_tempo_wobble_flagged():
    beats = np.concatenate([np.arange(0, 10, 0.5), 10 + np.arange(0, 10, 0.55)])  # 120 -> 109 bpm
    assert mr.beat_stats(beats)["wobble"] > mr.WOBBLE_MAX
    assert mr.beat_stats(np.arange(0, 10, 0.5))["wobble"] < 0.001


def test_one_beat_stutter_flagged():
    beats = np.arange(0, 30, 0.5)
    beats[46:] += 0.1  # one interval +20 %: too short for the smoothed drift to see
    assert np.max(np.abs(np.diff(mr.smooth(beats)) - 0.5)) / 0.5 < mr.WOBBLE_MAX
    assert mr.beat_stats(beats)["wobble"] > mr.WOBBLE_MAX


def test_frame_jitter_is_not_wobble():
    rng = np.random.default_rng(5)
    beats = np.arange(0, 30, 0.5)
    jittered = np.round((beats + rng.uniform(-0.008, 0.008, len(beats))) / 0.016) * 0.016
    assert mr.beat_stats(jittered)["wobble"] < 0.02


def test_lift_found_at_percussion_step():
    rng = np.random.default_rng(2)
    perc = rng.standard_normal(30 * SR) * 0.05
    perc[13 * SR:] *= 6
    t, ratio = mr.lift_time(perc, SR)
    assert t is not None and abs(t - 13.0) <= 0.5 and ratio > mr.LIFT_RATIO
    flat_t, _ = mr.lift_time(rng.standard_normal(30 * SR) * 0.05, SR)
    assert flat_t is None


# ---------------- make_bed ----------------

def band_db(x, sr, lo, hi):
    spec = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(len(x), 1 / sr)
    return 10 * np.log10(spec[(f >= lo) & (f < hi)].sum() + 1e-12)


def test_lift_window_high_passes_and_has_no_clicks():
    rng = np.random.default_rng(3)
    sr = 32000
    y = rng.standard_normal(10 * sr) * 0.2
    grid = Grid(steady_grid()["beats"], 0, 4)
    a, b = mb.lift_window(grid, 3, sr)
    assert (a, b) == (round(grid.D(2, 2) * sr), round(grid.D(3) * sr))
    out = mb.apply_lift(y, sr, a, b)
    mid = slice(a + 2000, b - 2000)
    assert band_db(y[mid], sr, 20, 200) - band_db(out[mid], sr, 20, 200) > 20
    # outside the window nothing changes
    assert np.allclose(out[:a], y[:a]) and np.allclose(out[b:], y[b:])
    # edges: sample-to-sample jumps stay within the range of the source signal
    typical = np.percentile(np.abs(np.diff(y)), 99.9)
    for edge in (a, b):
        seg = out[edge - 600:edge + 600]
        assert np.max(np.abs(np.diff(seg))) <= typical * 1.2


def test_lift_edges_are_ramped_on_low_frequency_material():
    sr = 32000
    t = np.arange(10 * sr) / sr
    y = 0.5 * np.sin(2 * np.pi * 50 * t)  # almost nothing survives the 600 Hz high-pass
    a, b = int(3.005 * sr), int(5.005 * sr)  # edges on a sine peak, not a zero crossing
    out = mb.apply_lift(y, sr, a, b)
    step = np.max(np.abs(np.diff(y)))
    for edge in (a, b):
        assert np.max(np.abs(np.diff(out[edge - 50:edge + 50]))) < 3 * step


def test_lift_window_outside_bed_is_refused(tmp_path):
    p = write_project(tmp_path, duration=10)
    (p / "beats.json").write_text(json.dumps(steady_grid()))
    seed = tmp_path / "seed.wav"
    sf.write(seed, np.zeros(11 * SR, dtype=np.float32) + 0.01, SR)
    r = run_script("make_bed.py", seed, p, "--drop-bar", "40")
    assert r.returncode == 2


def test_bed_has_exact_duration_and_drop(tmp_path):
    p = write_project(tmp_path, duration=10)
    (p / "beats.json").write_text(json.dumps(steady_grid()))
    seed = tmp_path / "seed.wav"
    rng = np.random.default_rng(4)
    sf.write(seed, (rng.standard_normal(int(11.3 * SR)) * 0.2).astype(np.float32), SR)
    r = run_script("make_bed.py", seed, p, "--drop-bar", "3")
    assert r.returncode == 0, r.stderr
    y, sr = sf.read(p / "assets" / "audio" / "bgm.wav")
    assert len(y) == 10 * sr
    short = tmp_path / "short.wav"
    sf.write(short, np.zeros(9 * SR, dtype=np.float32), SR)
    assert run_script("make_bed.py", short, p).returncode == 2


def test_beat_grid_main_writes_beats_json(tmp_path):
    p = write_project(tmp_path, duration=20)
    true = np.arange(0.5, 21.0, 0.5)
    f = tmp_path / "clicks.wav"
    sf.write(f, kick_track(true, 21.0), SR)
    r = run_script("beat_grid.py", f, p)
    assert r.returncode == 0, r.stderr
    g = json.loads((p / "beats.json").read_text())
    assert set(g) == {"beats", "downbeat_phase", "downbeats"}
    assert g["downbeats"] == [round(b, 3) for b in g["beats"][g["downbeat_phase"]::4]]
    assert g["beats"][-1] >= 20 + 16 * 0.49  # four bars past the end
    assert abs(np.median(np.diff(g["beats"])) - 0.5) < 0.005
    assert min(abs(d - 2.5) for d in g["downbeats"]) < 0.1  # the accented kicks: 0.5, 2.5, 4.5 ...


def test_music_rank_main_orders_and_exits_1_when_all_rejected(tmp_path):
    good = tmp_path / "good.wav"
    sf.write(good, kick_track(np.arange(0.5, 21.0, 0.5), 21.0), SR)
    bad = tmp_path / "bad.wav"
    y = kick_track(np.arange(0.5, 21.0, 0.5), 21.0)
    y[5 * SR:6 * SR] = 0
    sf.write(bad, y, SR)
    out = tmp_path / "rank.json"
    r = run_script("music_rank.py", "--duration", "20", "--json", out, bad, good)
    assert r.returncode == 0, r.stderr
    ranked = json.loads(out.read_text())
    assert [Path(x["file"]).name for x in ranked] == ["good.wav", "bad.wav"] and ranked[1]["rejected"]
    assert run_script("music_rank.py", "--duration", "20", bad).returncode == 1
    junk = tmp_path / "junk.wav"
    junk.write_bytes(b"not audio")
    r = run_script("music_rank.py", "--duration", "20", junk)
    assert r.returncode == 2 and "Traceback" not in r.stderr


def test_beat_grid_and_make_bed_refuse_unreadable_audio(tmp_path):
    p = write_project(tmp_path, duration=10)
    (p / "beats.json").write_text(json.dumps(steady_grid()))
    junk = tmp_path / "junk.wav"
    junk.write_bytes(b"not audio")
    for script in ("beat_grid.py", "make_bed.py"):
        r = run_script(script, junk, p)
        assert r.returncode == 2 and "Traceback" not in r.stderr, (script, r.stderr)


def test_riser_tail_ends_on_the_drop():
    sr = 1000
    y = np.zeros(10 * sr)
    riser = np.linspace(0.1, 1.0, 2 * sr)
    out = mb.add_riser(y.copy(), sr, riser, 5.0, 0.5)
    nz = np.nonzero(out)[0]
    assert nz[0] == 3 * sr and nz[-1] == 5 * sr - 1 and out[5 * sr - 1] == 0.5


def test_long_riser_is_cut_with_a_ramp_and_never_past_the_bed():
    sr = 1000
    riser = np.ones(4 * sr)
    out = mb.add_riser(np.zeros(10 * sr), sr, riser, 1.0, 1.0)  # 4 s riser, 1 s before the drop
    assert out[0] == 0.0 and np.max(np.abs(np.diff(out[:sr]))) < 0.1
    assert np.allclose(out[100:sr], 1.0) and not out[sr:].any()
    near_end = mb.add_riser(np.zeros(10 * sr), sr, riser, 11.0, 1.0)  # drop past the bed end
    assert len(near_end) == 10 * sr and near_end[-1] == 1.0


def test_downbeat_survives_beats_added_in_front():
    heard = np.arange(1.5, 20.0, 0.5)  # the music starts at 1.5 s, on an accented beat
    strengths = [1.0 if i % 4 == 0 else 0.3 for i in range(len(heard))]
    beats, phase = bg.full_grid(heard, strengths, 20.0, 4)
    assert beats[0] < 1.0  # beats were added in front
    assert beats[phase] == 1.5
