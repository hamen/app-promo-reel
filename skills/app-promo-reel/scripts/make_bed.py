#!/usr/bin/env python3
"""Cut the chosen MusicGen seed into the music bed: exact duration, short fade-in, fade-out,
and an optional synthetic lift before the drop.

--drop-bar k   high-passes the half bar before bar k: samples [D(k-1, bpb/2), D(k)), with
               equal-gain ramps at both edges, so the full band "drops" back in on D(k).
--riser FILE   places the tail of FILE so it ends exactly on D(k) (needs --drop-bar).

Usage: make_bed.py <seed.wav> <project_dir> [--drop-bar k] [--riser riser.mp3] [--riser-gain 0.5]
Writes <project_dir>/assets/audio/bgm.wav.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import scipy.signal as ss
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Grid, decode_audio, die, load_project  # noqa: E402

RAMP = 0.012
FADE_IN = 0.010
FADE_OUT = 0.8
LIFT_HP = 600.0


def lift_window(grid, drop_bar, sr):
    """Sample range [start, end) of the synthetic lift before `drop_bar`."""
    start = grid.D(drop_bar - 1, grid.bpb // 2)
    end = grid.D(drop_bar)
    return int(round(start * sr)), int(round(end * sr))


def apply_lift(y, sr, a, b, hp=LIFT_HP, ramp=RAMP):
    """High-pass y[a:b] (zero-phase) with equal-gain crossfades of `ramp` s at both edges."""
    if a < 0 or b > len(y) or b - a < 4 * int(ramp * sr):
        raise ValueError(f"lift window {a / sr:.3f}-{b / sr:.3f}s is not fully inside the bed")
    sos = ss.butter(4, hp, btype="high", fs=sr, output="sos")
    filt = ss.sosfiltfilt(sos, y, axis=0)
    w = np.zeros(len(y))
    w[a:b] = 1.0
    n = int(ramp * sr)
    w[a:a + n] = np.linspace(0, 1, n)
    w[b - n:b] = np.linspace(1, 0, n)
    if y.ndim == 2:
        w = w[:, None]
    return (1 - w) * y + w * filt


def fades(y, sr):
    n_in, n_out = int(FADE_IN * sr), int(FADE_OUT * sr)
    env = np.ones(len(y))
    env[:n_in] = np.linspace(0, 1, n_in)
    env[-n_out:] = np.linspace(1, 0, n_out)
    return y * (env[:, None] if y.ndim == 2 else env)


def add_riser(y, sr, riser, end_t, gain):
    end = int(round(end_t * sr))
    start = end - len(riser)
    r = riser[max(0, -start):] * gain
    start = max(0, start)
    if y.ndim == 2:
        r = r[:, None]
    y[start:start + len(r)] += r
    return y


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("seed")
    ap.add_argument("project_dir")
    ap.add_argument("--drop-bar", type=int)
    ap.add_argument("--riser")
    ap.add_argument("--riser-gain", type=float, default=0.5)
    a = ap.parse_args()
    pdir = Path(a.project_dir)
    project = load_project(pdir)
    y, sr = sf.read(a.seed, always_2d=False)
    n = int(round(project["duration"] * sr))
    if len(y) < n:
        die(f"{a.seed} is {len(y) / sr:.2f}s, shorter than the {project['duration']:g}s video")
    y = y[:n].astype(np.float64)
    if a.drop_bar is not None:
        grid = Grid.load(pdir / "beats.json", project["beats_per_bar"])
        try:
            lo, hi = lift_window(grid, a.drop_bar, sr)
            y = apply_lift(y, sr, lo, hi)
        except ValueError as e:
            die(str(e))
        print(f"synthetic lift {lo / sr:.3f}-{hi / sr:.3f}s, drop on {grid.D(a.drop_bar):.3f}s")
        if a.riser:
            y = add_riser(y, sr, decode_audio(a.riser, sr), grid.D(a.drop_bar), a.riser_gain)
    elif a.riser:
        die("--riser needs --drop-bar")
    y = fades(y, sr)
    peak = np.max(np.abs(y))
    if peak > 0.99:
        y *= 0.99 / peak
    out = pdir / "assets" / "audio" / "bgm.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out, y.astype(np.float32), sr, subtype="PCM_16")
    print(f"wrote {out} ({len(y) / sr:.3f}s)")


if __name__ == "__main__":
    main()
