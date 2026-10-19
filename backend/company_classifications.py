"""User company-nature choices; never changes participation or contracts."""
from copy import deepcopy
import uuid

from .company_profiles import PROFILE_LABELS, profile_fields


def validate_categories(categories):
    if (not isinstance(categories, list) or not categories or len(categories) > len(PROFILE_LABELS)
            or any(not isinstance(item, str) or item not in PROFILE_LABELS for item in categories)
            or len(set(categories)) != len(categories)
            or ('unknown' in categories and len(categories) != 1)):
        raise ValueError('기업 성격을 하나 이상 선택하십시오. 미확인은 단독으로 선택합니다.')
    return [category for category in PROFILE_LABELS if category in categories]


def apply_company_classification(ds, payload, stamp):
    allowed = {'company_id', 'categories', 'note', 'reset'}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ValueError('기업 성격 입력 항목을 확인하십시오.')
    cid = payload.get('company_id')
    if not isinstance(cid, str) or cid not in ds.get('companies', {}):
        raise ValueError('분류할 기업을 찾을 수 없습니다.')
    reset = payload.get('reset', False)
    if not isinstance(reset, bool):
        raise ValueError('자동 분류 복귀 값이 올바르지 않습니다.')
    if reset and 'categories' in payload:
        raise ValueError('자동 분류 복귀 시 기업 성격을 함께 지정하지 마십시오.')
    note = payload.get('note', '')
    if not isinstance(note, str) or len(note) > 1000:
        raise ValueError('기업 분류 메모는 1,000자 이내로 입력하십시오.')
    categories = None if reset else validate_categories(payload.get('categories'))
    current = ds.setdefault('company_classifications', {})
    previous = deepcopy(current.get(cid))
    history_id = 'classification-' + uuid.uuid4().hex
    if reset:
        current.pop(cid, None)
        updated = None
    else:
        updated = {'id': cid, 'company_id': cid, 'categories': categories,
                   'note': note.strip(), 'updated_at': stamp, 'history_id': history_id,
                   'basis': 'user_company_nature', 'project_role_separate': True}
        current[cid] = updated
    ds.setdefault('company_classification_history', {})[history_id] = {
        'id': history_id, 'company_id': cid, 'operation': 'reset' if reset else 'set',
        'previous': previous, 'current': deepcopy(updated), 'at': stamp,
        'note': note.strip(),
        'project_role_separate': True}
    audit_id = uuid.uuid4().hex
    ds.setdefault('audit', {})[audit_id] = {'id': audit_id, 'operation': 'company-classification',
        'company_id': cid, 'history_id': history_id, 'at': stamp}
    return {'company_id': cid, 'history_id': history_id,
            **profile_fields(ds['companies'][cid], updated)}
