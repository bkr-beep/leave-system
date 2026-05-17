# 📋 Leave Management System

A complete leave application, approval, and monitoring system.

---

## 🚀 Quick Start

```bash
cd leave_system
python3 app.py
```

Then open:
- **Staff Form** → http://localhost:5050/
- **Manager Dashboard** → http://localhost:5050/dashboard
- **Settings** → http://localhost:5050/settings

---

## ⚙️ First-Time Setup

### 1. Configure Email (Settings page)
Visit `/settings` and fill in:
| Field | Value |
|-------|-------|
| Manager Name | Your name |
| Manager Email | Your email (receives approval requests) |
| SMTP Host | `smtp.gmail.com` (Gmail) |
| SMTP Port | `587` |
| SMTP Username | Your Gmail address |
| SMTP Password | [Gmail App Password](https://myaccount.google.com/apppasswords) |
| Public Base URL | `https://yourserver.com` (where this app is hosted) |

> **Gmail users**: You must create an App Password (not your normal Gmail password).  
> Go to: Google Account → Security → 2-Step Verification → App Passwords

### 2. Add Your Staff
On the Settings page, add/remove staff members and set their leave balances.

---

## 📧 How the Approval Flow Works

1. **Staff** submits leave via the web form → `/`
2. **Manager** receives an email with the application details + **Approve / Reject buttons**
3. Clicking the button records the decision and:
   - Deducts balance (on approval)
   - Notifies the staff member by email
4. **Dashboard** updates in real-time (auto-refreshes every 30 seconds)

---

## 🗂️ Leave Categories

| Type | Default Balance |
|------|----------------|
| Annual Leave | 14 days/year |
| Medical Leave | 14 days/year |
| No Pay Leave | Unlimited (365) |
| Compassionate Leave | 3 days |

---

## 📊 Dashboard Features

- **KPI Cards** — Total / Pending / Approved / Rejected counts
- **Leave by Type** — Doughnut chart of all applications
- **Monthly Trend** — Line chart of approvals over last 6 months
- **Applications Table** — Filterable by status, type, name; inline approve/reject
- **Staff Balances** — Progress bars showing remaining leave days per employee

---

## 🗄️ Database

SQLite file at: `data/leaves.db`

Tables:
- `leave_applications` — all leave records with status, tokens, dates
- `staff` — employee records with leave balances

---

## 📁 File Structure

```
leave_system/
├── app.py                  # Main Flask application
├── config.json             # SMTP & manager config (auto-created)
├── data/
│   └── leaves.db           # SQLite database
└── templates/
    ├── apply.html          # Staff-facing leave form
    ├── dashboard.html      # Manager dashboard
    ├── settings.html       # Configuration page
    └── action_result.html  # Approve/reject confirmation page
```

---

## 🔒 Deployment Tips

- For production, use **Gunicorn**: `gunicorn -w 2 -b 0.0.0.0:5050 app:app`
- Put behind **Nginx** or **Caddy** with HTTPS for real email approval links
- The approval token in each email link is cryptographically random and single-use
