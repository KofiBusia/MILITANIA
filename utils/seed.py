import os
import secrets
from extensions import db
from models import AdminUser, AssetClass, DEFAULT_ASSET_CLASSES


def seed_asset_classes():
    """Idempotent: only inserts classes that don't exist yet by code, so
    it never touches or duplicates ones a Super Admin has added since."""
    existing = {a.code for a in AssetClass.query.all()}
    added = 0
    for code, label in DEFAULT_ASSET_CLASSES:
        if code not in existing:
            db.session.add(AssetClass(code=code, label=label))
            added += 1
    if added:
        db.session.commit()
        print(f"[SEED] Added {added} default asset class(es)")


def _bootstrap_password():
    env_pw = os.environ.get('SUPER_ADMIN_PASSWORD')
    if env_pw:
        return env_pw
    return secrets.token_urlsafe(16)


def seed_super_admin():
    """Creates the default Super Admin (MA001) if it doesn't exist yet, and
    keeps its password in sync with SUPER_ADMIN_PASSWORD whenever that env
    var is set — so rotating the secret in Render and redeploying is
    enough to change it, no manual DB surgery required."""
    admin = AdminUser.query.filter_by(staff_id='MA001').first()
    env_pw = os.environ.get('SUPER_ADMIN_PASSWORD')
    if not admin:
        pw = _bootstrap_password()
        admin = AdminUser(
            staff_id='MA001', full_name='Super Administrator',
            email='admin@militania.invest', role='SUPER_ADMIN', is_active=True,
        )
        admin.set_password(pw)
        db.session.add(admin)
        db.session.commit()
        if not env_pw:
            print(f"[SEED] Created MA001 with a generated password: {pw}")
        else:
            print("[SEED] Created MA001 super admin from SUPER_ADMIN_PASSWORD env var")
    elif env_pw and not admin.check_password(env_pw):
        admin.set_password(env_pw)
        db.session.commit()
        print("[SEED] Synced MA001 password to current SUPER_ADMIN_PASSWORD env var")
