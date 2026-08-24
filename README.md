# 🎯 AI Job Hunter Agent

A production-quality personal job-search agent that runs daily, searches multiple job sources, uses AI to match jobs against your resume, deduplicates results, and sends you a beautifully formatted email with new matching jobs.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🤖 **AI Matching** | LLM-powered semantic skill matching (GKE ↔ Kubernetes, Terraform ↔ IaC) |
| 📊 **0-100 Scoring** | Intelligent scoring across 6 dimensions |
| 🔎 **Multi-Source** | RemoteOK, Naukri, Arbeitnow, Adzuna, Jooble, LinkedIn URL discovery |
| 🔄 **Deduplication** | Canonical hash + URL matching prevents duplicate emails |
| 📅 **Daily Schedule** | Automatically runs at 9:00 AM IST (configurable) |
| ▶/⏹ **START/STOP** | Full agent control with database preservation |
| 📧 **Rich Email** | Dark-themed HTML email with match scores and apply links |
| 🎛️ **Dashboard** | Real-time web UI for status, controls, and job browsing |
| 📄 **Resume Upload** | Upload PDF resume; skills extracted automatically |
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
│           CompanyCareer │ LinkedIn URL Discovery             │
│  Matcher: Gemini / OpenAI / Mock (configurable)             │
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

You can also update preferences via the API:
```bash
curl -X PUT http://localhost:8000/api/preferences \
  -H "Content-Type: application/json" \
  -d '{"job_preferences": {"minimum_salary_inr": 1200000}}'
```

---

## 📄 Resume Upload

1. **Via Dashboard**: Click the resume upload area and select your PDF
2. **Via API**:
   ```bash
   curl -X POST http://localhost:8000/api/resume/upload \
     -F "file=@/path/to/your/resume.pdf"
   ```

The parser extracts:
- Skills and technologies
- Cloud platforms (GCP, AWS, Azure)
- DevOps tools (Kubernetes, Terraform, Docker, etc.)
- Years of experience
- Education and certifications

---

## ▶ START / STOP the Agent

### Via Dashboard
Click the **"Start Agent"** or **"Stop Agent"** button on the dashboard.

### Via API

```bash
# Start
curl -X POST http://localhost:8000/api/agent/start

# Stop
curl -X POST http://localhost:8000/api/agent/stop

# Status
curl http://localhost:8000/api/agent/status

# Trigger manual search
curl -X POST http://localhost:8000/api/agent/search
```

### Behavior

| State | Behavior |
|---|---|
| **RUNNING** | Searches daily at 9:00 AM IST. Emails new matching jobs. |
| **STOPPED** | No searches. No emails. Database preserved. |
| **Restart after stop** | Only emails jobs discovered after restart date. |

---

## 📅 Daily Scheduling

The agent runs automatically every day at **9:00 AM IST**.

Configure in `.env`:
```env
SCHEDULER_TIMEZONE=Asia/Kolkata
SCHEDULER_HOUR=9
SCHEDULER_MINUTE=0
```

If the machine is offline at the scheduled time, the job is missed gracefully (logged, not retried). APScheduler uses `coalesce=True` to prevent pile-up.

---

## 📧 Email

### Test Email Configuration
```bash
curl -X POST http://localhost:8000/api/agent/test-email
```

If email is not configured, the test email is saved to `email_output/test_email_*.html` — open it in a browser to preview.

### Email Format
- Subject: `[AI Job Hunter] 7 New DevOps Jobs Found — 22 Aug 2026`
- Groups: 🔥 Excellent (90-100) | 💼 Strong (80-89) | 👍 Good (70-79)
- Each job: title, company, location, salary, experience, skills, match reasoning, apply button

---

## 🎯 Match Scoring

| Component | Max Points | Factors |
|---|---|---|
| Title relevance | 20 | Exact/partial/fuzzy match against preferred titles |
| Technical skills | 30 | Semantic matching with synonym resolution |
| Experience | 15 | In-range / under / over |
| Location + work mode | 15 | India / Remote / Hybrid |
| Salary | 10 | Above/below minimum INR |
| Overall relevance | 10 | DevOps keywords in description |
| **Total** | **100** | |

**Skill Synonyms** (built-in):
- GKE → Kubernetes
- Terraform → Infrastructure as Code
- GCP → Google Cloud Platform
- ArgoCD → GitOps
- (and many more in `config.yaml`)

Only jobs scoring **≥ 70** are emailed.

---

## 🔌 Adding a New Job Source

1. Create a new file in `app/sources/`:

```python
# app/sources/my_new_source.py
from app.sources.base import JobSource, RawJob

class MyNewSource(JobSource):
    name = "MySource"
    description = "My custom job source"

    async def search(self) -> list[RawJob]:
        jobs = []
        # ... fetch and parse jobs ...
        return jobs
```

2. Register it in `app/sources/__init__.py`:

```python
from app.sources.my_new_source import MyNewSource

def get_all_sources(preferences, search_settings):
    source_classes = [
        RemoteOKSource,
        # ... existing sources ...
        MyNewSource,  # ← add here
    ]
    ...
```

That's it. The agent will automatically call it on every search run.

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=app --cov-report=html

# Run specific test file
pytest tests/test_matching.py -v

# Run specific test
pytest tests/test_deduplication.py::TestDeduplication::test_removes_exact_duplicate -v
```

All tests use mocked external services — no real API calls required.

---

## 🐳 Docker Reference

```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f job-hunter-api

# Rebuild after code changes
docker compose build job-hunter-api
docker compose up -d job-hunter-api

# Stop (database preserved)
docker compose down

# Stop and delete database (fresh start)
docker compose down -v

# Shell into container
docker compose exec job-hunter-api bash
```

---

## 📁 Project Structure

```
AI_Job_Hunter_Agent/
├── app/
│   ├── main.py                    # FastAPI entrypoint
│   ├── config.py                  # Settings + config.yaml loader
│   ├── api/
│   │   ├── routes_agent.py        # START/STOP/STATUS/SEARCH
│   │   ├── routes_jobs.py         # GET /jobs, GET /jobs/{id}
│   │   ├── routes_preferences.py  # GET/PUT /preferences
│   │   └── routes_resume.py       # POST/GET /resume
│   ├── agents/
│   │   └── job_agent.py           # Main orchestrator
│   ├── sources/
│   │   ├── base.py                # JobSource abstract class
│   │   ├── job_boards.py          # RemoteOK, Arbeitnow, Adzuna, Jooble
│   │   ├── company_careers.py     # Company pages + Naukri
│   │   ├── public_search.py       # Public search fallback
│   │   └── linkedin_discovery.py  # LinkedIn URL via SerpAPI
│   ├── matching/
│   │   ├── matcher.py             # LLM abstraction + JobMatcher
│   │   ├── scoring.py             # 0-100 scoring engine
│   │   └── resume_parser.py       # PDF resume parser
│   ├── database/
│   │   ├── database.py            # SQLAlchemy async engine
│   │   └── models.py              # ORM models
│   ├── notifications/
│   │   └── email.py               # SMTP email sender
│   ├── scheduler/
│   │   └── scheduler.py           # APScheduler daily cron
│   └── templates/
│       ├── dashboard.html         # Web dashboard
│       └── email.html             # HTML email template
├── tests/
│   ├── conftest.py
│   ├── test_matching.py
│   ├── test_deduplication.py
│   ├── test_sources.py
│   ├── test_agent.py
│   └── test_email.py
├── docker/
│   └── init.sql
├── config.yaml                    # Job preferences (edit freely)
├── .env.example                   # Environment variables template
├── .gitignore
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── pytest.ini
└── README.md
```

---

## 🔒 Security

- **Never** commit `.env` to git — it's in `.gitignore`
- Use Gmail **App Passwords**, not your real password
- All API keys are in `.env` only
- Docker Compose uses bind mounts for `config.yaml` (read-only)
- Non-root user in Docker container

---

## ⚠️ Important: What the Agent Does NOT Do

The agent will **NEVER**:
- ❌ Apply for jobs automatically
- ❌ Log into LinkedIn
- ❌ Use your LinkedIn credentials
- ❌ Scrape authenticated pages
- ❌ Bypass CAPTCHA or rate limits
- ❌ Send messages to recruiters

The agent **only**:
- ✅ Finds jobs from public sources
- ✅ Scores them against your resume
- ✅ Emails you the best matches
- ✅ You apply manually

---

## 🔧 Troubleshooting

### "Database connection failed"
- Check PostgreSQL is running: `pg_isready`
- Verify `DATABASE_URL` in `.env`
- For Docker: `docker compose logs postgres`

### "Email not sending"
- Use an App Password, not your Gmail password
- Enable 2FA first, then create App Password
- Test: `curl -X POST http://localhost:8000/api/agent/test-email`
- If not configured, email is saved to `email_output/`

### "No jobs found"
- Agent must be RUNNING: click Start on dashboard
- Click "Search Now" for immediate search
- Check logs: `docker compose logs -f job-hunter-api`
- Add Adzuna/Jooble keys for better India coverage

### "LLM matching not working"
- Set `LLM_PROVIDER=mock` in `.env` to use rule-based matching (no API key needed)
- For Gemini: get a free key at [aistudio.google.com](https://aistudio.google.com/app/apikey)

### "Scheduler not running"
- The scheduler starts with the app
- Check: `curl http://localhost:8000/api/agent/status`
- Look for `next_scheduled_run` in the response

---

## 📊 API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Dashboard UI |
| GET | `/health` | Health check |
| GET | `/api/agent/status` | Agent status + stats |
| POST | `/api/agent/start` | Start the agent |
| POST | `/api/agent/stop` | Stop the agent |
| POST | `/api/agent/search` | Trigger manual search |
| POST | `/api/agent/test-email` | Send test email |
| GET | `/api/agent/runs` | Search run history |
| GET | `/api/jobs` | List discovered jobs |
| GET | `/api/jobs/{id}` | Get job details |
| GET | `/api/preferences` | Get job preferences |
| PUT | `/api/preferences` | Update preferences |
| POST | `/api/resume/upload` | Upload PDF resume |
| GET | `/api/resume` | Get parsed resume data |
| GET | `/docs` | Swagger UI |
