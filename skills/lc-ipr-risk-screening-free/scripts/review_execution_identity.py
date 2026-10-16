"""Read-only recovery of host-issued execution identities; historical audits stay immutable."""
from copy import deepcopy
from pathlib import Path
from common import load_json, sha256_file, sha256_json

REVISION = 'stable-native-run-id-v1'


def identity_fields(run_id):
    return {'execution_identity_revision': REVISION, 'run_id': run_id}


def audit_identity(audit):
    present = 'execution_identity_revision' in audit or 'run_id' in audit
    if not present:
        return None
    if (audit.get('execution_identity_revision') != REVISION
            or not isinstance(audit.get('run_id'), str) or not audit['run_id'].strip()):
        raise ValueError('FINAL_REVIEW_RETAINED_IDENTITY_INVALID')
    return audit['run_id']


def record_from_audit(directory, audit, raw, run_id):
    return {'module_id': audit['module_id'], 'chain_id': audit['chain_id'],
        'session_id': audit['session_id'], 'agent_id': audit['session_id'], 'run_id': run_id,
        'input_digest': audit['input_digest'], 'packet_sha256': audit['packet_sha256'],
        'judgment': deepcopy(raw),
        'host_audit': {'path': str(Path(directory)/'audit.json'),
                       'sha256': sha256_file(Path(directory)/'audit.json')}}


def recovery_index(output_dir, digest, frozen_sha256, material):
    """Collect only records bound by validated own-chain reviews or completed summaries."""
    from final_review import validate_envelope
    from module_review import _validate_retained_integrity, summary_digests_echoed
    from report_review_host import parse_agent_trace
    root=Path(output_dir)
    result={'records': {}, 'reviews': {}, 'module_consumers': set(), 'final_consumers': set()}
    receipt=root/'freeze-receipt.json'
    if receipt.is_file() and load_json(receipt).get('status') == 'pair_validated':
        result['final_consumers'].update(('1','2'))
    def remember(record, chain):
        if (not isinstance(record, dict) or record.get('chain_id') != chain
                or record.get('input_digest') != digest or not isinstance(record.get('run_id'), str)
                or not record['run_id'].strip()):
            raise ValueError('FINAL_REVIEW_RETAINED_IDENTITY_INVALID')
        from module_review import SYNTHETIC_REVISIONS
        if record.get('synthetic') in SYNTHETIC_REVISIONS:
            # r6: a fallback module or program summary has no native session; validate_envelope recomputed it
            result['records'][(chain,record['module_id'],record['session_id'])]=deepcopy(record)
            return
        host=record.get('host_audit') or {}
        audit_path=Path(str(host.get('path') or ''))
        if not audit_path.is_file() or sha256_file(audit_path) != host.get('sha256'):
            raise ValueError('FINAL_REVIEW_RETAINED_AUDIT_CHANGED')
        audit=load_json(audit_path)
        _validate_retained_integrity(audit_path.parent, record['session_id'], record['judgment'], digest, frozen_sha256)
        session, raw=parse_agent_trace((audit_path.parent/'events.jsonl').read_text(encoding='utf-8', errors='replace'))
        identity=audit_identity(audit)
        if (session != record['session_id'] or raw != record['judgment']
                or identity is not None and identity != record['run_id']
                or record_from_audit(audit_path.parent, audit, raw, record['run_id']) != record):
            raise ValueError('FINAL_REVIEW_RETAINED_IDENTITY_CONFLICT')
        key=(chain,record['module_id'],session)
        if key in result['records'] and result['records'][key] != record:
            raise ValueError('FINAL_REVIEW_RETAINED_IDENTITY_CONFLICT')
        result['records'][key]=deepcopy(record)
    for chain in ('1','2'):
        parent=root/chain
        review_path=parent/'review.json'
        if review_path.exists():
            result['final_consumers'].add(chain)
            review=load_json(review_path)
            validate_envelope(review, material)
            execution=review['review_context']['execution']
            integrated=execution.get('integrated_execution')
            modules=execution.get('module_execution')
            if integrated:
                rows=[integrated['record']]
            elif modules:
                rows=[*modules['modules'],modules['summary']]
            else:
                raise ValueError('FINAL_REVIEW_RETAINED_IDENTITY_INVALID')
            for record in rows: remember(record,chain)
            result['reviews'][chain]=review
        if not parent.is_dir():
            continue
        for directory in sorted(parent.iterdir()):
            if not directory.is_dir() or not (directory.name=='summary' or directory.name.startswith('summary.attempt-')):
                continue
            result['module_consumers'].add(chain)
            audit_path=directory/'audit.json'
            if audit_path.is_file():
                _validate_retained_integrity(directory,None,None,digest,frozen_sha256)
            packet_path,trace_path=directory/'packet.json',directory/'events.jsonl'
            if not packet_path.is_file() or not trace_path.is_file():
                continue
            packet=load_json(packet_path)
            try:
                _,raw=parse_agent_trace(trace_path.read_text(encoding='utf-8',errors='replace'))
            except (ValueError,KeyError,TypeError):
                continue  # Incomplete native output is not an identity witness.
            rows=packet.get('modules')
            if (packet.get('chain_id') != chain or packet.get('evidence_digest') != digest
                    or not isinstance(rows,list)
                    or (summary_digests_echoed(packet.get('task'))
                        and raw.get('module_review_digests') != [sha256_json(row) for row in rows])):
                continue
            for record in rows: remember(record,chain)
    return result


def retained_identity(index, directory, chain, group, session):
    """No new identity can replace a record already consumed by downstream work."""
    audit_path=Path(directory)/'audit.json'
    if not audit_path.is_file():
        return None
    audit=load_json(audit_path)
    identity=audit_identity(audit)
    original=index['records'].get((str(chain),group,session))
    if original:
        if identity is not None and identity != original['run_id']:
            raise ValueError('FINAL_REVIEW_RETAINED_IDENTITY_CONFLICT')
        return original['run_id']
    if identity is not None:
        return identity
    downstream=(str(chain) in index['final_consumers'] or
                group not in {'summary','integrated'} and str(chain) in index['module_consumers'])
    if downstream:
        raise ValueError('FINAL_REVIEW_RETAINED_IDENTITY_UNCONFIRMED')
    # The legacy no-consumer recovery convention is deterministic. Do not add
    # fields to its historical audit or infer a lost native PID/exit code.
    return 'retained-trace-'+session
