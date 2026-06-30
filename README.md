# Job Application Co-Pilot

**Your editor for the job hunt.** Hand over your résumé and a job description, and
a team of AI agents reads your real experience and assembles a tailored
application kit: a fit analysis, a rewritten résumé, a cover letter, and interview
prep — all grounded in what your résumé actually says, never invented.

The backend is a FastAPI service that runs a LangGraph multi-agent pipeline. The
frontend is a single-page app built from plain HTML, CSS, and JavaScript (no build
step). **Local development is zero-setup: it runs on a SQLite file with no
database server to install.** PostgreSQL is used only for production deployment.

---

## Table of contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Architecture & tech stack](#architecture--tech-stack)
- [Project layout](#project-layout)
- [Data model](#data-model)
- [API overview](#api-overview)
- [Prerequisites](#prerequisites)
- [Run it on macOS](#run-it-on-macos)
- [Run it on Windows](#run-it-on-windows)
- [Configuration](#configuration)
- [Running the tests](#running-the-tests)
- [Deploying to Render](#deploying-to-render)
- [Design notes](#design-notes)

---

## What it does

You create an account, upload your résumé (PDF), and paste a job description (or
just give a link and the backend scrapes it). A few seconds later you get a
complete, role-specific kit:

**The four generated artifacts**

1. **Fit analysis** — a computed 0–100 fit score, the requirements you already meet, the gaps to address, and the strengths to lead with for *this* role.
2. **Résumé rewrite** — your existing bullets re-angled around the job's keywords, shown as a proofreader's diff: the original struck through in red beside the improved version in green, each with a short note on why it's stronger.
3. **Cover letter** — a grounded one-page letter matched to the company and role. A fact-checker audits it against your résumé, so it never claims a skill you don't have.
4. **Interview prep** — ten likely questions, each with a strong sample answer drawn from your real experience.

**The extra tools**

- **ATS keyword scan** — scores how well your rewritten résumé would survive an automated keyword screen, and tells you which honest keywords to add. It ignores hedged "haven't used X" mentions instead of rewarding them.
- **Voice mock interview** — practice an answer out loud (speech-to-text in the browser) and get it graded against the ideal answer, with concrete strengths and improvements.
- **Salary-negotiation coach** — enter an offer and get two ready-to-send negotiation scripts (all amounts in Indian Rupees, ₹).
- **One-click exports** — download the rewritten résumé as a PDF, the cover letter as a Word `.docx`, and a one-week follow-up reminder as a calendar `.ics` file.

**The workspace**

Everything lives in a split-screen "command center": a roster on the left lists
your whole pipeline of applications (with a live status pill, search, multi-select
delete, and an application-status dropdown — Not Applied / Applied / Interviewing /
Rejected), and the stage on the right shows the selected role's kit behind a tab
bar. You can regenerate any single artifact without re-running the whole pipeline.

---

## How it works

Submitting a role kicks off a background pipeline so the API can respond
instantly; the frontend polls until the kit is ready. The pipeline is a
coordinator that fans out to three agents in parallel, with a self-correction loop
on the cover letter:

```
START → coordinator → fit_analyst ─┬─ resume_writer ───────────────────────┬─→ END
                                   ├─ interviewer ──────────────────────────┤
                                   └─ cover_letter_writer → verify_cover_letter
                                              ▲                       │
                                              └──── "retry" ──────────┘  ("proceed") → END
```

1. **Coordinator** trims and normalizes the résumé and JD text.
2. **Fit Analyst** compares the two and produces the structured fit analysis.
3. **Résumé Writer**, **Cover Letter writer**, and **Interviewer** all run off that analysis at the same time.
4. **The Governor** (`verify_cover_letter`) checks the drafted letter against the résumé. If it finds a claim the résumé doesn't support, it sends the letter back for a corrective rewrite — capped at two drafts, so the loop always terminates. When the job needs a skill the candidate lacks, the writer bridges the gap honestly (emphasizing transferable, first-principles experience) rather than claiming the skill.

If any single agent hits an error (say, a flaky LLM call), it records the error
and returns nothing instead of bringing down the whole run.

---

## Architecture & tech stack

| Layer         | Technology                                                          |
| ------------- | ------------------------------------------------------------------ |
| Backend API   | FastAPI, served by Uvicorn                                          |
| Database      | SQLAlchemy 2 — **SQLite locally (zero setup)**, PostgreSQL in production |
| Migrations    | Alembic                                                             |
| Agents        | LangGraph (a coordinator + four agents + the Governor)             |
| LLM provider  | Groq (`llama-3.3-70b`) or OpenAI (`gpt-4o-mini`)                   |
| Auth          | JWT access tokens, bcrypt-hashed passwords                          |
| Résumé parser | `pypdf`                                                             |
| JD scraping   | `requests` + `beautifulsoup4` (with an SSRF guard)                 |
| Exports       | `python-docx` (DOCX) and `fpdf2` (PDF)                            |
| Frontend      | Vanilla HTML + CSS + JavaScript (`fetch`, no build step)           |

---

## Project layout

```
job_copilot_root/
├─ backend/
│  ├─ app/
│  │  ├─ api/         FastAPI routers (auth, roles, drafts, analysis)
│  │  ├─ core/        config, security (JWT), DB session, shared dependencies
│  │  ├─ models/      SQLAlchemy models: User, Role, Draft
│  │  ├─ schemas/     Pydantic request/response validation
│  │  ├─ services/    PDF parsing, JD scraping, exports, and the agent pipeline
│  │  │  └─ agents/   the LangGraph graph, nodes, prompts, and state
│  │  └─ main.py      the FastAPI application factory
│  ├─ migrations/     Alembic migration environment + versions
│  ├─ tests/          the pytest suite
│  ├─ setup_env.py    creates backend/.env (used by the launchers)
│  ├─ requirements.txt
│  └─ .env.example
├─ frontend/
│  ├─ index.html      the single-page-app shell
│  ├─ css/styles.css
│  └─ js/
│     ├─ api.js       fetch() wrappers around every endpoint
│     └─ app.js       views, rendering, and client state
├─ run.sh             one-click setup + launcher (macOS / Linux)
├─ run.ps1            one-click setup + launcher (Windows)
├─ Makefile           task runner (setup, migrate, run, test)
└─ render.yaml        Render deploy blueprint (PostgreSQL)
```

---

## Data model

Three tables, owned top to bottom (deleting a user cascades to their roles and
drafts):

- **User** — an account: email, bcrypt-hashed password, optional name. Authenticates with JWT access tokens.
- **Role** — one target job: title, company, the full JD text (and the URL it was scraped from, if any), the plain text extracted from the uploaded résumé, and the user-managed application status.
- **Draft** — the generated kit for a role: `fit_analysis`, `resume_rewrite`, `cover_letter`, and `interview_qa` (stored as JSON), plus a `status` (pending → processing → completed / failed) the frontend polls on.

---

## API overview

All endpoints are under `http://127.0.0.1:8000`. Interactive docs are at
`http://127.0.0.1:8000/docs` once the backend is running.

| Method & path                              | What it does                                        |
| ------------------------------------------ | --------------------------------------------------- |
| `POST /auth/register`, `/auth/login`, `GET /auth/me` | Create an account, log in (get a token), read the current user. |
| `POST /roles`                              | Upload a résumé + JD, create a role, start generation. |
| `GET /roles`, `GET /roles/{id}`            | List the user's roles / fetch one.                  |
| `GET /roles/{id}/draft`, `GET /drafts/{id}`| Poll the generated draft.                           |
| `PATCH /roles/{id}`                        | Update the application status.                       |
| `DELETE /roles/{id}`, `POST /roles/bulk-delete` | Delete one or several roles.                   |
| `POST /roles/{id}/regenerate/{artifact}`   | Re-run one agent (`resume` / `cover` / `interview`).|
| `POST /roles/{id}/ats-score`, `/interview/grade`, `/salary-coach` | The extra analysis tools. |
| `GET /roles/{id}/export/resume.pdf`, `/cover-letter.docx`, `/calendar` | Download the artifacts. |
| `GET /health`                              | Liveness probe.                                     |

---

## Prerequisites

Just two things — **no database to install**:

- **Python 3.10–3.12** (3.13 isn't supported yet because of a dependency).
- A free **LLM API key** from [Groq](https://console.groq.com/keys).

---

## Run it on macOS

### Step 1 — Install Python

With [Homebrew](https://brew.sh):

```bash
brew install python@3.11
```

### Step 2 — Run the one-click launcher

From the project root:

```bash
chmod +x run.sh   # first time only
./run.sh
```

That's it. The launcher creates the virtualenv, installs the dependencies, creates
`backend/.env` (with a generated JWT secret), creates the local **SQLite** database
by running the migrations, starts both servers, and opens
**http://127.0.0.1:5500** in your browser. Press **Ctrl-C** to stop.

There's no database server to install or configure — the app keeps its data in a
single file at `backend/job_copilot.db`.

### Step 3 — Add your Groq key (for AI generation)

The launcher sets everything up, but it can't know your API key. To generate kits,
open `backend/.env`, set:

```ini
GROQ_API_KEY=gsk_your_key_here
```

then re-run `./run.sh`. (Without a key you can still sign up and explore the app;
generation just reports a friendly failure.)

> **Prefer to do it by hand?** See [Manual setup](#manual-setup) below.

---

## Run it on Windows

### Step 1 — Install Python

Download **Python 3.11** (or 3.10 / 3.12) from
[python.org/downloads](https://www.python.org/downloads/). In the installer, tick
**“Add python.exe to PATH”** on the first screen, then install.

### Step 2 — Run the one-click launcher

From the project root, in PowerShell:

```powershell
.\run.ps1
```

That's it. The launcher creates the virtualenv, installs the dependencies, creates
`backend\.env` (with a generated JWT secret), creates the local **SQLite** database
by running the migrations, starts both servers, and opens
**http://127.0.0.1:5500** in your browser.

There's no database server to install or configure — the app keeps its data in a
single file at `backend\job_copilot.db`.

> If PowerShell blocks the script, allow local scripts for your user once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then re-run `.\run.ps1`.

### Step 3 — Add your Groq key (for AI generation)

Open `backend\.env`, set `GROQ_API_KEY=gsk_your_key_here`, and re-run `.\run.ps1`.
(Without a key you can still sign up and explore; generation just reports a
friendly failure.)

> **Prefer to do it by hand?** See [Manual setup](#manual-setup) below.

---

## Manual setup

If you'd rather run each step yourself instead of using the launcher:

**macOS / Linux**

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
#   In backend/.env set JWT_SECRET_KEY and GROQ_API_KEY. Leave DATABASE_URL unset
#   to use SQLite locally. Generate a secret with:
#     python3 -c "import secrets; print(secrets.token_urlsafe(64))"

alembic upgrade head                       # creates backend/job_copilot.db

uvicorn app.main:app --reload              # terminal 1
cd ../frontend && python3 -m http.server 5500   # terminal 2
```

**Windows (PowerShell)**

```powershell
cd backend
py -3.11 -m venv .venv          # swap -3.11 for the version you installed
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt

Copy-Item .env.example .env
#   In backend\.env set JWT_SECRET_KEY and GROQ_API_KEY. Leave DATABASE_URL unset
#   to use SQLite locally. Generate a secret with:
#     python -c "import secrets; print(secrets.token_urlsafe(64))"

alembic upgrade head                       # creates backend\job_copilot.db

uvicorn app.main:app --reload              # terminal 1
cd ..\frontend ; python -m http.server 5500     # terminal 2
```

Open **http://127.0.0.1:5500**.

---

## Configuration

All settings live in `backend/.env`. The only ones you need locally are
`JWT_SECRET_KEY` and an LLM key — the database needs no configuration. See
`.env.example` for the full list.

| Variable               | Example                                          | What it's for                                                |
| ---------------------- | ------------------------------------------------ | ------------------------------------------------------------ |
| `JWT_SECRET_KEY`       | *(a long random string)*                         | Signs login tokens.                                          |
| `GROQ_API_KEY`         | `gsk_...`                                         | Required when `LLM_PROVIDER=groq`.                          |
| `LLM_PROVIDER`         | `groq`                                            | Which provider the agents use: `groq` or `openai`.          |
| `OPENAI_API_KEY`       | `sk-...`                                           | Required when `LLM_PROVIDER=openai`.                       |
| `DATABASE_URL`         | *(unset locally)*                                | Leave unset to use SQLite. Set to a PostgreSQL URL in production. |
| `BACKEND_CORS_ORIGINS` | `http://localhost:5500,http://127.0.0.1:5500`    | Frontend origins allowed to call the API.                   |

> Generation needs a working LLM key. Without one, the agents fail gracefully and
> the draft is marked **failed** rather than crashing the server.

---

## Running the tests

```bash
cd backend
source .venv/bin/activate            # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest                               # or: make test
```

The suite is self-contained — it uses an in-memory SQLite database and a fake LLM,
so it needs no API key and nothing external. You should see **48 passed, 1
skipped** (the skipped test only runs when no LLM key is configured).

---

## Deploying to Render

Production runs on **PostgreSQL**, and `render.yaml` wires it up for you.

The app is built to switch databases purely through the `DATABASE_URL` environment
variable, with no code changes:

- **Locally**, `DATABASE_URL` is unset, so the app falls back to SQLite.
- **In production**, Render provisions a managed PostgreSQL database and injects its
  `DATABASE_URL`. Render hands it out using the legacy `postgres://` scheme; the
  app automatically rewrites that to `postgresql://`, which is what SQLAlchemy 2
  requires (`app/core/config.py`). The `check_same_thread` connection flag is
  applied only for SQLite, never for PostgreSQL.

To deploy, point a new Render Blueprint at this repo. The blueprint provisions the
database, installs dependencies, runs `alembic upgrade head` before each deploy
(Render's filesystem is ephemeral, so migrations run every time), and starts the
API. Set `GROQ_API_KEY` and `BACKEND_CORS_ORIGINS` in the dashboard — they're
marked `sync: false`, so they never live in the repo.

---

## Design notes

- **Zero-setup local, Postgres in production.** Local development uses a SQLite file so there's nothing to install; production sets `DATABASE_URL` to PostgreSQL. The same code drives both.
- **Grounded, or it doesn't ship.** The cover-letter Governor fact-checks every draft against the résumé and rewrites anything it can't support. When the JD needs a skill the candidate lacks, the writer bridges the gap honestly instead of claiming it. The ATS scan is just as strict — it ignores hedged "haven't used X" mentions rather than rewarding them.
- **Rupees throughout.** All money in the app — the salary coach, its prompts, and the UI — is in Indian Rupees (₹).
- **No build step on the frontend.** It's plain HTML, CSS, and JavaScript served as static files, so there's nothing to compile and the API client is a single `window.API` object.
```
