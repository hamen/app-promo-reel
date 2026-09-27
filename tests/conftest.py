import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "app-promo-reel" / "scripts"
TEMPLATE = SCRIPTS.parent / "template"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))


def click(sr, dur=0.004, freq=3000.0, amp=0.8):
    t = np.arange(int(dur * sr)) / sr
    return amp * np.sin(2 * np.pi * freq * t) * np.exp(-t / (dur / 4))


def write_project(tmp_path, duration=30, stores=("app_store", "google_play"), bpb=4):
    p = tmp_path / "proj"
    p.mkdir(exist_ok=True)
    (p / "project.json").write_text(json.dumps({"app": "demo", "variant": "a", "duration": duration, "fps": 30,
                                                "beats_per_bar": bpb, "stores": list(stores)}))
    return p


def steady_grid(first=0.5, iv=0.5, n=70, phase=0):
    return {"beats": [round(first + i * iv, 4) for i in range(n)], "downbeat_phase": phase}


@pytest.fixture(autouse=True)
def no_git_env(monkeypatch):
    """bin/ci runs inside the pre-push hook, where git exports GIT_DIR and friends. Tests that
    run git (or scripts that do) must not act on this repository."""
    for k in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(k)


@pytest.fixture(autouse=True)
def no_user_sfx(monkeypatch):
    """The README has users export SFX_DIR. Scaffold calls that inherit it would copy the user's
    sounds into test projects (or die on a stale path); tests that need it set it themselves."""
    monkeypatch.delenv("SFX_DIR", raising=False)


@pytest.fixture
def project(tmp_path):
    p = write_project(tmp_path)
    (p / "beats.json").write_text(json.dumps(steady_grid()))
    return p


def run_script(name, *args, env=None):
    return subprocess.run([sys.executable, str(SCRIPTS / name), *map(str, args)], capture_output=True, text=True,
                          env=env)


def tone_file(path, seconds=0.3, sr=44100):
    t = np.arange(int(seconds * sr)) / sr
    sf.write(path, 0.3 * np.sin(2 * np.pi * 440 * t), sr)
    return path
