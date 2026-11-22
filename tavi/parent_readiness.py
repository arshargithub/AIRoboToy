"""Local parent-reported account status. Never grants child-cloud authorization."""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .experiment_workflow import ROOT

STATUSES=('not_sure','not_enabled','enabled')
SCOPES=('not_checked','explicit_zdr','inherits_zdr')


def save_readiness(body, *, root=None):
    status,scope=body.get('status'),body.get('scope')
    if status not in STATUSES or scope not in SCOPES:raise ValueError('Choose an account status and project scope')
    if status!='enabled' and scope!='not_checked':raise ValueError('Project scope requires reported ZDR approval')
    record={'kind':'paprika_parent_readiness','schema_version':1,'reported_status':status,'reported_project_scope':scope,
        'provider_or_account_verified':False,'child_cloud_authorized':False,
        'policy_checked_date':'2026-11-04','reported_utc':datetime.now(timezone.utc).isoformat(),
        'interpretation':'Parent report only. Provider approval, exact runtime project and endpoint eligibility must be verified before personal child data is processed remotely.'}
    raw=json.dumps(record,sort_keys=True,separators=(',',':')).encode()
    folder=Path(root) if root else ROOT/'.tavi/private-parent-readiness';folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    if sum(p.stat().st_size for p in folder.glob('*.json'))+len(raw)>1_000_000:raise ValueError('Readiness results folder full; existing files preserved')
    path=folder/(hashlib.sha256(raw).hexdigest()+'.json')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=folder,prefix='.readiness-',delete=False) as stream:
            temporary=Path(stream.name);stream.write(raw);stream.flush();os.fsync(stream.fileno())
        try:os.link(temporary,path)
        except FileExistsError:
            if path.read_bytes()!=raw:raise ValueError('Saved status integrity mismatch')
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return {'saved':True,'file':path.name,'child_cloud_authorized':False,
        'next':'We will review the reported account scope before any child trial. Adult/synthetic work remains allowed.'}
