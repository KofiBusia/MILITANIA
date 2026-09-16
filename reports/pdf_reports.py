import io, os
from datetime import date, datetime
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT

from models import ClientAccount, Investment, Transaction, get_asset_labels, SPECIAL_ASSET_CLASSES
from utils.market_data import get_fx_rate

BLACK  = colors.HexColor('#171717')
BRONZE = colors.HexColor('#A9815E')
BRONZE2 = colors.HexColor('#D3B18A')
CREAM  = colors.HexColor('#F6F1EA')
WHITE  = colors.white
GREY   = colors.HexColor('#6B6459')
GREEN  = colors.HexColor('#2E7D32')
RED    = colors.HexColor('#C62828')

LOGO_PATH = os.path.join(os.path.dirname(__file__), '..', 'static', 'img', 'logo.png')
LW, LH = landscape(A4)


def fmt(v, dp=2):
    if v is None: return '—'
    return f'{v:,.{dp}f}'

def fmt_pct(v):
    if v is None: return '—'
    return f'{v:.2f}%'

def make_styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle('cell', parent=ss['Normal'], fontSize=7.5, leading=9, alignment=TA_LEFT))
    ss.add(ParagraphStyle('small', parent=ss['Normal'], fontSize=7, textColor=GREY))
    return ss

def P(text, style):
    return Paragraph(text or '—', style)

def tbl_style():
    ts = TableStyle([
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 7.5),
        ('BACKGROUND', (0,0), (-1,0), BLACK),
        ('TEXTCOLOR', (0,0), (-1,0), BRONZE2),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [WHITE, CREAM]),
        ('GRID', (0,0), (-1,-1), 0.4, colors.HexColor('#D8CFC0')),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ])
    return ts

def total_row(ts, idx):
    ts.add('BACKGROUND', (0,idx), (-1,idx), BRONZE)
    ts.add('TEXTCOLOR', (0,idx), (-1,idx), WHITE)
    ts.add('FONTNAME', (0,idx), (-1,idx), 'Helvetica-Bold')

def section_heading(story, text, S):
    story.append(Spacer(1, 0.25*cm))
    story.append(Paragraph(f'<font color="#A9815E"><b>{text}</b></font>', S['Heading3']))
    story.append(HRFlowable(width='100%', thickness=0.75, color=BRONZE))
    story.append(Spacer(1, 0.15*cm))

def lhf(title_line='Portfolio Valuation Report', as_of=None):
    as_of = as_of or date.today()
    def _hf(canv, doc):
        canv.saveState()
        w, h = LW, LH
        if os.path.exists(LOGO_PATH):
            canv.drawImage(LOGO_PATH, 0.7*cm, h-1.5*cm, 3.4*cm, 1.3*cm, preserveAspectRatio=True, mask='auto')
        canv.setFont('Helvetica-Bold', 8); canv.setFillColor(BRONZE)
        canv.drawString(4.4*cm, h-0.9*cm, title_line.upper())
        canv.setFont('Helvetica', 7); canv.setFillColor(GREY)
        canv.drawRightString(w-0.7*cm, h-0.85*cm, f'Valuation Date: {as_of.strftime("%d %b %Y")}')
        canv.drawRightString(w-0.7*cm, h-1.2*cm, f'Generated: {datetime.utcnow().strftime("%d %b %Y %H:%M UTC")}')
        canv.setStrokeColor(BRONZE); canv.setLineWidth(1.2)
        canv.line(0.7*cm, h-1.6*cm, w-0.7*cm, h-1.6*cm)
        canv.setFont('Helvetica', 6.5); canv.setFillColor(GREY)
        canv.drawString(0.7*cm, 0.55*cm, 'MILITANIA INVESTMENT — CONFIDENTIAL — FOR AUTHORISED RECIPIENTS ONLY')
        canv.drawRightString(w-0.7*cm, 0.55*cm, f'Page {doc.page}')
        canv.restoreState()
    return _hf


def generate_pvr(account_number):
    acc = ClientAccount.query.filter_by(account_number=account_number).first()
    if not acc:
        raise ValueError('Account not found')
    investments = Investment.query.filter_by(account_number=account_number, status='APPROVED').all()
    cash = acc.cash_balance

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=1.2*cm, rightMargin=1.2*cm,
                             topMargin=1.9*cm, bottomMargin=1.4*cm)
    S = make_styles()
    story = []

    total_inv = sum(i.computed_mkt_value for i in investments)
    total_port = total_inv + cash
    by_class = {}
    for inv in investments:
        by_class[inv.asset_class] = by_class.get(inv.asset_class, 0) + inv.computed_mkt_value

    info = [
        ['Client:', acc.full_name, 'Account No.:', acc.account_number],
        ['Account Type:', acc.account_type, 'Base Currency:', acc.base_currency],
        ['Risk Profile:', acc.risk_profile or '—', 'Investment Objective:', acc.investment_objective or '—'],
    ]
    info_tbl = Table(info, colWidths=[3.3*cm, 8*cm, 4*cm, 8*cm])
    info_tbl.setStyle(TableStyle([
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'), ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8), ('TEXTCOLOR', (0,0), (0,-1), GREY), ('TEXTCOLOR', (2,0), (2,-1), GREY),
        ('BACKGROUND', (0,0), (-1,-1), CREAM), ('BOX', (0,0), (-1,-1), 0.75, BRONZE),
        ('TOPPADDING', (0,0), (-1,-1), 3), ('BOTTOMPADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(info_tbl)
    story.append(Spacer(1, 0.3*cm))

    # GHS equivalent is shown alongside USD throughout using the live FX
    # feed (utils/market_data.py, sourced from open.er-api.com) — GHS is
    # the reference currency Ghana-based stakeholders expect to see next
    # to the USD figures this report is otherwise denominated in.
    ghs_per_usd = get_fx_rate('USD', 'GHS')
    def ghs(usd_val):
        return (usd_val or 0) * ghs_per_usd

    asset_labels = get_asset_labels()
    section_heading(story, 'PORTFOLIO SUMMARY (USD)', S)
    sum_rows = [['Asset Class', 'Market Value (USD)', 'GHS Equivalent', 'Weight %']]
    for cls, lbl in asset_labels.items():
        mv = by_class.get(cls, 0)
        if mv:
            wt = (mv/total_port*100) if total_port else 0
            sum_rows.append([lbl, fmt(mv), fmt(ghs(mv)), fmt_pct(wt)])
    cash_wt = (cash/total_port*100) if total_port else 0
    sum_rows.append(['Cash & Bank Balances', fmt(cash), fmt(ghs(cash)), fmt_pct(cash_wt)])
    t_idx = len(sum_rows)
    sum_rows.append(['TOTAL PORTFOLIO VALUE', fmt(total_port), fmt(ghs(total_port)), '100.00%'])
    sum_tbl = Table(sum_rows, colWidths=[7*cm, 5*cm, 5*cm, 3*cm])
    ts = tbl_style(); ts.add('ALIGN', (1,0), (-1,-1), 'RIGHT'); total_row(ts, t_idx)
    sum_tbl.setStyle(ts)
    story.append(sum_tbl)
    story.append(Paragraph(f'FX rate: 1 USD = {ghs_per_usd:,.4f} GHS (live, source: open.er-api.com)', S['small']))
    story.append(Spacer(1, 0.4*cm))

    mm = [i for i in investments if i.asset_class in ('MONEY_MARKET', 'GOVT_SECURITIES')]
    if mm:
        section_heading(story, 'MONEY MARKET & GOVERNMENT SECURITIES', S)
        rows = [['Issuer', 'Trade Date', 'Principal (USD)', 'Rate %', 'Days Run', 'Accrued Int.', 'Mkt Value (USD)', 'Maturity']]
        tot = 0
        for i in mm:
            mv = i.computed_mkt_value; tot += mv
            rows.append([P(i.issuer, S['cell']), i.trade_date.strftime('%d %b %Y') if i.trade_date else '—',
                fmt(i.total_cost), fmt_pct(i.interest_rate), str(i.days_run), fmt(i.accrued_interest), fmt(mv),
                i.maturity_date.strftime('%d %b %Y') if i.maturity_date else '—'])
        rows.append(['TOTAL','','','','','',fmt(tot),''])
        tbl = Table(rows, colWidths=[4*cm,2.5*cm,3*cm,1.8*cm,1.8*cm,2.5*cm,2.8*cm,2.5*cm])
        ts = tbl_style(); ts.add('ALIGN',(2,0),(-1,-1),'RIGHT'); total_row(ts, len(rows)-1)
        tbl.setStyle(ts); story.append(tbl); story.append(Spacer(1,0.25*cm))

    bonds = [i for i in investments if i.asset_class in ('BONDS', 'EUROBONDS')]
    if bonds:
        section_heading(story, 'BONDS, EUROBONDS & FIXED INCOME', S)
        rows = [['Issuer', 'Trade Date', 'Face Value (USD)', 'Coupon %', 'Accrued Int.', 'Mkt Value (USD)', 'Maturity']]
        tot = 0
        for i in bonds:
            mv = i.computed_mkt_value; tot += mv
            rows.append([P(i.issuer, S['cell']), i.trade_date.strftime('%d %b %Y') if i.trade_date else '—',
                fmt(i.face_value), fmt_pct(i.coupon_rate), fmt(i.accrued_interest), fmt(mv),
                i.maturity_date.strftime('%d %b %Y') if i.maturity_date else '—'])
        rows.append(['TOTAL','','','','',fmt(tot),''])
        tbl = Table(rows, colWidths=[4.5*cm,2.5*cm,3*cm,1.8*cm,2.8*cm,2.8*cm,2.8*cm])
        ts = tbl_style(); ts.add('ALIGN',(2,0),(-1,-1),'RIGHT'); total_row(ts, len(rows)-1)
        tbl.setStyle(ts); story.append(tbl); story.append(Spacer(1,0.25*cm))

    def _equities_section(title, asset_class):
        eq = [i for i in investments if i.asset_class == asset_class]
        if not eq:
            return
        section_heading(story, title, S)
        rows = [['Symbol', 'Security', 'Exchange', 'Qty', 'Unit Cost', 'Mkt Price', 'Mkt Value (USD)', 'Gain/Loss', 'Return %']]
        tot_cost = tot_mv = 0
        for i in eq:
            mv = i.computed_mkt_value; cost = i.total_cost or 0
            gain = mv-cost; ret = (gain/cost*100) if cost else 0
            tot_cost += cost; tot_mv += mv
            price = i.live_price if i.live_price is not None else i.current_price
            rows.append([i.symbol or '—', P(i.security_name, S['cell']), i.exchange or '—',
                fmt(i.quantity,0), fmt(i.unit_cost), fmt(price), fmt(mv), fmt(gain), fmt_pct(ret)])
        tot_gain = tot_mv-tot_cost; tot_ret = (tot_gain/tot_cost*100) if tot_cost else 0
        rows.append(['TOTAL','','','','','',fmt(tot_mv),fmt(tot_gain),fmt_pct(tot_ret)])
        tbl = Table(rows, colWidths=[1.8*cm,4*cm,2.2*cm,1.5*cm,2*cm,2*cm,2.8*cm,2.2*cm,1.6*cm])
        ts = tbl_style(); ts.add('ALIGN',(3,0),(-1,-1),'RIGHT'); total_row(ts, len(rows)-1)
        tbl.setStyle(ts); story.append(tbl); story.append(Spacer(1,0.25*cm))

    _equities_section('GSE EQUITIES — GHANA STOCK EXCHANGE', 'GSE_EQUITIES')
    _equities_section('GLOBAL EQUITIES', 'GLOBAL_EQUITIES')

    mf = [i for i in investments if i.asset_class == 'MUTUAL_FUNDS']
    if mf:
        section_heading(story, 'MUTUAL FUNDS & ETFS', S)
        rows = [['Security', 'Units', 'Unit Cost', 'NAV Price', 'Mkt Value (USD)', 'Gain/Loss']]
        tot_cost = tot_mv = 0
        for i in mf:
            mv = i.computed_mkt_value; cost = i.total_cost or 0
            tot_cost += cost; tot_mv += mv
            rows.append([P(i.security_name, S['cell']), fmt(i.quantity), fmt(i.unit_cost), fmt(i.current_price), fmt(mv), fmt(mv-cost)])
        rows.append(['TOTAL','','','',fmt(tot_mv),fmt(tot_mv-tot_cost)])
        tbl = Table(rows, colWidths=[5*cm,2.5*cm,2.5*cm,2.5*cm,3*cm,2.8*cm])
        ts = tbl_style(); ts.add('ALIGN',(1,0),(-1,-1),'RIGHT'); total_row(ts, len(rows)-1)
        tbl.setStyle(ts); story.append(tbl); story.append(Spacer(1,0.25*cm))

    # Anything not covered by a dedicated section above — Private Equity,
    # Real Estate, custom admin-created classes, etc. — still gets
    # line-item detail here rather than only showing up in the summary
    # total, valued at cost since these have no live pricing source.
    other = [i for i in investments if i.asset_class not in SPECIAL_ASSET_CLASSES]
    if other:
        section_heading(story, 'OTHER HOLDINGS', S)
        rows = [['Asset Class', 'Security / Issuer', 'Trade Date', 'Mkt Value (USD)']]
        tot = 0
        for i in other:
            mv = i.computed_mkt_value; tot += mv
            rows.append([asset_labels.get(i.asset_class, i.asset_class.replace('_',' ')),
                P(i.security_name or i.issuer or i.symbol, S['cell']),
                i.trade_date.strftime('%d %b %Y') if i.trade_date else '—', fmt(mv)])
        rows.append(['TOTAL','','',fmt(tot)])
        tbl = Table(rows, colWidths=[4.5*cm,7*cm,3*cm,3.5*cm])
        ts = tbl_style(); ts.add('ALIGN',(3,0),(-1,-1),'RIGHT'); total_row(ts, len(rows)-1)
        tbl.setStyle(ts); story.append(tbl); story.append(Spacer(1,0.25*cm))

    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=BRONZE))
    story.append(Spacer(1, 0.15*cm))
    disc = (f'All monetary values in USD. This report is prepared for informational purposes only and does '
            f'not constitute investment advice. Valuation Date: {date.today().strftime("%d %b %Y")} | '
            f'Generated: {datetime.utcnow().strftime("%d %b %Y %H:%M UTC")} — CONFIDENTIAL')
    story.append(Paragraph(disc, S['small']))

    doc.build(story, onFirstPage=lhf('Portfolio Valuation Report'), onLaterPages=lhf('Portfolio Valuation Report'))
    buf.seek(0)
    return buf


def generate_statement(account_number, date_from=None, date_to=None):
    acc = ClientAccount.query.filter_by(account_number=account_number).first()
    if not acc:
        raise ValueError('Account not found')
    query = Transaction.query.filter_by(account_number=account_number, status='APPROVED')
    if date_from: query = query.filter(Transaction.txn_date >= date_from)
    if date_to: query = query.filter(Transaction.txn_date <= date_to)
    txns = query.order_by(Transaction.txn_date.asc(), Transaction.id.asc()).all()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=1.2*cm, rightMargin=1.2*cm,
                             topMargin=1.9*cm, bottomMargin=1.4*cm)
    S = make_styles()
    story = []
    story.append(Paragraph(f'<b>{acc.full_name}</b> &middot; {acc.account_number}', S['Heading2']))
    story.append(Spacer(1, 0.2*cm))

    CREDIT = {'DEPOSIT', 'TRANSFER_IN', 'DIVIDEND', 'COUPON', 'SELL'}
    rows = [['Date', 'Type', 'Description', 'Debit (USD)', 'Credit (USD)', 'Balance (USD)']]
    bal = 0.0
    for t in txns:
        if t.txn_type in CREDIT:
            bal += t.amount; debit = ''; credit = fmt(t.amount)
        else:
            bal -= t.amount; debit = fmt(t.amount); credit = ''
        rows.append([t.txn_date.strftime('%d %b %Y'), t.txn_type.replace('_',' '),
            P(t.description or '—', S['cell']), debit, credit, fmt(bal)])
    if len(rows) == 1:
        rows.append(['—','No transactions in this period','','','',''])
    tbl = Table(rows, colWidths=[2.5*cm,3*cm,8*cm,3*cm,3*cm,3*cm], repeatRows=1)
    ts = tbl_style(); ts.add('ALIGN',(3,0),(-1,-1),'RIGHT')
    tbl.setStyle(ts)
    story.append(tbl)
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(f'Closing Balance: USD {fmt(bal)}', S['Heading3']))

    doc.build(story, onFirstPage=lhf('Transaction Statement'), onLaterPages=lhf('Transaction Statement'))
    buf.seek(0)
    return buf


def generate_global_report(asset_class=None):
    accounts = ClientAccount.query.filter_by(status='APPROVED').all()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=1.2*cm, rightMargin=1.2*cm,
                             topMargin=1.9*cm, bottomMargin=1.4*cm)
    S = make_styles()
    story = []
    story.append(Paragraph('GLOBAL AUM REPORT — ALL ACCOUNTS', S['Heading2']))
    story.append(Spacer(1, 0.2*cm))

    rows = [['Account No.', 'Client', 'Investments (USD)', 'Cash (USD)', 'Total Portfolio (USD)']]
    grand_inv = grand_cash = 0.0
    for acc in accounts:
        q = Investment.query.filter_by(account_number=acc.account_number, status='APPROVED')
        if asset_class: q = q.filter_by(asset_class=asset_class)
        invs = q.all()
        inv_val = sum(i.computed_mkt_value for i in invs)
        cash = acc.cash_balance
        grand_inv += inv_val; grand_cash += cash
        rows.append([acc.account_number, P(acc.full_name, S['cell']), fmt(inv_val), fmt(cash), fmt(inv_val+cash)])
    rows.append(['TOTAL','',fmt(grand_inv),fmt(grand_cash),fmt(grand_inv+grand_cash)])
    tbl = Table(rows, colWidths=[3*cm,7*cm,4*cm,4*cm,4*cm], repeatRows=1)
    ts = tbl_style(); ts.add('ALIGN',(2,0),(-1,-1),'RIGHT'); total_row(ts, len(rows)-1)
    tbl.setStyle(ts)
    story.append(tbl)

    title = f'Global Report — {get_asset_labels().get(asset_class, "All Classes") if asset_class else "All Classes"}'
    doc.build(story, onFirstPage=lhf(title), onLaterPages=lhf(title))
    buf.seek(0)
    return buf
