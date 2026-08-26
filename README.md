# 🎯 AI Job Hunter Agent

A production-quality personal job-search agent that runs daily, searches multiple job sources, uses AI to match jobs against your resume, deduplicates results, and sends you a beautifully formatted email with new matching jobs.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🤖 **AI Matching** | Gemini 2.5 Flash powered semantic skill matching (GKE ↔ Kubernetes, Terraform ↔ IaC) with automatic quota fallback |
| 📊 **0-100 Scoring** | Intelligent scoring across 6 dimensions |
| 🔎 **Multi-Source** | RemoteOK, Naukri (dedicated adapter), Arbeitnow, Adzuna, Jooble, LinkedIn URL discovery, Company pages |
| 🔄 **Deduplication** | Canonical hash + URL matching prevents duplicate emails |
| 📅 **Daily Schedule** | Automatically runs at 9:00 AM IST (configurable) |
| ▶/⏹ **START/STOP** | Full agent control with database preservation |
| 📧 **Rich Email** | Dark-themed HTML email with match scores and apply links |
| 🎛️ **Dashboard** | Real-time web UI with date/time stamps, recency sorting, dynamic job counts, and pagination |
| 📄 **Resume Re-upload** | Upload/re-upload PDF resume with instant search prompt and automated skill extraction |
| 📋 **Job Search Report** | Formatted multi-source breakdown logged after every search run |
| 🐳 **Docker** | Full Docker Compose stack |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI Web App                         │
│  Dashboard (HTML/JS) │  REST API  │  APScheduler            │
└─────────────────────────────────────────────────────────────┘
         │                  │                    │
         ▼                  ▼                    ▼
┌─────────────────────────────────────────────────────────────┐
│                      Job Agent Core                         │
│  Sources: RemoteOK │ Naukri │ Arbeitnow │ Adzuna │ Jooble   │
│           CompanyCareers │ LinkedIn URL Discovery           │
│  Matcher: Gemini (2.5-flash) / OpenAI / Mock (configurable) │
│  Scorer:  Title(20) + Skills(30) + Exp(15) + Loc(15)        │
│           Salary(10) + Relevance(10) = 100pts               │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────┐
│    PostgreSQL DB      │
│  agent_state         │
│  jobs + job_matches  │
│  sent_jobs           │
│  search_runs         │
│  resume_data         │
└──────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL 15+
- Docker & Docker Compose (for Docker mode)

### Option A: Docker (Recommended)

```bash
# 1. Clone the project
cd AI_Job_Hunter_Agent

# 2. Copy and configure environment
cp .env.example .env
# Edit .env with your API keys and email settings

# 3. Start everything
docker compose up -d

# 4. Visit dashboard
open http://localhost:8000

# 5. Click "Start Agent" and "Search Now"
```

### Option B: Local Development

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate   # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and configure .env
cp .env.example .env
# Edit .env with your credentials

# 4. Create database
createdb jobhunter  # or use your PostgreSQL tool

# 5. Start the app
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 6. Visit dashboard
open http://localhost:8000
```

---

## ⚙️ Environment Variables

Copy `.env.example` to `.env` and configure:

### Required

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `EMAIL_HOST` | SMTP host (e.g. `smtp.gmail.com`) |
| `EMAIL_PORT` | SMTP port (e.g. `587`) |
| `EMAIL_USERNAME` | Your email address |
| `EMAIL_PASSWORD` | Gmail App Password (not your real password!) |
| `EMAIL_TO` | Where to send job emails |
| `LLM_PROVIDER` | `gemini` / `openai` / `mock` |
| `GEMINI_MODEL` | `gemini-2.5-flash` (default) |

### Gmail Setup (App Password)
1. Enable 2-Factor Authentication on your Google account
2. Go to: Google Account → Security → App Passwords
3. Create a new App Password for "Mail"
4. Use that password in `EMAIL_PASSWORD`

### Optional (Improves job coverage)

| Variable | Where to Get |
|---|---|
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com/app/apikey) — Free tier |
| `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` | [developer.adzuna.com](https://developer.adzuna.com/) — Free |
| `JOOBLE_API_KEY` | [jooble.org/api/about](https://jooble.org/api/about) — Free |
| `SERPAPI_KEY` | [serpapi.com](https://serpapi.com) — Paid ($50/mo) for LinkedIn URL discovery |

> **Naukri.com** — Dedicated ethical adapter (`app/sources/naukri.py`). No API key is required or available. See the [Naukri Integration Notes](#naukri-integration-notes) section below.

---

## ⚠️ Naukri Integration Notes

Naukri.com is India's largest job board and is integrated via a dedicated adapter in `app/sources/naukri.py`.

- **No authorized public API exists.** Naukri does not provide a developer API program. Enterprise access is restricted to direct account management.
- **Ethical & Compliant Access Only.** `NaukriSource` makes transparent HTTP GET requests with an explicit header identifying the tool: `User-Agent: AI-Job-Hunter/1.0 (personal job search tool; not a browser)`. It strictly avoids browser fingerprinting, spoofing headers, CAPTCHA solving, session warming, or rate limit evasion.
- **Non-retryable 4xx Handling.** If Naukri returns an access-denied status code (400, 401, 403, 406, 429), the source logs a single warning and immediately yields `[]` without retrying.
- **Exponential Backoff for 5xx.** Server errors (500, 502, 503) and network failures retry up to 2 times with backoff.
- **Graceful Failure.** If blocked, **the agent continues running normally using all other job sources.**
- **Do not add Naukri credentials to `.env`.** None are supported.

| Scenario | Behaviour |
|---|---|
| Naukri returns 200 OK | Jobs are parsed and included |
| Naukri returns 4xx (access denied/bot block) | Logs warning, returns `[]` immediately without retrying |
| Naukri returns 5xx (server error) | Retries up to 2× with backoff, then returns `[]` |
| Network timeout | Retries up to 2× with backoff, then returns `[]` |

---

## 📊 Job Search Summary Report

At the conclusion of every job search run, the agent logs a structured report to stdout/logs:

```text
==================== Job Search Report — 09:00 AM ====================
LinkedIn            : 24 discovered
Adzuna              : 41 discovered
Jooble              : 18 discovered
Company Sites       : 13 discovered
RemoteOK            : 7 discovered
Naukri              : unavailable
----------------------------------------------------------------------
After deduplication : 72 unique jobs
AI matched          : 19
New since yesterday : 8
Email sent successfully.
======================================================================
```

---

## 📄 Resume Upload & Re-upload

1. **Dashboard Upload / Re-upload:**
   - Click the upload area or the **`📤 Re-upload`** / **`🔄 Change File`** buttons in the Resume card.
   - Upload your PDF resume file.
   - The parser extracts skills, cloud platforms, DevOps tools, and experience.
   - After a successful upload, an instant dialog offers: *"Would you like to run a job search now with your new resume?"*
2. **Via API:**
   ```bash
   curl -X POST http://localhost:8000/api/resume/upload \
     -F "file=@/path/to/your/resume.pdf"
   ```

---

## 📋 Job Preferences

Edit `config.yaml` to change what jobs you search for:

```yaml
job_preferences:
  job_titles:
    - DevOps Engineer
    - SRE
    - Platform Engineer

  experience:
    minimum_years: 1
    maximum_years: 3

  minimum_salary_inr: 1000000  # ₹10 LPA

  locations:
    - India
    - Remote India

  preferred_skills:
    - GCP
    - Kubernetes
    - Terraform
```

**No restart required** — preferences are reloaded on every search run.

---

## ▶ START / STOP the Agent

### Via Dashboard
Click **"Start Agent"** or **"Stop Agent"** on the dashboard.

### Via API

```bash
# Start
curl -X POST http://localhost:8000/api/agent/start

# Stop
curl -X POST http://localhost:8000/api/agent/stop

# Status
curl http://localhost:8000/api/agent/status

# Trigger manual search (works in any state)
curl -X POST http://localhost:8000/api/agent/search
```

---

## 🎯 Match Scoring & Quota Safety

| Component | Max Points | Factors |
|---|---|---|
| Title relevance | 20 | Exact/partial/fuzzy match against preferred titles |
| Technical skills | 30 | Semantic matching with synonym resolution |
| Experience | 15 | In-range / under / over |
| Location + work mode | 15 | India / Remote / Hybrid |
| Salary | 10 | Above/below minimum INR |
| Overall relevance | 10 | DevOps keywords in description |
| **Total** | **100** | |

- **Gemini 2.5 Flash Integration:** Uses Gemini for intelligent job parsing and description scoring.
- **Automatic LLM Quota Fallback:** If Gemini hits rate limits (429 / `ResourceExhausted`), the system automatically disables Gemini calls for the current run and falls back to rule-based scoring without failing the run.
- **Match Threshold:** Only jobs scoring **≥ 70** are emailed.

---

## 🧪 Testing

The repository features 118 unit tests covering all components:

```bash
# Run all 118 unit tests
pytest tests/ -v

# Test specific components
pytest tests/test_naukri.py -v
pytest tests/test_matching.py -v
```

All tests execute offline using mocked HTTP services.

---

## 📁 Project Structure

```
AI_Job_Hunter_Agent/
├── app/
│   ├── main.py                    # FastAPI entrypoint
│   ├── config.py                  # Settings + config.yaml loader
│   ├── api/
│   │   ├── routes_agent.py        # START/STOP/STATUS/SEARCH
│   │   ├── routes_jobs.py         # GET /jobs (recency sorted + counts)
│   │   ├── routes_preferences.py  # GET/PUT /preferences
│   │   └── routes_resume.py       # POST/GET /resume
│   ├── agents/
│   │   └── job_agent.py           # Main orchestrator + Report logger
│   ├── sources/
│   │   ├── base.py                # JobSource abstract class
│   │   ├── naukri.py              # Dedicated ethical Naukri adapter
│   │   ├── job_boards.py          # RemoteOK, Arbeitnow, Adzuna, Jooble
│   │   ├── company_careers.py     # Company career pages
│   │   ├── public_search.py       # Public search fallback
│   │   └── linkedin_discovery.py  # LinkedIn URL via SerpAPI
│   ├── matching/
│   │   ├── matcher.py             # LLM abstraction + Gemini 2.5 + Fallback
│   │   ├── scoring.py             # 0-100 scoring engine
│   │   └── resume_parser.py       # PDF resume parser
│   ├── database/
│   │   ├── database.py            # Async SQLAlchemy + Savepoints
│   │   └── models.py              # ORM models
│   ├── notifications/
│   │   └── email.py               # SMTP email sender
│   ├── scheduler/
│   │   └── scheduler.py           # APScheduler daily cron
│   └── templates/
│       ├── dashboard.html         # Web dashboard UI
│       └── email.html             # HTML email template
├── tests/
│   ├── test_naukri.py             # 29 Naukri adapter unit tests
│   ├── test_matching.py           # Matcher & scoring tests
│   ├── test_deduplication.py      # Job deduplication tests
│   ├── test_sources.py            # Source adapter tests
│   ├── test_agent.py              # Orchestrator tests
│   └── test_email.py              # Email rendering tests
├── config.yaml                    # Job preferences
├── .env.example                   # Environment variables template
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## 🔒 Security & Ethics

- **No Bot Evasion:** Does not spoof client fingerprints, bypass CAPTCHA, or simulate human interaction on protected job boards.
- **Environment Isolation:** Secrets are kept strictly in `.env`.
- **Database Safety:** Uses SQLAlchemy `SAVEPOINT` nesting to prevent transaction corruption on unique constraint violations.
- **Manual Apply:** The agent never automatically submits applications or communicates with recruiters on your behalf.
