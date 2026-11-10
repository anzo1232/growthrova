"""Timestamped contact sheets from decoded media, never automatic creative approval."""
from pathlib import Path
from PIL import Image, ImageDraw
import subprocess,json,hashlib,math,tempfile

class ReviewQueueError(ValueError): pass

def _run(args,timeout=15):
    try:
        result=subprocess.run(args,capture_output=True,check=True,timeout=timeout)
        if result.stderr.strip():
            raise ReviewQueueError('Media decoder reported an error')
        return result.stdout
    except (OSError,subprocess.SubprocessError) as exc:
        raise ReviewQueueError('Media could not be safely decoded') from exc

def generate(video_path,out_dir,*,samples=8):
    src=Path(video_path);target=Path(out_dir)
    if not src.is_file() or src.is_symlink() or src.suffix.lower()!='.mp4' or src.stat().st_size>70*1024*1024:
        raise ReviewQueueError('Missing or unsafe review video')
    if type(samples) is not int or not 4<=samples<=12:
        raise ReviewQueueError('Invalid review sampling')
    if target.is_symlink():raise ReviewQueueError('Unsafe review destination')
    digest=hashlib.sha256(src.read_bytes()).hexdigest()
    try:
        probe=json.loads(_run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,avg_frame_rate','-of','json',str(src)]))
        duration=float(probe['format']['duration'])
        stream=next(x for x in probe['streams'] if x.get('codec_type')=='video')
        rate=stream.get('avg_frame_rate','0/1').split('/')
        fps=float(rate[0])/float(rate[1]) if len(rate)==2 and float(rate[1]) else 0
        if not math.isfinite(duration) or not 1<=duration<=60:raise ValueError()
        if not math.isfinite(fps) or fps<=0:fps=4
    except (ValueError,KeyError,TypeError,StopIteration) as exc:
        raise ReviewQueueError('Invalid video metadata') from exc
    # Do not round a timestamp past the last actual decoded frame.
    end=max(0,duration-max(.05,1/fps)-.002)
    times=[round(min((i+.5)*duration/samples,end),6) for i in range(samples)]
    target.mkdir(parents=True,exist_ok=True)
    rows=math.ceil(samples/4)
    sheet=Image.new('RGB',(4*270,rows*520),(18,20,24));draw=ImageDraw.Draw(sheet)
    frames=[]
    with tempfile.TemporaryDirectory(prefix='.review-stage-',dir=target) as tmp:
        stage=Path(tmp)
        for i,second in enumerate(times):
            raw=_run(['ffmpeg','-v','error','-nostdin','-ss',str(second),'-i',str(src),'-frames:v','1',
                '-vf','scale=270:480:force_original_aspect_ratio=decrease,pad=270:480:(ow-iw)/2:(oh-ih)/2,format=rgb24',
                '-f','rawvideo','-pix_fmt','rgb24','pipe:1'])
            if len(raw)!=270*480*3:raise ReviewQueueError('Missing or malformed decoded frame')
            thumb=Image.frombytes('RGB',(270,480),raw)
            name=f'frame-{i+1:02}.jpg';dest=stage/name;thumb.save(dest,quality=89)
            x=(i%4)*270;y=(i//4)*520;sheet.paste(thumb,(x,y))
            draw.text((x+10,y+484),f'Frame {i+1:02} | {second:.2f}s',fill='white')
            frames.append({'index':i+1,'timeSeconds':second,'file':str(target/name),
                'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
        if hashlib.sha256(src.read_bytes()).hexdigest()!=digest:
            raise ReviewQueueError('Source changed during review')
        art=stage/'contact-sheet.jpg';sheet.save(art,quality=89)
        report={'sha256':digest,'sampledFrames':len(frames),'frames':frames,'gridRows':rows,'gridColumns':4,
            'durationSeconds':duration,'contactSheet':str(target/art.name),
            'contactSheetSha256':hashlib.sha256(art.read_bytes()).hexdigest(),
            'reviewStatus':'human_review_required','coverage':'sampled_frames_not_continuous_video_review',
            'checks':['subject_identity','scale_and_geometry','physics','temporal_continuity','business_claims','mobile_readability'],
            'approved':False,'published':False,'automaticCreativeAcceptance':False}
        (stage/'review.json').write_text(json.dumps(report,indent=2)+'\n')
        for item in stage.iterdir():item.replace(target/item.name)
    return report
