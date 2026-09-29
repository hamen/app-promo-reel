#!/usr/bin/env python3
"""Finish a rendered reel: loudness, checks, contact sheet, versioned output.

1. Two-pass loudnorm (I=-14 LUFS, TP=-2 dBTP) on the 48 kHz WAV of the raw render. The final
   AAC file must measure within 1 LU of -14 LUFS and at most -1 dBTP, or the run fails.
2. A/V check before the AAC encode: the cross-correlation lag between the WAV before and
   after loudnorm must be < 5 ms.
3. Mux: video stream copied (-c:v copy), audio AAC, to renders/<app>-<variant>-v<N>.checking.mp4,
   N = one more than the highest existing version (a leftover .checking file counts too).
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
7. Frame checks on the final MP4 (warnings only: they never fail the run or rename the file):
   a blank opening (frame 0 is the feed thumbnail; the hook must show within 1 s) and "pops",
   frame-to-frame changes far above their neighbours: a one-frame flash, or a cut that is near
   no beat and no scene start. They find one-frame events, not two texts on top of each other
   during a crossfade: that is for the critique loop in SKILL.md.

Only when every check passed is the file renamed to ...-v<N>.mp4 (sheet: -v<N>-sheet.jpg). A
failed check exits 1 and names it ...-v<N>-failed.mp4; so does any other exit after the mux
(an error, Ctrl-C). The report, -v<N>-report.json, is written last, with the final names. A
.checking file left by a killed run was never checked; the script never deletes it.

Usage: finish.py <project_dir> <raw_render.mp4> [--frames 1.0,5.2,...]
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import scipy.signal as ss

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import attack_index, decode_audio, die, load_project, read_json  # noqa: E402

SR = 48000
TARGET_I, TARGET_TP, TARGET_LRA = -14.0, -2.0, 11.0
# gate on the final AAC file: AAC adds a few tenths of a dB of inter-sample peak on top of the
# -2 dBTP PCM target, so the delivered file is held to -1 dBTP (the usual platform ceiling)
MAX_LU_OFF, MAX_FINAL_TP = 1.0, -1.0
MAX_LAG = 0.005
SYNC_WINDOW = 0.150
TEMPLATE_LEN = 0.25  # seconds of each SFX used as the matched-filter template
MIN_MATCH = 0.2      # normalised correlation below this = the sound is not in the window
# frame checks, on frames decoded to FRAME_W px wide grayscale. Calibrated 2026-09-29 on three
# delivered reels: an empty gradient opening measures 1.4-2.2 detail, frames with text or UI 2.8+;
# scene cuts change 30-100 gray levels in one frame, a headline settling after its slam 4-10.
FRAME_W = 54
BLANK_DETAIL = 2.5   # mean neighbouring-pixel difference below this = nothing to read on the frame
POP_MIN = 12.0       # a spike changes at least this many gray levels (mean) from the frame before
POP_RATIO = 3.0      # ... and this many times the median change of the 3 frames on each side
POP_GROUP = 3        # spikes at most this many frames apart are one fast move
POP_LEAD = 0.15      # a fast move may start up to this long before the beat it lands on
HOOK_BY = 1.0        # seconds: something readable must be on screen by then


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        die(f"{cmd[0]} failed ({' '.join(map(str, cmd[1:6]))} ...):\n{r.stderr[-800:]}")
    return r


def next_version_path(renders, stem):
    """renders/<stem>-v<N>.mp4 with N = max existing (incl. -failed and .checking) + 1."""
    pat = re.compile(re.escape(stem) + r"-v(\d+)(?:-failed|\.checking)?\.mp4$")
    nums = [int(m.group(1)) for p in renders.glob(f"{stem}-v*.mp4") if (m := pat.match(p.name))]
    return renders / f"{stem}-v{max(nums, default=0) + 1}.mp4"


def video_info(path):
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
               "stream=codec_name,width,height,nb_read_packets,duration:format=duration", "-of", "json",
               str(path)]).stdout
    doc = json.loads(out)
    streams = doc.get("streams") or []
    if not streams:
        die(f"{path} has no video stream")
    s = streams[0]
    # some containers keep the duration on the format, not the stream; ffprobe writes "N/A" when
    # it has none
    duration = next((d for d in (_seconds(s.get("duration")), _seconds(doc.get("format", {}).get("duration")))
                     if d is not None), None)
    if duration is None:
        die(f"ffprobe gives no duration for {path}")
    return {"codec": s["codec_name"], "width": s["width"], "height": s["height"],
            "frames": int(s["nb_read_packets"]), "duration": round(duration, 3)}


def _seconds(v):
    """A duration from ffprobe, or None for "N/A", a missing value, NaN or infinity."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


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


def window_energy(x, n):
    """Sum of squares of every n-sample window of x (len(x) - n + 1 values), in O(len(x))."""
    run_sum = np.concatenate(([0.0], np.cumsum(np.asarray(x, dtype=np.float64) ** 2)))
    return run_sum[n:] - run_sum[:-n]


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
    energy = window_energy(seg, n)
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


def loudness_problems(final):
    i, tp = float(final["input_i"]), float(final["input_tp"])
    out = []
    if abs(i - TARGET_I) > MAX_LU_OFF:
        out.append(f"final loudness {i:.2f} LUFS is more than {MAX_LU_OFF:g} LU from {TARGET_I:g}")
    if tp > MAX_FINAL_TP:
        out.append(f"final true peak {tp:.2f} dBTP is above {MAX_FINAL_TP:g} dBTP")
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


def late_starts(pdir, realized, fps, sr=SR):
    """{file: ms of leading silence} for the files of align "start" cues (checked for sync or not)
    whose sound begins more than one frame after the cue time."""
    out = {}
    for f in dict.fromkeys(c["file"] for c in realized if c.get("align") == "start"):
        path = Path(pdir) / f
        if path.is_file():
            ms = attack_index(decode_audio(path, sr)) / sr * 1000
            if ms > 1000 / fps:
                out[f] = ms
    return out


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


def decode_gray(mp4, width, height):
    """Every frame of mp4 as float32 grayscale, FRAME_W px wide, height kept in proportion.
    Raises (never die()): the frame checks must not end the run."""
    h = max(2, round(FRAME_W * height / width / 2) * 2)
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp4), "-vf", f"scale={FRAME_W}:{h},format=gray",
                        "-f", "rawvideo", "-"], capture_output=True)
    if r.returncode:
        raise RuntimeError(f"ffmpeg could not decode the frames: {r.stderr.decode(errors='replace')[-300:]}")
    n = len(r.stdout) // (FRAME_W * h)
    return np.frombuffer(r.stdout[:n * FRAME_W * h], np.uint8).reshape(n, h, FRAME_W).astype(np.float32)


def frame_detail(frames):
    """Mean absolute difference between neighbouring pixels, per frame: ~0 on a flat colour."""
    return (np.abs(np.diff(frames, axis=2)).mean(axis=(1, 2))
            + np.abs(np.diff(frames, axis=1)).mean(axis=(1, 2)))


def pop_events(frames, dt):
    """Spikes of the frame-to-frame change: [{"type": "flash" | "cut", "time", "frames"}].
    A flash is one odd frame (the change into it and back out are one event); a cut is one spike
    or a run of spikes at most POP_GROUP frames apart (one fast move)."""
    n = len(frames)
    d = np.zeros(n)
    d[1:] = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
    spikes = []
    for i in range(1, n):
        around = np.concatenate([d[max(1, i - 3):i], d[i + 1:i + 4]])  # d[0] is not a change
        if d[i] > POP_MIN and (not len(around) or d[i] > POP_RATIO * np.median(around)):
            spikes.append(i)
    # flashes first: grouped into a fast move, a glitch frame next to a cut would go unreported
    events, cuts, spikeset = [], [], set(spikes)
    for a in spikes:
        if a not in spikeset:
            continue
        if a + 1 in spikeset and np.abs(frames[a + 1] - frames[a - 1]).mean() < d[a] / 3:
            events.append({"type": "flash", "time": round(a * dt, 3), "frames": 1})
            spikeset -= {a, a + 1}
        else:
            cuts.append(a)
    i = 0
    while i < len(cuts):
        run_ = [cuts[i]]
        while i + 1 < len(cuts) and cuts[i + 1] - run_[-1] <= POP_GROUP:
            i += 1
            run_.append(cuts[i])
        events.append({"type": "cut", "time": round(run_[0] * dt, 3), "end": round(run_[-1] * dt, 3),
                       "frames": run_[-1] - run_[0] + 1})
        i += 1
    return sorted(events, key=lambda e: e["time"])


def scene_starts(html):
    """data-start of every live <section> of the built index.html (as build.check_scenes reads it)."""
    live = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    starts = []
    for tag in re.findall(r"<section\b[^>]*>", live):
        m = re.search(r"""\bdata-start\s*=\s*(["'])(.*?)\1""", tag)
        if m:
            starts.append(float(m.group(2)))
    return starts


def frame_checks(pdir, mp4, vi):
    """Blank opening and pops on the final MP4. Returns the report dict; its "warnings" are
    printed and never change the exit code. Reads files with plain read_text/json.loads, never
    read_json or die(): a SystemExit here would turn a good reel into -failed."""
    frames = decode_gray(mp4, vi["width"], vi["height"])
    if not len(frames):
        raise RuntimeError("no frame decoded")
    # video_info gives the video STREAM's duration (the container's only as a fallback): muxed audio
    # that runs longer must not stretch the frame times
    dt = vi["duration"] / len(frames)
    warnings, notes = [], []

    detail = frame_detail(frames)
    readable = np.flatnonzero(detail >= BLANK_DETAIL)
    first = round(float(readable[0] * dt), 3) if len(readable) else None
    if first is None:
        warnings.append("no frame has anything to read on it: the video looks empty")
    else:
        if detail[0] < BLANK_DETAIL:
            warnings.append("frame 0 is blank, and feeds show frame 0 as the thumbnail: start on the hook "
                            "text or UI")
        if first > HOOK_BY:
            warnings.append(f"nothing to read until {first:.2f} s: the hook must show within {HOOK_BY:g} s")

    marks = []
    sources = (("index.html", lambda: scene_starts((pdir / "index.html").read_text())),
               ("beats.json", lambda: [float(b) for b in json.loads((pdir / "beats.json").read_text())["beats"]]))
    for name, load in sources:
        try:
            marks += load()
        except (OSError, ValueError, TypeError, KeyError, OverflowError) as e:
            notes.append(f"{name} not read ({e!r}): cuts are not compared with it")
    events = pop_events(frames, dt)
    for e in events:
        if e["type"] == "flash":
            warnings.append(f"one-frame flash at {e['time']:.2f} s: a glitch frame (look at it)")
            continue
        e["planned"] = any(e["time"] - 2 * dt - 1e-6 <= m <= e["end"] + POP_LEAD for m in marks)
        if not e["planned"]:
            warnings.append(f"sudden change at {e['time']:.2f} s near no beat and no scene start (look at it)")
    return {"frame0_blank": bool(detail[0] < BLANK_DETAIL), "first_detail_time": first,
            "events": events, "warnings": warnings, "notes": notes}


def _checks(pdir, project, raw_mp4, realized, checking, sheet, frames):
    """Mux the loudness-normalised audio to `checking`, make the contact sheet at `sheet` and run
    every check. Returns (problems, report); naming the files is the caller's job."""
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
             str(checking)])
    finally:
        shutil.rmtree(work, ignore_errors=True)

    vi_raw, vi_out = video_info(raw_mp4), video_info(checking)
    if vi_raw != vi_out:
        problems.append(f"video stream changed: {vi_raw} -> {vi_out}")
    frame = 1.0 / project["fps"]
    if abs(vi_out["duration"] - project["duration"]) > frame + 1e-6:
        problems.append(f"video is {vi_out['duration']}s, project.json says {project['duration']:g}s")

    rows, sync_problems = sync_report(decode_audio(checking, SR), realized, project["fps"], pdir)
    problems += sync_problems

    dur = project["duration"]
    times = frames or [round(dur * i / 9, 2) for i in range(9)] + [round(dur - 0.1, 2)]
    last = min(dur, vi_out["duration"]) - 0.05
    contact_sheet(checking, [min(t, last) for t in times], sheet)
    try:
        frame_report = frame_checks(pdir, checking, vi_out)
    except Exception as e:  # a heuristic check that cannot run is a note, never a failed reel
        frame_report = {"warnings": [], "notes": [f"frame checks did not run: {e!r}"]}

    final = measure(checking)
    problems += loudness_problems(final)
    return problems, {"loudnorm_input": meas, "final_lufs": final["input_i"], "final_tp": final["input_tp"],
                      "lag_ms": round(lag * 1000, 2), "video": vi_out, "sync": rows, "frames": frame_report,
                      "problems": problems}


def finish(project_dir, raw_mp4, frames=None):
    pdir = Path(project_dir)
    project = load_project(pdir)
    raw_mp4 = Path(raw_mp4)
    if not raw_mp4.is_file():
        die(f"{raw_mp4} not found")
    realized_path = pdir / "cues.realized.json"
    if not realized_path.is_file():
        die(f"{realized_path} not found: run build.py before finish.py")
    realized = read_json(realized_path, list)
    for cue in realized:
        if not (isinstance(cue, dict) and isinstance(cue.get("id"), str) and isinstance(cue.get("file"), str)
                and isinstance(cue.get("time"), (int, float)) and not isinstance(cue.get("time"), bool)):
            die(f"{realized_path}: every entry needs id, file and time (it is written by build.py: rebuild)")
    renders = pdir / "renders"
    renders.mkdir(exist_ok=True)
    stem = f"{project['app']}-{project['variant']}"
    out = next_version_path(renders, stem)
    checking = out.with_name(out.stem + ".checking.mp4")
    sheet = out.with_name(out.stem + ".checking-sheet.jpg")
    failed, failed_sheet = out.with_name(out.stem + "-failed.mp4"), out.with_name(out.stem + "-failed-sheet.jpg")
    good_sheet = out.with_name(out.stem + "-sheet.jpg")
    report_path = out.with_name(out.stem + "-report.json")
    partial = report_path.with_name("." + report_path.name + ".partial")
    # reads only the cue sounds, so it runs before the mux: an error here leaves no file in renders/
    late = late_starts(pdir, realized, project["fps"])
    try:
        problems, report = _checks(pdir, project, raw_mp4, realized, checking, sheet, frames)
        final_mp4, final_sheet = (failed, failed_sheet) if problems else (out, good_sheet)
        checking.rename(final_mp4)
        sheet.rename(final_sheet)
        report = {"output": str(final_mp4), "sheet": str(final_sheet), **report}
        partial.write_text(json.dumps(report, indent=1) + "\n")
        os.replace(partial, report_path)
    except BaseException:
        # an error or Ctrl-C anywhere after the mux, up to the report: the run did not complete, so
        # nothing may keep a delivery name; no report is left
        for src, dst in ((checking, failed), (out, failed), (sheet, failed_sheet), (good_sheet, failed_sheet)):
            if src.exists():
                src.rename(dst)
        partial.unlink(missing_ok=True)
        raise

    rows, vi_out = report["sync"], report["video"]
    if rows:
        found = [r for r in rows if r["delta_ms"] is not None]
        worst = max((abs(r["delta_ms"]) for r in found), default=0)
        masked = [r["id"] for r in rows if r["delta_ms"] is None]
        print(f"sync: {len(found)} of {len(rows)} checked cues found, worst {worst:.1f} ms"
              + (f"; not found: {', '.join(masked)}" if masked else ""))
    else:
        print("sync: no cues (no SFX mixed)")
    for w in report["frames"]["warnings"]:
        print(f"warning: {w}", file=sys.stderr)
    for note in report["frames"]["notes"]:
        print(f"note: {note}", file=sys.stderr)
    for f, ms in late.items():
        print(f"warning: {f} starts with {ms:.0f} ms of silence and its cues use align \"start\", so it "
              f"sounds {ms:.0f} ms after the cue time; use align \"attack\" or trim the file", file=sys.stderr)
    print(f"loudness {report['final_lufs']} LUFS, true peak {report['final_tp']} dBTP; loudnorm lag "
          f"{report['lag_ms']:.2f} ms; video {vi_out}")
    if problems:
        print("FAILED:\n  " + "\n  ".join(problems), file=sys.stderr)
        print(f"output kept as {final_mp4}", file=sys.stderr)
        return 1
    print(f"ok: {final_mp4}\ncontact sheet: {final_sheet}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir")
    ap.add_argument("raw_mp4")
    ap.add_argument("--frames", help="comma-separated times for the contact sheet")
    a = ap.parse_args()
    try:
        frames = [float(x) for x in a.frames.split(",")] if a.frames else None
    except ValueError:
        die(f"--frames takes comma-separated seconds, got {a.frames!r}")
    if frames and min(frames) < 0:
        die("--frames times must be 0 or more")
    sys.exit(finish(a.project_dir, a.raw_mp4, frames))


if __name__ == "__main__":
    main()
