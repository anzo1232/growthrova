"""Bounded, offline visual scene discovery for speech-light business footage.

Uses FFmpeg scene changes, never an AI provider. Outputs labelled review-only
candidate windows. Does not pretend to know objects, treatments or product claims.
"""
from __future__ import annotations
import json
import math
import re
import subprocess

PTS = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")

class VisualSourceError(ValueError):
    pass

def _probe(path, *, subprocess_run=subprocess.run):
    args=["ffprobe","-v","error","-show_entries","format=duration",
          "-of","json",str(path)]
    r=subprocess_run(args,capture_output=True,text=True,timeout=12)
    if r.returncode:
        raise VisualSourceError("Video cannot be inspected.")
    try: duration=float(json.loads(r.stdout)["format"]["duration"])
    except (ValueError,TypeError,KeyError) as exc:
        raise VisualSourceError("Video duration is not available.") from exc
    if not math.isfinite(duration) or duration<3:
        raise VisualSourceError("Video is too short or invalid.")
    return min(duration,600.0)

def windows_from_cuts(cuts, duration, *, min_seconds=5, max_seconds=22, limit=36):
    """Return non-overlapping review windows with stable, grounded labels."""
    duration=float(duration)
    if not math.isfinite(duration) or duration<3: return []
    clean=[0.0]
    for item in sorted(cuts):
        try: time=float(item)
        except (TypeError,ValueError): continue
        if math.isfinite(time) and 0<time<duration and time-clean[-1]>=2.0:
            clean.append(time)
    clean.append(duration)
    chunks=[]
    cursor=0.0
    for boundary in clean[1:]:
        while boundary-cursor>max_seconds:
            chunks.append((cursor,cursor+max_seconds))
            cursor+=max_seconds
        if boundary-cursor>=min_seconds:
            chunks.append((cursor,boundary))
            cursor=boundary
    if duration-cursor>=min_seconds:
        chunks.append((cursor,duration))
    # Keep time order rather than falsely ranking images by their title.
    out=[]
    # Sample across the complete source, not only its first set of cuts.
    # Deterministic temporal coverage avoids silently missing late footage.
    if len(chunks)>limit:
        indices=[min(len(chunks)-1,round(i*(len(chunks)-1)/(limit-1))) for i in range(limit)] if limit>1 else [len(chunks)//2]
        chunks=[chunks[i] for i in indices]
    for start,end in chunks:
        if end-start<min_seconds:continue
        out.append({
          "timestamp_start":round(start,2),
          "timestamp_end":round(end,2),
          "title":f"Visual scene {len(out)+1}",
          "score":0,
          "reason":"Scene changes and duration heuristic only — review the actual footage.",
          "visual_only":True,
          "review_required":True,
          "clip_kind":"visual_draft",
        })
    return out

def scan_visual_scenes(video_path, *, max_seconds=600, threshold=.25, subprocess_run=subprocess.run):
    limit=max(30,min(600,int(max_seconds)))
    duration=_probe(video_path,subprocess_run=subprocess_run)
    args=["ffmpeg","-hide_banner","-nostdin","-loglevel","info",
          "-ss","0","-i",str(video_path),"-t",str(min(duration,limit)),
          "-vf",f"scale=320:-2,select='gt(scene,{threshold})',showinfo",
          "-an","-f","null","-"]
    try:
        result=subprocess_run(args,capture_output=True,text=True,
                              timeout=80)
    except subprocess.TimeoutExpired as exc:
        raise VisualSourceError("Scene detection timed out.") from exc
    if result.returncode:
        raise VisualSourceError("Scene detection could not finish.")
    cuts=[]
    for line in (result.stderr or "").splitlines():
        if "showinfo" not in line:continue
        match=PTS.search(line)
        if match:
            cuts.append(float(match.group(1)))
    scenes=windows_from_cuts(cuts,min(duration,limit))
    if not scenes:
        # Valid footage can contain one static scene; show honest review windows.
        scenes=windows_from_cuts([],min(duration,limit),min_seconds=3)
    return {"scenes":scenes,"duration_s":round(min(duration,limit),2),
            "method":"ffmpeg_scene_boundaries","review_required":True,
            "visual_ai_used":False}
