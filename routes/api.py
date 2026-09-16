from flask import Blueprint, jsonify, session
from flask_login import login_required, current_user
from models import ClientAccount, Investment
from utils.market_data import get_all_stocks, get_all_fx, refresh_if_stale

api_bp = Blueprint('api', __name__)


@api_bp.route('/stocks')
def stocks():
    refresh_if_stale()
    return jsonify(get_all_stocks())


@api_bp.route('/fx')
def fx_rates():
    refresh_if_stale()
    return jsonify(get_all_fx())


@api_bp.route('/portfolio-summary/<account_number>')
@login_required
def portfolio_summary(account_number):
    if session.get('user_type') == 'client' and current_user.account_number != account_number:
        return jsonify({'error': 'Access denied'}), 403
    acc = ClientAccount.query.filter_by(account_number=account_number).first()
    if not acc:
        return jsonify({'error': 'Account not found'}), 404
    investments = Investment.query.filter_by(account_number=account_number, status='APPROVED').all()
    total = sum(i.computed_mkt_value for i in investments)
    cash = acc.cash_balance
    return jsonify({
        'account_number': account_number, 'full_name': acc.full_name,
        'total_investments': round(total, 2), 'cash_balance': round(cash, 2),
        'total_portfolio': round(total + cash, 2), 'currency': 'USD',
    })
