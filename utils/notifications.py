from flask import request
from flask_login import current_user
from extensions import db
from models import AuditLog


def audit(action, target=None, detail=None, actor=None):
    a = actor or (current_user if current_user.is_authenticated else None)
    actor_type = 'admin' if a and hasattr(a, 'staff_id') else ('client' if a else 'system')
    actor_name = getattr(a, 'staff_id', None) or getattr(a, 'account_number', None) or 'system'
    log = AuditLog(
        actor_type=actor_type,
        actor_id=getattr(a, 'id', None),
        actor_name=str(actor_name),
        action=action,
        target=target,
        detail=detail,
    )
    db.session.add(log)
    db.session.commit()
