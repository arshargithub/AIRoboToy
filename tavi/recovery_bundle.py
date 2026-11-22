"""Source-first local recovery bundles. No inference, live restore or job replay.

Native derivatives can be regenerated; canonical words, attribution, tombstones
and ambiguous job states cannot. A bundle is a checkpoint, never evidence that
no later deletion happened. Spending and voice profiles are deliberately outside
this archive and are never rolled back by it.
"""
import json
from pathlib import Path
import re
from uuid import uuid4

from experiments.memory.queue_snapshot import (
    _guard, _digest, _json, _read_db, _summary, snapshot_queue, verify_snapshot, restore_offline,
)
from tavi.memory_generation import native_directory

FORMAT = 'paprika-source-recovery-v1'


def safe_path(path):
    path = _guard(Path(path).absolute())
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Recovery paths cannot contain symlinks')
    return path


def records(path):
    db = _read_db(safe_path(path))
    try:
        db.execute('BEGIN')
        _summary(db)
        return {'epoch': db.execute('SELECT revocation_epoch FROM learning_meta WHERE id=1').fetchone()[0],
                'rows': [dict(zip(('id','sha','state','revision','job'), row)) for row in
                         db.execute('SELECT id,sha,state,revision,job FROM learning ORDER BY id')]}
    finally:
        db.rollback();db.close()


def create_bundle(root, parent, *, source_realm):
    root, parent = safe_path(root), safe_path(parent)
    manifest = root/'native-generation.json'
    if not manifest.is_file():
        raise ValueError('An existing generation is required; never assign one during backup')
    if manifest.stat().st_size > 2048:
        raise ValueError('Bounded generation manifest required')
    original = manifest.read_bytes()
    native_directory(root, source_realm=source_realm)  # Validates root/mode/realm binding.
    if not parent.is_dir():
        raise ValueError('Existing backup destination required')
    target = parent/('source-recovery-'+uuid4().hex)
    target.mkdir(mode=0o700)
    archive = snapshot_queue(safe_path(root/'learning.sqlite3'), target)
    _json(target/'original-generation.json', json.loads(original))
    if manifest.read_bytes() != original:
        raise ValueError('Generation changed during backup; retain incomplete bundle')
    value = {'format': FORMAT, 'complete': True, 'source_realm': source_realm,
             'queue_archive': archive.name, 'queue_manifest_sha256': _digest(archive/'manifest.json'),
             'generation_sha256': _digest(target/'original-generation.json'),
             'native_derivatives_included': False, 'spend_ledger_included': False,
             'voice_profiles_included': False, 'can_activate_live': False,
             'automatic_replay_allowed': False}
    _json(target/'manifest.json', value)
    verify_bundle(target)
    return target


def verify_bundle(folder):
    folder = safe_path(folder)
    file = safe_path(folder/'manifest.json')
    if not file.is_file() or file.stat().st_size > 16384:
        raise ValueError('Completed recovery manifest required')
    value = json.loads(file.read_text())
    if (value.get('format') != FORMAT or value.get('complete') is not True
            or value.get('source_realm') not in ('fixture','household')
            or any(value.get(k) is not False for k in (
                'native_derivatives_included','spend_ledger_included','voice_profiles_included',
                'can_activate_live','automatic_replay_allowed'))
            or not re.fullmatch(r'queue-snapshot-[a-f0-9]{32}', value.get('queue_archive',''))):
        raise ValueError('Unqualified recovery bundle')
    generation = safe_path(folder/'original-generation.json')
    archive = safe_path(folder/value['queue_archive'])
    if (_digest(generation) != value['generation_sha256']
            or _digest(safe_path(archive/'manifest.json')) != value['queue_manifest_sha256']):
        raise ValueError('Recovery bundle changed')
    original = json.loads(generation.read_text())
    if original.get('source_realm','fixture') != value['source_realm']:
        raise ValueError('Recovery realm changed')
    verify_snapshot(archive)
    return value


def restore_bundle(folder, parent):
    folder, parent = safe_path(folder), safe_path(parent)
    value = verify_bundle(folder)
    # restore_offline writes quarantine BEFORE copying any database bytes.
    target = restore_offline(folder/value['queue_archive'], parent)
    _json(target/'original-generation.json', json.loads((folder/'original-generation.json').read_text()))
    _json(target/'recovery-origin.json', {'format': FORMAT, 'source_realm': value['source_realm'],
                                        'bundle_manifest_sha256': _digest(folder/'manifest.json')})
    return target


def rebuild_plan(restored, *, current_queue=None):
    """Return a review plan, never make a restored queue live or spend money."""
    restored = safe_path(restored)
    marker = restored/'RESTORE_OFFLINE_ONLY.json'
    if not marker.is_file() or json.loads(marker.read_text()).get('automatic_replay_allowed') is not False:
        raise ValueError('Quarantined offline copy required')
    # Verify the restored bytes against the original queue archive before reading.
    manifest = json.loads((restored/'restored-manifest.json').read_text())
    if _digest(restored/'queue.sqlite3') != manifest['database_sha256']:
        raise ValueError('Restored source bytes changed')
    view = records(restored/'queue.sqlite3')
    equal = None if current_queue is None else view == records(current_queue)
    states = {s: [r['id'] for r in view['rows'] if r['state'] == s]
              for s in ('complete','pending','working','revoked')}
    status = ('stale_checkpoint' if equal is False else 'needs_job_reconciliation' if states['working']
              else 'needs_authority_review' if equal is None else 'needs_native_rebuild')
    return {'status': status, 'matches_current_authority': equal, 'revocation_epoch': view['epoch'],
            'completed_source_candidates': states['complete'], 'pending_not_replayed': states['pending'],
            'ambiguous_not_replayed': states['working'], 'excluded_revoked': states['revoked'],
            'requires_new_native_generation': True, 'requires_explicit_inference_budget': True,
            'requires_projection_verification': True, 'can_activate_live': False,
            'automatic_replay_allowed': False,
            'warning': 'If the latest authority is lost, this checkpoint cannot prove absence of later corrections or deletions.'}
