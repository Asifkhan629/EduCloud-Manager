# EduCloud Manager

**Cloud-Based Student Record Management System** built with Flask, SQLAlchemy, SQLite/PostgreSQL, HTML, CSS, and vanilla JavaScript. This college-project edition includes server-side role checks and a responsive API-backed dashboard—not just a static prototype.

> **Demonstration-data warning:** all sample people and academic records are fictional. Demo accounts use temporary passwords and force a password change on first login. Do not upload real student data to a public repository or use this configuration as-is for a production institution.

## 1. Features

- **Three roles:** administrator, teacher, and student; sessions and permissions are checked on the server.
- **Secure sign-in:** Werkzeug password hashes, CSRF protection for state-changing requests, secure-cookie configuration for HTTPS deployment, login rate limiting, and one-time admin password resets.
- **Student records:** create, view, update, search, filter, paginate, deactivate/reactivate, assign a class, and export directory records.
- **Academic structure:** departments, classes/sections, subjects, teachers, and explicit teacher-to-class-to-subject assignments.
- **Attendance:** bulk Present / Absent / On Leave entry, existing-session updates, duplicate prevention, date filters, percentage summaries, threshold flags, and CSV export.
- **Assessment and marks:** maximum and passing marks, marks validation, remarks, missing marks kept separate from zero, grade calculations, pass/fail indicators, and results by subject and term.
- **Reports:** access-controlled CSV exports for students, attendance, and marks. The report screen can be printed or saved as PDF using the browser.
- **Analytics:** dashboard statistics and a Chart.js attendance trend (the surrounding dashboard works if Chart.js cannot load).
- **Fictional sample dataset:** 3 departments, 3 classes, 6 subjects, 5 teachers, 30 students, teacher assignments, enrollments, 30 completed weekday attendance dates, and 2 assessments per subject.
- **Deployment-ready database layer:** SQLite locally; SQLAlchemy can use PostgreSQL for hosted deployment.

## 2. Folder structure

```text
EduCloud-Manager/
├── app.py                 # Flask app, database models, routes, validation, authorization
├── requirements.txt       # Python dependencies
├── schema.sql             # Normalized SQLite schema reference/bootstrap
├── seed.py                # Safe, fictional demo-data seeder
├── tests.py               # Automated backend/access-control tests
├── .env.example           # Environment variable template
├── .gitignore
├── README.md
├── migrations/
│   ├── alembic.ini
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 20261014_0001_initial_schema.py
├── templates/
│   └── index.html         # Single-page application shell
└── static/
    ├── style.css          # Responsive visual system
    └── script.js          # API-connected UI interactions
```

The SQLAlchemy models in `app.py` are the cross-database schema source of truth. For an empty local SQLite database, `schema.sql` is applied first when `AUTO_CREATE_DB=1`. The project also includes Flask-Migrate/Alembic with an initial migration for repeatable initialization on SQLite or PostgreSQL. Future schema changes should use reviewed migrations; `create_all()` does not alter existing columns.

## 3. Requirements

- Windows 10/11, macOS, or Linux
- Python **3.11 or 3.12** recommended
- VS Code (optional, but beginner-friendly)
- Internet for first-time pip installs and external Google Fonts / Chart.js; core form/table functionality does not depend on Chart.js

Install Python from [python.org](https://www.python.org/downloads/). On Windows, tick **Add Python to PATH** during installation. Verify in PowerShell:

```powershell
py --version
py -m pip --version
```

If `py` is unavailable, use `python` in the commands below.

## 4. Open the project in VS Code

1. Extract the `EduCloud-Manager.zip` archive to a normal folder such as `C:\Projects\EduCloud-Manager`.
2. Open VS Code → **File → Open Folder…** → select `EduCloud-Manager`.
3. Open **Terminal → New Terminal** and select PowerShell, unless your terminal is already PowerShell.

## 5. Create the virtual environment and install dependencies

Run in **PowerShell** from the project root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks environment activation, use this for the current terminal only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Alternative **Command Prompt (cmd.exe)** commands:

```bat
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 6. Configure environment variables

Create a local `.env` file by copying `.env.example`:

```powershell
Copy-Item .env.example .env
```

Open `.env` and replace `SECRET_KEY` with a long, random secret. You can generate one with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the generated value into `.env`. Keep `.env` private; it is ignored by Git. For local development, the default database is `sqlite:///educloud.db` (Flask-SQLAlchemy places relative SQLite files in the app's `instance` folder).

## 7. Initialize the database and insert demo data

For a quick local start, `AUTO_CREATE_DB=1` initializes the local SQLite database when the app starts. Or explicitly initialize the mapped schema:

```powershell
python -c "from app import app, db; app.app_context().push(); db.create_all(); print('Database ready')"
```

To initialize from the **versioned migration** instead (recommended when validating production-like setup), run with automatic creation disabled:

```powershell
$env:AUTO_CREATE_DB = "0"
flask --app app db upgrade
Remove-Item Env:AUTO_CREATE_DB
```

The included migration creates every normalized table. Run database migrations before starting the app with `AUTO_CREATE_DB=0`.

Insert the fictional dataset:

```powershell
python seed.py
```

The seed script is additive, wraps inserts in a transaction, never deletes existing records, and exits without changes if the demo `admin` account already exists. It refuses to seed when `FLASK_ENV=production`; it also refuses non-SQLite databases unless `ALLOW_DEMO_SEED=1` is deliberately provided for a disposable database. **Never run the demo seeder against a production database.**

Seed script rerun check:

```powershell
python seed.py
```

The second run should say that demo data already exists and make no changes.

## 8. Run the application

```powershell
python app.py
```

Open this URL in your browser:

**http://127.0.0.1:5000**

Health check: **http://127.0.0.1:5000/api/health**

Use `Ctrl+C` in the terminal to stop the server. For local development only, you can set `FLASK_DEBUG=1` in `.env`; never enable Flask debug mode on a public server.

## 9. Demo accounts

| Role | Username | Initial password |
|---|---|---|
| Administrator | `admin` | `AdminDemo2026!` |
| Teacher | `teacher1` | `TeachDemo2026!` |
| Student | `student001` | `StudentDemo2026!` |

All initial demo accounts require a password change after sign-in. Choose at least 10 characters, including a letter and a number. These credentials are for a local demonstration only; change them before showing the app publicly and never reuse them elsewhere.

Other demo student usernames are `student002` through `student030`; teacher usernames are `teacher1` through `teacher5`. The sample emails use the reserved `example.com` domain. Seeded phone numbers are fictional.

## 10. Automated tests

The tests use Flask's built-in test client and a separate SQLite database named `instance/educloud_test.db`. They cover CSRF protection, authentication, role protection, student creation/search, assigned-teacher attendance access, duplicate-batch handling, marks limits and grading, authorized CSV export, admin password reset, and safe seed reruns.

PowerShell / Command Prompt (inside the activated virtual environment):

```powershell
python -m unittest -v tests.py
```

The test suite drops and recreates only its dedicated test database. It does not point at or delete the default `educloud.db` file. Run the tests after editing backend routes or database models.

## 11. Attendance and grading policies

**Attendance percentage:** `Present sessions / eligible recorded sessions × 100`. The system only counts saved attendance records, so sessions that have not been recorded cannot be counted. By default, `On Leave` stays in the denominator and does not count as present. Set `EXCLUDE_APPROVED_LEAVE=1` only if your institution treats approved leave as excluded. Attendance attention threshold defaults to `75`; change `ATTENDANCE_THRESHOLD` to configure it.

**Grades:** defaults are `A+ ≥ 90`, `A ≥ 80`, `B ≥ 70`, `C ≥ 60`, `D ≥ 50`, and `F < 50`. The `GRADE_BOUNDARIES` environment variable accepts a JSON object of grade names and minimum percentages. Grade labels are evaluated from the highest boundary down. An assessment row with no mark remains missing; it is not treated as zero. A subject-term result is marked Fail if an entered assessment is below its configured passing marks or the resulting overall grade is F.

## 12. Useful API endpoints

All data endpoints except `/api/health` require a signed-in user. POST/PATCH/DELETE requests require the CSRF token, sent by the frontend in `X-CSRFToken`.

| Endpoint | Purpose | Allowed roles |
|---|---|---|
| `POST /api/login`, `POST /api/logout` | Session authentication | Public / signed-in |
| `GET /api/dashboard`, `GET /api/me` | Role-aware dashboard and profile | All roles |
| `GET/POST /api/students` | Student records | Read scope by role; create admin only |
| `PATCH/DELETE /api/students/<id>` | Update/deactivate student | Admin only |
| `GET/POST /api/teachers` | List/create teacher accounts | Admin only |
| `POST /api/assignments` | Assign teacher/class/subject | Admin only |
| `GET/POST /api/attendance` | Query and bulk-save attendance | Read scope by role; save admin/assigned teacher |
| `GET/POST /api/assessments` | List/create assessments | Read scope by role; create admin/assigned teacher |
| `GET/POST /api/marks` | Read/save entered marks | Read scope by role; save admin/assigned teacher |
| `GET /api/results` | Subject/term result summaries | Own results / assigned classes / admin |
| `GET /api/reports/*.csv` | Download data exports | Role-limited at server side |
| `POST /api/change-password` | Change current user's password | Signed-in user |
| `POST /api/users/<id>/reset-password` | Issue one-time temporary password | Admin only |
| `GET /api/health` | Health check | Public |

## 13. Cloud deployment (Render + PostgreSQL)

A local SQLite file is **not** cloud hosting. For hosted use, deploy the Flask service and use a managed, persistent PostgreSQL database. Render's current Flask quickstart uses `pip install -r requirements.txt` as the build command and `gunicorn app:app` to start the service ([Render Flask deployment guide](https://render.com/docs/deploy-flask)). Configure secrets in the Render dashboard instead of committing them ([environment variable guide](https://render.com/docs/configure-environment-variables)). SQLAlchemy's PostgreSQL dialect uses a database URL and driver such as psycopg ([SQLAlchemy PostgreSQL docs](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html)).

1. Push the code to a **private** GitHub repository if your institution's work contains any non-public materials. For the fictional demo, public is fine once credentials are changed or clearly treated as demo-only.
2. In Render, create a managed PostgreSQL database and note its **internal connection URL** (use the URL appropriate for the web service's region/network).
3. Create a new **Web Service** connected to your repository.
4. Set **Build Command** to `pip install -r requirements.txt`.
5. Set **Start Command** to `gunicorn app:app`.
6. Set environment variables in Render:
   - `FLASK_ENV=production`
   - `FLASK_DEBUG=0`
   - `SECRET_KEY` = a strong unique random value
   - `DATABASE_URL` = your managed PostgreSQL connection URL
   - `COOKIE_SECURE=1`
   - `AUTO_CREATE_DB=0`
   - `ATTENDANCE_THRESHOLD=75`
   - `EXCLUDE_APPROVED_LEAVE=0` (unless your formal attendance policy excludes approved leave)
   - `RATELIMIT_STORAGE_URI` = a shared Redis URL for multi-instance deployment; in-process memory rate limits reset on restart and are not shared across instances
7. Configure the service's **Pre-Deploy Command** (or run once in a provider shell before enabling traffic) as `flask --app app db upgrade`, using the same production `DATABASE_URL`. The initial migration is included in the repository.
8. Confirm HTTPS is enabled by the hosting provider. Do not disable secure cookies in production.
9. Open `/api/health` and verify `{"status":"ok","database":"connected"}`.
10. Do **not** run `seed.py` against the production database. Create the first administrator through a reviewed administrative provisioning procedure and distribute temporary passwords securely. This starter project's seed accounts are only for the local demonstration.

### Database initialization and schema changes

The app's `db.create_all()` convenience bootstrap does **not** alter existing tables when models change. Flask-Migrate/Alembic is configured and the initial migration is included. For future schema changes, keep automatic creation disabled while generating and applying migrations:

```powershell
$env:AUTO_CREATE_DB = "0"
flask --app app db migrate -m "Describe schema change"
flask --app app db upgrade
Remove-Item Env:AUTO_CREATE_DB
```

Review generated migration code, test it against a disposable/staging database, back up PostgreSQL, and plan rollback/recovery before production. Commit reviewed migrations alongside code. Do not run `db init` repeatedly in an already initialized repository, and do not regard `create_all()` as a migration tool. A managed persistent database is required; do not store production SQLite records on an ephemeral hosting filesystem.

## 14. Security and production checklist

- Replace `SECRET_KEY`; use secret-manager environment variables and never commit `.env`.
- Use PostgreSQL with backups and access controls for real student data.
- Use HTTPS and `COOKIE_SECURE=1`.
- Configure shared Redis storage for login rate limits when deploying multiple application workers/instances.
- Change or remove demo credentials; keep temporary passwords private and force rotation.
- Review the legal/privacy requirements that apply to student education records before production use.
- Add audit retention policy, monitoring, database backups, an email/password reset workflow, migrations, and security review before institutional adoption.
- Minimize stored personal data, never log passwords, and never publish real student information in GitHub sample data.

## 15. Troubleshooting

**`py` or `python` is not recognized:** reinstall Python with “Add Python to PATH,” then reopen the terminal.

**`Activate.ps1 cannot be loaded`:** use the process-only execution policy command in section 5, or switch to Command Prompt and activate `activate.bat`.

**`ModuleNotFoundError`:** activate `.venv` and run `pip install -r requirements.txt` again.

**Database file or permission error:** close the app, verify write permission in the project folder, and confirm the active `.env` uses the expected `DATABASE_URL`. Do not delete a database containing records you need.

**Invalid CSRF token:** refresh the page and sign in again. In this version, anonymous startup API checks preserve the login-page token, authentication rotates the token safely, and the frontend refreshes and retries once if an old tab submits a stale token. If you upgraded from an older ZIP, stop Flask with `Ctrl+C`, replace the project files with this updated version, then run `python app.py` again.

**Login returns 429:** the login rate limit was exceeded; wait a minute. For a multi-instance deployment, configure shared Redis storage.

**Chart is blank:** the dashboard still works without Chart.js; check the network/CDN or use the Attendance table and CSV exports.

**No classes or subjects in a form:** seed the local demo database or ask an administrator to create departments, classes, subjects, teacher accounts, and assignments first.

**Teacher cannot see or edit a class:** the administrator must assign the exact teacher + class + subject combination. Hiding a UI button is not the permission boundary; the backend checks assignments on each write.

**Seed script says the data already exists:** it intentionally does not create duplicates or reset data. To demonstrate a fresh dataset, use a separate empty local database URL (do not delete or reset any database with records you need).

---

Built as an educational demonstration project. Review and extend its operational, privacy, and migration practices before using it with real institutional records.
