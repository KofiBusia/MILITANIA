from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db
from models import AdminUser, ClientUser, ClientAccount
from utils.notifications import audit
from datetime import datetime

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_type = request.form.get('login_type', 'client')

        if login_type == 'admin':
            staff_id = request.form.get('staff_id', '').strip()
            password = request.form.get('password', '')
            user = AdminUser.query.filter_by(staff_id=staff_id).first()
            if user and user.is_active and user.check_password(password):
                user.last_login = datetime.utcnow()
                db.session.commit()
                login_user(user)
                session['user_type'] = 'admin'
                audit('LOGIN', target=f'admin:{staff_id}', actor=user)
                return redirect(url_for('admin.dashboard'))
            flash('Invalid staff ID or password.', 'error')

        else:
            account_number = request.form.get('account_number', '').strip().upper()
            phone = request.form.get('phone', '').strip()
            user = ClientUser.query.filter_by(account_number=account_number, phone=phone).first()
            if user and user.is_active:
                acc = ClientAccount.query.filter_by(account_number=account_number).first()
                if acc and acc.status == 'APPROVED':
                    user.last_login = datetime.utcnow()
                    db.session.commit()
                    login_user(user)
                    session['user_type'] = 'client'
                    audit('LOGIN', target=f'client:{account_number}', actor=user)
                    return redirect(url_for('user.dashboard'))
                elif acc and acc.status == 'PENDING':
                    flash('Your account is still pending approval. You will be notified once approved.', 'error')
                else:
                    flash('Account not found or not approved.', 'error')
            else:
                flash('Invalid account number or phone number.', 'error')

    return render_template('auth/login.html')


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        country = request.form.get('country', '').strip()
        risk_profile = request.form.get('risk_profile', '')
        investment_objective = request.form.get('investment_objective', '').strip()

        if not full_name or not phone:
            flash('Full name and phone number are required.', 'error')
            return redirect(request.url)

        last = ClientAccount.query.order_by(ClientAccount.id.desc()).first()
        acc_no = f'MI-{(last.id+1 if last else 1):05d}'
        acc = ClientAccount(
            account_number=acc_no, full_name=full_name, email=email, phone=phone,
            country=country, risk_profile=risk_profile, investment_objective=investment_objective,
            base_currency='USD', status='PENDING',
        )
        db.session.add(acc)
        db.session.flush()
        client_user = ClientUser(account_number=acc_no, phone=phone, is_active=True)
        db.session.add(client_user)
        db.session.commit()
        audit('SIGNUP', target=acc_no, detail=full_name)
        flash(f'Application submitted! Your account number is {acc_no}. '
              f'An administrator will review and approve your account shortly — '
              f'you can then sign in with this account number and your phone number.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/signup.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('public.home'))
