#!/usr/bin/env python3
"""Finish a rendered reel: loudness, checks, contact sheet, versioned output.

1. Two-pass loudnorm (I=-14 LUFS, TP=-2 dBTP) on the 48 kHz WAV of the raw render.
2. A/V check before the AAC encode: the cross-correlation lag between the WAV before and
   after loudnorm must be < 5 ms.
3. Mux: video stream copied (-c:v copy), audio AAC. Output name
   renders/<app>-<variant>-v<N>.mp4, N = one more than the highest existing version.
   An existing file is never overwritten.
4. Picture check: codec, size, frame count and duration of the video stream are unchanged,
   and the duration matches project.json within one frame.
5. Sync report: for each cue in cues.realized.json (the cues build.py actually mixed) with
   "sync": true, the strongest onset in the final audio within +-150 ms. A delta over one
   frame, or no onset in the window, is flagged.
6. Contact sheet of frames from the final MP4.

Any failed check exits 1 and renames the output to ...-v<N>-failed.mp4.

Usage: finish.py <project_dir> <raw_render.mp4> [--frames 1.0,5.2,...]
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import scipy.signal as ss

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import decode_audio, die, load_project  # noqa: E402

SR = 48000
TARGET_I, TARGET_TP, TARGET_LRA = -14.0, -2.0, 11.0
MAX_LAG = 0.005
SYNC_WINDOW = 0.150
ONSET_HOP = 0.001
ONSET_WIN = 0.004
ONSET_MIN_DB = 3.0


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def next_version_path(renders, stem):
    """renders/<stem>-v<N>.mp4 with N = max existing (incl. -failed) + 1."""
    pat = re.compile(re.escape(stem) + r"-v(\d+)(?:-failed)?\.mp4$")
    nums = [int(m.group(1)) for p in renders.glob(f"{stem}-v*.mp4") if (m := pat.match(p.name))]
    return renders / f"{stem}-v{max(nums, default=0) + 1}.mp4"


def video_info(path):
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
               "stream=codec_name,width,height,nb_read_packets,duration", "-of", "json", str(path)]).stdout
    s = json.loads(out)["streams"][0]
    return {"codec": s["codec_name"], "width": s["width"], "height": s["height"],
            "frames": int(s["nb_read_packets"]), "duration": round(float(s.get("duration", 0)), 3)}


LOUDNORM = f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}"


def measure(path):
    """loudnorm analysis pass: input_i, input_tp, input_lra, input_thresh, target_offset."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
                        LOUDNORM + ":print_format=json", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr)
    if p.returncode or not m:
        die("loudnorm analysis failed:\n" + p.stderr[-800:])
    return json.loads(m.group(0))


def loudnorm(src_wav, dst_wav):
    base = LOUDNORM
    s = measure(src_wav)
    af = (f"{base}:measured_I={s['input_i']}:measured_TP={s['input_tp']}:measured_LRA={s['input_lra']}"
          f":measured_thresh={s['input_thresh']}:offset={s['target_offset']}:linear=true")
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src_wav), "-af", af, "-ar", str(SR), "-c:a", "pcm_s16le",
         str(dst_wav)])
    return s


def lag_seconds(a, b, sr=SR, max_lag=0.1):
    """Lag of b against a (seconds), searched within +-max_lag."""
    n = min(len(a), len(b))
    a, b = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
    c = ss.correlate(b, a, mode="full", method="fft")
    mid = n - 1
    k = int(max_lag * sr)
    seg = c[mid - k:mid + k + 1]
    return (int(np.argmax(seg)) - k) / sr


def onset_curve(y, sr=SR):
    """Rise in log energy between consecutive short frames (dB). Returns (curve, times)."""
    hop, win = int(ONSET_HOP * sr), int(ONSET_WIN * sr)
    n = (len(y) - win) // hop
    idx = np.arange(n)[:, None] * hop + np.arange(win)[None, :]
    e = 10 * np.log10(np.mean(y[idx] ** 2, axis=1) + 1e-10)
    rise = np.maximum(0, e[1:] - e[:-1])
    # compare each frame with the one 2 frames earlier as well, for smeared attacks
    rise2 = np.maximum(0, e[2:] - e[:-2])
    curve = np.maximum(rise[1:], rise2)
    t = (np.arange(len(curve)) + 2) * hop / sr
    return curve, t


def sync_report(y, realized, fps, sr=SR):
    curve, t = onset_curve(y, sr)
    frame = 1.0 / fps
    rows = []
    for cue in realized:
        if not cue.get("sync", True):
            continue
        m = (t >= cue["time"] - SYNC_WINDOW) & (t <= cue["time"] + SYNC_WINDOW)
        if not m.any() or curve[m].max() < ONSET_MIN_DB:
            rows.append({**cue, "onset": None, "delta_ms": None, "flag": "no onset"})
            continue
        onset = float(t[m][np.argmax(curve[m])])
        delta = onset - cue["time"]
        rows.append({**cue, "onset": round(onset, 4), "delta_ms": round(delta * 1000, 1),
                     "flag": "off by more than one frame" if abs(delta) > frame else None})
    return rows


def contact_sheet(mp4, times, dest):
    from PIL import Image
    tmp = Path(tempfile.mkdtemp(prefix="reel-sheet-"))
    try:
        thumbs = []
        for i, t in enumerate(times):
            f = tmp / f"{i:03d}.png"
            run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(mp4), "-frames:v", "1",
                 "-vf", "scale=270:-2", str(f)])
            thumbs.append(Image.open(f).convert("RGB"))
        tw, th = thumbs[0].size
        cols = min(len(thumbs), 6)
        rows = -(-len(thumbs) // cols)
        sheet = Image.new("RGB", (cols * tw, rows * th), "black")
        for i, im in enumerate(thumbs):
            sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
        sheet.save(dest, quality=88)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def finish(project_dir, raw_mp4, frames=None):
    pdir = Path(project_dir)
    project = load_project(pdir)
    raw_mp4 = Path(raw_mp4)
    if not raw_mp4.is_file():
        die(f"{raw_mp4} not found")
    realized_path = pdir / "cues.realized.json"
    realized = json.loads(realized_path.read_text()) if realized_path.is_file() else []
    renders = pdir / "renders"
    renders.mkdir(exist_ok=True)
    stem = f"{project['app']}-{project['variant']}"
    out = next_version_path(renders, stem)
    work = Path(tempfile.mkdtemp(prefix="reel-finish-"))
    problems = []
    try:
        raw_wav, norm_wav = work / "raw.wav", work / "norm.wav"
        run(["ffmpeg", "-v", "error", "-y", "-i", str(raw_mp4), "-vn", "-ar", str(SR), "-ac", "2",
             "-c:a", "pcm_s16le", str(raw_wav)])
        meas = loudnorm(raw_wav, norm_wav)
        lag = lag_seconds(decode_audio(raw_wav, SR), decode_audio(norm_wav, SR))
        if abs(lag) >= MAX_LAG:
            problems.append(f"loudnorm moved audio by {lag * 1000:.1f} ms")
        run(["ffmpeg", "-v", "error", "-n", "-i", str(raw_mp4), "-i", str(norm_wav), "-map", "0:v:0",
             "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
             str(out)])
    finally:
        shutil.rmtree(work, ignore_errors=True)

    vi_raw, vi_out = video_info(raw_mp4), video_info(out)
    if vi_raw != vi_out:
        problems.append(f"video stream changed: {vi_raw} -> {vi_out}")
    frame = 1.0 / project["fps"]
    if abs(vi_out["duration"] - project["duration"]) > frame + 1e-6:
        problems.append(f"video is {vi_out['duration']}s, project.json says {project['duration']:g}s")

    rows = sync_report(decode_audio(out, SR), realized, project["fps"])
    flagged = [r for r in rows if r["flag"]]
    problems += [f"cue {r['id']} at {r['time']:.3f}s: {r['flag']}"
                 + (f" ({r['delta_ms']:+.1f} ms)" if r["delta_ms"] is not None else "") for r in flagged]

    dur = project["duration"]
    times = frames or [round(dur * i / 9, 2) for i in range(9)] + [round(dur - 0.1, 2)]
    sheet = out.with_name(out.stem + "-sheet.jpg")
    last = min(dur, vi_out["duration"]) - 0.05
    contact_sheet(out, [min(t, last) for t in times], sheet)

    final = measure(out)
    report = {"output": str(out), "sheet": str(sheet), "loudnorm_input": meas, "final_lufs": final["input_i"],
              "final_tp": final["input_tp"], "lag_ms": round(lag * 1000, 2),
              "video": vi_out, "sync": rows, "problems": problems}
    if problems:
        failed = out.with_name(out.stem + "-failed.mp4")
        out.rename(failed)
        report["output"] = str(failed)
    out.with_name(out.stem + "-report.json").write_text(json.dumps(report, indent=1) + "\n")

    if rows:
        worst = max((abs(r["delta_ms"]) for r in rows if r["delta_ms"] is not None), default=0)
        print(f"sync: {len(rows)} cues, {len(flagged)} flagged, worst {worst:.1f} ms")
    else:
        print("sync: no cues (no SFX mixed)")
    print(f"loudness {final['input_i']} LUFS, true peak {final['input_tp']} dBTP; loudnorm lag {lag * 1000:.2f} ms; video {vi_out}")
    if problems:
        print("FAILED:\n  " + "\n  ".join(problems), file=sys.stderr)
        print(f"output kept as {report['output']}", file=sys.stderr)
        return 1
    print(f"ok: {out}\ncontact sheet: {sheet}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir")
    ap.add_argument("raw_mp4")
    ap.add_argument("--frames", help="comma-separated times for the contact sheet")
    a = ap.parse_args()
    frames = [float(x) for x in a.frames.split(",")] if a.frames else None
    sys.exit(finish(a.project_dir, a.raw_mp4, frames))


if __name__ == "__main__":
    main()
