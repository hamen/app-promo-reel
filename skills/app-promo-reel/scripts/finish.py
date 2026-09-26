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
   "sync": true, the cue's own sound is located within +-150 ms by a matched filter
   (normalised cross-correlation with the SFX file) on the final audio minus the music bed.
   A found cue more than one frame off fails the check, and so does a cue that is not found
   ("masked": under a louder sound, or missing). A cue that is meant to sit under a louder
   sound is marked "sync": false in cues.json and is not checked.
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
from common import attack_index, decode_audio, die, load_project  # noqa: E402

SR = 48000
TARGET_I, TARGET_TP, TARGET_LRA = -14.0, -2.0, 11.0
MAX_LAG = 0.005
SYNC_WINDOW = 0.150
TEMPLATE_LEN = 0.25  # seconds of each SFX used as the matched-filter template
MIN_MATCH = 0.2      # normalised correlation below this = the sound is not in the window


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        die(f"{cmd[0]} failed ({' '.join(map(str, cmd[1:6]))} ...):\n{r.stderr[-800:]}")
    return r


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


def locate(y, tmpl, t, window=SYNC_WINDOW, sr=SR):
    """Matched filter: where does `tmpl` (the cue's own sound) start in y, within t +- window?
    Returns (start_time, normalised correlation 0-1). Music does not correlate with the SFX
    waveform, so the peak marks the SFX even inside a full mix; the gain of loudnorm cancels."""
    n = len(tmpl)
    a = max(0, int(round((t - window) * sr)))
    seg = y[a:int(round((t + window) * sr)) + n]
    if len(seg) < n:
        return None, 0.0
    num = ss.correlate(seg, tmpl, mode="valid", method="fft")
    energy = np.convolve(seg.astype(np.float64) ** 2, np.ones(n), mode="valid")
    ncc = num / (np.sqrt(np.maximum(energy, 1e-12)) * np.linalg.norm(tmpl) + 1e-12)
    k = int(np.argmax(ncc))
    return (a + k) / sr, float(ncc[k])


def required_match(n, sr=SR, window=SYNC_WINDOW):
    """Correlation a sound must reach to count as found. Noise alone reaches about
    sqrt(2 ln(lags) / n) by chance, which is high for very short sounds."""
    lags = 2 * window * sr + 1
    return max(MIN_MATCH, 1.5 * np.sqrt(2 * np.log(lags) / max(n, 1)))


def remove_bed(y, bed):
    """Subtract the music bed (least-squares gain) so quiet SFX stand out for matching."""
    n = min(len(y), len(bed))
    if n == 0 or not np.any(bed[:n]):
        return y
    g = float(np.dot(y[:n], bed[:n]) / np.dot(bed[:n], bed[:n]))
    out = y.astype(np.float64).copy()
    out[:n] -= g * bed[:n]
    return out


def sync_report(y, realized, fps, project_dir, sr=SR):
    """Per cue: found (with delta), off by more than one frame, or masked (not found: usually
    under a louder sound). Returns (rows, problems)."""
    frame = 1.0 / fps
    bed_path = Path(project_dir) / "assets" / "audio" / "bgm.wav"
    if bed_path.is_file():
        y = remove_bed(y, decode_audio(bed_path, sr))
    templates, rows = {}, []
    for cue in realized:
        if not cue.get("sync", True):
            continue
        if cue["file"] not in templates:
            path = Path(project_dir) / cue["file"]
            if not path.is_file():
                die(f"{path} (cue {cue['id']}) is gone since build.py ran; rebuild and render again")
            snd = decode_audio(path, sr)
            lead = attack_index(snd)
            templates[cue["file"]] = (snd[lead:lead + int(TEMPLATE_LEN * sr)], lead / sr)
        tmpl, lead = templates[cue["file"]]
        expected = cue["time"] + lead  # where the audible attack should be
        found, score = locate(y, tmpl, expected, sr=sr)
        base = {**cue, "lead_ms": round(lead * 1000, 1), "match": round(score, 3)}
        if found is None or score < required_match(len(tmpl), sr):
            rows.append({**base, "found": None, "delta_ms": None, "flag": "masked"})
            continue
        delta = found - expected
        rows.append({**base, "found": round(found, 4), "delta_ms": round(delta * 1000, 1),
                     "flag": "off by more than one frame" if abs(delta) > frame else None})
    problems = [f"cue {r['id']} at {r['time']:.3f}s: off by more than one frame ({r['delta_ms']:+.1f} ms)"
                for r in rows if r["flag"] == "off by more than one frame"]
    problems += [f"cue {r['id']} at {r['time']:.3f}s: not found in the final audio (masked by a louder sound, "
                 f"or missing). If it is meant to sit under a louder sound, set \"sync\": false on it in "
                 f"cues.json and rebuild" for r in rows if r["flag"] == "masked"]
    return rows, problems


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
    if not realized_path.is_file():
        die(f"{realized_path} not found: run build.py before finish.py")
    realized = json.loads(realized_path.read_text())
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

    rows, sync_problems = sync_report(decode_audio(out, SR), realized, project["fps"], pdir)
    problems += sync_problems

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
        found = [r for r in rows if r["delta_ms"] is not None]
        worst = max((abs(r["delta_ms"]) for r in found), default=0)
        masked = [r["id"] for r in rows if r["delta_ms"] is None]
        print(f"sync: {len(found)} of {len(rows)} checked cues found, worst {worst:.1f} ms"
              + (f"; not found: {', '.join(masked)}" if masked else ""))
        late = {r["file"]: r["lead_ms"] for r in rows
                if r.get("align") == "start" and r["lead_ms"] > 1000 / project["fps"]}
        for f, ms in late.items():
            print(f"warning: {f} starts with {ms:.0f} ms of silence and its cues use align \"start\", so it "
                  f"sounds {ms:.0f} ms after the cue time; use align \"attack\" or trim the file", file=sys.stderr)
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
