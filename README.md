# 🎓 EduCloud Manager

**Cloud-Based Student Record Management System**

EduCloud Manager is a web-based academic management application designed to simplify student record management, attendance tracking, marks management, grading, and academic reporting.

Built using **Python Flask, SQLAlchemy, SQLite/PostgreSQL, HTML, CSS, and JavaScript**, the application provides separate dashboards for administrators, teachers, and students, with server-side authentication and role-based access control.

## ✨ Features

- 🔐 **Role-Based Login:** Separate administrator, teacher, and student access.
- 👨‍🎓 **Student Management:** Add, view, update, search, filter, and manage student records.
- 🏫 **Academic Management:** Organize departments, classes, sections, subjects, and teacher assignments.
- 📅 **Attendance Management:** Record Present, Absent, and On Leave statuses, calculate attendance percentages, and export attendance reports.
- 📝 **Marks and Grading:** Manage assessments, validate marks, calculate grades, and determine pass/fail status.
- 📊 **Interactive Dashboard:** View academic statistics and attendance trends.
- 📄 **Academic Reports:** Export student records, attendance, and marks to CSV.
- 🛡️ **Security:** Password hashing, CSRF protection, session management, login rate limiting, and server-side permission checks.
- 🗃️ **Database Support:** SQLite for local development and PostgreSQL for hosted deployments.
- 🧪 **Automated Tests:** Test authentication, access control, student management, attendance, grading, and reporting.
- ☁️ **Cloud-Ready Architecture:** Includes database migrations and deployment configuration guidance.

## 🛠️ Technology Stack

| Technology | Purpose |
|---|---|
| Python | Backend programming |
| Flask | Web framework and API |
| SQLAlchemy | Database ORM |
| SQLite | Local database |
| PostgreSQL | Hosted database option |
| HTML5 | Page structure |
| CSS3 | Responsive styling |
| JavaScript | Frontend interactions |
| Chart.js | Attendance visualization |
| Flask-Migrate / Alembic | Database migrations |
| Unittest | Automated testing |

## 📂 Project Structure

```text
EduCloud-Manager/
│
├── app.py
├── seed.py
├── tests.py
├── requirements.txt
├── schema.sql
├── .env.example
├── .gitignore
├── README.md
│
├── migrations/
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
│
├── templates/
│   └── index.html
│
└── static/
    ├── style.css
    └── script.js
```

## ⚙️ Prerequisites

Install the following software:

- Python 3.11 or 3.12
- Git
- Visual Studio Code (recommended)
- A terminal such as PowerShell or Command Prompt

Verify Python:

```bash
py --version
```

If the `py` command is unavailable, use `python` instead.

## 🚀 Installation and Execution

### Step 1: Clone the repository

Open your terminal and execute:

```bash
git clone https://github.com/Asifkhan629/EduCloud-Manager.git
```

Navigate to the project directory:

```bash
cd EduCloud-Manager
```

### Step 2: Create a virtual environment

```bash
py -m venv .venv
```

Activate it in Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

For Command Prompt, use:

```bat
.venv\Scripts\activate.bat
```

### Step 3: Install dependencies

Upgrade pip and install the required libraries:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: Configure environment variables

Create your local `.env` file from the example:

```powershell
Copy-Item .env.example .env
```

Open `.env` and configure the required settings. Generate a secure secret key with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Use the generated value for `SECRET_KEY` in your local environment configuration. Never publish actual secrets or production credentials.

### Step 5: Initialize the database

For a quick local setup, the application can initialize its database automatically when `AUTO_CREATE_DB=1`.

Alternatively, initialize the database explicitly:

```bash
python -c "from app import app, db; app.app_context().push(); db.create_all(); print('Database ready')"
```

For migration-based initialization, use PowerShell:

```powershell
$env:AUTO_CREATE_DB = "0"
flask --app app db upgrade
Remove-Item Env:AUTO_CREATE_DB
```

Run migrations before starting the application when automatic database creation is disabled.

### Step 6: Insert sample data

Run:

```bash
python seed.py
```

The seed script inserts fictional demonstration records, including students, teachers, subjects, attendance, and assessments.

The sample dataset includes:

- 3 departments
- 3 classes
- 6 subjects
- 5 teachers
- 30 students
- Sample attendance and assessment records

The seed script is designed to avoid duplicating existing demonstration data. Use it only with a disposable development database.

### Step 7: Run the application

Start the Flask server:

```bash
python app.py
```

Open your browser and visit:

**http://127.0.0.1:5000**

Health-check endpoint:

**http://127.0.0.1:5000/api/health**

Keep the terminal running while using the application. Press `Ctrl+C` to stop the server.

## 👥 User Roles

### Administrator

- Manage student and teacher accounts.
- Organize departments, classes, and subjects.
- Assign teachers to classes and subjects.
- Manage attendance and assessments.
- View dashboard analytics.
- Export academic reports.
- Reset user passwords.

### Teacher

- View assigned classes and students.
- Record and update attendance for assigned classes.
- Create assessments and enter marks.
- Review student performance and grades.
- Access authorized academic information.

### Student

- Access permitted student information.
- View attendance summaries.
- Check marks and subject results.
- View relevant academic information through the student dashboard.

Access to features is enforced by the backend according to the authenticated user's role and permissions.

## 🧪 Run Automated Tests

From the project root, with the virtual environment activated, execute:

```bash
python -m unittest -v tests.py
```

The test suite covers areas such as:

- Authentication and session handling
- CSRF protection
- Role-based access control
- Student record management
- Attendance processing
- Marks validation and grading
- Authorized CSV exports
- Password reset behavior
- Safe sample-data seeding

Review the test output to verify the results in your environment.

## 📊 Attendance and Grading

### Attendance calculation

The default attendance percentage is calculated as:

```text
Attendance Percentage =
(Present Sessions / Eligible Recorded Sessions) × 100
```

The default attendance threshold is 75%, which can be configured through environment variables.

### Grade calculation

The default grade boundaries are:

| Percentage | Grade |
|---|---|
| 90% and above | A+ |
| 80–89% | A |
| 70–79% | B |
| 60–69% | C |
| 50–59% | D |
| Below 50% | F |

These boundaries can be customized using the project's configuration.

## 🔌 API Overview

The application provides API endpoints for authentication, student records, attendance, assessments, marks, results, and reports.

| Endpoint | Purpose |
|---|---|
| `/api/health` | Check application and database health |
| `/api/login` | Authenticate a user |
| `/api/logout` | End the current session |
| `/api/dashboard` | Retrieve role-specific dashboard data |
| `/api/students` | Access authorized student records |
| `/api/attendance` | Manage attendance records |
| `/api/assessments` | Manage assessments |
| `/api/marks` | Retrieve or save marks |
| `/api/results` | Retrieve academic results |
| `/api/reports/*.csv` | Export authorized reports |

The API enforces authentication and permissions where required. State-changing requests also use CSRF protection.

## ☁️ Deployment

The application supports a deployment path using Flask and PostgreSQL.

Before hosting:

1. Configure production environment variables and a strong secret key.
2. Use a persistent PostgreSQL database.
3. Run database migrations.
4. Configure HTTPS and secure cookies.
5. Configure appropriate login rate-limit storage.
6. Verify health checks and role-based permissions.
7. Never use the demonstration seed accounts for production.

The repository includes migration and deployment configuration files to help prepare the application for hosting.

## 🔮 Future Enhancements

- Email notifications for attendance and results
- PDF report generation
- Advanced academic performance analytics
- Student performance prediction
- Bulk student import from CSV
- Improved mobile-responsive dashboards
- Cloud backup and recovery
- Additional administrative audit reports

## 🎯 Learning Outcomes

This project demonstrates practical experience with:

- Full-stack web development
- Python and Flask
- Relational database design
- SQLAlchemy ORM
- Authentication and authorization
- Attendance and grading logic
- REST API development
- Data visualization
- Automated testing
- Database migrations
- Cloud deployment preparation

## ⚠️ Disclaimer

EduCloud Manager is an educational demonstration project. All sample student and academic records are fictional. Before using the application in a real institution, conduct appropriate security, privacy, access-control, and deployment reviews.

## 👨‍💻 Author

**Asif Khan**

GitHub: https://github.com/Asifkhan629

## ⭐ Support

If you find this project useful, consider giving the repository a star.
