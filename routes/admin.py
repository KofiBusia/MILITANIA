from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_required, current_user
from extensions import db
from models import (AdminUser, ClientAccount, ClientUser, Investment, Transaction, ClientRequest,
                     ADMIN_ROLES, AssetClass, get_asset_classes, get_asset_labels)
from utils.notifications import audit
from datetime import datetime, date

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*a, **kw):
        if not current_user.is_authenticated or session.get('user_type') != 'admin':
            return redirect(url_for('auth.login'))
        return f(*a, **kw)
    return decorated


def permission_required(permission):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*a, **kw):
            if not current_user.is_authenticated or session.get('user_type') != 'admin':
                return redirect(url_for('auth.login'))
            if not current_user.has_permission(permission):
                flash('Insufficient permissions.', 'error')
                return redirect(url_for('admin.dashboard'))
            return f(*a, **kw)
        return decorated
    return decorator


def _float(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def _parse_date(s):
    if not s: return None
    try: return datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError: return None


@admin_bp.route('/')
@admin_required
def dashboard():
    from utils.market_data import refresh_if_stale, get_fx_rate, get_all_fx
    refresh_if_stale()
    total_accounts = ClientAccount.query.filter_by(status='APPROVED').count()
    pending_accounts = ClientAccount.query.filter_by(status='PENDING').count()
    investments = Investment.query.filter_by(status='APPROVED').all()
    pending_investments = Investment.query.filter_by(status='PENDING').count()
    pending_transactions = Transaction.query.filter_by(status='PENDING').count()
    pending_requests = ClientRequest.query.filter_by(status='PENDING').count()
    aum = sum(i.computed_mkt_value for i in investments)
    total_cash = sum(a.cash_balance for a in ClientAccount.query.filter_by(status='APPROVED').all())
    total_aum = aum + total_cash
    recent_txns = Transaction.query.order_by(Transaction.created_at.desc()).limit(10).all()
    asset_labels = get_asset_labels()
    by_class = {}
    for inv in investments:
        lbl = asset_labels.get(inv.asset_class, inv.asset_class)
        by_class[lbl] = by_class.get(lbl, 0) + inv.computed_mkt_value
    fx = get_all_fx()
    return render_template('admin/dashboard.html',
        total_accounts=total_accounts, pending_accounts=pending_accounts,
        total_investments=len(investments), pending_investments=pending_investments,
        pending_transactions=pending_transactions, pending_requests=pending_requests,
        total_aum=total_aum, total_cash=total_cash, recent_txns=recent_txns,
        by_class=by_class, fx=fx, now=date.today())


@admin_bp.route('/accounts')
@admin_required
def accounts():
    q = request.args.get('q', ''); status = request.args.get('status', '')
    query = ClientAccount.query
    if q:
        query = query.filter((ClientAccount.account_number.ilike(f'%{q}%')) |
                              (ClientAccount.full_name.ilike(f'%{q}%')))
    if status:
        query = query.filter_by(status=status)
    return render_template('admin/accounts.html',
        accounts=query.order_by(ClientAccount.created_at.desc()).all(), q=q, status=status)


@admin_bp.route('/accounts/new', methods=['GET', 'POST'])
@permission_required('create_account')
def new_account():
    if request.method == 'POST':
        last = ClientAccount.query.order_by(ClientAccount.id.desc()).first()
        acc_no = f'MI-{(last.id+1 if last else 1):05d}'
        acc = ClientAccount(
            account_number=acc_no,
            full_name=request.form.get('full_name'), email=request.form.get('email'),
            phone=request.form.get('phone'), address=request.form.get('address'),
            country=request.form.get('country'), account_type=request.form.get('account_type', 'Individual'),
            risk_profile=request.form.get('risk_profile'),
            investment_objective=request.form.get('investment_objective'),
            status='APPROVED', created_by=current_user.id,
        )
        db.session.add(acc)
        db.session.flush()
        phone = request.form.get('phone', '')
        db.session.add(ClientUser(account_number=acc_no, phone=phone, is_active=True))
        db.session.commit()
        audit('ACCOUNT_CREATE', target=acc_no, detail=acc.full_name)
        flash(f'Account {acc_no} created and approved.', 'success')
        return redirect(url_for('admin.accounts'))
    return render_template('admin/account_form.html')


@admin_bp.route('/accounts/<int:acc_id>')
@admin_required
def view_account(acc_id):
    from utils.market_data import refresh_if_stale, get_all_fx
    refresh_if_stale()
    acc = ClientAccount.query.get_or_404(acc_id)
    investments = Investment.query.filter_by(account_number=acc.account_number, status='APPROVED').all()
    pending_invs = Investment.query.filter_by(account_number=acc.account_number, status='PENDING').all()
    all_txns = Transaction.query.filter_by(account_number=acc.account_number)\
                    .order_by(Transaction.txn_date.desc()).all()
    pending_reqs = ClientRequest.query.filter_by(account_number=acc.account_number, status='PENDING').all()
    return render_template('admin/account_view.html', acc=acc, investments=investments,
        pending_invs=pending_invs, transactions=all_txns, pending_reqs=pending_reqs, fx=get_all_fx())


@admin_bp.route('/accounts/<int:acc_id>/approve', methods=['POST'])
@permission_required('approve_account')
def approve_account(acc_id):
    acc = ClientAccount.query.get_or_404(acc_id)
    acc.status = 'APPROVED'
    db.session.commit()
    audit('ACCOUNT_APPROVED', target=acc.account_number)
    flash(f'Account {acc.account_number} approved.', 'success')
    return redirect(url_for('admin.accounts'))


@admin_bp.route('/investments')
@admin_required
def investments():
    q = request.args.get('q', ''); status = request.args.get('status', ''); asset_class = request.args.get('asset_class', '')
    query = Investment.query
    if q: query = query.filter(Investment.account_number.ilike(f'%{q}%'))
    if status: query = query.filter_by(status=status)
    if asset_class: query = query.filter_by(asset_class=asset_class)
    return render_template('admin/investments.html',
        investments=query.order_by(Investment.created_at.desc()).all(),
        q=q, status=status, asset_class=asset_class, asset_classes=get_asset_classes(), asset_labels=get_asset_labels())


@admin_bp.route('/investments/new', methods=['GET', 'POST'])
@permission_required('enter_investment')
def new_investment():
    accounts = ClientAccount.query.filter_by(status='APPROVED').order_by(ClientAccount.full_name).all()
    if request.method == 'POST':
        acc_no = request.form.get('account_number')
        acc = ClientAccount.query.filter_by(account_number=acc_no).first()
        if not acc:
            flash('Account not found.', 'error'); return redirect(request.url)
        asset_class = request.form.get('asset_class', '').upper()
        trade_date = _parse_date(request.form.get('trade_date')) or date.today()

        symbol = security_name = issuer = sector = exchange = None
        quantity = unit_cost = total_cost = current_price = None
        face_value = interest_rate = coupon_rate = None
        tenor = maturity_date = None
        commission_note = ''

        if asset_class in ('GSE_EQUITIES', 'GLOBAL_EQUITIES'):
            symbol = request.form.get('symbol')
            security_name = request.form.get('security_name')
            sector = request.form.get('sector')
            exchange = 'GSE' if asset_class == 'GSE_EQUITIES' else request.form.get('exchange')
            quantity = _float(request.form.get('eq_quantity'))
            purchase_price = _float(request.form.get('eq_purchase_price'))
            cp_input = _float(request.form.get('eq_current_price'))
            price_currency = request.form.get('eq_currency', 'USD')
            commission_pct = _float(request.form.get('eq_commission_pct'))
            if commission_pct is None:
                commission_pct = 2.5 if asset_class == 'GSE_EQUITIES' else 0.0

            fx = 1.0
            if price_currency == 'GHS':
                from utils.market_data import get_fx_rate
                fx = get_fx_rate('GHS', 'USD')

            unit_cost = round(purchase_price * fx, 6) if purchase_price else None
            current_price = round(cp_input * fx, 6) if cp_input else unit_cost
            if quantity and unit_cost:
                principal = quantity * unit_cost
                total_cost = round(principal * (1 + commission_pct / 100), 4)
                commission_note = f' commission={commission_pct}% ({price_currency} entry)'

        elif asset_class in ('MONEY_MARKET', 'GOVT_SECURITIES'):
            issuer = request.form.get('mm_issuer')
            face_value = _float(request.form.get('mm_face_value'))
            interest_rate = _float(request.form.get('mm_interest_rate'))
            tenor = int(request.form.get('mm_tenor')) if request.form.get('mm_tenor') else None
            maturity_date = _parse_date(request.form.get('mm_maturity_date'))
            total_cost = face_value

        elif asset_class in ('BONDS', 'EUROBONDS'):
            issuer = request.form.get('bond_issuer')
            face_value = _float(request.form.get('bond_face_value'))
            coupon_rate = _float(request.form.get('bond_coupon_rate'))
            maturity_date = _parse_date(request.form.get('bond_maturity_date'))
            total_cost = face_value

        elif asset_class == 'MUTUAL_FUNDS':
            security_name = request.form.get('mf_security_name')
            sector = request.form.get('mf_fund_type')
            quantity = _float(request.form.get('mf_units'))
            unit_cost = _float(request.form.get('mf_unit_cost'))
            current_price = _float(request.form.get('mf_nav')) or unit_cost
            if quantity and unit_cost:
                total_cost = round(quantity * unit_cost, 4)

        else:  # generic panel — Private Equity, Real Estate, any custom class, etc.
            security_name = request.form.get('alt_name')
            issuer = request.form.get('alt_issuer')
            sector = request.form.get('alt_sector')
            total_cost = _float(request.form.get('alt_total_cost'))

        inv = Investment(
            account_number=acc_no, asset_class=asset_class,
            symbol=symbol, security_name=security_name, issuer=issuer, sector=sector, exchange=exchange,
            quantity=quantity, unit_cost=unit_cost, total_cost=total_cost, current_price=current_price,
            face_value=face_value, interest_rate=interest_rate, coupon_rate=coupon_rate,
            tenor=tenor, trade_date=trade_date, maturity_date=maturity_date,
            status='APPROVED' if current_user.is_super_admin else 'PENDING',
            approved_by=current_user.id if current_user.is_super_admin else None,
        )
        db.session.add(inv)
        db.session.commit()
        audit('INV_ENTRY', target=acc_no, detail=f'{asset_class} cost={total_cost}{commission_note}')
        flash('Investment recorded.', 'success')
        return redirect(url_for('admin.investments'))
    return render_template('admin/investment_form.html', accounts=accounts,
                            asset_classes=get_asset_classes(), asset_labels=get_asset_labels())


@admin_bp.route('/investments/<int:inv_id>/approve', methods=['POST'])
@permission_required('approve_investment')
def approve_investment(inv_id):
    inv = Investment.query.get_or_404(inv_id)
    inv.status = 'APPROVED'
    inv.approved_by = current_user.id
    db.session.commit()
    audit('INV_APPROVED', target=inv.account_number, detail=f'id={inv.id}')
    flash('Investment approved.', 'success')
    return redirect(url_for('admin.investments'))


@admin_bp.route('/transactions')
@admin_required
def transactions():
    q = request.args.get('q', ''); status = request.args.get('status', '')
    query = Transaction.query
    if q: query = query.filter(Transaction.account_number.ilike(f'%{q}%'))
    if status: query = query.filter_by(status=status)
    return render_template('admin/transactions.html',
        transactions=query.order_by(Transaction.txn_date.desc()).limit(500).all(), q=q, status=status)


@admin_bp.route('/transactions/new', methods=['GET', 'POST'])
@permission_required('enter_investment')
def new_transaction():
    accounts = ClientAccount.query.filter_by(status='APPROVED').order_by(ClientAccount.full_name).all()
    if request.method == 'POST':
        acc_no = request.form.get('account_number')
        txn_type = request.form.get('txn_type')
        amount = _float(request.form.get('amount')) or 0
        acc = ClientAccount.query.filter_by(account_number=acc_no).first()
        if not acc:
            flash('Account not found.', 'error'); return redirect(request.url)
        if txn_type in ('WITHDRAWAL', 'TRANSFER_OUT', 'FEE') and acc.cash_balance < amount:
            flash(f'Insufficient cash. Balance: ${acc.cash_balance:,.2f}', 'error')
            return redirect(request.url)
        is_immediate = current_user.is_super_admin
        txn = Transaction(
            account_number=acc_no, txn_type=txn_type, amount=amount, currency='USD',
            description=request.form.get('description'),
            txn_date=_parse_date(request.form.get('txn_date')) or date.today(),
            status='APPROVED' if is_immediate else 'PENDING',
            approved_by=current_user.id if is_immediate else None,
            reference=f'MIL-{int(datetime.utcnow().timestamp())}',
        )
        db.session.add(txn)
        db.session.commit()
        audit('TXN_ENTRY', target=acc_no, detail=f'{txn_type} {amount}')
        flash('Transaction recorded.', 'success')
        return redirect(url_for('admin.transactions'))
    return render_template('admin/transaction_form.html', accounts=accounts)


@admin_bp.route('/transactions/<int:txn_id>/approve', methods=['POST'])
@permission_required('approve_investment')
def approve_transaction(txn_id):
    txn = Transaction.query.get_or_404(txn_id)
    txn.status = 'APPROVED'
    txn.approved_by = current_user.id
    db.session.commit()
    audit('TXN_APPROVED', target=txn.account_number, detail=f'id={txn.id}')
    flash('Transaction approved.', 'success')
    return redirect(url_for('admin.transactions'))


@admin_bp.route('/requests')
@admin_required
def client_requests():
    status = request.args.get('status', '')
    query = ClientRequest.query
    if status: query = query.filter_by(status=status)
    return render_template('admin/client_requests.html',
        requests=query.order_by(ClientRequest.created_at.desc()).all(), status=status)


@admin_bp.route('/requests/<int:req_id>/action', methods=['POST'])
@permission_required('approve_investment')
def action_request(req_id):
    r = ClientRequest.query.get_or_404(req_id)
    action = request.form.get('action')
    if action == 'approve':
        if r.request_type in ('DEPOSIT',) and r.amount:
            db.session.add(Transaction(account_number=r.account_number, txn_type='DEPOSIT',
                amount=r.amount, currency='USD', status='APPROVED', approved_by=current_user.id,
                description='Approved from client request', reference=f'MIL-{int(datetime.utcnow().timestamp())}'))
        elif r.request_type == 'WITHDRAWAL' and r.amount:
            db.session.add(Transaction(account_number=r.account_number, txn_type='WITHDRAWAL',
                amount=r.amount, currency='USD', status='APPROVED', approved_by=current_user.id,
                description='Approved from client request', reference=f'MIL-{int(datetime.utcnow().timestamp())}'))
        r.status = 'APPROVED'
    else:
        r.status = 'REJECTED'
    r.resolved_at = datetime.utcnow()
    db.session.commit()
    audit('REQ_ACTION', target=r.account_number, detail=f'req={r.id} {action}')
    flash(f'Request {action}d.', 'success')
    return redirect(url_for('admin.client_requests'))


@admin_bp.route('/asset-classes')
@permission_required('manage_all')
def asset_classes_page():
    return render_template('admin/asset_classes.html',
        classes=AssetClass.query.order_by(AssetClass.label).all())


@admin_bp.route('/asset-classes/new', methods=['POST'])
@permission_required('manage_all')
def new_asset_class():
    code = (request.form.get('code') or '').strip().upper().replace(' ', '_')
    label = (request.form.get('label') or '').strip()
    if not code or not label:
        flash('Both a code and a label are required.', 'error')
        return redirect(url_for('admin.asset_classes_page'))
    if AssetClass.query.filter_by(code=code).first():
        flash(f'Asset class "{code}" already exists.', 'error')
        return redirect(url_for('admin.asset_classes_page'))
    db.session.add(AssetClass(code=code, label=label))
    db.session.commit()
    audit('ASSET_CLASS_CREATE', target=code, detail=label)
    flash(f'Asset class "{label}" ({code}) created. It will appear in the '
          f'investment form under a generic entry panel and be valued at cost '
          f'until given dedicated pricing logic.', 'success')
    return redirect(url_for('admin.asset_classes_page'))


@admin_bp.route('/stocks')
@permission_required('manage_all')
def stocks():
    from models import StockPrice
    return render_template('admin/stocks.html', stocks=StockPrice.query.order_by(StockPrice.symbol).all())


@admin_bp.route('/stocks/<int:stock_id>/override', methods=['POST'])
@permission_required('manage_all')
def override_stock(stock_id):
    from models import StockPrice
    s = StockPrice.query.get_or_404(stock_id)
    s.price = _float(request.form.get('price'))
    s.is_manual_override = True
    s.updated_at = datetime.utcnow()
    db.session.commit()
    flash(f'{s.symbol} price manually overridden.', 'success')
    return redirect(url_for('admin.stocks'))


@admin_bp.route('/stocks/<int:stock_id>/resume-live', methods=['POST'])
@permission_required('manage_all')
def resume_live_price(stock_id):
    from models import StockPrice
    s = StockPrice.query.get_or_404(stock_id)
    s.is_manual_override = False
    db.session.commit()
    flash(f'{s.symbol} resumed live pricing.', 'success')
    return redirect(url_for('admin.stocks'))


@admin_bp.route('/refresh-market-data')
@admin_required
def refresh_market_data():
    from utils.market_data import fetch_fx_rates, fetch_global_prices, fetch_gse_prices
    fetch_fx_rates(); fetch_global_prices(); fetch_gse_prices()
    flash('Market data refreshed.', 'success')
    return redirect(request.referrer or url_for('admin.dashboard'))


@admin_bp.route('/users')
@permission_required('manage_all')
def admin_users():
    return render_template('admin/admin_users.html',
        users=AdminUser.query.order_by(AdminUser.created_at.desc()).all(), roles=ADMIN_ROLES)


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@permission_required('manage_all')
def new_admin_user():
    if request.method == 'POST':
        role = request.form.get('role')
        password = request.form.get('password', '')
        email = (request.form.get('email') or '').strip().lower()
        import re as _re
        pw_errors = []
        if len(password) < 10: pw_errors.append('at least 10 characters')
        if not _re.search(r'[A-Z]', password): pw_errors.append('one uppercase letter')
        if not _re.search(r'[a-z]', password): pw_errors.append('one lowercase letter')
        if not _re.search(r'\d', password): pw_errors.append('one number')
        if not _re.search(r'[!@#$%^&*(),.?":{}|<>_\-]', password): pw_errors.append('one special character')
        if pw_errors:
            flash(f'Password too weak — must contain: {", ".join(pw_errors)}.', 'error')
            return redirect(request.url)
        existing = AdminUser.query.filter(db.func.lower(AdminUser.email) == email).first()
        if existing:
            flash(f'That email is already registered to {existing.staff_id}.', 'error')
            return redirect(request.url)
        last = AdminUser.query.order_by(AdminUser.id.desc()).first()
        staff_id = f'MA{(last.id+1 if last else 1):03d}'
        u = AdminUser(staff_id=staff_id, full_name=request.form.get('full_name'), email=email,
                      role=role, must_change_password=True)
        u.set_password(password)
        try:
            db.session.add(u); db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f'Could not create staff account: {e.__class__.__name__}', 'error')
            return redirect(request.url)
        audit('STAFF_CREATE', target=f'staff:{staff_id}', detail=f'role={role}')
        flash(f'Staff {staff_id} created.', 'success')
        return redirect(url_for('admin.admin_users'))
    return render_template('admin/admin_user_form.html', roles=ADMIN_ROLES)


@admin_bp.route('/change-password', methods=['GET', 'POST'])
@admin_required
def change_password():
    if request.method == 'POST':
        new_pw = request.form.get('new_password', ''); confirm = request.form.get('confirm_password', '')
        import re as _re
        pw_errors = []
        if len(new_pw) < 10: pw_errors.append('at least 10 characters')
        if not _re.search(r'[A-Z]', new_pw): pw_errors.append('one uppercase letter')
        if not _re.search(r'[a-z]', new_pw): pw_errors.append('one lowercase letter')
        if not _re.search(r'\d', new_pw): pw_errors.append('one number')
        if not _re.search(r'[!@#$%^&*(),.?":{}|<>_\-]', new_pw): pw_errors.append('one special character')
        if pw_errors:
            flash(f'Password too weak — must contain: {", ".join(pw_errors)}.', 'error')
            return redirect(request.url)
        if new_pw != confirm:
            flash('Passwords do not match.', 'error'); return redirect(request.url)
        u = AdminUser.query.get(current_user.id)
        u.set_password(new_pw); u.must_change_password = False
        db.session.commit()
        audit('PASSWORD_CHANGE', target=f'staff:{u.staff_id}')
        flash('Password updated.', 'success')
        return redirect(url_for('admin.dashboard'))
    return render_template('admin/change_password.html', forced=getattr(current_user, 'must_change_password', False))


@admin_bp.before_request
def _enforce_password_change():
    if not current_user.is_authenticated or session.get('user_type') != 'admin':
        return
    if getattr(current_user, 'must_change_password', False) and request.endpoint != 'admin.change_password':
        return redirect(url_for('admin.change_password'))
