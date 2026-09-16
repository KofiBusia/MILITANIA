from flask import Blueprint, send_file, request, redirect, url_for, flash, render_template, session
from flask_login import login_required, current_user
from models import ClientAccount, get_asset_classes, get_asset_labels
from reports.pdf_reports import generate_pvr, generate_statement, generate_global_report
from datetime import datetime, date

reports_bp = Blueprint('reports', __name__)


def _parse_date(s):
    if not s: return None
    try: return datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError: return None


def _client_can_access(account_number):
    return current_user.account_number == account_number


@reports_bp.route('/pvr/<account_number>')
@login_required
def pvr(account_number):
    if session.get('user_type') == 'client' and not _client_can_access(account_number):
        flash('Access denied.', 'error')
        return redirect(url_for('user.dashboard'))
    try:
        buf = generate_pvr(account_number)
        fname = f'PVR_{account_number.replace("-","_")}_{date.today().strftime("%Y-%m-%d")}.pdf'
        return send_file(buf, mimetype='application/pdf',
                         as_attachment=request.args.get('download') == '1', download_name=fname)
    except Exception as e:
        flash(f'Report error: {e}', 'error')
        redirect_url = url_for('user.dashboard') if session.get('user_type') == 'client' else url_for('admin.dashboard')
        return redirect(request.referrer or redirect_url)


@reports_bp.route('/statement/<account_number>')
@login_required
def statement(account_number):
    if session.get('user_type') == 'client' and not _client_can_access(account_number):
        flash('Access denied.', 'error')
        return redirect(url_for('user.dashboard'))
    date_from = _parse_date(request.args.get('from')); date_to = _parse_date(request.args.get('to'))
    try:
        buf = generate_statement(account_number, date_from, date_to)
        fname = f'Statement_{account_number.replace("-","_")}_{date.today().strftime("%Y-%m-%d")}.pdf'
        return send_file(buf, mimetype='application/pdf',
                         as_attachment=request.args.get('download') == '1', download_name=fname)
    except Exception as e:
        flash(f'Statement error: {e}', 'error')
        redirect_url = url_for('user.dashboard') if session.get('user_type') == 'client' else url_for('admin.dashboard')
        return redirect(request.referrer or redirect_url)


@reports_bp.route('/global')
@login_required
def global_report():
    if session.get('user_type') != 'admin':
        flash('Staff access only.', 'error')
        return redirect(url_for('user.dashboard'))
    asset_class = request.args.get('asset_class')
    try:
        buf = generate_global_report(asset_class)
        fname = f'GlobalReport_{date.today().strftime("%Y-%m-%d")}.pdf'
        return send_file(buf, mimetype='application/pdf',
                         as_attachment=request.args.get('download') == '1', download_name=fname)
    except Exception as e:
        flash(f'Report error: {e}', 'error')
        return redirect(request.referrer or url_for('admin.dashboard'))


@reports_bp.route('/menu')
@login_required
def menu():
    accounts = ClientAccount.query.filter_by(status='APPROVED').order_by(ClientAccount.full_name).all()
    return render_template('admin/reports_menu.html', accounts=accounts, asset_classes=get_asset_classes(),
                            asset_labels=get_asset_labels(), now=datetime.utcnow())
