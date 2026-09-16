from flask import Blueprint, render_template
from datetime import datetime

public_bp = Blueprint('public', __name__)


@public_bp.route('/')
def home():
    return render_template('public/home.html')


@public_bp.route('/about')
def about():
    return render_template('public/about.html')


@public_bp.route('/portfolio')
def portfolio():
    return render_template('public/portfolio.html')


@public_bp.route('/contact')
def contact():
    return render_template('public/contact.html')
