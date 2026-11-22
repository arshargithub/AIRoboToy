"""Persist unique bank identity; never silently adopt a copied/legacy index."""
import json
import os
from pathlib import Path
import re
from uuid import uuid4


def native_directory(root,*,source_realm='household'):
    if source_realm not in ('fixture','household'):raise ValueError('Unknown source realm')
    root=Path(root)
    if root.is_symlink() or not root.is_dir():raise ValueError('Existing local household root required')
    manifest=root/'native-generation.json';native=root/'native'
    if native.is_symlink():raise ValueError('Native generation cannot be a symlink')
    if (native/'source-ledger.sqlite3').exists():
        raise ValueError('Legacy flat native index needs offline migration, not automatic adoption')
    if not manifest.exists():
        body={'version':1,'root':str(root.resolve()),'generation':uuid4().hex,'source_realm':source_realm}
        # Incomplete writes remain visible and block opening, rather than
        # silently assigning a different identity after a crash.
        try:
            with os.fdopen(os.open(manifest,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600),'w') as f:
                json.dump(body,f,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
            fd=os.open(root,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
        except FileExistsError:pass
    stat=manifest.lstat()
    if manifest.is_symlink() or not manifest.is_file() or stat.st_mode&0o077 or stat.st_size>2048:
        raise ValueError('Private native generation manifest required')
    value=json.loads(manifest.read_text())
    if (value.get('version')!=1 or value.get('root')!=str(root.resolve())
            or value.get('source_realm','fixture')!=source_realm
            or not isinstance(value.get('generation'),str) or not re.fullmatch('[a-f0-9]{32}',value['generation'])):
        raise ValueError('Native generation changed or was copied; offline reconciliation required')
    target=native/('household-'+value['generation'])
    if target.is_symlink():raise ValueError('Native generation cannot be a symlink')
    native.mkdir(mode=0o700,exist_ok=True);target.mkdir(mode=0o700,exist_ok=True)
    return target


def validate_worker_realm(directory,realm):
    """A trusted worker option cannot silently repurpose a household bank."""
    if realm not in ('fixture','household'):raise ValueError('Unknown source realm')
    directory=Path(directory);root=directory.parent.parent;manifest=root/'native-generation.json'
    if not manifest.exists():
        if realm=='household':raise ValueError('Household source generation must be explicit')
        return # Older experimental stores are fixtures, never household authority.
    if native_directory(root,source_realm=realm).resolve()!=directory.resolve():
        raise ValueError('Worker generation does not match its source realm')
