# Real Freelance Jobs - Production Telegram Bot & Automated Verification System

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/telegram-python--telegram--bot%20v22-blue)](https://python-telegram-bot.org/)
[![API](https://img.shields.io/badge/FastAPI-0.110%2B-green)](https://fastapi.tiangolo.com/)
[![Database](https://img.shields.io/badge/SQLAlchemy-2.0%20(SQLite%20%7C%20PostgreSQL)-orange)](https://www.sqlalchemy.org/)

**Real Freelance Jobs** (`@RealFreelanceJobsBot`) is an automated, asynchronous Telegram bot and verification platform designed to screen freelance job postings and participants for fraud, phishing, and scam indicators.

---

## 🛡️ Core Safety & Legal Guardrails

> [!IMPORTANT]
> **Legal Notice**: Real Freelance Jobs is an **automated risk-screening and moderation system**, NOT an escrow service, employer, or legal certifier.
> - The system **never** claims any job or user is 100% genuine or guaranteed.
> - The system assigns a transparent **Risk Score (0–100)**:
>   * `0 - 20`: **Low Risk** (Eligible for moderation approval)
>   * `21 - 50`: **Review Recommended** (Held for human review)
>   * `51 - 75`: **High Risk** (Held / Blocked, admin alerted)
>   * `76 - 100`: **Very High Risk** (Held / Blocked, admin alerted)
> - **Zero Tolerance for Sensitive Credentials**: The bot **never** asks for OTPs, passwords, private keys, crypto seed phrases, bank logins, card numbers, or unnecessary government IDs.

---

## 📁 Project Architecture

```
real-freelance-bot/
├── bot.py                     # Master runner (PTB Application & FastAPI server)
├── config.py                  # Pydantic Settings and environment configuration
├── requirements.txt           # Production dependencies
├── .env.example               # Configuration template with secret placeholders
├── .gitignore                 # Excludes secrets, databases, and logs
├── Dockerfile                 # Multi-stage lightweight container
├── docker-compose.yml         # Container compose with SQLite and PostgreSQL
├── README.md                  # Comprehensive setup and deployment documentation
├── api/
│   ├── __init__.py
│   └── server.py              # FastAPI REST API & /health check endpoint
├── database/
│   ├── __init__.py
│   ├── db.py                  # Async SQLAlchemy session and engine management
│   ├── models.py              # User, Job, VerificationEvent, Report, AuditLog tables
│   └── crud.py                # Reusable async CRUD repository functions
├── handlers/
│   ├── __init__.py
│   ├── start.py               # /start, /rules, /help handlers
│   ├── verification.py        # /verify & /status interactive pledge workflow
│   ├── jobs.py                # /submit 10-step wizard with real-time screening
│   ├── reports.py             # /report command for community scam reporting
│   ├── admin.py               # /admin, /pending, /approve, /reject, /ban, /stats
│   └── group.py               # "Verified Freelance Joba" group spam moderation
├── services/
│   ├── __init__.py
│   ├── website_checker.py     # Async HTTP/HTTPS reachability, TLS, and parked domains
│   ├── domain_checker.py      # URL shorteners, disposable TLDs, and email mismatches
│   ├── scam_detector.py       # Heuristic pattern detection (fees, crypto, phishing)
│   ├── ai_analyzer.py         # Google Gemini & OpenAI structured scam analysis
│   └── moderation.py          # Unified pipeline synthesizing risk scores and actions
├── utils/
│   ├── __init__.py
│   ├── logger.py              # Structured logging with token/secret masking
│   ├── rate_limiter.py        # Anti-flood rate limiting per user
│   └── formatters.py          # HTML message cards and mandatory safety disclaimers
└── tests/
    ├── __init__.py
    ├── test_scam_detector.py  # Heuristic pattern & risk scoring tests
    ├── test_domain_checker.py # Domain integrity and URL shortener tests
    ├── test_db.py             # Async database operations & model tests
    └── test_api_and_moderation.py # FastAPI health & full screening tests
```

---

## 🚀 Quick Setup Guide (Windows PowerShell)

Follow these exact commands in Windows PowerShell:

### 1. Clone or Open Project Directory
```powershell
cd c:\Users\rathod\Downloads\.agents\real-freelance-bot
```

### 2. Create and Activate a Python Virtual Environment
```powershell
# Create virtual environment
python -m venv venv

# Activate virtual environment
.\venv\Scripts\Activate.ps1
```
*(If PowerShell restricts scripts, run: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`)*

### 3. Install Required Dependencies
```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy the template to `.env`:
```powershell
Copy-Item .env.example .env
```
Open `.env` in your editor and fill in your credentials:
```env
# 1. Telegram Bot Token from @BotFather
TELEGRAM_BOT_TOKEN=AAGcVuWOGWm9I4Ug3-OqCeVxU-zx_aBPxCM

# 2. Your Telegram User ID (get from @userinfobot)
ADMIN_IDS=

# 3. Verified Freelance Joba Group / Channel ID (supergroup starts with -100)
TELEGRAM_GROUP_ID=-1001234567890

# 4. Optional AI Key for deep semantic analysis (Gemini or OpenAI)
AI_PROVIDER=gemini
AI_API_KEY=your_gemini_api_key_here
AI_MODEL=gemini-1.5-flash
```

---

## 🧪 Local Testing & Verification

### Run the Automated Test Suite
To verify the database, scam detection algorithms, domain checkers, and FastAPI endpoints:
```powershell
python -m unittest discover -s tests -p "test_*.py"
```
You should see:
```text
Ran 24 tests in ...s
OK
```

### Start the Bot and Web Server
```powershell
python bot.py
```
Expected output:
```text
2026-09-12 21:03:00 | INFO | RealFreelanceJobs:45 | Initializing database schema...
2026-09-12 21:03:00 | INFO | RealFreelanceJobs:48 | Database schema initialized successfully.
2026-09-12 21:03:01 | INFO | RealFreelanceJobs:125 | Connecting bot @RealFreelanceJobsBot...
2026-09-12 21:03:01 | INFO | RealFreelanceJobs:130 | Bot polling started successfully.
2026-09-12 21:03:01 | INFO | RealFreelanceJobs:98 | FastAPI health check server running on http://0.0.0.0:8000
```

### Validate FastAPI Health Check
Open another PowerShell tab or browser:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health"
```
Response:
```json
{
  "status": "ok",
  "database": "healthy",
  "bot_username": "RealFreelanceJobsBot",
  "ai_provider": "gemini",
  "ai_configured": true
}
```

---

## 🤖 Telegram Bot Commands Reference

### Member Commands
| Command | Description |
| :--- | :--- |
| `/start` | Welcome message, community introduction, and interactive menu |
| `/verify` | One-tap anti-scam pledge and membership verification profile |
| `/submit` | 10-step wizard to submit a freelance job for automated screening |
| `/status` | View your verification status, account risk rating, and submission stats |
| `/myid` | Inspect your Telegram User ID, chat ID, and current role |
| `/pricing` | View transparent employer services, featured posts & sponsorships |
| `/rules` | View our zero-tolerance community rules |
| `/report` | Report a fraudulent job or suspicious user (`/report <id> <reason>`) |
| `/help` | Detailed help, FAQ, and safety advisories |

### Administrator Commands (Restricted to `ADMIN_IDS`)
| Command | Description |
| :--- | :--- |
| `/admin` | Interactive dashboard with pending jobs, stats, and audit controls |
| `/pending` | List submissions pending review with inline Approve / Reject buttons |
| `/job <id>` | Inspect full diagnostic details, flags, AI reasoning, and website status |
| `/user <user_id>` | Inspect a user profile, submission history, and risk score |
| `/approve <id>` | Approve a job, publish to group, and notify the submitter |
| `/reject <id> [reason]` | Reject a submission and send courteous feedback to submitter |
| `/feature <job_id>` | Toggle `⭐ FEATURED` highlight for an approved job |
| `/sponsor <job_id>` | Toggle `💎 SPONSORED` badge for an approved job |
| `/suspicious <user_id>` | Flag an account as `SUSPICIOUS` (holding future posts for review) |
| `/unflag <user_id>` | Clear suspicion flags and restore account to `VERIFIED` |
| `/ban <user_id> [reason]` | Ban a malicious user from submitting jobs |
| `/unban <user_id>` | Restore a banned user to verified status |
| `/stats` | View live platform metrics (total users, approved jobs, scam attempts) |

---

## 💎 Legal & Transparent Monetization Architecture

> [!NOTE]
> **Anti-Extortion Guarantee**:
> Real Freelance Jobs never charges job seekers or basic posters. We strictly forbid any "unlock fees", "withdrawal fees", "activation fees", or "mandatory verification fees".

The platform supports legal, voluntary employer monetization options:
1. **⭐ Featured Placement**: Pinned job postings at the top of the community channel for enhanced visibility.
2. **💎 Sponsored Listings**: Priority listing in daily/weekly job digests and distinct visual branding.
3. **🏢 Verified Employer Service**: Independent domain and business registry verification.
4. **🤝 Voluntary Community Support**: Donations to support server hosting and AI analysis costs.

Employers can review options using `/pricing` or `/sponsor`.

---

## 🌐 Setting Up Telegram

### 1. Create Your Bot
1. Open Telegram and message `@BotFather`.
2. Send `/newbot`.
3. Set display name: `Real Freelance Jobs`.
4. Set username: `RealFreelanceJobsBot` (or your chosen available username).
5. Copy the generated API token into `.env` under `TELEGRAM_BOT_TOKEN`.

### 2. Find Your Telegram User ID
1. You can message `@userinfobot` on Telegram, or run the bot and send `/myid`.
2. Note your numerical `Id` (e.g., `123456789`).
3. Set this in `.env` under `ADMIN_IDS`.

### 3. Connect the Group ("Verified Freelance Joba")
1. Create a Telegram supergroup or channel named `Verified Freelance Joba`.
2. Add `@RealFreelanceJobsBot` as an **Administrator** with permissions:
   - *Delete messages* (to intercept unverified job spam)
   - *Post messages* (to broadcast approved jobs)
3. Forward a message from the group to `@userinfobot` or use `@RawDataBot` to find the Chat ID (starts with `-100`).
4. Place the ID in `.env` under `TELEGRAM_GROUP_ID`.

---

## 🐳 Docker Deployment

### Run with Docker Compose (SQLite Default)
```bash
docker compose up -d --build
```

### Run with PostgreSQL Profile
```bash
docker compose --profile with-postgres up -d --build
```

---

## ☁️ Cloud Deployment Guide

### Deploying to Render / Railway / VPS

#### 1. Railway
1. Push this repository to GitHub.
2. In Railway, click **New Project** → **Deploy from GitHub repo**.
3. Add Environment Variables from `.env.example`.
4. Railway will automatically detect the `Dockerfile` or `Procfile`.
5. Set Health Check Path: `/health`.

#### 2. Render
1. Create a **Web Service** connected to your repo.
2. Set Environment: **Python 3**.
3. Build Command: `pip install -r requirements.txt`.
4. Start Command: `python bot.py`.
5. Add required Environment Variables.
6. Health Check Path: `/health`.

---

## 🔧 Troubleshooting

| Issue | Cause & Solution |
| :--- | :--- |
| `TelegramError: Unauthorized` | Invalid `TELEGRAM_BOT_TOKEN` in `.env`. Verify token with @BotFather. |
| `FastAPI server runs, but bot doesn't poll` | You have a placeholder token (e.g. `your_telegram_bot_token_here`). Add a real token to start Telegram polling. |
| `Bot fails to delete messages in group` | Bot is not an **Administrator** in the group or lacks `Delete messages` rights. |
| `AI returns heuristic fallback` | Normal behavior if `AI_API_KEY` is not provided. The system continues to operate seamlessly using local heuristics. |
| `Database is locked (SQLite)` | SQLite is great for single instances. If scaling horizontally to multiple replicas, configure PostgreSQL via `DATABASE_URL=postgresql+asyncpg://...`. |

---

## ⚖️ License & Credits
Developed for legitimate remote and freelance work communities.
Protected under the MIT License.
