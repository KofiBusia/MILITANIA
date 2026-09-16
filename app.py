import os
from flask import Flask, render_template
from flask_cors import CORS
from datetime import datetime

from extensions import db, login_manager, bcrypt

DB_SCHEMA = 'militania'  # namespaces every table inside the shared Postgres
                          # database so this app can never collide with, or
                          # accidentally read/write, another app's tables.


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')

    default_sqlite_path = os.path.join(app.instance_path, 'militania.db').replace('\\', '/')
    os.makedirs(app.instance_path, exist_ok=True)
    database_url = os.environ.get('DATABASE_URL', f'sqlite:///{default_sqlite_path}')
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
    is_postgres = database_url.startswith('postgresql://')

    is_production = os.environ.get('RENDER') is not None
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = is_production
    app.config['REMEMBER_COOKIE_HTTPONLY'] = True
    app.config['REMEMBER_COOKIE_SECURE'] = is_production

    # Schema isolation must happen BEFORE models.py is imported anywhere,
    # since SQLAlchemy reads db.metadata.schema at Table-construction time
    # (i.e. at model class-definition time), not later.
    if is_postgres:
        db.metadata.schema = DB_SCHEMA

    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    @app.after_request
    def _security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if is_production:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    from routes.public import public_bp
    from routes.auth import auth_bp
    from routes.admin import admin_bp
    from routes.user import user_bp
    from routes.api import api_bp
    from routes.reports import reports_bp
    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(user_bp, url_prefix='/portfolio')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(reports_bp, url_prefix='/reports')

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    with app.app_context():
        def _safe(fn, label):
            try:
                fn()
            except Exception as e:
                db.session.rollback()
                print(f"[STARTUP] {label} failed and was skipped: {e}")

        pg_lock_conn = None
        if is_postgres:
            from sqlalchemy import text as _text
            pg_lock_conn = db.engine.connect()
            pg_lock_conn.execute(_text('SELECT pg_advisory_lock(991177001)'))
        try:
            from utils.schema_migrate import ensure_schema
            _safe(lambda: ensure_schema(DB_SCHEMA if is_postgres else None), 'ensure_schema')
            _safe(db.create_all, 'db.create_all')
            from utils.seed import seed_super_admin
            _safe(seed_super_admin, 'seed_super_admin')
            from utils.market_data import fetch_fx_rates, fetch_global_prices
            _safe(fetch_fx_rates, 'fetch_fx_rates')
            _safe(fetch_global_prices, 'fetch_global_prices')
        finally:
            if pg_lock_conn is not None:
                from sqlalchemy import text as _text
                pg_lock_conn.execute(_text('SELECT pg_advisory_unlock(991177001)'))
                pg_lock_conn.close()

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True, port=5050, host='0.0.0.0')
