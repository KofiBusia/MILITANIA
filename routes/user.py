from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_required, current_user
from extensions import db
from models import ClientAccount, Investment, Transaction, ClientRequest, ASSET_LABELS
from utils.notifications import audit
from datetime import datetime

user_bp = Blueprint('user', __name__)


def client_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*a, **kw):
        if not current_user.is_authenticated or session.get('user_type') != 'client':
            return redirect(url_for('auth.login'))
        return f(*a, **kw)
    return decorated


def get_account():
    return ClientAccount.query.filter_by(account_number=current_user.account_number).first()


@user_bp.route('/')
@client_required
def dashboard():
    from utils.market_data import refresh_if_stale
    refresh_if_stale()
    acc = get_account()
    investments = Investment.query.filter_by(account_number=acc.account_number, status='APPROVED').all()
    transactions = Transaction.query.filter_by(account_number=acc.account_number)\
                        .order_by(Transaction.txn_date.desc()).limit(20).all()
    requests_ = ClientRequest.query.filter_by(account_number=acc.account_number)\
                        .order_by(ClientRequest.created_at.desc()).limit(5).all()
    total_value = sum(i.computed_mkt_value for i in investments)
    cash = acc.cash_balance
    portfolio_value = total_value + cash
    by_class = {}
    for inv in investments:
        lbl = ASSET_LABELS.get(inv.asset_class, inv.asset_class)
        by_class[lbl] = by_class.get(lbl, 0) + inv.computed_mkt_value
    return render_template('user/dashboard.html', acc=acc, investments=investments,
        transactions=transactions, requests=requests_, total_value=total_value, cash=cash,
        portfolio_value=portfolio_value, by_class=by_class)


@user_bp.route('/statement')
@client_required
def statement():
    acc = get_account()
    transactions = Transaction.query.filter_by(account_number=acc.account_number)\
                        .order_by(Transaction.txn_date.desc()).all()
    return render_template('user/statement.html', acc=acc, transactions=transactions)


@user_bp.route('/requests', methods=['GET', 'POST'])
@client_required
def requests_page():
    acc = get_account()
    if request.method == 'POST':
        req_type = request.form.get('request_type')
        amount = request.form.get('amount')
        details = request.form.get('details', '')
        try:
            amount_f = float(amount) if amount else None
        except ValueError:
            amount_f = None
        r = ClientRequest(account_number=acc.account_number, request_type=req_type,
                           amount=amount_f, details=details, status='PENDING')
        db.session.add(r)
        db.session.commit()
        audit('CLIENT_REQUEST', target=acc.account_number, detail=f'{req_type} {amount_f}', actor=current_user)
        flash('Your request has been submitted. An administrator will review it shortly.', 'success')
        return redirect(url_for('user.requests_page'))
    reqs = ClientRequest.query.filter_by(account_number=acc.account_number)\
                    .order_by(ClientRequest.created_at.desc()).all()
    return render_template('user/requests.html', acc=acc, requests=reqs)


@user_bp.route('/change-password', methods=['GET', 'POST'])
@client_required
def change_password():
    from models import ClientUser
    if request.method == 'POST':
        new_pw = request.form.get('new_password', ''); confirm = request.form.get('confirm_password', '')
        if len(new_pw) < 6:
            flash('Password must be at least 6 characters.', 'error'); return redirect(request.url)
        if new_pw != confirm:
            flash('Passwords do not match.', 'error'); return redirect(request.url)
        user = ClientUser.query.get(current_user.id)
        user.set_password(new_pw)
        user.must_change_password = False
        db.session.commit()
        flash('Password updated successfully.', 'success')
        return redirect(url_for('user.dashboard'))
    return render_template('user/change_password.html')
