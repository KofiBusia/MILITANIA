from datetime import datetime, date
from extensions import db, bcrypt, login_manager
from flask_login import UserMixin

ADMIN_ROLES = {
    'SUPER_ADMIN':         {'label': 'Super Admin',          'level': 100},
    'ACCOUNT_MANAGER':     {'label': 'Account Manager',      'level': 40},
    'INVESTMENT_OFFICER':  {'label': 'Investment Officer',   'level': 50},
    'APPROVER':            {'label': 'Approver',             'level': 60},
    'REPORT_VIEWER':       {'label': 'Report Viewer',        'level': 10},
}
PERMISSION_MAP = {
    'manage_all': 100, 'create_account': 40, 'approve_account': 60,
    'enter_investment': 50, 'approve_investment': 60, 'view_reports': 10,
}

ASSET_CLASSES = ['MONEY_MARKET', 'BONDS', 'GLOBAL_EQUITIES', 'MUTUAL_FUNDS']
ASSET_LABELS = {
    'MONEY_MARKET': 'Money Market',
    'BONDS': 'Bonds & Fixed Income',
    'GLOBAL_EQUITIES': 'Global Equities',
    'MUTUAL_FUNDS': 'Mutual Funds & ETFs',
}

@login_manager.user_loader
def load_user(user_id):
    uid = str(user_id)
    if uid.startswith('admin_'):
        return AdminUser.query.get(int(uid.split('_')[1]))
    return ClientUser.query.get(int(uid))


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id         = db.Column(db.Integer, primary_key=True)
    actor_type = db.Column(db.String(20))
    actor_id   = db.Column(db.Integer)
    actor_name = db.Column(db.String(120))
    action     = db.Column(db.String(100))
    target     = db.Column(db.String(120), nullable=True)
    detail     = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AdminUser(UserMixin, db.Model):
    __tablename__ = 'admin_users'
    id            = db.Column(db.Integer, primary_key=True)
    staff_id      = db.Column(db.String(20), unique=True, nullable=False)
    full_name     = db.Column(db.String(120), nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role          = db.Column(db.String(40), nullable=False, default='REPORT_VIEWER')
    is_active     = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    last_login    = db.Column(db.DateTime, nullable=True)
    must_change_password = db.Column(db.Boolean, default=False)

    def get_id(self): return f'admin_{self.id}'
    def set_password(self, pw): self.password_hash = bcrypt.generate_password_hash(pw).decode('utf-8')
    def check_password(self, pw): return bcrypt.check_password_hash(self.password_hash, pw)
    def has_permission(self, p):
        return ADMIN_ROLES.get(self.role, {}).get('level', 0) >= PERMISSION_MAP.get(p, 100)
    @property
    def is_super_admin(self): return self.role == 'SUPER_ADMIN'


class ClientAccount(db.Model):
    __tablename__ = 'client_accounts'
    id                    = db.Column(db.Integer, primary_key=True)
    account_number        = db.Column(db.String(20), unique=True, nullable=False)
    full_name             = db.Column(db.String(150), nullable=False)
    email                 = db.Column(db.String(120), nullable=True)
    phone                 = db.Column(db.String(30), nullable=True)
    address               = db.Column(db.String(200), nullable=True)
    country               = db.Column(db.String(80), nullable=True)
    account_type          = db.Column(db.String(30), default='Individual')
    base_currency         = db.Column(db.String(5), default='USD')
    risk_profile          = db.Column(db.String(30), nullable=True)
    investment_objective  = db.Column(db.String(120), nullable=True)
    status                = db.Column(db.String(20), default='PENDING')  # PENDING, APPROVED, SUSPENDED
    created_at            = db.Column(db.DateTime, default=datetime.utcnow)
    created_by            = db.Column(db.Integer, nullable=True)

    @property
    def cash_balance(self):
        CREDIT = {'DEPOSIT', 'TRANSFER_IN', 'DIVIDEND', 'COUPON', 'SELL'}
        total = 0.0
        for t in self.transactions:
            if t.status == 'APPROVED':
                if t.txn_type in CREDIT:
                    total += t.amount
                else:
                    total -= t.amount
        return max(0.0, total)

    @property
    def pending_deposits(self):
        return sum(t.amount for t in self.transactions
                   if t.status == 'PENDING' and t.txn_type in ('DEPOSIT', 'TRANSFER_IN'))

    transactions = db.relationship('Transaction', backref='account',
                                    primaryjoin='foreign(Transaction.account_number)==ClientAccount.account_number',
                                    viewonly=True)


class ClientUser(UserMixin, db.Model):
    __tablename__ = 'client_users'
    id             = db.Column(db.Integer, primary_key=True)
    account_number = db.Column(db.String(20), nullable=False)
    phone          = db.Column(db.String(30), nullable=True)
    password_hash  = db.Column(db.String(256), nullable=True)
    is_active      = db.Column(db.Boolean, default=True)
    last_login     = db.Column(db.DateTime, nullable=True)
    must_change_password = db.Column(db.Boolean, default=False)

    def get_id(self): return str(self.id)
    def set_password(self, pw): self.password_hash = bcrypt.generate_password_hash(pw).decode('utf-8')
    def check_password(self, pw): return bool(self.password_hash) and bcrypt.check_password_hash(self.password_hash, pw)


class Investment(db.Model):
    __tablename__ = 'investments'
    id               = db.Column(db.Integer, primary_key=True)
    account_number   = db.Column(db.String(20), nullable=False)
    asset_class      = db.Column(db.String(30), nullable=False)
    symbol           = db.Column(db.String(20), nullable=True)
    security_name    = db.Column(db.String(150), nullable=True)
    issuer           = db.Column(db.String(150), nullable=True)
    sector           = db.Column(db.String(80), nullable=True)
    exchange         = db.Column(db.String(30), nullable=True)
    quantity         = db.Column(db.Float, nullable=True)
    unit_cost        = db.Column(db.Float, nullable=True)
    total_cost       = db.Column(db.Float, nullable=True)
    current_price    = db.Column(db.Float, nullable=True)
    live_price       = db.Column(db.Float, nullable=True)
    face_value       = db.Column(db.Float, nullable=True)
    interest_rate    = db.Column(db.Float, nullable=True)
    coupon_rate      = db.Column(db.Float, nullable=True)
    tenor            = db.Column(db.Integer, nullable=True)  # days
    trade_date       = db.Column(db.Date, nullable=True)
    maturity_date    = db.Column(db.Date, nullable=True)
    status           = db.Column(db.String(20), default='PENDING')  # PENDING, APPROVED, SOLD, REJECTED
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    approved_by      = db.Column(db.Integer, nullable=True)

    @property
    def days_run(self):
        return max(0, (date.today() - self.trade_date).days) if self.trade_date else 0

    @property
    def days_to_maturity(self):
        return max(0, (self.maturity_date - date.today()).days) if self.maturity_date else None

    @property
    def accrued_interest(self):
        if self.asset_class in ('MONEY_MARKET', 'BONDS') and self.face_value and (self.interest_rate or self.coupon_rate):
            rate = self.interest_rate or self.coupon_rate
            ref = self.trade_date
            days = max(0, (date.today() - ref).days) if ref else 0
            return self.face_value * (rate / 100) * days / 365
        return 0.0

    @property
    def computed_mkt_value(self):
        if self.asset_class == 'MONEY_MARKET':
            principal = self.face_value or self.total_cost or 0
            return principal + self.accrued_interest
        elif self.asset_class == 'BONDS':
            if self.face_value and (self.interest_rate or self.coupon_rate):
                return (self.face_value or 0) + self.accrued_interest
            return self.total_cost or 0
        elif self.asset_class in ('GLOBAL_EQUITIES', 'MUTUAL_FUNDS'):
            price = self.live_price if self.live_price is not None else self.current_price
            if self.quantity and price:
                return self.quantity * price
            return self.total_cost or 0
        return self.total_cost or 0


class Transaction(db.Model):
    __tablename__ = 'transactions'
    id             = db.Column(db.Integer, primary_key=True)
    account_number = db.Column(db.String(20), nullable=False)
    txn_type       = db.Column(db.String(20), nullable=False)  # DEPOSIT, WITHDRAWAL, TRANSFER_IN, TRANSFER_OUT, FEE, DIVIDEND, COUPON, BUY, SELL
    amount         = db.Column(db.Float, nullable=False)
    currency       = db.Column(db.String(5), default='USD')
    description    = db.Column(db.String(200), nullable=True)
    txn_date       = db.Column(db.Date, default=date.today)
    status         = db.Column(db.String(20), default='PENDING')
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    approved_by    = db.Column(db.Integer, nullable=True)
    reference      = db.Column(db.String(40), nullable=True)


class ClientRequest(db.Model):
    __tablename__ = 'client_requests'
    id             = db.Column(db.Integer, primary_key=True)
    account_number = db.Column(db.String(20), nullable=False)
    request_type   = db.Column(db.String(30), nullable=False)  # DEPOSIT, WITHDRAWAL, INVESTMENT, OTHER
    amount         = db.Column(db.Float, nullable=True)
    details        = db.Column(db.Text, nullable=True)
    status         = db.Column(db.String(20), default='PENDING')
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at    = db.Column(db.DateTime, nullable=True)


class FXRate(db.Model):
    __tablename__ = 'fx_rates'
    id         = db.Column(db.Integer, primary_key=True)
    base       = db.Column(db.String(5), nullable=False)
    quote      = db.Column(db.String(5), nullable=False)
    rate       = db.Column(db.Float, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)


class StockPrice(db.Model):
    __tablename__ = 'stock_prices'
    id                = db.Column(db.Integer, primary_key=True)
    symbol            = db.Column(db.String(20), nullable=False, unique=True)
    name              = db.Column(db.String(120), nullable=True)
    exchange          = db.Column(db.String(30), nullable=True)
    price             = db.Column(db.Float, nullable=True)
    change_pct        = db.Column(db.Float, nullable=True)
    is_manual_override = db.Column(db.Boolean, default=False)
    updated_at        = db.Column(db.DateTime, default=datetime.utcnow)
