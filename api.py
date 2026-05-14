import sqlite3
import re
import os
from flask import Flask, request, jsonify, session, redirect, url_for, Response
from datetime import datetime
from pathlib import Path
from werkzeug.security import check_password_hash

# Load .env
_env = Path('/opt/openvest-api/.env')
if _env.exists():
    for line in _env.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

app = Flask(__name__)
app.secret_key = os.environ['SECRET_KEY']

DB = '/opt/openvest-api/waitlist.db'

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute('''
            CREATE TABLE IF NOT EXISTS waitlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                phone TEXT,
                interested_companies TEXT,
                investment_size TEXT,
                created_at TEXT NOT NULL
            )
        ''')

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
VALID_SIZES = {'10k', '50k', '100k', '200k', '500k', '1000k', '2000k+'}

# ── Waitlist API ─────────────────────────────────────────────────────────────

@app.route('/api/waitlist', methods=['POST'])
def waitlist_submit():
    data = request.get_json(silent=True) or {}
    name  = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    phone = (data.get('phone') or '').strip() or None
    companies = (data.get('interested_companies') or '').strip() or None
    size  = (data.get('investment_size') or '').strip() or None

    if not name:
        return jsonify({'error': 'Name is required'}), 400
    if not email or not EMAIL_RE.match(email):
        return jsonify({'error': 'Valid email is required'}), 400
    if size and size not in VALID_SIZES:
        return jsonify({'error': 'Invalid investment size'}), 400

    try:
        with get_db() as db:
            db.execute(
                'INSERT INTO waitlist (name, email, phone, interested_companies, investment_size, created_at) VALUES (?,?,?,?,?,?)',
                (name, email, phone, companies, size, datetime.utcnow().isoformat())
            )
        return jsonify({'ok': True}), 201
    except sqlite3.IntegrityError:
        return jsonify({'error': 'This email is already on the waitlist'}), 409

# ── Admin UI ──────────────────────────────────────────────────────────────────

LOGIN_PAGE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenVest Admin</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0a0e1a;color:#f9fafb;display:flex;align-items:center;justify-content:center;min-height:100vh}
  .card{background:#111827;border:1px solid #1f2937;border-radius:16px;padding:2.5rem;width:100%;max-width:380px}
  .logo{font-size:1.3rem;font-weight:800;margin-bottom:2rem;color:#f9fafb}
  .logo span{color:#818cf8}
  label{display:block;font-size:0.8rem;font-weight:600;color:#9ca3af;margin-bottom:0.4rem}
  input{width:100%;padding:0.7rem 1rem;border-radius:10px;border:1px solid #1f2937;background:#0a0e1a;color:#f9fafb;font-size:0.9rem;outline:none;margin-bottom:1rem;transition:border-color .2s}
  input:focus{border-color:#6366f1}
  button{width:100%;padding:0.8rem;background:#6366f1;color:#fff;border:none;border-radius:10px;font-size:1rem;font-weight:700;cursor:pointer}
  button:hover{background:#818cf8}
  .err{color:#f87171;font-size:0.85rem;margin-bottom:1rem}
</style>
</head>
<body>
<div class="card">
  <div class="logo">Open<span>Vest</span> Admin</div>
  {error}
  <form method="POST">
    <label>Email</label>
    <input type="email" name="email" required autofocus>
    <label>Password</label>
    <input type="password" name="password" required>
    <button type="submit">Sign in</button>
  </form>
</div>
</body>
</html>'''

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin'):
            return redirect('/admin/login')
        return f(*args, **kwargs)
    return decorated

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        valid_email = os.environ.get('ADMIN_EMAIL', '').lower()
        valid_hash  = os.environ.get('ADMIN_PASSWORD_HASH', '')
        if email == valid_email and check_password_hash(valid_hash, password):
            session['admin'] = True
            return redirect('/admin')
        return LOGIN_PAGE.replace('{error}', '<div class="err">Invalid email or password.</div>')
    return LOGIN_PAGE.replace('{error}', '')

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect('/admin/login')

@app.route('/admin')
@admin_required
def admin_dashboard():
    with get_db() as db:
        rows = db.execute('SELECT * FROM waitlist ORDER BY created_at DESC').fetchall()
    rows = [dict(r) for r in rows]

    size_labels = {
        '10k': '$10K–$49K', '50k': '$50K–$99K', '100k': '$100K–$199K',
        '200k': '$200K–$499K', '500k': '$500K–$999K', '1000k': '$1M–$1.99M', '2000k+': '$2M+'
    }

    rows_html = ''
    for r in rows:
        dt = r['created_at'][:10] if r['created_at'] else '—'
        size = size_labels.get(r['investment_size'] or '', r['investment_size'] or '—')
        rows_html += f'''<tr>
          <td>{r["name"]}</td>
          <td><a href="mailto:{r["email"]}">{r["email"]}</a></td>
          <td>{r["phone"] or "—"}</td>
          <td>{r["interested_companies"] or "—"}</td>
          <td>{size}</td>
          <td>{dt}</td>
        </tr>'''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Waitlist — OpenVest Admin</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0a0e1a;color:#f9fafb;min-height:100vh}}
  nav{{display:flex;align-items:center;justify-content:space-between;padding:1rem 2rem;border-bottom:1px solid #1f2937;background:#111827}}
  .logo{{font-size:1.1rem;font-weight:800}}.logo span{{color:#818cf8}}
  .nav-right{{display:flex;align-items:center;gap:1.5rem;font-size:0.85rem;color:#9ca3af}}
  .nav-right a{{color:#9ca3af;text-decoration:none}}.nav-right a:hover{{color:#f9fafb}}
  main{{max-width:1200px;margin:0 auto;padding:2.5rem 2rem}}
  h1{{font-size:1.6rem;font-weight:800;margin-bottom:0.5rem;letter-spacing:-0.5px}}
  .sub{{color:#9ca3af;font-size:0.9rem;margin-bottom:2rem}}
  .stats-bar{{display:flex;gap:2rem;margin-bottom:2rem;flex-wrap:wrap}}
  .stat-chip{{background:#111827;border:1px solid #1f2937;border-radius:12px;padding:1rem 1.5rem}}
  .stat-chip .n{{font-size:1.6rem;font-weight:800;letter-spacing:-1px}}
  .stat-chip .l{{font-size:0.78rem;color:#9ca3af;margin-top:0.15rem}}
  .table-wrap{{background:#111827;border:1px solid #1f2937;border-radius:14px;overflow:hidden}}
  table{{width:100%;border-collapse:collapse;font-size:0.88rem}}
  thead{{background:#0a0e1a}}
  th{{padding:0.85rem 1.25rem;text-align:left;font-size:0.75rem;font-weight:700;letter-spacing:0.5px;text-transform:uppercase;color:#9ca3af;border-bottom:1px solid #1f2937}}
  td{{padding:0.85rem 1.25rem;border-bottom:1px solid #1f2937;color:#e5e7eb;vertical-align:top}}
  tr:last-child td{{border-bottom:none}}
  tr:hover td{{background:rgba(99,102,241,0.04)}}
  td a{{color:#818cf8;text-decoration:none}}
  td a:hover{{text-decoration:underline}}
  .empty{{text-align:center;padding:3rem;color:#9ca3af}}
  .export-btn{{padding:0.5rem 1.1rem;background:#6366f1;color:#fff;border:none;border-radius:8px;font-size:0.85rem;font-weight:600;cursor:pointer;text-decoration:none}}
  .export-btn:hover{{background:#818cf8}}
</style>
</head>
<body>
<nav>
  <div class="logo">Open<span>Vest</span> <span style="font-weight:400;color:#4b5563;font-size:0.85rem">/ Admin</span></div>
  <div class="nav-right">
    <a href="/admin/export">Export CSV</a>
    <a href="/admin/logout">Sign out</a>
  </div>
</nav>
<main>
  <h1>Waitlist</h1>
  <p class="sub">All signups, newest first.</p>
  <div class="stats-bar">
    <div class="stat-chip"><div class="n">{len(rows)}</div><div class="l">Total signups</div></div>
    <div class="stat-chip"><div class="n">{sum(1 for r in rows if r["investment_size"] in ("1000k","2000k+"))}</div><div class="l">$1M+ investors</div></div>
    <div class="stat-chip"><div class="n">{sum(1 for r in rows if r["phone"])}</div><div class="l">With phone</div></div>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Name</th><th>Email</th><th>Phone</th><th>Interested companies</th><th>Investment size</th><th>Date</th></tr></thead>
      <tbody>{"".join([rows_html]) if rows else '<tr><td colspan="6" class="empty">No signups yet.</td></tr>'}
      </tbody>
    </table>
  </div>
</main>
</body>
</html>'''

@app.route('/admin/export')
@admin_required
def admin_export():
    with get_db() as db:
        rows = db.execute('SELECT * FROM waitlist ORDER BY created_at DESC').fetchall()
    lines = ['id,name,email,phone,interested_companies,investment_size,created_at']
    for r in rows:
        def esc(v): return f'"{(v or "").replace(chr(34), chr(34)*2)}"'
        lines.append(f'{r["id"]},{esc(r["name"])},{esc(r["email"])},{esc(r["phone"])},{esc(r["interested_companies"])},{esc(r["investment_size"])},{esc(r["created_at"])}')
    return Response('\n'.join(lines), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=waitlist.csv'})

init_db()
