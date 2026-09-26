"""Shared helpers: project.json, the beat grid and the D()/E() beat addressing.

Beat addressing (one signature everywhere, see references/pipeline.md):
  D(bar, beat=0)  time of `beat` (0-based) inside `bar`. Bar 0 starts on the first
                  downbeat; negative bars are pickup beats before it.
  E(bar, beat=0)  the "and": halfway between D(bar, beat) and the next beat.
"""
import json
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


def die(msg, code=2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def load_project(project_dir):
    path = Path(project_dir) / "project.json"
    if not path.is_file():
        die(f"{path} not found (is this a project folder made by new_project.py?)")
    data = {**PROJECT_DEFAULTS, **json.loads(path.read_text())}
    data["duration"] = float(data["duration"])
    bad = [s for s in data["stores"] if s not in KNOWN_STORES]
    if bad or not data["stores"]:
        die(f"project.json stores must be a non-empty subset of {list(KNOWN_STORES)}, got {data['stores']}")
    return data


class Grid:
    def __init__(self, beats, downbeat_phase, beats_per_bar=4):
        self.beats = [float(b) for b in beats]
        self.first = int(downbeat_phase)
        self.bpb = int(beats_per_bar)

    @classmethod
    def load(cls, path, beats_per_bar=4):
        g = json.loads(Path(path).read_text())
        return cls(g["beats"], g["downbeat_phase"], beats_per_bar)

    def _index(self, bar, beat):
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
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def decode_audio(path, sr, mono=True):
    """Decode any audio/video file to float32 numpy samples with ffmpeg."""
    import numpy as np
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-acodec", "pcm_f32le", "-ar", str(sr)]
    if mono:
        cmd += ["-ac", "1"]
    cmd.append("-")
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()
