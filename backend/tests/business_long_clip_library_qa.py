"""Isolated real-media QA: export multiple independent clips, not a montage.

No accounts, billing, publishing or production writes. Caller supplies local video.
"""
import argparse
import json
import subprocess
from pathlib import Path
from business_visual import scan_visual_scenes

def export(source, destination, count=12):
    source=Path(source).resolve(strict=True)
    destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    analysis=scan_visual_scenes(str(source))
    candidates=[s for s in analysis['scenes'] if 3<=s['timestamp_end']-s['timestamp_start']<=30]
    if len(candidates)<count:raise RuntimeError('Insufficient validated source windows')
    # Uniform timeline sample. No claim of AI scene ranking.
    picks=[candidates[round(i*(len(candidates)-1)/(count-1))] for i in range(count)]
    report=[]
    for i,s in enumerate(picks,1):
        path=destination/f'clip-{i:02d}.mp4'
        start=float(s['timestamp_start']);duration=float(s['timestamp_end'])-start
        cmd=['ffmpeg','-hide_banner','-nostdin','-loglevel','error','-y',
            '-ss',str(start),'-i',str(source),'-t',str(round(duration,3)),
            '-vf','scale=360:640:force_original_aspect_ratio=increase,crop=360:640,setsar=1',
            '-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p',
            '-c:a','aac','-b:a','96k','-movflags','+faststart',str(path)]
        subprocess.run(cmd,check=True,timeout=75,capture_output=True)
        check=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries',
             'format=duration:stream=codec_type,width,height','-of','json',str(path)],text=True,timeout=12))
        assert path.stat().st_size>1500 and check['streams'][0]['width']==360
        assert check['streams'][0]['height']==640
        record={'index':i,'source_start_s':start,'duration_s':round(float(check['format']['duration']),2),
                'bytes':path.stat().st_size,'filename':path.name}
        report.append(record)
        print('CLIP_READY',json.dumps(record),flush=True)
    (destination/'manifest.json').write_text(json.dumps({'source_duration_s':analysis['duration_s'],
        'candidate_count':len(candidates),'clips':report},indent=2))
    print('BATCH_COMPLETE',len(report),'clips',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source');parser.add_argument('destination')
    parser.add_argument('--count',type=int,default=12);args=parser.parse_args()
    if not 2<=args.count<=24:parser.error('Choose 2–24 test clips')
    export(args.source,args.destination,args.count)
