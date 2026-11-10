"""Offline playable, source-hashed temporal review derivatives and evidence anchors.

A segment can actually be watched, including its original audio if present.
The manifest proves only generation/decodability of derivatives, not that a
person viewed them or that any physical motion or creative decision is correct.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import business_media_replay as replay


class TemporalReviewError(ValueError):
    pass


VERSION = 1
HANDLE_SECONDS = 0.25  # adjacent clips overlap across every scene/window boundary
COVERAGE = 'full_timeline_playable_derivative_clips_not_verified_watching'
ENCODING = 'offline_ffmpeg_h264_aac_review_proxy_not_original_pixels'
MANIFEST_KEYS = {
    'version', 'createdAt', 'sourceSha256', 'sourceFileSize',
    'sourceDurationSeconds', 'sourceAudioPresent', 'packetSha256',
    'windowSeconds', 'reviewDirectory', 'derivativeEncoding', 'clips',
    'coverage', 'wholeExportViewed', 'creativeApproved', 'published',
    'providerCalls', 'networkRequests', 'limitations', 'manifestSha256',
}
CLIP_KEYS = {
    'windowId', 'startSeconds', 'endSeconds', 'playbackStartSeconds',
    'playbackEndSeconds', 'clipFile', 'clipSha256',
    'clipDurationSeconds', 'decodedVideoFrames', 'hasVideo', 'hasAudio',
}
NOTE_KEYS = {
    'windowId', 'clipSha256', 'atSeconds', 'category', 'severity',
    'reviewerReference', 'reviewOrigin', 'observation',
}
REVIEW_ORIGINS = {'manual_review_declared', 'customer_source_specific'}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _fingerprint(metadata):
    return hashlib.sha256(json.dumps(
        metadata, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
    ).encode()).hexdigest()


def _probe(path):
    try:
        process = subprocess.run(
            ['ffprobe', '-v', 'error', '-count_frames', '-show_entries',
             'format=duration:stream=codec_type,nb_read_frames', '-of', 'json',
             str(path)], capture_output=True, check=True, timeout=25,
        )
        data = json.loads(process.stdout)
        duration = float(data['format']['duration'])
        streams = data['streams']
        videos = [s for s in streams if s.get('codec_type') == 'video']
        audio = any(s.get('codec_type') == 'audio' for s in streams)
        frames = int(videos[0]['nb_read_frames'])
        if not math.isfinite(duration) or duration <= 0 or frames <= 0:
            raise ValueError()
        return {'duration': duration, 'audio': audio, 'video': bool(videos),
                'frames': frames}
    except (subprocess.SubprocessError, OSError, ValueError, KeyError,
            TypeError, IndexError) as exc:
        raise TemporalReviewError('Local derivative has no valid decoded video') from exc


def _source_and_packet(video_path, packet):
    try:
        source = replay._safe_video(video_path)
        replay._verify(source, packet)
    except (replay.ReplayError, OSError, ValueError, TypeError) as exc:
        raise TemporalReviewError('Original source or replay evidence failed verification') from exc
    stream = _probe(source)
    if abs(stream['duration'] - packet['durationSeconds']) > 0.05:
        raise TemporalReviewError('Replay duration is not the original source duration')
    return source, stream


def prepare_clips(video_path, packet, out_dir):
    """Create complete playable time-coded proxies offline, never creative approval."""
    source, stream = _source_and_packet(video_path, packet)
    destination = Path(out_dir)
    if destination.is_symlink() or destination.exists():
        raise TemporalReviewError('Fresh, unused review destination required')
    parent = destination.parent
    if not parent.is_dir():
        raise TemporalReviewError('Review parent directory must already exist')
    source_digest = _sha(source)
    segments = []
    with tempfile.TemporaryDirectory(prefix='.temporal-review-stage-', dir=parent) as staging:
        stage = Path(staging)
        for i, window in enumerate(packet['temporalWindows']):
            begin = window['startSeconds']
            end = window['endSeconds']
            playback_start = round(max(0.0, begin - HANDLE_SECONDS), 6)
            playback_end = round(min(packet['durationSeconds'], end + HANDLE_SECONDS), 6)
            filename = f'window-{i+1:02d}.mp4'
            clip = stage / filename
            # Accurate input-side decoding before output trim; never stream-copy
            # keyframe-aligned chunks that can include unrelated preceding frames.
            args = [
                'ffmpeg', '-v', 'error', '-nostdin', '-i', str(source),
                '-ss', f'{playback_start:.6f}', '-t', f'{playback_end-playback_start:.6f}',
                '-map', '0:v:0', '-map', '0:a:0?',
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19',
                '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '128k',
                '-movflags', '+faststart', str(clip),
            ]
            try:
                subprocess.run(args, capture_output=True, check=True, timeout=90)
            except (OSError, subprocess.SubprocessError) as exc:
                raise TemporalReviewError('Local video or audio clipping failed') from exc
            result = _probe(clip)
            if result['audio'] != stream['audio']:
                raise TemporalReviewError('Playable derivative silently omitted source audio')
            if abs(result['duration']-(playback_end-playback_start)) > 0.16:
                raise TemporalReviewError('Derivative clip duration does not match source window')
            segments.append({
                'windowId': window['id'], 'startSeconds': begin,
                'endSeconds': end, 'playbackStartSeconds': playback_start,
                'playbackEndSeconds': playback_end,
                'clipFile': str(destination / filename),
                'clipSha256': _sha(clip),
                'clipDurationSeconds': result['duration'],
                'decodedVideoFrames': result['frames'],
                'hasVideo': result['video'], 'hasAudio': result['audio'],
            })
        if _sha(source) != source_digest or source_digest != packet['sourceSha256']:
            raise TemporalReviewError('Original source changed during derivative generation')
        manifest = {
            'version': VERSION, 'createdAt': datetime.now(timezone.utc).isoformat(),
            'sourceSha256': source_digest, 'sourceFileSize': source.stat().st_size,
            'sourceDurationSeconds': packet['durationSeconds'],
            'sourceAudioPresent': stream['audio'],
            'packetSha256': packet['packetSha256'],
            'windowSeconds': packet['windowSeconds'],
            'reviewDirectory': str(destination),
            'derivativeEncoding': ENCODING, 'clips': segments,
            'coverage': COVERAGE,
            'wholeExportViewed': False, 'creativeApproved': False,
            'published': False, 'providerCalls': 0, 'networkRequests': 0,
            'limitations': [
                'Proxies are re-encoded; confirm pixel-level faults against original media.',
                'Complete playable timeline is not evidence a reviewer watched it.',
                'Neither clip generation nor annotations prove physics or identity realism.',
                'Creative acceptance and publication are prohibited by this artifact.',
            ],
        }
        manifest['manifestSha256'] = _fingerprint(manifest)
        (stage / 'temporal-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        stage.replace(destination)
    verify_clips(source, packet, manifest)
    return manifest


def verify_clips(video_path, packet, manifest):
    """Fail closed on stale source, missing/wrong videos and overstated coverage."""
    source, stream = _source_and_packet(video_path, packet)
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_KEYS:
        raise TemporalReviewError('Malformed or incomplete temporal manifest')
    fp = manifest['manifestSha256']
    if not isinstance(fp, str) or fp != _fingerprint(
        {k: v for k, v in manifest.items() if k != 'manifestSha256'}
    ):
        raise TemporalReviewError('Temporal manifest metadata changed')
    if (manifest['version'] != VERSION or manifest['coverage'] != COVERAGE
            or manifest['derivativeEncoding'] != ENCODING
            or manifest['wholeExportViewed'] is not False
            or manifest['creativeApproved'] is not False
            or manifest['published'] is not False
            or manifest['providerCalls'] != 0 or manifest['networkRequests'] != 0):
        raise TemporalReviewError('Unsupported visual coverage or approval assertion')
    if (manifest['sourceSha256'] != packet['sourceSha256']
            or manifest['sourceSha256'] != _sha(source)
            or manifest['sourceFileSize'] != source.stat().st_size
            or manifest['sourceDurationSeconds'] != packet['durationSeconds']
            or manifest['sourceAudioPresent'] is not stream['audio']
            or manifest['packetSha256'] != packet['packetSha256']
            or manifest['windowSeconds'] != packet['windowSeconds']):
        raise TemporalReviewError('Temporal evidence is not bound to this source and packet')
    directory = Path(manifest['reviewDirectory'])
    if directory.is_symlink() or not directory.is_dir():
        raise TemporalReviewError('Temporal review directory is missing or unsafe')
    clips = manifest['clips']
    windows = packet['temporalWindows']
    if not isinstance(clips, list) or len(clips) != len(windows):
        raise TemporalReviewError('Playable temporal windows are incomplete')
    for i, (segment, window) in enumerate(zip(clips, windows)):
        if not isinstance(segment, dict) or set(segment) != CLIP_KEYS:
            raise TemporalReviewError('Invalid clip evidence structure')
        if (segment['windowId'] != window['id']
                or segment['startSeconds'] != window['startSeconds']
                or segment['endSeconds'] != window['endSeconds']
                or segment['playbackStartSeconds'] != round(max(0.0, window['startSeconds'] - HANDLE_SECONDS), 6)
                or segment['playbackEndSeconds'] != round(min(packet['durationSeconds'], window['endSeconds'] + HANDLE_SECONDS), 6)):
            raise TemporalReviewError('Temporal clips are misordered or misaligned')
        clip = Path(segment['clipFile'])
        if (clip.is_symlink() or clip.parent != directory
                or clip.name != f'window-{i+1:02d}.mp4' or not clip.is_file()
                or _sha(clip) != segment['clipSha256']):
            raise TemporalReviewError('Playable clip is missing, replaced or tampered')
        actual = _probe(clip)
        if (segment['hasVideo'] is not True
                or segment['hasAudio'] is not stream['audio']
                or actual['video'] is not True
                or actual['audio'] is not stream['audio']
                or type(segment['decodedVideoFrames']) is not int
                or actual['frames'] != segment['decodedVideoFrames']
                or type(segment['clipDurationSeconds']) not in (float, int)
                or not math.isfinite(segment['clipDurationSeconds'])
                or abs(actual['duration'] - segment['clipDurationSeconds']) > 0.005
                or abs(actual['duration'] - (
                    segment['playbackEndSeconds'] - segment['playbackStartSeconds'])) > 0.16):
            raise TemporalReviewError('Video playback duration, audio or frame evidence differs')
    if _sha(source) != packet['sourceSha256']:
        raise TemporalReviewError('Source modified while verifying timeline')
    return True


def assess_clip_findings(video_path, packet, manifest, findings, *, prior_replay_assessment=None):
    """Record clip-specific *attributed claims*, never certify that clips were watched."""
    verify_clips(video_path, packet, manifest)
    if not isinstance(findings, list) or len(findings) > 90:
        raise TemporalReviewError('Bounded attributed review findings required')
    prior_rejected = False
    prior_unlocated = False
    prior_disposition = None
    if prior_replay_assessment is not None:
        if (not isinstance(prior_replay_assessment, dict)
                or not isinstance(prior_replay_assessment.get('observations'), list)):
            raise TemporalReviewError('A prior replay must contain original attributed findings')
        try:
            checked_prior = replay.assess(
                video_path, packet, prior_replay_assessment['observations'])
        except (replay.ReplayError, ValueError, TypeError, KeyError) as exc:
            raise TemporalReviewError('The prior replay is not verifiable') from exc
        if prior_replay_assessment != checked_prior:
            raise TemporalReviewError('Prior review claims have changed or belong to other media')
        prior_rejected = checked_prior['sourceSpecificRejection']
        prior_unlocated = any(
            item['type'] == 'project_feedback' for item in checked_prior['observations'])
        prior_disposition = checked_prior['disposition']
    by_id = {s['windowId']: s for s in manifest['clips']}
    annotated = set()
    rejected = False
    for note in findings:
        if not isinstance(note, dict) or set(note) != NOTE_KEYS:
            raise TemporalReviewError('Finding must have a complete, exact clip citation')
        clip = by_id.get(note['windowId'])
        if clip is None or note['clipSha256'] != clip['clipSha256']:
            raise TemporalReviewError('Finding is not bound to this playable clip')
        t = note['atSeconds']
        if type(t) not in (float, int) or not math.isfinite(t) or not (
            clip['startSeconds'] <= t < clip['endSeconds']
        ):
            raise TemporalReviewError('Specific timestamp must be inside the cited clip')
        if note['category'] not in replay.CATEGORIES or note['severity'] not in replay.SEVERITIES:
            raise TemporalReviewError('Invalid creative concern or severity')
        origin = note['reviewOrigin']
        if origin not in REVIEW_ORIGINS:
            raise TemporalReviewError('Unsupported or self-generated quality evidence origin')
        ref = note['reviewerReference']
        if not isinstance(ref, str) or not replay.REF.fullmatch(ref):
            raise TemporalReviewError('Attribution reference is missing')
        observation = note['observation']
        if not isinstance(observation, str) or not 24 <= len(observation) <= 300 or any(
            ord(c) < 32 for c in observation
        ):
            raise TemporalReviewError('Evidence requires a specific bounded observation')
        annotated.add(clip['windowId'])
        rejected |= note['severity'] in {'major', 'critical'}
    pending = [w['id'] for w in packet['temporalWindows'] if w['id'] not in annotated]
    disposition = (
        'rejected_by_prior_or_clip_finding' if prior_rejected else
        'rejected_by_attributed_clip_finding' if rejected else
        'hold_prior_unlocated_feedback' if prior_unlocated else
        'needs_independent_creative_review' if not pending else
        'needs_temporal_review'
    )
    return {
        'version': VERSION,
        'sourceSha256': packet['sourceSha256'],
        'packetSha256': packet['packetSha256'],
        'manifestSha256': manifest['manifestSha256'],
        'annotatedWindows': sorted(annotated),
        'unannotatedWindows': pending,
        'observations': [dict(note) for note in findings],
        'sourceSpecificRejection': rejected or prior_rejected,
        'priorReplayDisposition': prior_disposition,
        'priorReplaySourceSpecificRejection': prior_rejected,
        'priorReplayUnlocatedFeedback': prior_unlocated,
        'disposition': disposition,
        'wholeExportViewed': False,
        'qualityScore': None, 'creativeApproved': False, 'published': False,
        'canPublish': False, 'providerCalls': 0, 'networkRequests': 0,
        'limitations': [
            'Manual notes and derivative clips are not verified independent viewing.',
            'Positive annotations are not artistic or physical-realism acceptance.',
        ],
    }
