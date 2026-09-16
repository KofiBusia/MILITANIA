import socket
import threading
import time
import requests
import urllib3.util.connection as urllib3_cn

# Force IPv4 — some cloud hosts have no outbound IPv6 route, which makes
# IPv6-preferring DNS resolution hang/fail against hosts that do have an
# AAAA record even though the A record works fine.
def _allowed_gai_family():
    return socket.AF_INET
urllib3_cn.allowed_gai_family = _allowed_gai_family

from extensions import db
from models import FXRate, StockPrice
from datetime import datetime

GLOBAL_STOCKS = [
    {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"},
    {"symbol": "MSFT", "name": "Microsoft Corp.", "exchange": "NASDAQ"},
    {"symbol": "GOOGL", "name": "Alphabet Inc.", "exchange": "NASDAQ"},
    {"symbol": "AMZN", "name": "Amazon.com Inc.", "exchange": "NASDAQ"},
    {"symbol": "META", "name": "Meta Platforms Inc.", "exchange": "NASDAQ"},
    {"symbol": "NVDA", "name": "NVIDIA Corp.", "exchange": "NASDAQ"},
    {"symbol": "TSLA", "name": "Tesla Inc.", "exchange": "NASDAQ"},
    {"symbol": "JPM", "name": "JPMorgan Chase & Co.", "exchange": "NYSE"},
    {"symbol": "V", "name": "Visa Inc.", "exchange": "NYSE"},
    {"symbol": "JNJ", "name": "Johnson & Johnson", "exchange": "NYSE"},
    {"symbol": "BRK-B", "name": "Berkshire Hathaway", "exchange": "NYSE"},
    {"symbol": "GLD", "name": "SPDR Gold Shares", "exchange": "NYSEARCA"},
]

FX_PAIRS = ['GHS', 'GBP', 'EUR', 'NGN', 'CNY', 'ZAR']  # all quoted as 1 USD = X <ccy>


def fetch_fx_rates():
    try:
        r = requests.get('https://open.er-api.com/v6/latest/USD', timeout=(5, 8))
        r.raise_for_status()
        data = r.json()
        rates = data.get('rates', {})
        with db.session.no_autoflush:
            usd_row = FXRate.query.filter_by(base='USD', quote='USD').first()
            if not usd_row:
                usd_row = FXRate(base='USD', quote='USD', rate=1.0)
                db.session.add(usd_row)
            usd_row.rate = 1.0
            usd_row.updated_at = datetime.utcnow()
            for ccy in FX_PAIRS:
                if ccy not in rates:
                    continue
                row = FXRate.query.filter_by(base='USD', quote=ccy).first()
                if not row:
                    row = FXRate(base='USD', quote=ccy)
                    db.session.add(row)
                row.rate = rates[ccy]
                row.updated_at = datetime.utcnow()
            db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        print(f'[FX] refresh failed: {e}')
        return False


def fetch_global_prices():
    ok_count = 0
    for stock in GLOBAL_STOCKS:
        symbol = stock['symbol']
        try:
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
            r = requests.get(url, timeout=(4, 6), headers={'User-Agent': 'Mozilla/5.0'})
            r.raise_for_status()
            result = r.json()['chart']['result'][0]
            meta = result['meta']
            price = meta.get('regularMarketPrice')
            prev_close = meta.get('previousClose') or meta.get('chartPreviousClose')
            change_pct = ((price - prev_close) / prev_close * 100) if (price and prev_close) else 0
            with db.session.no_autoflush:
                row = StockPrice.query.filter_by(symbol=symbol).first()
                if not row:
                    row = StockPrice(symbol=symbol, name=stock['name'], exchange=stock['exchange'])
                    db.session.add(row)
                if row.is_manual_override:
                    continue
                row.price = price
                row.change_pct = round(change_pct, 3)
                row.updated_at = datetime.utcnow()
                db.session.commit()
            ok_count += 1
        except Exception as e:
            db.session.rollback()
            print(f'[GLOBAL] {symbol} refresh error: {e}')
    return ok_count


def get_fx_rate(base, quote):
    """Returns: 1 <base> = X <quote>. Both currencies are matched against
    our USD-anchored table, converting via USD as the pivot when neither
    side is USD."""
    if base == quote:
        return 1.0
    if base == 'USD':
        row = FXRate.query.filter_by(base='USD', quote=quote).first()
        return row.rate if row else 1.0
    if quote == 'USD':
        row = FXRate.query.filter_by(base='USD', quote=base).first()
        return (1.0 / row.rate) if (row and row.rate) else 1.0
    base_row = FXRate.query.filter_by(base='USD', quote=base).first()
    quote_row = FXRate.query.filter_by(base='USD', quote=quote).first()
    if base_row and quote_row and base_row.rate:
        return quote_row.rate / base_row.rate
    return 1.0


def get_all_fx():
    out = {}
    for row in FXRate.query.all():
        out[row.quote] = {'rate': row.rate, 'updated': row.updated_at.strftime('%H:%M') if row.updated_at else '—'}
    return out


def get_all_stocks():
    return [{
        'symbol': s.symbol, 'name': s.name, 'exchange': s.exchange,
        'price': s.price, 'change_pct': s.change_pct,
        'updated': s.updated_at.strftime('%H:%M') if s.updated_at else '—',
        'is_manual_override': s.is_manual_override,
    } for s in StockPrice.query.all()]


_last_refresh = {'ts': 0}
_refresh_lock = threading.Lock()

def refresh_if_stale(max_age_seconds=300):
    """Fast, non-blocking staleness check on the calling thread; the actual
    network fetch runs in a background thread so a slow upstream API never
    holds up the HTTP request that triggered this check."""
    now = time.time()
    with _refresh_lock:
        if now - _last_refresh['ts'] < max_age_seconds:
            return
        _last_refresh['ts'] = now

    from flask import current_app
    app_obj = current_app._get_current_object()

    def _do_refresh():
        with app_obj.app_context():
            fetch_fx_rates()
            fetch_global_prices()

    threading.Thread(target=_do_refresh, daemon=True).start()
