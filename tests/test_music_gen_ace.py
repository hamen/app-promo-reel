"""music_gen_ace.py against a fake `acestep` package: no ACE-Step, no GPU, no network.

The fake records every call in calls.jsonl and init.json next to it, and behaves as fake.json says:
{"init": "ok" | "fail" | "oom-raise" | "oom-text",
 "gen": {"<seed>": "ok" | "raise" | "oom-class" | "oom-runtime" | "oom-result" | "no-audio"},
 "seconds": {"<seed>": length of the WAV it writes (default: the duration it was asked for)}}
"""
import fcntl
import json
import sys

import pytest
import soundfile as sf

import music_gen_ace

INFERENCE = '''
import json, wave
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "fake.json").read_text())


class OutOfMemoryError(RuntimeError):
    pass


class GenerationParams:
    def __init__(self, **kw):
        self.kw = kw


class GenerationConfig:
    def __init__(self, **kw):
        self.kw = kw


def generate_music(dit_handler, llm_handler, params, config, save_dir=None):
    seed = params.kw["seed"]
    with open(ROOT / "calls.jsonl", "a") as f:
        f.write(json.dumps({"params": params.kw, "config": config.kw, "llm": llm_handler,
                            "save_dir": save_dir}) + "\\n")
    mode = CFG.get("gen", {}).get(str(seed), "ok")
    if mode == "raise":
        raise ValueError("boom")
    if mode == "oom-class":
        raise OutOfMemoryError("CUDA error")
    if mode == "oom-runtime":
        raise RuntimeError("CUDA out of memory. Tried to allocate 20.00 MiB")
    if mode == "oom-result":
        return SimpleNamespace(success=False, error="CUDA out of memory. Tried to allocate 24.00 MiB", audios=[])
    if mode == "no-audio":
        return SimpleNamespace(success=True, error=None, audios=[])
    seconds = CFG.get("seconds", {}).get(str(seed), params.kw["duration"])
    path = Path(save_dir) / f"{seed}-out.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(int(seed).to_bytes(2, "little", signed=True) * int(seconds * 8000))
    return SimpleNamespace(success=True, error=None, audios=[{"path": str(path)}])
'''

HANDLER = '''
import json
from .inference import CFG, ROOT, OutOfMemoryError


class AceStepHandler:
    def initialize_service(self, project_root, config_path, device="auto", **kw):
        (ROOT / "init.json").write_text(json.dumps({"project_root": project_root, "config_path": config_path,
                                                    "device": device}))
        mode = CFG.get("init", "ok")
        if mode == "oom-raise":
            raise OutOfMemoryError("CUDA error")
        if mode == "oom-text":
            return "CUDA out of memory. Tried to allocate 20.00 MiB", False
        if mode == "fail":
            return "no model files", False
        return "[OK] Model initialized", True
'''


@pytest.fixture
def ace(tmp_path, monkeypatch):
    """A fake ACE-Step clone; returns a function that writes fake.json and runs main()."""
    root = tmp_path / "ace"
    (root / "acestep").mkdir(parents=True)
    (root / "acestep" / "__init__.py").write_text("")
    (root / "acestep" / "inference.py").write_text(INFERENCE)
    (root / "acestep" / "handler.py").write_text(HANDLER)
    monkeypatch.setenv("ACESTEP_DIR", str(root))
    monkeypatch.setattr(music_gen_ace, "LOCK", tmp_path / "lock")  # never the real lock
    monkeypatch.setattr(sys, "path", list(sys.path))
    for name in [m for m in sys.modules if m == "acestep" or m.startswith("acestep.")]:
        monkeypatch.delitem(sys.modules, name)
    out = tmp_path / "work"

    def run(cfg=None, *args, seeds="5,17", duration="30"):
        (root / "fake.json").write_text(json.dumps(cfg or {}))
        for name in [m for m in sys.modules if m == "acestep" or m.startswith("acestep.")]:
            del sys.modules[name]
        music_gen_ace.main(["--prompt", "bright synth pop", "--bpm", "120", "--duration", duration,
                            "--seeds", seeds, "--out", str(out), *args])

    run.root, run.out = root, out
    return run


def calls(ace):
    path = ace.root / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def leftovers(out):
    return sorted(p.name for p in out.iterdir() if p.name.startswith("."))


def test_without_acestep_dir_it_says_how_to_install(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(music_gen_ace, "LOCK", tmp_path / "lock")
    with pytest.raises(SystemExit) as e:
        music_gen_ace.main(["--prompt", "x", "--bpm", "120", "--duration", "30", "--seeds", "1",
                            "--out", str(tmp_path / "o")])
    assert e.value.code == 2 and "ACESTEP_DIR is not set" in capsys.readouterr().err


def test_each_seed_gets_its_own_file_and_its_own_seed(ace, capsys):
    ace()
    for seed in (5, 17):
        y, sr = sf.read(ace.out / f"bgm_{seed}.wav", dtype="int16")
        assert sr == 8000 and len(y) == 40 * 8000 and set(y.tolist()) == {seed}
    assert leftovers(ace.out) == []
    got = calls(ace)
    assert [c["params"]["seed"] for c in got] == [5, 17]
    assert [c["config"]["seeds"] for c in got] == [[5], [17]]
    for c in got:
        assert c["llm"] is None
        assert c["params"] == {**c["params"], "task_type": "text2music", "caption": "bright synth pop",
                               "lyrics": "[Instrumental]", "instrumental": True, "bpm": 120, "duration": 40.0,
                               "timesignature": "4", "thinking": False, "use_cot_caption": False,
                               "use_cot_metas": False, "use_cot_language": False}
        assert c["config"] == {"batch_size": 1, "audio_format": "wav", "use_random_seed": False,
                               "seeds": c["config"]["seeds"]}
    init = json.loads((ace.root / "init.json").read_text())
    assert init == {"project_root": str(ace.root), "config_path": "acestep-v15-turbo", "device": "auto"}


def test_device_and_meter_reach_acestep(ace):
    ace(None, "--device", "cpu", "--beats-per-bar", "3", seeds="5")
    assert json.loads((ace.root / "init.json").read_text())["device"] == "cpu"
    assert calls(ace)[0]["params"]["timesignature"] == "3"


def test_a_seed_shorter_than_the_reel_gets_no_file(ace, capsys):
    # 25 s is shorter than the reel; 35 s is shorter than asked (40 s) but covers the reel
    with pytest.raises(SystemExit) as e:
        ace({"seconds": {"5": 35, "17": 25}})
    assert e.value.code == 2
    assert (ace.out / "bgm_5.wav").exists() and not (ace.out / "bgm_17.wav").exists()
    assert "seed(s) 17 came out shorter than 30s" in capsys.readouterr().err
    assert leftovers(ace.out) == []


@pytest.mark.parametrize("mode", ["raise", "no-audio"])
def test_a_failed_generation_exits_2_and_leaves_nothing(ace, capsys, mode):
    ace.out.mkdir()
    (ace.out / "bgm_5.wav").write_bytes(b"old seed")  # from an earlier run: must not survive
    with pytest.raises(SystemExit) as e:
        ace({"gen": {"5": mode}})
    assert e.value.code == 2 and "seed 5" in capsys.readouterr().err
    assert list(ace.out.iterdir()) == []


@pytest.mark.parametrize("cfg", [{"gen": {"5": "oom-class"}}, {"gen": {"5": "oom-runtime"}},
                                 {"gen": {"5": "oom-result"}}, {"init": "oom-raise"}, {"init": "oom-text"}])
def test_gpu_out_of_memory_exits_3_with_the_cpu_hint(ace, capsys, cfg):
    with pytest.raises(SystemExit) as e:
        ace(cfg)
    assert e.value.code == 3 and "run again with --device cpu" in capsys.readouterr().err
    assert list(ace.out.iterdir()) == []


def test_a_model_that_cannot_load_exits_2(ace, capsys):
    with pytest.raises(SystemExit) as e:
        ace({"init": "fail"})
    assert e.value.code == 2 and "no model files" in capsys.readouterr().err


def test_a_second_generator_exits_2_and_touches_nothing(ace, capsys):
    ace.out.mkdir()
    (ace.out / "bgm_5.wav").write_bytes(b"a live seed of the running generator")
    with open(music_gen_ace.LOCK, "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SystemExit) as e:
            ace()
    assert e.value.code == 2 and "another music generator is running" in capsys.readouterr().err
    assert (ace.out / "bgm_5.wav").read_bytes() == b"a live seed of the running generator"
    assert calls(ace) == []


def test_the_lock_is_music_gen_s_lock():
    import music_gen
    assert music_gen_ace.LOCK == music_gen.LOCK


@pytest.mark.parametrize("args", [["--bpm", "29"], ["--bpm", "301"], ["--duration", "0"],
                                  ["--duration", "nan"], ["--duration", "591"]])
def test_values_acestep_cannot_make_exit_2(ace, args):
    argv = {"--bpm": "120", "--duration": "30", **dict(zip(args[::2], args[1::2]))}
    with pytest.raises(SystemExit) as e:
        music_gen_ace.main(["--prompt", "x", "--seeds", "1", "--out", str(ace.out),
                            *[x for kv in argv.items() for x in kv]])
    assert e.value.code == 2 and calls(ace) == []
