"""Offline source-decoded scene-change CANDIDATES; never creative approval.

Detected ffmpeg showinfo PTS is a measured source-frame time, not a validated
author edit, identity/physics finding, or proof no other cuts exist. Evidence is
bound to original bytes, complete replay, and playable derivative manifests.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import business_boundary_evidence as boundary
import business_media_replay as replay
import business_temporal_review as temporal

VERSION = 1
SCENE_THRESHOLD = 0.20
OFFSET_SECONDS = 0.125
MAX_CANDIDATES = 90
COVERAGE = 'source_scene_change_candidates_not_exhaustive_edit_detection'
DETECTOR = 'ffmpeg_select_gt_scene_0.20_showinfo_original_source_pts'
PTS_PATTERN = re.compile(r'Parsed_showinfo_\d+.*?\bn:\s*\d+\s+pts:\s*-?\d+\s+pts_time:\s*([0-9]+(?:\.[0-9]+)?)')
MANIFEST_KEYS = {
    'version', 'createdAt', 'sourceSha256', 'sourceFileSize',
    'sourceDurationSeconds', 'packetSha256', 'temporalManifestSha256',
    'sceneThreshold', 'detector', 'candidateCount', 'reviewDirectory',
    'candidates', 'coverage', 'wholeExportViewed', 'creativeApproved',
    'canPublish', 'providerCalls', 'networkRequests', 'limitations', 'manifestSha256',
}
CANDIDATE_KEYS = {
    'candidateId', 'sourcePtsSeconds', 'reviewWindowId',
    'leftAtSeconds', 'rightAtSeconds', 'leftFrameFile', 'rightFrameFile',
    'pairFile', 'leftFrameSha256', 'rightFrameSha256', 'pairSha256',
}
NOTE_KEYS = {
    'candidateId', 'sourcePtsSeconds', 'leftFrameSha256',
    'rightFrameSha256', 'category', 'comparison', 'reviewOrigin',
    'reviewerReference', 'observation',
}
CATEGORIES = {
    'subject_identity', 'scene_continuity', 'object_path', 'physical_mechanics',
    'forbidden_people', 'branding', 'other',
}
COMPARISONS = {'consistent', 'inconsistent', 'uncertain'}


class SceneCutError(ValueError):
    pass


def _sha(path):
    return boundary._sha(path)


def _fingerprint(data):
    return boundary._fingerprint(data)


def _source(video_path, packet, temporal_manifest):
    try:
        temporal.verify_clips(video_path, packet, temporal_manifest)
        source = replay._safe_video(video_path)
    except (temporal.TemporalReviewError, replay.ReplayError, ValueError, OSError,
            TypeError, KeyError) as exc:
        raise SceneCutError('Original source, replay or temporal manifest does not verify') from exc
    return source


def _scan(source, duration):
    """Return every ffmpeg-selected source-frame PTS, not inferred edit times."""
    expression = f"select='gt(scene,{SCENE_THRESHOLD:.2f})',showinfo"
    try:
        p = subprocess.run(
            ['ffmpeg', '-hide_banner', '-v', 'info', '-nostdin', '-i', str(source),
             '-vf', expression, '-an', '-f', 'null', '-'],
            capture_output=True, check=True, timeout=95,
        )
        log = p.stderr.decode('utf-8', errors='replace')
    except (OSError, subprocess.SubprocessError) as exc:
        raise SceneCutError('Source-frame scene-change scan failed closed') from exc
    if len(log) > 8_000_000:
        raise SceneCutError('Detector output exceeds safe bound')
    hits = []
    for line in log.splitlines():
        match = PTS_PATTERN.search(line)
        if not match:
            continue
        timestamp = round(float(match.group(1)), 6)
        if not math.isfinite(timestamp) or not 0 < timestamp < duration:
            raise SceneCutError('Detector returned an invalid source time')
        if hits and timestamp <= hits[-1]:
            raise SceneCutError('Detector returned repeated or unsorted frame PTS')
        hits.append(timestamp)
        if len(hits) > MAX_CANDIDATES:
            raise SceneCutError('Too many candidates for trustworthy bounded review')
    # Missing/unknown FFmpeg diagnostics should never become proof of zero cuts.
    if 'showinfo' not in log and not hits:
        # A zero-change scan normally logs a filter line via a Parsed_showinfo
        # configuration message. A missing filter is an execution incompatibility.
        if 'Parsed_select_' not in log:
            raise SceneCutError('Scene-change filter diagnostics unavailable')
    return hits


def _candidate(source_pts, index, duration, temporal_manifest, dest):
    left = round(max(0.0, source_pts-OFFSET_SECONDS), 6)
    right = round(min(duration-0.001, source_pts+OFFSET_SECONDS), 6)
    if not left < source_pts < right:
        raise SceneCutError('Candidate is too close to a source boundary')
    windows = [w for w in temporal_manifest['clips']
               if w['startSeconds'] <= source_pts < w['endSeconds']]
    if len(windows) != 1:
        raise SceneCutError('Detected source PTS does not map to one review window')
    prefix = f'scene-candidate-{index:02d}'
    return {
        'candidateId': prefix, 'sourcePtsSeconds': source_pts,
        'reviewWindowId': windows[0]['windowId'],
        'leftAtSeconds': left, 'rightAtSeconds': right,
        'leftFrameFile': str(dest/f'{prefix}-left.png'),
        'rightFrameFile': str(dest/f'{prefix}-right.png'),
        'pairFile': str(dest/f'{prefix}-pair.png'),
    }


def _decode(source, time, filename):
    try:
        return boundary._extract(source, time, filename)
    except boundary.BoundaryError as exc:
        raise SceneCutError('Could not re-decode original scene pixels') from exc


def _pair(left, right, left_time, right_time, filename):
    try:
        boundary._render_pair(left, right, left_time, right_time, filename)
    except (OSError, ValueError) as exc:
        raise SceneCutError('Could not render source-linked comparison') from exc


def prepare(video_path, packet, temporal_manifest, out_dir):
    """Create a complete inventory of *detector candidates*, never assert coverage of every cut."""
    source = _source(video_path, packet, temporal_manifest)
    dest = Path(out_dir)
    if dest.is_symlink() or dest.exists() or not dest.parent.is_dir():
        raise SceneCutError('Fresh unused destination with existing parent required')
    sha = _sha(source)
    duration = packet['durationSeconds']
    timestamps = _scan(source, duration)
    candidates = []
    with tempfile.TemporaryDirectory(prefix='.scene-cut-stage-', dir=dest.parent) as staging:
        stage = Path(staging)
        for index, pts in enumerate(timestamps, 1):
            entry = _candidate(pts, index, duration, temporal_manifest, dest)
            left = stage/Path(entry['leftFrameFile']).name
            right = stage/Path(entry['rightFrameFile']).name
            pair_file = stage/Path(entry['pairFile']).name
            entry['leftFrameSha256'] = _decode(source, entry['leftAtSeconds'], left)
            entry['rightFrameSha256'] = _decode(source, entry['rightAtSeconds'], right)
            _pair(left, right, entry['leftAtSeconds'], entry['rightAtSeconds'], pair_file)
            entry['pairSha256'] = _sha(pair_file)
            candidates.append(entry)
        if _sha(source) != sha:
            raise SceneCutError('Original source changed during scene analysis')
        result = {
            'version': VERSION, 'createdAt': datetime.now(timezone.utc).isoformat(),
            'sourceSha256': sha, 'sourceFileSize': source.stat().st_size,
            'sourceDurationSeconds': duration,
            'packetSha256': packet['packetSha256'],
            'temporalManifestSha256': temporal_manifest['manifestSha256'],
            'sceneThreshold': SCENE_THRESHOLD, 'detector': DETECTOR,
            'candidateCount': len(candidates), 'reviewDirectory': str(dest),
            'candidates': candidates, 'coverage': COVERAGE,
            'wholeExportViewed': False, 'creativeApproved': False,
            'canPublish': False, 'providerCalls': 0, 'networkRequests': 0,
            'limitations': [
                'FFmpeg luminance/colour scene-score threshold produces candidates, not a complete edit decision list.',
                'PTS identifies the selected original decoded frame; nearby PNGs are requested seeks, not verified PTS.',
                'A scene change does not prove a bad identity, continuity, drop trajectory, or simulated project.',
                'An empty candidate list does not mean an entire video has been watched or contains no real cuts.',
                'Declared reviewer notes are not authenticated independent ground truth or creative approval.',
            ],
        }
        result['manifestSha256'] = _fingerprint(result)
        (stage/'scene-cut-manifest.json').write_text(json.dumps(result, indent=2)+'\n')
        stage.replace(dest)
    verify(video_path, packet, temporal_manifest, result)
    return result


def verify(video_path, packet, temporal_manifest, evidence):
    """Re-run actual scene detection and source pixel extraction, not just hash metadata."""
    source = _source(video_path, packet, temporal_manifest)
    if not isinstance(evidence, dict) or set(evidence) != MANIFEST_KEYS:
        raise SceneCutError('Malformed candidate evidence')
    if evidence['manifestSha256'] != _fingerprint({
        k: v for k, v in evidence.items() if k != 'manifestSha256'
    }):
        raise SceneCutError('Candidate evidence metadata has changed')
    if (evidence['version'] != VERSION or evidence['sceneThreshold'] != SCENE_THRESHOLD
            or evidence['detector'] != DETECTOR or evidence['coverage'] != COVERAGE
            or evidence['wholeExportViewed'] is not False
            or evidence['creativeApproved'] is not False
            or evidence['canPublish'] is not False
            or type(evidence['providerCalls']) is not int or evidence['providerCalls'] != 0
            or type(evidence['networkRequests']) is not int or evidence['networkRequests'] != 0):
        raise SceneCutError('Untrusted detector settings or claimed creative approval')
    if (evidence['sourceSha256'] != _sha(source)
            or evidence['sourceSha256'] != packet['sourceSha256']
            or evidence['sourceFileSize'] != source.stat().st_size
            or evidence['sourceDurationSeconds'] != packet['durationSeconds']
            or evidence['packetSha256'] != packet['packetSha256']
            or evidence['temporalManifestSha256'] != temporal_manifest['manifestSha256']):
        raise SceneCutError('Scene evidence does not match this exact original source')
    dest = Path(evidence['reviewDirectory'])
    if dest.is_symlink() or not dest.is_dir():
        raise SceneCutError('Missing or unsafe scene review directory')
    saved = dest/'scene-cut-manifest.json'
    if saved.is_symlink() or not saved.is_file():
        raise SceneCutError('Original candidate manifest is missing')
    try:
        persisted = json.loads(saved.read_text())
    except (OSError, UnicodeError, ValueError) as exc:
        raise SceneCutError('Saved candidate manifest is not decodable') from exc
    if persisted != evidence:
        raise SceneCutError('Saved candidate manifest differs from verified evidence')
    timestamps = _scan(source, packet['durationSeconds'])
    entries = evidence['candidates']
    if (not isinstance(entries, list) or len(entries) != len(timestamps)
            or evidence['candidateCount'] != len(timestamps)):
        raise SceneCutError('Incomplete or inflated detected candidate inventory')
    with tempfile.TemporaryDirectory(prefix='.scene-cut-verify-') as tmp:
        root = Path(tmp)
        for index, (pts, entry) in enumerate(zip(timestamps, entries), 1):
            expected = _candidate(pts, index, packet['durationSeconds'], temporal_manifest, dest)
            if (not isinstance(entry, dict) or set(entry) != CANDIDATE_KEYS
                    or any(entry[k] != v for k, v in expected.items())):
                raise SceneCutError('Forged, reordered or retimed scene candidate')
            for side in ('left', 'right'):
                stored = Path(entry[f'{side}FrameFile'])
                if (stored.is_symlink() or stored.parent != dest or not stored.is_file()
                        or stored.name != f'scene-candidate-{index:02d}-{side}.png'
                        or _sha(stored) != entry[f'{side}FrameSha256']):
                    raise SceneCutError('Candidate original-frame evidence missing or altered')
                decoded = root/f'{index}-{side}.png'
                if _decode(source, entry[f'{side}AtSeconds'], decoded) != _sha(stored):
                    raise SceneCutError('Candidate source pixels do not match original video')
            pair_file = Path(entry['pairFile'])
            if (pair_file.is_symlink() or pair_file.parent != dest
                    or pair_file.name != f'scene-candidate-{index:02d}-pair.png'
                    or not pair_file.is_file() or _sha(pair_file) != entry['pairSha256']):
                raise SceneCutError('Candidate comparison image is missing or changed')
            expected_pair = root/f'{index}-pair.png'
            _pair(entry['leftFrameFile'], entry['rightFrameFile'],
                  entry['leftAtSeconds'], entry['rightAtSeconds'], expected_pair)
            if _sha(pair_file) != _sha(expected_pair):
                raise SceneCutError('Comparison montage is cropped, swapped or re-signed')
    if _sha(source) != packet['sourceSha256']:
        raise SceneCutError('Source changed during candidate verification')
    return True


def assess(video_path, packet, temporal_manifest, evidence, notes,
           *, prior_temporal_assessment=None, prior_replay_assessment=None):
    """Record source-bound allegations, preserving earlier failures, never release."""
    verify(video_path, packet, temporal_manifest, evidence)
    if not isinstance(notes, list) or len(notes) > 90:
        raise SceneCutError('Bounded observation list required')
    prior = None
    if prior_temporal_assessment is not None or prior_replay_assessment is not None:
        if prior_temporal_assessment is not None and (
                not isinstance(prior_temporal_assessment, dict)
                or not isinstance(prior_temporal_assessment.get('observations'), list)):
            raise SceneCutError('Prior review lacks its original observations')
        try:
            prior = temporal.assess_clip_findings(
                video_path, packet, temporal_manifest,
                prior_temporal_assessment['observations'] if prior_temporal_assessment else [],
                prior_replay_assessment=prior_replay_assessment,
            )
        except (temporal.TemporalReviewError, replay.ReplayError,
                ValueError, KeyError, TypeError) as exc:
            raise SceneCutError('Prior review does not verify against original source') from exc
        if prior_temporal_assessment is not None and prior != prior_temporal_assessment:
            raise SceneCutError('Prior temporal verdict or evidence was changed')
    by_id = {c['candidateId']: c for c in evidence['candidates']}
    observed, uncertain, negative, seen = set(), set(), False, set()
    for note in notes:
        if not isinstance(note, dict) or set(note) != NOTE_KEYS:
            raise SceneCutError('Observation lacks complete source evidence citation')
        expected = by_id.get(note['candidateId'])
        if (expected is None or note['sourcePtsSeconds'] != expected['sourcePtsSeconds']
                or note['leftFrameSha256'] != expected['leftFrameSha256']
                or note['rightFrameSha256'] != expected['rightFrameSha256']):
            raise SceneCutError('Observation is unrelated to measured scene source pixels')
        key = (note['candidateId'], note['category'])
        if key in seen:
            raise SceneCutError('Duplicate category assessment at one candidate')
        seen.add(key)
        if note['category'] not in CATEGORIES or note['comparison'] not in COMPARISONS:
            raise SceneCutError('Unsupported failure category or review finding')
        if note['reviewOrigin'] not in temporal.REVIEW_ORIGINS:
            raise SceneCutError('Self-generated labels are not independent evidence')
        if not isinstance(note['reviewerReference'], str) or not replay.REF.fullmatch(
                note['reviewerReference']):
            raise SceneCutError('Reviewer reference is invalid')
        observation = note['observation']
        if not isinstance(observation, str) or not 24 <= len(observation) <= 300 or any(
                ord(ch) < 32 for ch in observation):
            raise SceneCutError('Review observation must be specific and attributable')
        observed.add(note['candidateId'])
        if note['comparison'] == 'uncertain':
            uncertain.add(note['candidateId'])
        negative |= note['comparison'] == 'inconsistent'
    pending = [c['candidateId'] for c in evidence['candidates']
               if c['candidateId'] not in observed]
    prior_negative = bool(prior and prior['sourceSpecificRejection'])
    prior_unlocated = bool(prior and prior['priorReplayUnlocatedFeedback'])
    disposition = (
        'rejected_by_prior_or_candidate_finding' if prior_negative else
        'rejected_by_attributed_candidate_finding' if negative else
        'hold_prior_unlocated_feedback' if prior_unlocated else
        'hold_uncertain_scene_change' if uncertain else
        'needs_candidate_review' if pending else
        'needs_independent_original_video_review'
    )
    return {
        'version': VERSION, 'sourceSha256': packet['sourceSha256'],
        'packetSha256': packet['packetSha256'],
        'temporalManifestSha256': temporal_manifest['manifestSha256'],
        'sceneManifestSha256': evidence['manifestSha256'],
        'observations': [dict(note) for note in notes],
        'unassessedCandidates': pending, 'uncertainCandidates': sorted(uncertain),
        'priorDisposition': prior['disposition'] if prior else None,
        'sourceSpecificRejection': prior_negative or negative,
        'disposition': disposition, 'qualityScore': None,
        'wholeExportViewed': False, 'creativeApproved': False,
        'canPublish': False, 'providerCalls': 0, 'networkRequests': 0,
        'limitations': [
            'Detector candidates can omit cuts, especially fades, animation and visually similar edits.',
            'Review observations are declarations, not authenticated independent source labels.',
            'Whole-source playback and motion/physical realism evaluation remain required.',
        ],
    }
