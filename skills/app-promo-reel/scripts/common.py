"""Shared helpers: project.json, the beat grid and the D()/E() beat addressing.

Beat addressing (one signature everywhere, see references/pipeline.md):
  D(bar, beat=0)  time of `beat` (0-based) inside `bar`. Bar 0 starts on the first
                  downbeat; negative bars are pickup beats before it.
  E(bar, beat=0)  the "and": halfway between D(bar, beat) and the next beat.
"""
import json
import math
import subprocess
import sys
from pathlib import Path

PROJECT_DEFAULTS = {
    "duration": 30.0,
    "fps": 30,
    "width": 1080,
    "height": 1920,
    "beats_per_bar": 4,
    "stores": ["app_store", "google_play"],
}
KNOWN_STORES = ("app_store", "google_play")


def is_number(v):
    """A finite JSON number: int or float, not bool (True is an int in Python), not NaN/Infinity
    (Python's json accepts both), not an int too large for a float (a 400-digit JSON integer)."""
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return False
    try:
        return math.isfinite(v)
    except OverflowError:
        return False


def die(msg, code=2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def read_json(path, kind=dict):
    """Parse a JSON file the agent edits by hand; a missing file, bad JSON or the wrong top-level
    type exits 2 with the file name instead of a traceback."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        die(f"cannot read {path}: {e}")
    if not isinstance(data, kind):
        die(f"{path} must hold a JSON {'object' if kind is dict else 'array'}")
    return data


def load_project(project_dir):
    path = Path(project_dir) / "project.json"
    if not path.is_file():
        die(f"{path} not found (is this a project folder made by new_project.py?)")
    data = {**PROJECT_DEFAULTS, **read_json(path)}
    missing = [k for k in ("app", "variant") if not data.get(k)]
    if missing:
        die(f"{path} has no {' / '.join(missing)}")
    # JSON numbers only: a quoted "30" or true is a mistake to report, not to coerce
    bad = [k for k in ("duration", "fps", "beats_per_bar") if not is_number(data[k])]
    if bad:
        die(f"{path}: {', '.join(bad)} must be JSON numbers, got {', '.join(repr(data[k]) for k in bad)}")
    if data["beats_per_bar"] != int(data["beats_per_bar"]):
        die(f"{path}: beats_per_bar must be a whole number, got {data['beats_per_bar']}")
    data["duration"] = float(data["duration"])
    data["beats_per_bar"] = int(data["beats_per_bar"])  # fps stays as given: 29.97 is a real rate
    if data["duration"] <= 1 or data["fps"] <= 0 or data["beats_per_bar"] <= 0:
        die(f"{path}: duration must be above 1 s (the bed fades take 0.8 s), fps and beats_per_bar above 0")
    stores = data["stores"]
    bad = [s for s in stores if s not in KNOWN_STORES] if isinstance(stores, list) else [stores]
    if bad or not stores:
        die(f"project.json stores must be a non-empty subset of {list(KNOWN_STORES)}, got {data['stores']}")
    return data


class Grid:
    def __init__(self, beats, downbeat_phase, beats_per_bar=4):
        self.beats = [float(b) for b in beats]
        self.first = int(downbeat_phase)
        self.bpb = int(beats_per_bar)

    @classmethod
    def load(cls, path, beats_per_bar=4):
        g = read_json(path)
        phase = g.get("downbeat_phase")

        def bad_phase(top):
            die(f"{path}: downbeat_phase must be a whole number from 0 to {top} (below beats_per_bar "
                f"and inside the beat list), got {phase!r}")
        # checked before Grid() converts it: int(inf) from a JSON 1e999 raises OverflowError
        if not isinstance(phase, int) or isinstance(phase, bool):
            bad_phase(int(beats_per_bar) - 1)
        if not isinstance(g.get("beats"), list):
            die(f"{path} is not a beat grid from beat_grid.py (beats must be a JSON array, got {g.get('beats')!r})")
        try:
            grid = cls(g["beats"], phase, beats_per_bar)
        except (TypeError, ValueError, OverflowError) as e:
            die(f"{path} is not a beat grid from beat_grid.py ({e!r})")
        if not 0 <= phase < min(grid.bpb, len(grid.beats)):
            bad_phase(min(grid.bpb, len(grid.beats)) - 1)
        return grid

    def _index(self, bar, beat):
        if not 0 <= int(beat) < self.bpb:
            raise ValueError(f"D({bar}, {beat}): beat must be 0-{self.bpb - 1} (beats_per_bar {self.bpb})")
        i = self.first + int(bar) * self.bpb + int(beat)
        if not 0 <= i < len(self.beats):
            raise ValueError(f"D({bar}, {beat}) is outside the beat grid ({len(self.beats)} beats, "
                             f"first downbeat at index {self.first})")
        return i

    def D(self, bar, beat=0):
        return self.beats[self._index(bar, beat)]

    def E(self, bar, beat=0):
        i = self._index(bar, beat)
        if i + 1 >= len(self.beats):
            raise ValueError(f"E({bar}, {beat}) needs the beat after it, which is outside the grid")
        return (self.beats[i] + self.beats[i + 1]) / 2


def media_duration(path):
    """Duration in seconds of an audio or video file, read with ffprobe."""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True)
    if r.returncode:
        die(f"ffprobe could not read {path}:\n{r.stderr[-400:]}")
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        die(f"ffprobe gives no duration for {path}")


def decode_audio(path, sr, mono=True):
    """Decode any audio/video file to float32 numpy samples with ffmpeg."""
    import numpy as np
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-f", "f32le", "-acodec", "pcm_f32le", "-ar", str(sr)]
    if mono:
        cmd += ["-ac", "1"]
    cmd.append("-")
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode:
        die(f"ffmpeg could not decode {path}:\n{r.stderr.decode(errors='replace')[-600:]}")
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def attack_index(snd, rel=0.05):
    """First sample louder than `rel` of the peak (about -26 dB): where the sound is heard."""
    import numpy as np
    peak = float(np.max(np.abs(snd))) if len(snd) else 0.0
    return int(np.argmax(np.abs(snd) > rel * peak)) if peak > 0 else 0


def attack_seconds(path, sr=48000):
    """Seconds of near-silence before a sound file's attack."""
    return attack_index(decode_audio(path, sr)) / sr
