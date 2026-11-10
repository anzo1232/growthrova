"""Conservative source-pixel review-window boundary evidence; NEVER approval.

Pairs are decoded from the original MP4 on both sides of each two-second
review-window join, NOT detected video edits/shot cuts. They surface possible
continuity/physics concerns but do not prove realism, identify every real cut,
or authenticate a reviewer. They never authorise generation or publication.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

import business_media_replay as replay
import business_temporal_review as temporal


class BoundaryError(ValueError):
    pass


VERSION = 1
OFFSET_SECONDS = 0.125
# 'Temporal cuts' here are fixed review-window joins, NOT detected edit/scene cuts.
COVERAGE = 'all_temporal_cuts_original_decoded_still_pairs_not_motion_verdict'
PAIR_KEYS = {
    'boundaryId', 'previousWindowId', 'nextWindowId', 'atSeconds',
    'offsetSeconds', 'leftAtSeconds', 'rightAtSeconds',
    'leftFrameFile', 'rightFrameFile', 'pairFile',
    'leftFrameSha256', 'rightFrameSha256', 'pairSha256',
}
MANIFEST_KEYS = {
    'version', 'createdAt', 'sourceSha256', 'sourceFileSize',
    'sourceDurationSeconds', 'packetSha256', 'temporalManifestSha256',
    'boundaryCount', 'reviewDirectory', 'pairs', 'coverage',
    'wholeExportViewed', 'creativeApproved', 'canPublish', 'providerCalls',
    'networkRequests', 'limitations', 'manifestSha256',
}
NOTE_KEYS = {
    'boundaryId', 'leftFrameSha256', 'rightFrameSha256', 'category',
    'comparison', 'reviewOrigin', 'reviewerReference', 'observation',
}
CATEGORIES = {
    'subject_identity', 'scene_continuity', 'object_path', 'physical_mechanics',
    'forbidden_people', 'branding', 'other',
}
COMPARISONS = {'consistent', 'inconsistent', 'uncertain'}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _fingerprint(data):
    return hashlib.sha256(json.dumps(
        data, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
    ).encode()).hexdigest()


def _pair_meta(previous, following, index, duration, destination):
    boundary = previous['endSeconds']
    if previous['endSeconds'] != following['startSeconds']:
        raise BoundaryError('Source review windows must be contiguous')
    if not 0 < boundary < duration:
        raise BoundaryError('Boundary must lie strictly inside source duration')
    left = round(max(0.0, boundary-OFFSET_SECONDS), 6)
    right = round(min(duration-0.001, boundary+OFFSET_SECONDS), 6)
    if not left < boundary < right:
        raise BoundaryError('Cannot extract pixels either side of this boundary')
    prefix = f'boundary-{index:02}'
    return {
        'boundaryId': prefix,
        'previousWindowId': previous['windowId'],
        'nextWindowId': following['windowId'],
        'atSeconds': boundary, 'offsetSeconds': OFFSET_SECONDS,
        'leftAtSeconds': left, 'rightAtSeconds': right,
        'leftFrameFile': str(destination/f'{prefix}-left.png'),
        'rightFrameFile': str(destination/f'{prefix}-right.png'),
        'pairFile': str(destination/f'{prefix}-pair.png'),
    }


def _extract(source, requested_time, destination):
    """Decode the original locally; time is an extraction REQUEST, not a measured frame PTS."""
    try:
        subprocess.run([
            'ffmpeg', '-v', 'error', '-nostdin', '-i', str(source),
            '-ss', f'{requested_time:.6f}', '-frames:v', '1',
            '-c:v', 'png', str(destination),
        ], capture_output=True, check=True, timeout=30)
        with Image.open(destination) as image:
            image.verify()
        with Image.open(destination) as image:
            if min(image.size) < 32 or max(image.size) > 8192:
                raise BoundaryError('Decoded source frame has unsafe dimensions')
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise BoundaryError('Could not decode source pixels for cross-cut evidence') from exc
    return _sha(destination)


def _render_pair(left, right, left_time, right_time, dest):
    canvas = Image.new('RGB', (840, 760), '#171f24')
    draw = ImageDraw.Draw(canvas)
    for index, (filename, timestamp) in enumerate(((left, left_time), (right, right_time))):
        with Image.open(filename) as img:
            frame = ImageOps.contain(img.convert('RGB'), (400, 694))
        x = index*420+(420-frame.width)//2
        y = 42+(694-frame.height)//2
        canvas.paste(frame, (x, y))
        draw.text((index*420+14, 14), f'Original source requested t={timestamp:.3f}s',
                  fill='white')
    canvas.save(dest, format='PNG')


def prepare(video_path, packet, temporal_manifest, out_dir):
    """Build a complete cross-cut evidence folder; never mark a cut consistent."""
    try:
        temporal.verify_clips(video_path, packet, temporal_manifest)
    except (temporal.TemporalReviewError, replay.ReplayError, OSError) as exc:
        raise BoundaryError('Cannot prepare from unverified source/temporal evidence') from exc
    source = replay._safe_video(video_path)
    destination = Path(out_dir)
    if destination.is_symlink() or destination.exists() or not destination.parent.is_dir():
        raise BoundaryError('A fresh review destination with existing parent is required')
    source_hash = _sha(source)
    pairs = []
    with tempfile.TemporaryDirectory(prefix='.boundary-evidence-stage-', dir=destination.parent) as staging:
        stage = Path(staging)
        for index, (previous, following) in enumerate(
                zip(temporal_manifest['clips'], temporal_manifest['clips'][1:]), 1):
            entry = _pair_meta(previous, following, index, packet['durationSeconds'], destination)
            left = stage/Path(entry['leftFrameFile']).name
            right = stage/Path(entry['rightFrameFile']).name
            montage = stage/Path(entry['pairFile']).name
            entry['leftFrameSha256'] = _extract(source, entry['leftAtSeconds'], left)
            entry['rightFrameSha256'] = _extract(source, entry['rightAtSeconds'], right)
            _render_pair(left, right, entry['leftAtSeconds'], entry['rightAtSeconds'], montage)
            entry['pairSha256'] = _sha(montage)
            pairs.append(entry)
        if _sha(source) != source_hash:
            raise BoundaryError('Original source changed during frame extraction')
        result = {
            'version': VERSION, 'createdAt': datetime.now(timezone.utc).isoformat(),
            'sourceSha256': source_hash, 'sourceFileSize': source.stat().st_size,
            'sourceDurationSeconds': packet['durationSeconds'],
            'packetSha256': packet['packetSha256'],
            'temporalManifestSha256': temporal_manifest['manifestSha256'],
            'boundaryCount': len(pairs),
            'reviewDirectory': str(destination), 'pairs': pairs, 'coverage': COVERAGE,
            'wholeExportViewed': False, 'creativeApproved': False, 'canPublish': False,
            'providerCalls': 0, 'networkRequests': 0,
            'limitations': [
                'PNG files are decoded source frames at requested seek times; exact frame PTS is not independently recorded.',
                'Two adjacent stills do not establish motion physics, identity, genuine projects, or creative quality.',
                'Playback video from the temporal manifest is still required to assess moving objects.',
                'Reviewer origin is self-declared; favourable observations cannot approve delivery.',
            ],
        }
        result['manifestSha256'] = _fingerprint(result)
        (stage/'boundary-manifest.json').write_text(json.dumps(result, indent=2)+'\n')
        stage.replace(destination)
    verify(video_path, packet, temporal_manifest, result)
    return result


def verify(video_path, packet, temporal_manifest, evidence):
    """Re-decode original source pixels; a re-signed forged montage cannot pass."""
    try:
        temporal.verify_clips(video_path, packet, temporal_manifest)
        source = replay._safe_video(video_path)
    except (temporal.TemporalReviewError, replay.ReplayError, OSError) as exc:
        raise BoundaryError('Source or temporal manifest does not verify') from exc
    if not isinstance(evidence, dict) or set(evidence) != MANIFEST_KEYS:
        raise BoundaryError('Boundary evidence manifest is malformed')
    if evidence['manifestSha256'] != _fingerprint(
            {k: v for k, v in evidence.items() if k != 'manifestSha256'}):
        raise BoundaryError('Boundary evidence metadata has changed')
    if (evidence['version'] != VERSION or evidence['coverage'] != COVERAGE
            or evidence['wholeExportViewed'] is not False
            or evidence['creativeApproved'] is not False
            or evidence['canPublish'] is not False
            or type(evidence['providerCalls']) is not int or evidence['providerCalls'] != 0
            or type(evidence['networkRequests']) is not int or evidence['networkRequests'] != 0):
        raise BoundaryError('Evidence falsely claims review, approval or provider access')
    if (evidence['sourceSha256'] != packet['sourceSha256']
            or evidence['sourceSha256'] != _sha(source)
            or evidence['sourceFileSize'] != source.stat().st_size
            or evidence['sourceDurationSeconds'] != packet['durationSeconds']
            or evidence['packetSha256'] != packet['packetSha256']
            or evidence['temporalManifestSha256'] != temporal_manifest['manifestSha256']):
        raise BoundaryError('Cross-cut evidence belongs to a different source or replay')
    destination = Path(evidence['reviewDirectory'])
    if destination.is_symlink() or not destination.is_dir():
        raise BoundaryError('Evidence directory missing or unsafe')
    expected_count = max(0, len(temporal_manifest['clips'])-1)
    pairs = evidence['pairs']
    if (not isinstance(pairs, list) or len(pairs) != expected_count
            or evidence['boundaryCount'] != expected_count):
        raise BoundaryError('Not every cut has its own evidence pair')
    with tempfile.TemporaryDirectory(prefix='.boundary-verify-') as temp:
        for index, (actual, previous, following) in enumerate(
                zip(pairs, temporal_manifest['clips'], temporal_manifest['clips'][1:]), 1):
            expected = _pair_meta(previous, following, index, packet['durationSeconds'], destination)
            if not isinstance(actual, dict) or set(actual) != PAIR_KEYS or any(
                    actual[key] != value for key, value in expected.items()):
                raise BoundaryError('Boundary order, source time or frame path is forged')
            pngs = []
            for side in ('left', 'right'):
                path = Path(actual[f'{side}FrameFile'])
                if (path.is_symlink() or path.parent != destination or not path.is_file()
                        or path.name != f'boundary-{index:02}-{side}.png'):
                    raise BoundaryError('Source frame evidence is missing or swapped')
                try:
                    with Image.open(path) as image:
                        image.verify()
                except (OSError, ValueError) as exc:
                    raise BoundaryError('Original-frame evidence is not decodable') from exc
                if _sha(path) != actual[f'{side}FrameSha256']:
                    raise BoundaryError('Saved source frame was altered')
                extracted = Path(temp)/f'{index}-{side}.png'
                if _extract(source, actual[f'{side}AtSeconds'], extracted) != _sha(path):
                    raise BoundaryError('Saved frame does not match current source pixels')
                pngs.append(path)
            montage = Path(actual['pairFile'])
            if (montage.is_symlink() or montage.parent != destination
                    or montage.name != f'boundary-{index:02}-pair.png'
                    or not montage.is_file() or _sha(montage) != actual['pairSha256']):
                raise BoundaryError('Boundary contact pair is missing or altered')
            expected_pair = Path(temp)/f'expected-pair-{index}.png'
            _render_pair(pngs[0], pngs[1], actual['leftAtSeconds'],
                         actual['rightAtSeconds'], expected_pair)
            with Image.open(montage) as saved, Image.open(expected_pair) as reference:
                if saved.size != (840, 760) or saved.convert('RGB').tobytes() != reference.tobytes():
                    raise BoundaryError('Boundary montage is cropped or misleading')
    if _sha(source) != packet['sourceSha256']:
        raise BoundaryError('Source changed while verifying boundaries')
    return True


def assess(video_path, packet, temporal_manifest, evidence, notes,
           *, prior_temporal_assessment=None, prior_replay_assessment=None):
    """Attribute evidence-bound comparisons; never infer independent visual truth."""
    verify(video_path, packet, temporal_manifest, evidence)
    if not isinstance(notes, list) or len(notes) > 90:
        raise BoundaryError('A bounded list of comparison notes is required')
    prior = None
    if prior_temporal_assessment is not None or prior_replay_assessment is not None:
        if prior_temporal_assessment is not None and (
                not isinstance(prior_temporal_assessment, dict)
                or not isinstance(prior_temporal_assessment.get('observations'), list)):
            raise BoundaryError('Prior temporal review must carry its original observations')
        try:
            prior = temporal.assess_clip_findings(
                video_path, packet, temporal_manifest,
                prior_temporal_assessment['observations'] if prior_temporal_assessment else [],
                prior_replay_assessment=prior_replay_assessment,
            )
        except (temporal.TemporalReviewError, replay.ReplayError, ValueError, KeyError) as exc:
            raise BoundaryError('Prior temporal review does not verify') from exc
        if prior_temporal_assessment is not None and prior != prior_temporal_assessment:
            raise BoundaryError('Prior temporal claims were changed or are foreign to source')
    by_id = {entry['boundaryId']: entry for entry in evidence['pairs']}
    assessed, uncertain, rejected = set(), set(), False
    for item in notes:
        if not isinstance(item, dict) or set(item) != NOTE_KEYS:
            raise BoundaryError('Comparison must contain a complete evidence citation')
        expected = by_id.get(item['boundaryId'])
        if (expected is None or item['leftFrameSha256'] != expected['leftFrameSha256']
                or item['rightFrameSha256'] != expected['rightFrameSha256']):
            raise BoundaryError('Comparison references unrelated source pixels')
        if item['category'] not in CATEGORIES or item['comparison'] not in COMPARISONS:
            raise BoundaryError('Unsupported continuity question or finding')
        if item['reviewOrigin'] not in temporal.REVIEW_ORIGINS:
            raise BoundaryError('Cannot record AI self-label as independent comparison')
        if not isinstance(item['reviewerReference'], str) or not replay.REF.fullmatch(
                item['reviewerReference']):
            raise BoundaryError('Reviewer attribution is missing or malformed')
        observation = item['observation']
        if not isinstance(observation, str) or not 24 <= len(observation) <= 300 or any(
                ord(ch) < 32 for ch in observation):
            raise BoundaryError('Review requires a specific source-linked observation')
        if item['comparison'] == 'uncertain':
            uncertain.add(item['boundaryId'])
        assessed.add(item['boundaryId'])
        rejected |= item['comparison'] == 'inconsistent'
    pending = [b['boundaryId'] for b in evidence['pairs'] if b['boundaryId'] not in assessed]
    prior_rejected = bool(prior and prior['sourceSpecificRejection'])
    prior_unlocated = bool(prior and prior['priorReplayUnlocatedFeedback'])
    disposition = (
        'rejected_by_prior_or_boundary_finding' if prior_rejected else
        'rejected_by_attributed_boundary_finding' if rejected else
        'hold_prior_unlocated_feedback' if prior_unlocated else
        'hold_uncertain_boundary_evidence' if uncertain else
        'needs_boundary_review' if pending else
        'needs_independent_creative_review'
    )
    return {
        'version': VERSION, 'sourceSha256': packet['sourceSha256'],
        'packetSha256': packet['packetSha256'],
        'temporalManifestSha256': temporal_manifest['manifestSha256'],
        'boundaryManifestSha256': evidence['manifestSha256'],
        'observations': [dict(item) for item in notes],
        'assessedBoundaries': sorted(assessed),
        'unassessedBoundaries': pending, 'uncertainBoundaries': sorted(uncertain),
        'priorDisposition': prior['disposition'] if prior else None,
        'sourceSpecificRejection': prior_rejected or rejected,
        'disposition': disposition, 'qualityScore': None,
        'wholeExportViewed': False, 'creativeApproved': False, 'canPublish': False,
        'providerCalls': 0, 'networkRequests': 0,
        'limitations': [
            'Cross-cut stills cannot prove in-between motion or underlying project identity.',
            'Reviewer declarations are not independently authenticated or ground truth.',
            'Even fully consistent notes require independent creative and original-video review.',
        ],
    }
