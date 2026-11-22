"""Small private candidate backups on the Mac; no recordings or live restore.

Copied embeddings remain unqualified. A backup checksum is not a replacement
for original collection provenance or fresh independent calibration.
"""
import json
import os
from pathlib import Path
from uuid import uuid4

from experiments.memory.queue_snapshot import _digest, _json
from tavi.recovery_bundle import safe_path
from tavi.speaker_evidence import Candidate, FAMILY, profile_revision

FORMAT = 'paprika-voice-candidates-offline-v1'


def copy_private(source, destination):
    source = safe_path(source)
    if not source.is_file() or source.stat().st_size > 1_000_000:
        raise ValueError('Bounded existing profile required')
    raw = source.read_bytes()
    with os.fdopen(os.open(destination, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600), 'wb') as out:
        out.write(raw);out.flush();os.fsync(out.fileno())
    return raw


def checkpoint(catalogue, parent):
    parent = safe_path(parent)
    if not parent.is_dir():raise ValueError('Existing private checkpoint destination required')
    catalogue.refresh()
    if set(catalogue.entries) != FAMILY:raise ValueError('Four reviewed candidate profiles required')
    revision = catalogue.revision
    folder = parent/('voice-checkpoint-'+uuid4().hex);folder.mkdir(mode=0o700)
    files = {}
    for person, entry in sorted(catalogue.entries.items()):
        name = person+'.json'
        raw = copy_private(entry['path'], folder/name)
        candidate = Candidate.from_bytes(raw)
        if candidate != entry['candidate']:raise ValueError('Candidate changed during backup')
        files[name] = candidate.profile_sha256
    catalogue.refresh()
    if catalogue.revision != revision:raise ValueError('Profile selection changed during backup')
    _json(folder/'manifest.json', {'format': FORMAT, 'complete': True, 'profiles_revision': revision,
        'files': files, 'raw_recordings_included': False, 'credentials_included': False,
        'spend_ledger_included': False, 'can_activate_live': False,
        'recognition_enabled': False, 'authorizes_personal_memory': False,
        'provenance_note': 'Original profile bytes retained. Original collection archives and calibration are separate; never infer qualification from this copy.'})
    verify(folder)
    return folder


def verify(folder):
    folder = safe_path(folder);manifest = safe_path(folder/'manifest.json')
    if not manifest.is_file() or manifest.stat().st_size > 16384:
        raise ValueError('Completed candidate checkpoint required')
    value = json.loads(manifest.read_text())
    if (value.get('format') != FORMAT or value.get('complete') is not True
            or any(value.get(k) is not False for k in ('raw_recordings_included','credentials_included',
                 'spend_ledger_included','can_activate_live','recognition_enabled','authorizes_personal_memory'))
            or not isinstance(value.get('files'),dict) or set(value['files']) != {p+'.json' for p in FAMILY}):
        raise ValueError('Unqualified voice checkpoint')
    candidates = []
    for name, sha in value['files'].items():
        file = safe_path(folder/name)
        if not file.is_file() or file.stat().st_size > 1_000_000 or _digest(file) != sha:
            raise ValueError('Candidate checkpoint changed')
        candidate = Candidate.from_bytes(file.read_bytes())
        if candidate.person_id+'.json' != name:raise ValueError('Candidate attribution changed')
        candidates.append(candidate)
    if profile_revision(tuple(candidates)) != value['profiles_revision']:
        raise ValueError('Candidate selection changed')
    return value


def restore_offline(folder, parent):
    folder, parent = safe_path(folder), safe_path(parent)
    value = verify(folder)
    if not parent.is_dir():raise ValueError('Existing restore destination required')
    target = parent/('voice-offline-restore-'+uuid4().hex);target.mkdir(mode=0o700)
    _json(target/'RESTORE_VOICE_OFFLINE_ONLY.json', {'automatic_selection_allowed': False,
        'recognition_enabled': False, 'authorizes_personal_memory': False,
        'reason': 'Review original provenance, compatible model and independent calibration before any explicit enrollment adoption.'})
    for name in value['files']:copy_private(folder/name, target/name)
    _json(target/'manifest.json', value)
    verify(target)
    return target
