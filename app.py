#!/usr/bin/env python3
"""
Leave Application System
- Staff submit leave requests via web form
- Manager receives email with approve/reject links
- Approvals stored in SQLite database
- Dashboard for monitoring leave status
"""

import sqlite3
import smtplib
import os
import json
import secrets
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify, render_template, redirect, url_for, abort
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ── Config (loaded from config.json) ─────────────────────────────────────────
CONFIG_PATH = os.path.join(os.environ.get("DATA_DIR", os.path.dirname(__file__)), "config.json")

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}

def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

# ── Database ──────────────────────────────────────────────────────────────────
# Use /tmp on cloud (ephemeral but works), or local data/ folder when running locally
_data_dir = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
os.makedirs(_data_dir, exist_ok=True)
DB_PATH = os.path.join(_data_dir, "leaves.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS leave_applications (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            token       TEXT UNIQUE NOT NULL,
            staff_name  TEXT NOT NULL,
            staff_email TEXT NOT NULL,
            department  TEXT NOT NULL,
            leave_type  TEXT NOT NULL,
            start_date  TEXT NOT NULL,
            end_date    TEXT NOT NULL,
            days        REAL NOT NULL,
            reason      TEXT,
            status      TEXT DEFAULT 'Pending',
            applied_at  TEXT NOT NULL,
            actioned_at TEXT,
            actioned_by TEXT,
            remarks     TEXT
        );

        CREATE TABLE IF NOT EXISTS staff (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            email       TEXT NOT NULL UNIQUE,
            department  TEXT NOT NULL,
            annual_leave_balance  REAL DEFAULT 14,
            medical_leave_balance REAL DEFAULT 14,
            no_pay_leave_balance  REAL DEFAULT 365,
            compassionate_leave_balance REAL DEFAULT 3
        );
    """)
    # Seed demo staff if empty
    c.execute("SELECT COUNT(*) FROM staff")
    if c.fetchone()[0] == 0:
        demo = [
            ("Alice Tan",    "alice@company.com",   "Engineering",  14, 14, 365, 3),
            ("Bob Lim",      "bob@company.com",     "Marketing",    14, 14, 365, 3),
            ("Carol Wong",   "carol@company.com",   "Finance",      14, 14, 365, 3),
            ("David Ng",     "david@company.com",   "Operations",   14, 14, 365, 3),
        ]
        c.executemany("""
            INSERT INTO staff (name,email,department,
                annual_leave_balance,medical_leave_balance,
                no_pay_leave_balance,compassionate_leave_balance)
            VALUES (?,?,?,?,?,?,?)
        """, demo)
    conn.commit()
    conn.close()

# ── Helpers ───────────────────────────────────────────────────────────────────
LEAVE_TYPES = ["Annual Leave", "Medical Leave", "No Pay Leave", "Compassionate Leave"]

BALANCE_COLS = {
    "Annual Leave":        "annual_leave_balance",
    "Medical Leave":       "medical_leave_balance",
    "No Pay Leave":        "no_pay_leave_balance",
    "Compassionate Leave": "compassionate_leave_balance",
}

def workdays(start: str, end: str) -> float:
    """Count weekdays between two date strings (inclusive)."""
    from datetime import timedelta
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    count = 0
    cur = s
    while cur <= e:
        if cur.weekday() < 5:   # Mon–Fri
            count += 1
        cur += timedelta(days=1)
    return float(count)

def send_approval_email(app_data: dict, base_url: str):
    cfg = load_config()
    smtp_host  = cfg.get("smtp_host", "")
    smtp_port  = int(cfg.get("smtp_port", 587))
    smtp_user  = cfg.get("smtp_user", "")
    smtp_pass  = cfg.get("smtp_pass", "")
    mgr_email  = cfg.get("manager_email", "")
    mgr_name   = cfg.get("manager_name", "Manager")

    if not all([smtp_host, smtp_user, smtp_pass, mgr_email]):
        return False, "SMTP not configured"

    token = app_data["token"]
    approve_url = f"{base_url}/action/{token}/approve"
    reject_url  = f"{base_url}/action/{token}/reject"

    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto;">
      <div style="background:#1a73e8;padding:20px;border-radius:8px 8px 0 0;">
        <h2 style="color:white;margin:0;">📋 Leave Application – Action Required</h2>
      </div>
      <div style="background:#f9f9f9;padding:24px;border:1px solid #ddd;border-radius:0 0 8px 8px;">
        <p>Dear {mgr_name},</p>
        <p><strong>{app_data['staff_name']}</strong> has submitted a leave application.</p>
        <table style="width:100%;border-collapse:collapse;margin:16px 0;">
          <tr style="background:#e8f0fe;"><td style="padding:8px;font-weight:bold;">Staff</td><td style="padding:8px;">{app_data['staff_name']} ({app_data['staff_email']})</td></tr>
          <tr><td style="padding:8px;font-weight:bold;">Department</td><td style="padding:8px;">{app_data['department']}</td></tr>
          <tr style="background:#e8f0fe;"><td style="padding:8px;font-weight:bold;">Leave Type</td><td style="padding:8px;">{app_data['leave_type']}</td></tr>
          <tr><td style="padding:8px;font-weight:bold;">From</td><td style="padding:8px;">{app_data['start_date']}</td></tr>
          <tr style="background:#e8f0fe;"><td style="padding:8px;font-weight:bold;">To</td><td style="padding:8px;">{app_data['end_date']}</td></tr>
          <tr><td style="padding:8px;font-weight:bold;">Days</td><td style="padding:8px;">{app_data['days']} working day(s)</td></tr>
          <tr style="background:#e8f0fe;"><td style="padding:8px;font-weight:bold;">Reason</td><td style="padding:8px;">{app_data.get('reason','—')}</td></tr>
        </table>
        <div style="text-align:center;margin:24px 0;">
          <a href="{approve_url}" style="background:#34a853;color:white;padding:12px 32px;border-radius:6px;text-decoration:none;font-size:16px;margin-right:16px;">✅ Approve</a>
          <a href="{reject_url}"  style="background:#ea4335;color:white;padding:12px 32px;border-radius:6px;text-decoration:none;font-size:16px;">❌ Reject</a>
        </div>
        <p style="font-size:12px;color:#888;">Applied: {app_data['applied_at']}<br>
        Or visit: <a href="{base_url}/dashboard">{base_url}/dashboard</a></p>
      </div>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Leave Request] {app_data['staff_name']} – {app_data['leave_type']} ({app_data['days']}d)"
    msg["From"]    = smtp_user
    msg["To"]      = mgr_email
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, mgr_email, msg.as_string())
        return True, "sent"
    except Exception as e:
        return False, str(e)

def notify_staff(app_data: dict, action: str, remarks: str = ""):
    cfg = load_config()
    smtp_host = cfg.get("smtp_host", "")
    smtp_port = int(cfg.get("smtp_port", 587))
    smtp_user = cfg.get("smtp_user", "")
    smtp_pass = cfg.get("smtp_pass", "")

    if not all([smtp_host, smtp_user, smtp_pass]):
        return

    colour = "#34a853" if action == "approved" else "#ea4335"
    icon   = "✅" if action == "approved" else "❌"
    word   = action.capitalize()

    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto;">
      <div style="background:{colour};padding:20px;border-radius:8px 8px 0 0;">
        <h2 style="color:white;margin:0;">{icon} Leave Application {word}</h2>
      </div>
      <div style="background:#f9f9f9;padding:24px;border:1px solid #ddd;border-radius:0 0 8px 8px;">
        <p>Dear {app_data['staff_name']},</p>
        <p>Your leave application has been <strong>{word}</strong>.</p>
        <table style="width:100%;border-collapse:collapse;margin:16px 0;">
          <tr style="background:#f0f0f0;"><td style="padding:8px;font-weight:bold;">Leave Type</td><td style="padding:8px;">{app_data['leave_type']}</td></tr>
          <tr><td style="padding:8px;font-weight:bold;">Period</td><td style="padding:8px;">{app_data['start_date']} → {app_data['end_date']}</td></tr>
          <tr style="background:#f0f0f0;"><td style="padding:8px;font-weight:bold;">Days</td><td style="padding:8px;">{app_data['days']}</td></tr>
          {"<tr><td style='padding:8px;font-weight:bold;'>Remarks</td><td style='padding:8px;'>"+remarks+"</td></tr>" if remarks else ""}
        </table>
      </div>
    </html>
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Your leave application has been {word}"
    msg["From"]    = smtp_user
    msg["To"]      = app_data["staff_email"]
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo(); server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, app_data["staff_email"], msg.as_string())
    except Exception:
        pass

# ── Routes: Staff-facing ──────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("apply.html", leave_types=LEAVE_TYPES)

@app.route("/apply", methods=["POST"])
def submit_leave():
    data = request.get_json() or request.form.to_dict()
    required = ["staff_name","staff_email","department","leave_type","start_date","end_date"]
    for f in required:
        if not data.get(f):
            return jsonify({"ok": False, "error": f"Missing: {f}"}), 400

    if data["leave_type"] not in LEAVE_TYPES:
        return jsonify({"ok": False, "error": "Invalid leave type"}), 400

    days   = workdays(data["start_date"], data["end_date"])
    token  = secrets.token_urlsafe(32)
    now    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO leave_applications
            (token,staff_name,staff_email,department,leave_type,
             start_date,end_date,days,reason,status,applied_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (token, data["staff_name"], data["staff_email"], data["department"],
              data["leave_type"], data["start_date"], data["end_date"],
              days, data.get("reason",""), "Pending", now))
        conn.commit()
    finally:
        conn.close()

    app_data = {**data, "token": token, "days": days, "applied_at": now}
    base_url = request.host_url.rstrip("/")
    ok, msg  = send_approval_email(app_data, base_url)

    return jsonify({"ok": True, "days": days,
                    "email_sent": ok, "message": msg})

# ── Routes: Manager approval ──────────────────────────────────────────────────
@app.route("/action/<token>/<decision>")
def action(token, decision):
    if decision not in ("approve", "reject"):
        abort(400)

    conn = get_db()
    row  = conn.execute("SELECT * FROM leave_applications WHERE token=?", (token,)).fetchone()
    if not row:
        conn.close()
        return render_template("action_result.html",
                               success=False, message="Invalid or expired link.")

    if row["status"] != "Pending":
        conn.close()
        return render_template("action_result.html",
                               success=True,
                               message=f"This application was already {row['status'].lower()}.")

    status = "Approved" if decision == "approve" else "Rejected"
    now    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Deduct balance only on approval
    if status == "Approved":
        col = BALANCE_COLS.get(row["leave_type"])
        if col:
            conn.execute(f"""
                UPDATE staff SET {col} = MAX(0, {col} - ?)
                WHERE email = ?
            """, (row["days"], row["staff_email"]))

    conn.execute("""
        UPDATE leave_applications
        SET status=?, actioned_at=?, actioned_by=?
        WHERE token=?
    """, (status, now, "Manager", token))
    conn.commit()

    app_data = dict(row)
    conn.close()

    cfg = load_config()
    notify_staff(app_data, decision + "d",
                 remarks=f"Actioned by {cfg.get('manager_name','Manager')}")

    return render_template("action_result.html",
                           success=True,
                           message=f"Leave application has been <strong>{status}</strong>.",
                           staff=row["staff_name"],
                           leave_type=row["leave_type"],
                           days=row["days"],
                           period=f"{row['start_date']} → {row['end_date']}")

@app.route("/api/action-by-id/<int:app_id>/<decision>", methods=["POST"])
def action_by_id(app_id, decision):
    """Dashboard inline approve/reject without token link."""
    if decision not in ("approve", "reject"):
        return jsonify({"ok": False, "error": "Invalid decision"}), 400
    conn = get_db()
    row  = conn.execute("SELECT * FROM leave_applications WHERE id=?", (app_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "Not found"}), 404
    if row["status"] != "Pending":
        conn.close()
        return jsonify({"ok": False, "error": f"Already {row['status']}"}), 400

    status = "Approved" if decision == "approve" else "Rejected"
    now    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if status == "Approved":
        col = BALANCE_COLS.get(row["leave_type"])
        if col:
            conn.execute(f"""
                UPDATE staff SET {col} = MAX(0, {col} - ?)
                WHERE email = ?
            """, (row["days"], row["staff_email"]))

    conn.execute("""
        UPDATE leave_applications
        SET status=?, actioned_at=?, actioned_by=?
        WHERE id=?
    """, (status, now, "Manager (Dashboard)", app_id))
    conn.commit()

    app_data = dict(row)
    conn.close()
    notify_staff(app_data, decision + "d")
    return jsonify({"ok": True, "status": status})

@app.route("/action/<token>/remark", methods=["POST"])
def add_remark(token):
    remark = request.form.get("remark","")
    conn = get_db()
    conn.execute("UPDATE leave_applications SET remarks=? WHERE token=?", (remark,token))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ── Routes: Dashboard ─────────────────────────────────────────────────────────
@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

@app.route("/api/dashboard")
def api_dashboard():
    conn = get_db()

    # Summary counts
    counts = {r["status"]: r["cnt"] for r in conn.execute("""
        SELECT status, COUNT(*) cnt FROM leave_applications GROUP BY status
    """).fetchall()}

    # Recent applications
    apps = [dict(r) for r in conn.execute("""
        SELECT id,staff_name,department,leave_type,start_date,end_date,
               days,status,applied_at,actioned_at,remarks
        FROM leave_applications
        ORDER BY applied_at DESC LIMIT 100
    """).fetchall()]

    # Staff balances
    staff = [dict(r) for r in conn.execute("""
        SELECT name,department,email,
               annual_leave_balance,medical_leave_balance,
               no_pay_leave_balance,compassionate_leave_balance
        FROM staff ORDER BY department,name
    """).fetchall()]

    # Monthly trend (last 6 months)
    trend = [dict(r) for r in conn.execute("""
        SELECT strftime('%Y-%m', start_date) AS month,
               leave_type, COUNT(*) AS cnt
        FROM leave_applications
        WHERE status='Approved'
          AND start_date >= date('now','-6 months')
        GROUP BY month, leave_type
        ORDER BY month
    """).fetchall()]

    # By leave type
    by_type = [dict(r) for r in conn.execute("""
        SELECT leave_type, status, COUNT(*) cnt, SUM(days) total_days
        FROM leave_applications
        GROUP BY leave_type, status
    """).fetchall()]

    conn.close()
    return jsonify({
        "counts":  counts,
        "apps":    apps,
        "staff":   staff,
        "trend":   trend,
        "by_type": by_type,
    })

# ── Routes: Staff management (simple CRUD) ───────────────────────────────────
@app.route("/api/staff", methods=["GET"])
def get_staff():
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM staff ORDER BY name").fetchall()]
    conn.close()
    return jsonify(rows)

@app.route("/api/staff", methods=["POST"])
def add_staff():
    d = request.get_json()
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO staff (name,email,department,
                annual_leave_balance,medical_leave_balance,
                no_pay_leave_balance,compassionate_leave_balance)
            VALUES (?,?,?,?,?,?,?)
        """, (d["name"], d["email"], d["department"],
              d.get("annual_leave_balance", 14),
              d.get("medical_leave_balance", 14),
              d.get("no_pay_leave_balance", 365),
              d.get("compassionate_leave_balance", 3)))
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    finally:
        conn.close()

@app.route("/api/staff/<int:sid>", methods=["DELETE"])
def del_staff(sid):
    conn = get_db()
    conn.execute("DELETE FROM staff WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ── Routes: Settings ─────────────────────────────────────────────────────────
@app.route("/settings")
def settings_page():
    cfg = load_config()
    return render_template("settings.html", config=cfg)

@app.route("/api/settings", methods=["GET","POST"])
def api_settings():
    if request.method == "GET":
        cfg = load_config()
        cfg.pop("smtp_pass", None)   # don't expose password
        return jsonify(cfg)
    d = request.get_json()
    cfg = load_config()
    cfg.update(d)
    save_config(cfg)
    return jsonify({"ok": True})

# ── Auto-init on import (for gunicorn / cloud) ────────────────────────────────
init_db()

# ── Boot ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5050))
    print(f"\n🚀 Leave System running on http://0.0.0.0:{port}")
    print(f"   Staff form  → http://0.0.0.0:{port}/")
    print(f"   Dashboard   → http://0.0.0.0:{port}/dashboard")
    print(f"   Settings    → http://0.0.0.0:{port}/settings\n")
    app.run(host="0.0.0.0", port=port, debug=False)
