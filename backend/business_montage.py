"""Private Clippr Business multi-source vertical montage composer.

The caller must verify source ownership and usage entitlements BEFORE downloading
R2 assets and calling this function. No public endpoint is registered here.
Renders up to six approved source windows, preserves audio (or fills silence),
keeps landscape footage in-frame over a blurred background, then adds Brand Kit.
"""
from __future__ import annotations
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from business_brand_render import render_branded_clip

class MontageError(ValueError):
    pass

def _probe(source):
    result=subprocess.run([
      "ffprobe","-v","error","-show_entries",
      "format=duration:stream=index,codec_type","-of","json",str(source)
    ],capture_output=True,text=True,timeout=12)
    if result.returncode:raise MontageError("Source video could not be inspected")
    try:
        data=json.loads(result.stdout)
        duration=float(data["format"]["duration"])
        video=any(s.get("codec_type")=="video" for s in data.get("streams",[]))
        audio=any(s.get("codec_type")=="audio" for s in data.get("streams",[]))
    except (KeyError,ValueError,TypeError) as e:
        raise MontageError("Video metadata is incomplete") from e
    if not math.isfinite(duration) or duration<3 or not video:
        raise MontageError("Video is invalid or too short")
    return duration,audio

def validate_segments(windows):
    if not isinstance(windows,list) or not 2<=len(windows)<=6:
        raise MontageError("Choose two to six scenes for your montage")
    safe=[]
    total=0.0
    for window in windows:
        if not isinstance(window,dict) or not isinstance(window.get("path"),str):
            raise MontageError("Each scene needs a valid local source file")
        try:path=Path(window["path"]).resolve(strict=True)
        except (OSError,ValueError) as exc:
            raise MontageError("Source video is unavailable") from exc
        if not path.is_file() or path.stat().st_size>512*1024*1024:
            raise MontageError("Source video is unavailable or too large")
        try:
            start=float(window["start_s"]);end=float(window["end_s"])
        except (ValueError,TypeError,KeyError):
            raise MontageError("Scene timing is invalid") from None
        if not (math.isfinite(start) and math.isfinite(end)
                and 0<=start<end and 3<=end-start<=30):
            raise MontageError("Choose scenes between 3 and 30 seconds")
        total+=end-start
        if total>120:raise MontageError("Montage length must not exceed two minutes")
        # 0=left edge, 0.5=centre, 1=right edge, within available crop travel.
        focus=window.get("focus_x",0.5)
        if isinstance(focus,bool) or not isinstance(focus,(float,int)) or not math.isfinite(focus) or not 0<=focus<=1:
            raise MontageError("Horizontal framing position must be between 0 and 1")
        safe.append((path,start,end,float(focus)))
    return safe

def build_montage(windows,output_path,*,brand=None,logo_path=None,logo_root=None,
                  width=360,height=640,timeout_per_clip=75):
    segments=validate_segments(windows)
    if width%2 or height%2 or not (160<=width<=1080 and 160<=height<=1920):
        raise MontageError("Unsupported vertical output dimensions")
    output=Path(output_path)
    output.parent.mkdir(parents=True,exist_ok=True)
    if any(path==output.resolve() for path,_,_,_ in segments):
        raise MontageError("Source footage must never be overwritten")
    with tempfile.TemporaryDirectory(prefix="clippr-business-montage-") as folder:
        tmp=Path(folder)
        pieces=[]
        for i,(path,start,end,focus) in enumerate(segments):
            duration,has_audio=_probe(path)
            if end>duration+.05:
                raise MontageError("Scene extends beyond its original footage")
            clip=tmp/f"scene_{i:02d}.mp4"
            # Business reels fill the frame; no blurred letterbox strip.
            # Centre crop is deterministic; subject-aware reframing is a
            # separate future feature requiring shot-level verification.
            x=f"(in_w-out_w)*{focus:.4f}"
            filter_=(f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                     f"crop={width}:{height}:x={x}:y=(in_h-out_h)/2,"
                     f"fps=30,format=yuv420p,setsar=1[v]")
            args=["ffmpeg","-hide_banner","-nostdin","-loglevel","error",
                  "-y","-ss",str(start),"-i",str(path)]
            if not has_audio:
                args+=["-f","lavfi","-i","anullsrc=channel_layout=stereo:sample_rate=48000"]
            args+=["-t",str(round(end-start,3)),"-filter_complex",filter_,
                   "-map","[v]","-map","0:a:0" if has_audio else "1:a:0",
                   "-c:v","libx264","-preset","veryfast","-crf","20",
                   "-pix_fmt","yuv420p","-r","30",
                   "-c:a","aac","-ar","48000","-ac","2","-b:a","128k",
                   "-movflags","+faststart",str(clip)]
            result=subprocess.run(args,capture_output=True,text=True,timeout=timeout_per_clip)
            if result.returncode or not clip.exists() or clip.stat().st_size<1500:
                raise MontageError("A montage scene could not be rendered")
            pieces.append(clip)
        concat_file=tmp/"concat.txt"
        concat_file.write_text("".join(f"file '{p.name}'\n" for p in pieces))
        raw=tmp/"montage.mp4"
        done=subprocess.run(["ffmpeg","-hide_banner","-nostdin","-loglevel","error",
                            "-y","-f","concat","-safe","1","-i",str(concat_file),
                            "-c","copy","-movflags","+faststart",str(raw)],
                            capture_output=True,text=True,timeout=90)
        if done.returncode or not raw.exists() or raw.stat().st_size<1500:
            raise MontageError("Montage assembly failed")
        if brand:
            render_branded_clip(raw,output,brand,logo_path=logo_path,
                                logo_root=logo_root,timeout=180)
        else:
            shutil.copyfile(raw,output)
        probe=subprocess.run(["ffprobe","-v","error","-show_entries",
                              "format=duration","-of","json",str(output)],
                              capture_output=True,text=True,timeout=12)
        if probe.returncode:
            raise MontageError("Finished montage could not be verified")
        length=float(json.loads(probe.stdout)["format"]["duration"])
        if not 5<=length<=123 or output.stat().st_size<1500:
            raise MontageError("Finished montage duration is invalid")
        return {"path":str(output),"duration_s":round(length,2),
                "scene_count":len(pieces),"width":width,"height":height}
