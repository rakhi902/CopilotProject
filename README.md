# Job Application Co-Pilot

A web app that helps you apply for jobs. You give it your résumé and a job posting, and it builds a tailored application for you: a fit score, a rewritten résumé, a cover letter, and interview questions to practice with.

It runs on your own computer. The writing is done by an AI model through Groq, so you'll need a free key for that part. There's no database to install, and everything runs smoothly.

---

## What it does

You make an account, upload your résumé as a PDF, and paste in a job description (or just give it the link and it grabs the text itself). A few seconds later you get back:

- **A fit score.** A number from 0 to 100, plus what you already match, what you're missing, and the strengths to lead with.
- **A rewritten résumé.** Your bullet points reworked for this exact job, shown side by side: the old line crossed out in red, the new one in green.
- **A cover letter.** One page, written for this company and role. It gets checked against your résumé, so it won't claim a skill you don't actually have.
- **Interview prep.** Ten questions you're likely to be asked, each with a sample answer built from your real experience.

A few extra tools come with it:

- **ATS scan.** Checks how well your new résumé would get through an automated keyword filter, and tells you which honest keywords to add.
- **Mock interview.** Answer a question out loud and get it graded, with what was good and what to fix.
- **Salary coach.** Type in an offer (in ₹) and get two ready-to-send messages for negotiating it.
- **Downloads.** Save the résumé as a PDF, the cover letter as a Word file, and a one-week follow-up reminder for your calendar.

All your applications sit in one list. You can mark where each one stands (Not Applied, Applied, Interviewing, Rejected), search through them, delete several at once, and redo any single piece without rerunning the whole thing.

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

## What you need (Prerequisites)

Just two things — **no database to install**:

- **Python 3.10, 3.11, or 3.12.** Not 3.13 yet, because one of the libraries doesn't support it.
- **A free Groq API key** from https://console.groq.com/keys. This is what powers the writing.

There's no separate database to set up. The app keeps everything in one local file.

If you'd rather use OpenAI than Groq, you can: set `LLM_PROVIDER=openai` and `OPENAI_API_KEY` in `backend/.env`.

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

## Run it on Windows

1. Install Python from https://www.python.org/downloads/. On the first screen of the installer, check the box that says "Add python.exe to PATH."
2. Open the project folder in PowerShell and run:
   ```powershell
   .\run.ps1
   ```
3. The first run does the whole setup on its own: it builds the environment, installs the libraries, creates the local database, starts the app, and opens it in your browser at http://127.0.0.1:5500.

To turn on the AI writing, open `backend\.env`, paste your key after `GROQ_API_KEY=`, and run `.\run.ps1` again. Without a key you can still sign up and click around; only the writing won't work.

If PowerShell refuses to run the script, run this once and try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```
---

## Run it on Mac

1. Install Python with Homebrew:
   ```bash
   brew install python@3.11
   ```
2. From the project folder, run:
   ```bash
   chmod +x run.sh
   ./run.sh
   ```
3. It does the same setup and opens the app at http://127.0.0.1:5500.

Add your Groq key to `backend/.env` the same way, then run `./run.sh` again.

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

## Stopping and starting again

Press Ctrl-C in the terminal to stop the app. Your account and applications are saved in `backend/job_copilot.db`, so they'll be waiting for you when you run it again.


