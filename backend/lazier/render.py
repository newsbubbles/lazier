"""ffmpeg render engine: SRT writer, full export, and low-res proxy preview.

M1 supports the spine: one (or more) visual track(s) of image/video clips composited
over a black canvas, the master audio as the timeline length, optional positioned
audio clips (music/sfx) with optional ducking under the voice. The graph is built
from the project's clips, so it scales as the timeline grows.

Heavier compositing (custom scale/x/y transforms, chunked proxy cache, baked
animated captions) is M3+; this builds the honest first cut."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

from . import config, storage
from .models import Clip, MediaAsset, Project, Word

Progress = Optional[Callable[[float], None]]   # called with a 0..1 render fraction


# --- SRT ---------------------------------------------------------------------
def _ts(t: float) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(project: Project) -> Path:
    """Always written alongside the project, from pass-1 segments (caption-grained)."""
    items = project.segments or []
    out = storage.abs_path(project.id, "captions.srt")
    lines = []
    for i, seg in enumerate(items, start=1):
        lines.append(str(i))
        lines.append(f"{_ts(seg.start)} --> {_ts(seg.end)}")
        lines.append(seg.text)
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def _yt_ts(t: float) -> str:
    t = max(0, int(t))
    h, m, s = t // 3600, (t % 3600) // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def write_chapters(project: Project) -> Path:
    """YouTube-description chapters from the project's topic sections, one per line as
    'M:SS Title'. Paste into a YT description and YouTube auto-parses clickable chapters.
    YT requires the first at 0:00, >=3 chapters, each >=10s apart — which our flush topic
    sections satisfy. Written to the project folder so it's a copy-paste-ready artifact."""
    secs = sorted(project.sections, key=lambda s: s.start)
    out = storage.abs_path(project.id, "chapters.txt")
    lines = [f"{_yt_ts(0.0 if i == 0 else s.start)} "
             f"{(s.topic_label or s.visual_brief or f'Chapter {i + 1}').strip()}"
             for i, s in enumerate(secs)]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# --- ffmpeg graph ------------------------------------------------------------
def _visual_clips(project: Project) -> list[Clip]:
    clips: list[Clip] = []
    for t in project.tracks:
        if t.kind == "visual":
            clips.extend(t.clips)
    return sorted(clips, key=lambda c: c.timeline_start)


def _audio_clips(project: Project) -> list[tuple[Clip, bool, float]]:
    out = []
    for t in project.tracks:
        if t.kind == "audio":
            for c in t.clips:
                out.append((c, t.duck, t.gain))
    return out


def _fit(w: int, h: int) -> str:
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")


def _build_command(project: Project, out_path: Path, height: int | None) -> list[str]:
    audio_asset = project.audio_asset()
    if not audio_asset:
        raise RuntimeError("project has no audio; nothing to render")
    total = project.duration
    if total <= 0:
        raise RuntimeError("project duration is zero")

    W, H = project.width, project.height
    if height:  # proxy: shrink canvas, keep aspect
        H2 = height - (height % 2)
        W2 = int(round(W * H2 / H))
        W2 -= W2 % 2
        W, H = W2, H2
    fps_val = config.PROXY_FPS if height else project.fps   # preview renders at a low fps

    pdir = storage.project_dir(project.id)
    inputs: list[str] = []
    filt: list[str] = []

    # input 0 = master audio
    inputs += ["-i", str(pdir / audio_asset.local_path)]

    vclips = _visual_clips(project)
    vlabels: list[tuple[str, float, float]] = []  # (label, start, end)
    idx = 1
    for c in vclips:
        asset = project.assets.get(c.asset_id)
        if not asset:
            continue
        path = str(pdir / asset.local_path)
        start = c.timeline_start
        end = c.timeline_end
        dur = max(end - start, 0.04)
        lbl = f"v{idx}"

        if asset.kind == "image":
            inputs += ["-loop", "1", "-t", f"{dur:.3f}", "-i", path]
            chain = f"[{idx}:v]{_fit(W, H)}"
            if c.transforms.ken_burns:
                chain += (f",zoompan=z='min(zoom+0.0006,1.15)':d={max(int(dur*fps_val),1)}:"
                          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={fps_val}")
            chain += f",setpts=PTS-STARTPTS+{start:.3f}/TB"
        else:  # video
            si = c.source_in
            so = c.source_out if c.source_out is not None else si + dur
            inputs += ["-i", path]
            chain = (f"[{idx}:v]trim=start={si:.3f}:end={so:.3f},setpts=PTS-STARTPTS,"
                     f"{_fit(W, H)},setpts=PTS-STARTPTS+{start:.3f}/TB")

        if c.effects.fade_in > 0:
            chain += f",fade=t=in:st={start:.3f}:d={c.effects.fade_in:.3f}:alpha=0"
        if c.effects.fade_out > 0:
            chain += f",fade=t=out:st={max(end - c.effects.fade_out, 0):.3f}:d={c.effects.fade_out:.3f}"
        chain += f"[{lbl}]"
        filt.append(chain)
        vlabels.append((lbl, start, end))
        idx += 1

    # base canvas + overlay chain
    filt.append(f"color=c=black:s={W}x{H}:r={fps_val}:d={total:.3f}[base]")
    cur = "base"
    for i, (lbl, start, end) in enumerate(vlabels):
        nxt = "vout" if i == len(vlabels) - 1 else f"o{i}"
        filt.append(f"[{cur}][{lbl}]overlay=enable='between(t,{start:.3f},{end:.3f})':"
                    f"eof_action=pass:format=auto[{nxt}]")
        cur = nxt
    if not vlabels:
        filt.append("[base]null[vout]")

    # audio: master + positioned clips, optional ducking under the voice
    aclips = _audio_clips(project)
    voice = "0:a"
    if project.voice_enhance:                 # podcast vocal chain on the voice spine
        filt.append(f"[0:a]{config.VOICE_CHAIN}[voice]")
        voice = "voice"
    amix_inputs: list[str] = [voice]
    duck_streams: list[str] = []
    for j, (c, duck, gain) in enumerate(aclips):
        asset = project.assets.get(c.asset_id)
        if not asset:
            continue
        path = str(pdir / asset.local_path)
        si = c.source_in
        so = c.source_out if c.source_out is not None else si + (c.timeline_end - c.timeline_start)
        delay_ms = int(c.timeline_start * 1000)
        lab = f"a{j}"
        inputs += ["-i", path]
        achain = (f"[{idx}:a]atrim=start={si:.3f}:end={so:.3f},asetpts=PTS-STARTPTS,"
                  f"volume={gain:.3f},adelay={delay_ms}|{delay_ms}[{lab}]")
        filt.append(achain)
        if duck:
            duck_streams.append(lab)
        else:
            amix_inputs.append(lab)
        idx += 1

    # duck each ducked stream under the master voice, then mix everything
    for k, lab in enumerate(duck_streams):
        ducked = f"d{k}"
        filt.append(f"[{lab}][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300[{ducked}]")
        amix_inputs.append(ducked)

    if len(amix_inputs) == 1:
        amap = f"[{voice}]" if project.voice_enhance else "0:a"   # label needs brackets; raw doesn't
    else:
        joined = "".join(f"[{s}]" for s in amix_inputs)
        filt.append(f"{joined}amix=inputs={len(amix_inputs)}:normalize=0:duration=longest,"
                    f"alimiter=limit=0.95[aout]")
        amap = "[aout]"         # filter label: brackets in -map

    # Windows CreateProcess caps a command line at 32767 chars. With many clips the
    # inline filtergraph alone blows past that (~300 chars/clip), so write it to a file
    # and hand ffmpeg -filter_complex_script instead. Same graph, just off the argv.
    filter_path = out_path.with_name(out_path.stem + ".filter.txt")
    filter_path.parent.mkdir(parents=True, exist_ok=True)
    filter_path.write_text(";".join(filt), encoding="utf-8")

    crf = "30" if height else "20"
    preset = "ultrafast" if height else "medium"
    cmd = [config.FFMPEG, "-y", *inputs,
           "-filter_complex_script", str(filter_path),
           "-map", "[vout]", "-map", amap,
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", preset, "-crf", crf,
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000",   # pin 48k (loudnorm upsamples otherwise)
           "-t", f"{total:.3f}", "-movflags", "+faststart"]
    if height:  # proxy: dense keyframes so scrub-seek snaps instantly to the playhead
        gop = max(int(fps_val // 2), 5)
        cmd += ["-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0"]
    # machine-readable progress on stdout so callers can stream a real percentage
    cmd += ["-progress", "pipe:1", "-nostats"]
    cmd += [str(out_path)]
    return cmd


def _run(cmd: list[str], total: float = 0.0, on_progress: Progress = None) -> None:
    # With a listener + known duration, stream ffmpeg's -progress (out_time in microseconds)
    # into a 0..1 fraction. Without one, a plain blocking run — same command either way.
    if on_progress and total > 0:
        # stderr -> a temp file, NOT a pipe. With a 100-input filtergraph ffmpeg emits
        # enough startup output to fill an undrained stderr pipe (~64KB) and then blocks,
        # while we're busy reading the -progress stream on stdout: a deadlock. A file never
        # backpressures; we read it back only if the render fails.
        with tempfile.TemporaryFile() as errf:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf, text=True)
            for line in proc.stdout or []:
                line = line.strip()
                if line.startswith(("out_time_us=", "out_time_ms=")):  # both are microseconds
                    try:
                        on_progress(min(int(line.split("=", 1)[1]) / 1_000_000 / total, 0.999))
                    except ValueError:
                        pass
                elif line == "progress=end":
                    on_progress(1.0)
            proc.wait()
            if proc.returncode != 0:
                errf.seek(0)
                err = errf.read().decode("utf-8", "replace")
                tail = "\n".join(err.strip().splitlines()[-12:])
                raise RuntimeError(f"ffmpeg failed:\n{tail}")
    else:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            tail = "\n".join(res.stderr.strip().splitlines()[-12:])
            raise RuntimeError(f"ffmpeg failed:\n{tail}")


def render_proxy(project: Project, on_progress: Progress = None) -> Path:
    out = storage.abs_path(project.id, "proxies/preview.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(_build_command(project, out, height=config.PROXY_HEIGHT), project.duration, on_progress)
    return out


def render_export(project: Project, on_progress: Progress = None) -> dict:
    out = storage.abs_path(project.id, "exports/export.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(_build_command(project, out, height=None), project.duration, on_progress)
    srt = write_srt(project)
    chapters = write_chapters(project)
    return {"video": "exports/export.mp4", "srt": srt.name, "chapters": chapters.name}


# --- shorts (vertical 9:16 slice + burned captions) --------------------------
def _reframe(origin: str, w: int, h: int) -> str:
    """Scale-to-COVER the vertical frame then crop to fill: web-captures crop LEFT (the
    reading/content side), everything else crops CENTER. Works for any source aspect."""
    scale = f"scale={w}:{h}:force_original_aspect_ratio=increase"
    crop = f"crop={w}:{h}:0:0" if origin == "web" else f"crop={w}:{h}"
    return f"{scale},{crop},setsar=1"


def _build_short_command(project: Project, out_path: Path, ass_name: str,
                         t0: float, t1: float) -> list[str]:
    audio_asset = project.audio_asset()
    if not audio_asset:
        raise RuntimeError("project has no audio; nothing to render")
    W, H, fps = config.SHORTS_W, config.SHORTS_H, project.fps
    total = max(t1 - t0, 0.1)
    pdir = storage.project_dir(project.id)

    # input 0 = master audio, pre-trimmed to the window
    inputs = ["-ss", f"{t0:.3f}", "-to", f"{t1:.3f}", "-i", str(pdir / audio_asset.local_path)]
    filt: list[str] = []
    vlabels: list[tuple[str, float, float]] = []
    idx = 1
    for c in _visual_clips(project):
        cs, ce = max(c.timeline_start, t0), min(c.timeline_end, t1)
        if ce <= cs:
            continue                                  # clip doesn't touch the window
        asset = project.assets.get(c.asset_id)
        if not asset:
            continue
        path = str(pdir / asset.local_path)
        start, end = cs - t0, ce - t0                 # position within the short
        dur = max(end - start, 0.04)
        lbl = f"v{idx}"
        if asset.kind == "image":
            inputs += ["-loop", "1", "-t", f"{dur:.3f}", "-i", path]
            chain = f"[{idx}:v]{_reframe(asset.origin, W, H)}"
            if c.transforms.ken_burns:
                chain += (f",zoompan=z='min(zoom+0.0006,1.15)':d={max(int(dur*fps),1)}:"
                          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={fps}")
            chain += f",setpts=PTS-STARTPTS+{start:.3f}/TB"
        else:
            si = c.source_in + (cs - c.timeline_start)   # region of the source that maps here
            chain = (f"[{idx}:v]trim=start={si:.3f}:end={si + dur:.3f},setpts=PTS-STARTPTS,"
                     f"{_reframe(asset.origin, W, H)},setpts=PTS-STARTPTS+{start:.3f}/TB")
            inputs += ["-i", path]
        chain += f"[{lbl}]"
        filt.append(chain)
        vlabels.append((lbl, start, end))
        idx += 1

    filt.append(f"color=c=black:s={W}x{H}:r={fps}:d={total:.3f}[base]")
    cur = "base"
    for i, (lbl, s, e) in enumerate(vlabels):
        filt.append(f"[{cur}][{lbl}]overlay=enable='between(t,{s:.3f},{e:.3f})':"
                    f"eof_action=pass:format=auto[o{i}]")
        cur = f"o{i}"
    filt.append(f"[{cur}]ass={ass_name}[vout]")       # burn captions (ass by basename; cwd=out dir)

    filter_path = out_path.with_name(out_path.stem + ".filter.txt")
    filter_path.write_text(";".join(filt), encoding="utf-8")
    return [config.FFMPEG, "-y", *inputs,
            "-filter_complex_script", str(filter_path),
            "-map", "[vout]", "-map", "0:a",
            "-af", (config.VOICE_CHAIN if project.voice_enhance else "loudnorm"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{total:.3f}",
            "-movflags", "+faststart", str(out_path)]


def render_short(project: Project, plan) -> dict:
    """Render one vertical short for `plan` (a shorts.ShortPlan): reframe to 9:16, burn the
    word-level karaoke captions, write to exports/shorts/. ffmpeg runs with cwd=out dir so the
    ass= filter can reference the subtitle by basename (dodges Windows path escaping)."""
    from . import shorts
    t0, t1 = shorts.window_bounds(project, plan)
    out_dir = storage.abs_path(project.id, "exports/shorts")
    out_dir.mkdir(parents=True, exist_ok=True)
    out, ass_name = out_dir / "short_1.mp4", "short_1.ass"

    src = project.transcript.words if project.transcript else []
    words = [Word(text=w.text, start=max(w.start - t0, 0.0), end=max(w.end - t0, 0.01))
             for w in src if w.end > t0 and w.start < t1]
    (out_dir / ass_name).write_text(
        shorts.build_caption_ass(words, plan.caption_style, config.SHORTS_W, config.SHORTS_H),
        encoding="utf-8")

    res = subprocess.run(_build_short_command(project, out, ass_name, t0, t1),
                         cwd=str(out_dir), capture_output=True, text=True)
    if res.returncode != 0:
        tail = "\n".join(res.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"short render failed:\n{tail}")
    (out_dir / "short_1.txt").write_text(
        f"{plan.hook_title}\n\n{plan.social_caption}\n", encoding="utf-8")
    return {"video": "exports/shorts/short_1.mp4", "caption": "exports/shorts/short_1.txt",
            "start": round(t0, 2), "end": round(t1, 2), "duration": round(t1 - t0, 1)}
