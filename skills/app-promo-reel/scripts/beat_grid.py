#!/usr/bin/env python3
"""Beat grid for a music bed: librosa beat_track, then a kick-band phase check, a per-beat
refine to the kick (or hi-hat), local linear smoothing and the downbeat phase.

Writes beats.json: {"beats": [...], "downbeat_phase": p, "downbeats": [...]}.
All band filters are zero-phase (sosfiltfilt) so they do not shift the kick times.

Usage: beat_grid.py <audio.wav> <project_dir>      (writes <project_dir>/beats.json)
"""
import json
import sys
from pathlib import Path

import numpy as np
import scipy.signal as ss

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import die, load_project  # noqa: E402

SR = 32000
HOP = 256
REFINE_WINDOW = 0.040  # a refined beat never moves more than this from its input time


def band_envelope(y, sr, lo, hi=None, hop=HOP):
    """Onset-strength envelope of one band (zero-phase filter). Returns (env, times)."""
    import librosa
    if hi:
        sos = ss.butter(4, [lo, hi], btype="band", fs=sr, output="sos")
    else:
        sos = ss.butter(4, lo, btype="high", fs=sr, output="sos")
    yy = ss.sosfiltfilt(sos, y).astype("float32")
    env = librosa.onset.onset_strength(y=yy, sr=sr, hop_length=hop)
    return env, librosa.frames_to_time(np.arange(len(env)), sr=sr, hop_length=hop)


def peak_near(env, t_env, t, w=0.035):
    m = (t_env > t - w) & (t_env < t + w)
    return float(env[m].max()) if m.any() else 0.0


def phase_check(beats, kick, t_env):
    """Shift the grid by half a beat when the kick is stronger off the tracked beats.
    Returns (beats, shifted, on_strength)."""
    beats = np.asarray(beats, dtype=float)
    iv = float(np.median(np.diff(beats)))
    on = float(np.mean([peak_near(kick, t_env, b) for b in beats]))
    off_t = [b + iv / 2 for b in beats if b + iv / 2 < t_env[-1]]
    off = float(np.mean([peak_near(kick, t_env, b) for b in off_t])) if off_t else 0.0
    if off > on * 1.2:
        return beats + iv / 2, True, off
    return beats, False, on


def refine(beats, kick, hi, t_env, on_strength, window=REFINE_WINDOW):
    """Move each beat to the local kick peak, or the hi-hat peak when the kick is weak.
    A beat never moves more than `window`; when no peak is found it stays put."""
    out = []
    for b in beats:
        m = (t_env > b - window) & (t_env < b + window)
        if not m.any():
            out.append(b)
            continue
        env = kick if kick[m].max() > 0.5 * on_strength else hi
        seg = env[m]
        k = int(np.argmax(seg))
        # keep the beat when there is no real peak inside the window (flat, or rising past an edge)
        if seg[k] <= 1e-9 or k in (0, len(seg) - 1):
            out.append(b)
            continue
        t = float(t_env[m][k])
        out.append(t if abs(t - b) <= window else b)
    return np.array(out)


def smooth(beats, half=4):
    """Local linear fit over a sliding window: removes frame jitter, follows slow drift."""
    beats = np.asarray(beats, dtype=float)
    sm = []
    for i in range(len(beats)):
        lo, hi = max(0, i - half), min(len(beats), i + half + 1)
        idx = np.arange(lo, hi)
        sm.append(np.polyval(np.polyfit(idx, beats[lo:hi], 1), i))
    return np.array(sm)


def extend(beats, duration, lead=0.2):
    """Extrapolate whole beats so the grid covers 0-duration (and one beat past the end)."""
    beats = list(beats)
    iv = float(np.median(np.diff(beats)))
    while beats[-1] < duration:
        beats.append(beats[-1] + iv)
    while beats[0] - iv > lead:
        beats.insert(0, beats[0] - iv)
    return np.array(beats)


def downbeat_phase(strengths, bpb=4):
    """Index (0..bpb-1) of the beat position with the strongest mean accent."""
    s = np.asarray(strengths, dtype=float)
    return int(np.argmax([s[p::bpb].mean() for p in range(bpb)]))


def analyse(y, sr, duration, bpb=4):
    import librosa
    _, beats = librosa.beat.beat_track(y=y, sr=sr, units="time", hop_length=HOP)
    if len(beats) < 8:
        die(f"beat_track found only {len(beats)} beats; pick another seed")
    kick, t_env = band_envelope(y, sr, 40, 160)
    hi, _ = band_envelope(y, sr, 2500)
    beats, shifted, on = phase_check(beats, kick, t_env)
    beats = smooth(refine(beats, kick, hi, t_env, on))
    beats = extend(beats, duration)
    rms = lambda b: float(np.sqrt(np.mean(y[int(b * sr):int(b * sr) + 2000] ** 2))) if b * sr < len(y) else 0.0
    strengths = [peak_near(kick, t_env, b) + 25 * rms(b) for b in beats]
    phase = downbeat_phase(strengths, bpb)
    iv = np.diff(beats)
    print(f"half-beat shift: {'yes' if shifted else 'no'}; interval {iv.mean():.4f}s sd {iv.std() * 1000:.2f}ms; "
          f"first beat {beats[0]:.3f}; downbeat phase {phase}; {len(beats)} beats")
    return beats, phase


def main():
    if len(sys.argv) != 3:
        die(__doc__.strip().splitlines()[-1])
    audio, project_dir = sys.argv[1], Path(sys.argv[2])
    project = load_project(project_dir)
    import librosa
    y, sr = librosa.load(audio, sr=SR, mono=True)
    bpb = project["beats_per_bar"]
    beats, phase = analyse(y, sr, project["duration"], bpb)
    doc = {"beats": [round(float(b), 4) for b in beats], "downbeat_phase": phase,
           "downbeats": [round(float(b), 3) for b in beats[phase::bpb]]}
    (project_dir / "beats.json").write_text(json.dumps(doc, indent=0) + "\n")
    print("downbeats:", [round(float(b), 2) for b in beats[phase::bpb]])


if __name__ == "__main__":
    main()
