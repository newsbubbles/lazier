"""ffmpeg render engine: SRT writer, full export, and low-res proxy preview.

M1 supports the spine: one (or more) visual track(s) of image/video clips composited
over a black canvas, the master audio as the timeline length, optional positioned
audio clips (music/sfx) with optional ducking under the voice. The graph is built
from the project's clips, so it scales as the timeline grows.

Heavier compositing (custom scale/x/y transforms, chunked proxy cache, baked
animated captions) is M3+; this builds the honest first cut."""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import config, storage
from .models import Clip, MediaAsset, Project


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
                chain += (f",zoompan=z='min(zoom+0.0006,1.15)':d={int(dur*config.PROXY_HEIGHT)}:"
                          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps=25")
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
    filt.append(f"color=c=black:s={W}x{H}:r={project.fps}:d={total:.3f}[base]")
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
    amix_inputs: list[str] = ["0:a"]
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
        amap = "0:a"            # raw input stream: no brackets in -map
    else:
        joined = "".join(f"[{s}]" for s in amix_inputs)
        filt.append(f"{joined}amix=inputs={len(amix_inputs)}:normalize=0:duration=longest,"
                    f"alimiter=limit=0.95[aout]")
        amap = "[aout]"         # filter label: brackets in -map

    crf = "30" if height else "20"
    preset = "veryfast" if height else "medium"
    cmd = [config.FFMPEG, "-y", *inputs,
           "-filter_complex", ";".join(filt),
           "-map", "[vout]", "-map", amap,
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", preset, "-crf", crf,
           "-c:a", "aac", "-b:a", "192k",
           "-t", f"{total:.3f}", "-movflags", "+faststart",
           str(out_path)]
    return cmd


def _run(cmd: list[str]) -> None:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        tail = "\n".join(res.stderr.strip().splitlines()[-12:])
        raise RuntimeError(f"ffmpeg failed:\n{tail}")


def render_proxy(project: Project) -> Path:
    out = storage.abs_path(project.id, "proxies/preview.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(_build_command(project, out, height=config.PROXY_HEIGHT))
    return out


def render_export(project: Project) -> dict:
    out = storage.abs_path(project.id, "exports/export.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(_build_command(project, out, height=None))
    srt = write_srt(project)
    return {"video": "exports/export.mp4", "srt": srt.name}
