"""EduCloud Manager — Flask application with database-backed, role-aware APIs."""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from typing import Any

from flask import Flask, Response, g, jsonify, render_template, request, session
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_migrate import Migrate
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFError, CSRFProtect, generate_csrf
from sqlalchemy import CheckConstraint, UniqueConstraint, event, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

def database_url() -> str:
    raw = os.getenv("DATABASE_URL", "sqlite:///educloud.db").strip()
    # Providers commonly expose postgres://; SQLAlchemy uses an explicit psycopg driver.
    if raw.startswith("postgres://"):
        raw = "postgresql+psycopg://" + raw[len("postgres://"):]
    elif raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://"):]
    return raw

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", "dev-only-change-this-secret-key"),
    SQLALCHEMY_DATABASE_URI=database_url(),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1" or os.getenv("FLASK_ENV") == "production",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    ATTENDANCE_THRESHOLD=float(os.getenv("ATTENDANCE_THRESHOLD", "75")),
    EXCLUDE_APPROVED_LEAVE=os.getenv("EXCLUDE_APPROVED_LEAVE", "0").lower() in {"1", "true", "yes"},
    GRADE_BOUNDARIES=json.loads(os.getenv("GRADE_BOUNDARIES", '{"A+":90,"A":80,"B":70,"C":60,"D":50,"F":0}')),
    JSON_SORT_KEYS=False,
    AUTO_CREATE_DB=os.getenv("AUTO_CREATE_DB", "0" if os.getenv("FLASK_ENV") == "production" else "1").lower() in {"1", "true", "yes"},
)
if os.getenv("FLASK_ENV", "development").lower() == "production":
    configured_secret = str(app.config["SECRET_KEY"])
    if configured_secret == "dev-only-change-this-secret-key" or "replace-with" in configured_secret.lower() or len(configured_secret) < 32:
        raise RuntimeError("Set SECRET_KEY to a unique random value of at least 32 characters before production deployment.")

# SQLite requires foreign key enforcement to be enabled on each connection.
if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:"):
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"check_same_thread": False, "timeout": 20}, "pool_pre_ping": True}

db = SQLAlchemy(app)
migrate = Migrate(app, db)
csrf = CSRFProtect(app)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
    strategy="fixed-window",
)

# ---------- Data model ----------
class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (CheckConstraint("role IN ('admin','teacher','student')", name="ck_users_role"),)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "username": self.username, "email": self.email, "role": self.role,
                "is_active": self.is_active, "must_change_password": self.must_change_password}

class Department(db.Model):
    __tablename__ = "departments"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(16), unique=True, nullable=False)
    name = db.Column(db.String(120), unique=True, nullable=False)

class ClassGroup(db.Model):
    __tablename__ = "classes"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    section = db.Column(db.String(20), nullable=False, default="A")
    academic_year = db.Column(db.String(20), nullable=False)
    semester = db.Column(db.Integer, nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False)
    department = db.relationship("Department")
    __table_args__ = (UniqueConstraint("name", "section", "academic_year", "semester", "department_id", name="uq_class_section_year_sem_dept"),
                      CheckConstraint("semester >= 1 AND semester <= 12", name="ck_class_semester"))

class Student(db.Model):
    __tablename__ = "students"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), unique=True, nullable=False)
    roll_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(140), nullable=False, index=True)
    email = db.Column(db.String(160), unique=True, nullable=False)
    phone = db.Column(db.String(30))
    date_of_birth = db.Column(db.Date)
    gender = db.Column(db.String(30))
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False)
    course = db.Column(db.String(120), nullable=False)
    academic_year = db.Column(db.String(20), nullable=False)
    semester = db.Column(db.Integer, nullable=False)
    enrollment_date = db.Column(db.Date, nullable=False, default=date.today)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    user = db.relationship("User")
    department = db.relationship("Department")
    __table_args__ = (CheckConstraint("semester >= 1 AND semester <= 12", name="ck_student_semester"),)

class Teacher(db.Model):
    __tablename__ = "teachers"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), unique=True, nullable=False)
    employee_number = db.Column(db.String(40), unique=True, nullable=False)
    full_name = db.Column(db.String(140), nullable=False, index=True)
    email = db.Column(db.String(160), unique=True, nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    user = db.relationship("User")
    department = db.relationship("Department")

class Subject(db.Model):
    __tablename__ = "subjects"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(24), unique=True, nullable=False)
    name = db.Column(db.String(140), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False)
    credits = db.Column(db.Integer, nullable=False, default=3)
    department = db.relationship("Department")
    __table_args__ = (CheckConstraint("credits > 0 AND credits <= 10", name="ck_subject_credits"),)

class TeacherAssignment(db.Model):
    __tablename__ = "teacher_assignments"
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False)
    teacher = db.relationship("Teacher")
    class_group = db.relationship("ClassGroup")
    subject = db.relationship("Subject")
    __table_args__ = (UniqueConstraint("teacher_id", "class_id", "subject_id", name="uq_teacher_class_subject"),)

class Enrollment(db.Model):
    __tablename__ = "enrollments"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="RESTRICT"), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False)
    academic_term = db.Column(db.String(40), nullable=False, default="2026-27")
    enrolled_at = db.Column(db.Date, nullable=False, default=date.today)
    student = db.relationship("Student")
    class_group = db.relationship("ClassGroup")
    __table_args__ = (UniqueConstraint("student_id", "class_id", "academic_term", name="uq_enrollment_student_class_term"),)

class Attendance(db.Model):
    __tablename__ = "attendance"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="RESTRICT"), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False)
    attendance_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    student = db.relationship("Student")
    class_group = db.relationship("ClassGroup")
    subject = db.relationship("Subject")
    __table_args__ = (UniqueConstraint("student_id", "subject_id", "attendance_date", name="uq_attendance_student_subject_date"),
                      CheckConstraint("status IN ('Present','Absent','On Leave')", name="ck_attendance_status"),
                      db.Index("ix_attendance_class_subject_date", "class_id", "subject_id", "attendance_date"))

class Assessment(db.Model):
    __tablename__ = "assessments"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False)
    academic_term = db.Column(db.String(40), nullable=False)
    maximum_marks = db.Column(db.Float, nullable=False)
    passing_marks = db.Column(db.Float, nullable=False)
    assessment_date = db.Column(db.Date, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    class_group = db.relationship("ClassGroup")
    subject = db.relationship("Subject")
    __table_args__ = (UniqueConstraint("name", "class_id", "subject_id", "academic_term", name="uq_assessment_class_subject_term_name"),
                      CheckConstraint("maximum_marks > 0", name="ck_assessment_max_marks"),
                      CheckConstraint("passing_marks >= 0 AND passing_marks <= maximum_marks", name="ck_assessment_pass_marks"))

class Mark(db.Model):
    __tablename__ = "marks"
    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="RESTRICT"), nullable=False)
    marks_obtained = db.Column(db.Float, nullable=False)
    teacher_remarks = db.Column(db.String(500))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    assessment = db.relationship("Assessment")
    student = db.relationship("Student")
    __table_args__ = (UniqueConstraint("assessment_id", "student_id", name="uq_mark_assessment_student"),
                      CheckConstraint("marks_obtained >= 0", name="ck_mark_nonnegative"))

class ActivityLog(db.Model):
    __tablename__ = "activity_logs"
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(80), nullable=False)
    entity_id = db.Column(db.String(80))
    details = db.Column(db.String(500))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    actor = db.relationship("User")

# ---------- Common helpers ----------
def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def api_error(message: str, status: int = 400):
    return jsonify({"error": message}), status

def rotate_csrf_token() -> str:
    """Create a fresh CSRF token after an authentication-session change.

    Flask-WTF caches the generated token on ``g`` for the duration of a
    request. Clearing the session alone is not sufficient: generate_csrf()
    could return that cached pre-clear token without restoring the CSRF value
    in the new session. Clear both the configured session key and request
    cache before generating the replacement.
    """
    field_name = app.config.get("WTF_CSRF_FIELD_NAME", "csrf_token")
    session.pop(field_name, None)
    if hasattr(g, field_name):
        delattr(g, field_name)
    return generate_csrf()

def current_user() -> User | None:
    if "current_user" not in g:
        uid = session.get("user_id")
        g.current_user = db.session.get(User, uid) if uid else None
    return g.current_user

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or not user.is_active:
            # Keep the anonymous session's CSRF secret intact. The browser
            # loads /api/me before login; clearing the whole session here
            # invalidates the token rendered into the login page.
            session.pop("user_id", None)
            return api_error("Please log in to continue.", 401)
        if user.must_change_password and request.endpoint not in {"change_password", "me", "logout", "health", "index"}:
            return api_error("Change your temporary password before using the system.", 403)
        return fn(*args, **kwargs)
    return wrapped

def roles_required(*roles):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            user = current_user()
            if user.role not in roles:
                return api_error("You do not have permission to perform this action.", 403)
            return fn(*args, **kwargs)
        return wrapped
    return decorator

def payload() -> dict[str, Any]:
    return request.get_json(silent=True) or {}

def required(data: dict, *keys: str) -> str | None:
    for key in keys:
        if data.get(key) is None or str(data.get(key)).strip() == "":
            return f"{key.replace('_', ' ').capitalize()} is required."
    return None

def parse_int(value, field: str, minimum: int = 1) -> int:
    try:
        result = int(value)
    except (ValueError, TypeError):
        raise ValueError(f"{field.replace('_', ' ').capitalize()} must be a whole number.")
    if result < minimum:
        raise ValueError(f"{field.replace('_', ' ').capitalize()} must be at least {minimum}.")
    return result

def parse_date(value, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        raise ValueError(f"{field.replace('_', ' ').capitalize()} must be a valid date (YYYY-MM-DD).")

def valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value or ""))

def parse_bool(value: Any) -> bool:
    if isinstance(value, bool): return value
    if value in (1, "1", "true", "True", "yes", "on"): return True
    if value in (0, "0", "false", "False", "no", "off", None, ""): return False
    raise ValueError("Boolean fields must be true or false.")

def log_activity(action: str, entity_type: str, entity_id=None, details: str = "") -> None:
    db.session.add(ActivityLog(actor_id=current_user().id if current_user() else None, action=action,
                               entity_type=entity_type, entity_id=str(entity_id) if entity_id is not None else None,
                               details=(details or "")[:500]))

def teacher_can(teacher_user_id: int, class_id: int, subject_id: int) -> bool:
    return db.session.query(TeacherAssignment.id).join(Teacher).filter(
        Teacher.user_id == teacher_user_id, Teacher.is_active.is_(True),
        TeacherAssignment.class_id == class_id, TeacherAssignment.subject_id == subject_id
    ).first() is not None

def class_has_subject(class_id: int, subject_id: int) -> bool:
    return db.session.query(TeacherAssignment.id).filter_by(class_id=class_id, subject_id=subject_id).first() is not None

def student_enrolled(student_id: int, class_id: int) -> bool:
    return db.session.query(Enrollment.id).filter_by(student_id=student_id, class_id=class_id).first() is not None

def can_access_class(user: User, class_id: int, subject_id: int | None = None) -> bool:
    if user.role == "admin":
        return True
    if user.role == "teacher":
        q = db.session.query(TeacherAssignment.id).join(Teacher).filter(Teacher.user_id == user.id, TeacherAssignment.class_id == class_id)
        if subject_id is not None:
            q = q.filter(TeacherAssignment.subject_id == subject_id)
        return q.first() is not None
    student = Student.query.filter_by(user_id=user.id).first()
    if not student:
        return False
    q = db.session.query(Enrollment.id).filter_by(student_id=student.id, class_id=class_id)
    if subject_id is not None:
        q = q.join(TeacherAssignment, TeacherAssignment.class_id == Enrollment.class_id).filter(TeacherAssignment.subject_id == subject_id)
    return q.first() is not None

def attendance_percent(student_id: int, class_id: int | None = None, subject_id: int | None = None) -> float | None:
    query = Attendance.query.filter_by(student_id=student_id)
    if class_id is not None: query = query.filter_by(class_id=class_id)
    if subject_id is not None: query = query.filter_by(subject_id=subject_id)
    rows = query.all()
    eligible = [r for r in rows if not (app.config["EXCLUDE_APPROVED_LEAVE"] and r.status == "On Leave")]
    if not eligible: return None
    present = sum(1 for r in eligible if r.status == "Present")
    return round(100 * present / len(eligible), 2)

def grade_for(percent: float) -> str:
    bounds = app.config.get("GRADE_BOUNDARIES", {"A+": 90, "A": 80, "B": 70, "C": 60, "D": 50, "F": 0})
    for grade, minimum in sorted(bounds.items(), key=lambda x: float(x[1]), reverse=True):
        if percent >= float(minimum): return str(grade)
    return "F"

def student_dict(s: Student) -> dict[str, Any]:
    enrollment = Enrollment.query.filter_by(student_id=s.id).order_by(Enrollment.id.desc()).first()
    class_name = None
    class_id = None
    if enrollment:
        class_id = enrollment.class_id
        cg = enrollment.class_group
        class_name = f"{cg.name} - {cg.section} (Sem {cg.semester})"
    return {"id": s.id, "user_id": s.user_id, "roll_number": s.roll_number, "full_name": s.full_name,
            "email": s.email, "phone": s.phone or "", "date_of_birth": s.date_of_birth.isoformat() if s.date_of_birth else "",
            "gender": s.gender or "", "department_id": s.department_id, "department": s.department.name,
            "course": s.course, "academic_year": s.academic_year, "semester": s.semester,
            "enrollment_date": s.enrollment_date.isoformat() if s.enrollment_date else "",
            "class_id": class_id, "class_name": class_name, "is_active": s.is_active}

def teacher_dict(t: Teacher) -> dict[str, Any]:
    return {"id": t.id, "user_id": t.user_id, "employee_number": t.employee_number, "full_name": t.full_name,
            "email": t.email, "department_id": t.department_id, "department": t.department.name, "is_active": t.is_active}

def class_dict(c: ClassGroup) -> dict[str, Any]:
    return {"id": c.id, "name": c.name, "section": c.section, "academic_year": c.academic_year,
            "semester": c.semester, "department_id": c.department_id, "department": c.department.name}

def assessment_dict(a: Assessment) -> dict[str, Any]:
    return {"id": a.id, "name": a.name, "class_id": a.class_id, "class_name": f"{a.class_group.name} - {a.class_group.section}",
            "subject_id": a.subject_id, "subject": a.subject.name, "subject_code": a.subject.code,
            "academic_term": a.academic_term, "maximum_marks": a.maximum_marks, "passing_marks": a.passing_marks,
            "assessment_date": a.assessment_date.isoformat()}

def csv_response(filename: str, headers: list[str], rows: list[list[Any]]) -> Response:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    def safe_cell(value: Any) -> Any:
        # Prefix untrusted text that spreadsheets may interpret as a formula.
        if isinstance(value, str) and value[:1] in {"=", "+", "-", "@", "\t", "\r"}:
            return "'" + value
        return value
    writer.writerow(headers)
    writer.writerows([[safe_cell(value) for value in row] for row in rows])
    # UTF-8 BOM improves Excel compatibility for names and headers.
    return Response("\ufeff" + stream.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})

# ---------- Browser routes and authentication ----------
@app.route("/")
def index():
    return render_template("index.html")

@app.get("/api/health")
def health():
    try:
        db.session.execute(select(1))
        return jsonify({"status": "ok", "database": "connected"})
    except SQLAlchemyError:
        return jsonify({"status": "error", "database": "unavailable"}), 503

@app.post("/api/login")
@limiter.limit("5 per minute")
def login():
    data = payload()
    if not data.get("username") or not data.get("password"):
        return api_error("Enter your username/email and password.")
    identifier = str(data["username"]).strip().lower()
    user = User.query.filter(or_(func.lower(User.username) == identifier, func.lower(User.email) == identifier)).first()
    if not user or not user.is_active or not check_password_hash(user.password_hash, str(data["password"])):
        # Deliberately generic to avoid revealing which accounts exist.
        return api_error("Invalid username/email or password.", 401)
    session.clear()
    session.permanent = True
    session["user_id"] = user.id
    db.session.commit()
    csrf_token = rotate_csrf_token()
    return jsonify({"user": user.public(), "csrf_token": csrf_token})

@app.post("/api/logout")
@login_required
def logout():
    session.clear()
    csrf_token = rotate_csrf_token()
    return jsonify({"message": "You have been logged out.", "csrf_token": csrf_token})

@app.get("/api/me")
@login_required
def me():
    user = current_user()
    profile = None
    if user.role == "student":
        s = Student.query.filter_by(user_id=user.id).first()
        profile = student_dict(s) if s else None
    elif user.role == "teacher":
        t = Teacher.query.filter_by(user_id=user.id).first()
        profile = teacher_dict(t) if t else None
    return jsonify({"user": user.public(), "profile": profile})

@app.post("/api/change-password")
@login_required
def change_password():
    data = payload()
    if not data.get("current_password") or not data.get("new_password"):
        return api_error("Current and new passwords are required.")
    user = current_user()
    if not check_password_hash(user.password_hash, str(data["current_password"])):
        return api_error("Current password is incorrect.", 400)
    new_pw = str(data["new_password"])
    if len(new_pw) < 10 or not re.search(r"[A-Za-z]", new_pw) or not re.search(r"\d", new_pw):
        return api_error("Use at least 10 characters, including a letter and a number.")
    if check_password_hash(user.password_hash, new_pw):
        return api_error("Choose a password different from your current password.")
    user.set_password(new_pw)
    user.must_change_password = False
    log_activity("changed_password", "user", user.id)
    db.session.commit()
    return jsonify({"message": "Password updated successfully. You can now use the dashboard.", "user": user.public()})

# ---------- Dashboard and reference data ----------
@app.get("/api/dashboard")
@login_required
def dashboard():
    user = current_user()
    today = date.today()
    if user.role == "student":
        s = Student.query.filter_by(user_id=user.id).first()
        if not s: return api_error("Student profile is not configured.", 404)
        marks = Mark.query.join(Assessment).filter(Mark.student_id == s.id).all()
        average = round(sum((m.marks_obtained / m.assessment.maximum_marks) * 100 for m in marks) / len(marks), 2) if marks else None
        recent_attendance = Attendance.query.filter_by(student_id=s.id).order_by(Attendance.attendance_date.desc()).limit(8).all()
        return jsonify({"role": "student", "profile": student_dict(s), "attendance_percent": attendance_percent(s.id),
                        "academic_average": average, "assessments_recorded": len(marks),
                        "recent_attendance": [{"date": r.attendance_date.isoformat(), "subject": r.subject.name, "status": r.status} for r in recent_attendance],
                        "attendance_threshold": app.config["ATTENDANCE_THRESHOLD"], "exclude_approved_leave": app.config["EXCLUDE_APPROVED_LEAVE"]})
    if user.role == "teacher":
        teacher = Teacher.query.filter_by(user_id=user.id).first()
        if not teacher: return api_error("Teacher profile is not configured.", 404)
        assignments = TeacherAssignment.query.filter_by(teacher_id=teacher.id).all()
        class_ids = sorted({a.class_id for a in assignments})
        return jsonify({"role": "teacher", "classes": [class_dict(c) for c in ClassGroup.query.filter(ClassGroup.id.in_(class_ids)).all()] if class_ids else [],
                        "assignments": [{"class_id": a.class_id, "class_name": f"{a.class_group.name} - {a.class_group.section}", "subject_id": a.subject_id, "subject": a.subject.name, "subject_code": a.subject.code} for a in assignments],
                        "students_count": Student.query.join(Enrollment).filter(Enrollment.class_id.in_(class_ids), Student.is_active.is_(True)).distinct().count() if class_ids else 0,
                        "today_attendance_entries": Attendance.query.filter_by(recorded_by=user.id, attendance_date=today).count(), "attendance_threshold": app.config["ATTENDANCE_THRESHOLD"], "exclude_approved_leave": app.config["EXCLUDE_APPROVED_LEAVE"]})
    total_active_students = Student.query.filter_by(is_active=True).count()
    today_rows = Attendance.query.filter_by(attendance_date=today).all()
    present_today = sum(1 for r in today_rows if r.status == "Present")
    absence_today = sum(1 for r in today_rows if r.status == "Absent")
    student_percents = [attendance_percent(s.id) for s in Student.query.filter_by(is_active=True).all()]
    student_percents = [p for p in student_percents if p is not None]
    all_marks = Mark.query.join(Assessment).all()
    academic_average = round(sum((m.marks_obtained / m.assessment.maximum_marks) * 100 for m in all_marks) / len(all_marks), 2) if all_marks else None
    attention = []
    for s in Student.query.filter_by(is_active=True).all():
        percent = attendance_percent(s.id)
        if percent is not None and percent < app.config["ATTENDANCE_THRESHOLD"]:
            attention.append({"id": s.id, "name": s.full_name, "roll_number": s.roll_number, "attendance_percent": percent})
    attention.sort(key=lambda item: item["attendance_percent"])
    activities = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(8).all()
    return jsonify({"role": "admin", "total_students": total_active_students, "total_teachers": Teacher.query.filter_by(is_active=True).count(),
                    "total_classes": ClassGroup.query.count(), "total_subjects": Subject.query.count(), "departments": Department.query.count(),
                    "today_attendance": {"recorded": len(today_rows), "present": present_today, "absent": absence_today,
                                          "other": len(today_rows) - present_today - absence_today},
                    "average_attendance": round(sum(student_percents) / len(student_percents), 2) if student_percents else None,
                    "academic_average": academic_average, "attendance_attention": attention[:10],
                    "recent_activity": [{"action": a.action.replace("_", " "), "entity_type": a.entity_type, "created_at": a.created_at.isoformat() if a.created_at else ""} for a in activities],
                    "attendance_threshold": app.config["ATTENDANCE_THRESHOLD"], "exclude_approved_leave": app.config["EXCLUDE_APPROVED_LEAVE"]})

@app.get("/api/departments")
@login_required
def departments_list():
    return jsonify([{"id": d.id, "code": d.code, "name": d.name} for d in Department.query.order_by(Department.name).all()])

@app.post("/api/departments")
@roles_required("admin")
def department_create():
    data = payload(); error = required(data, "code", "name")
    if error: return api_error(error)
    code = str(data["code"]).strip().upper(); name = str(data["name"]).strip()
    if len(code) > 16 or len(name) > 120: return api_error("Department code or name is too long.")
    try:
        row = Department(code=code, name=name)
        db.session.add(row); db.session.flush(); log_activity("created_department", "department", row.id); db.session.commit()
        return jsonify({"message": "Department created.", "department": {"id": row.id, "code": row.code, "name": row.name}}), 201
    except IntegrityError:
        db.session.rollback(); return api_error("Department code and name must be unique.")

@app.get("/api/classes")
@login_required
def classes_list():
    user = current_user()
    if user.role == "teacher":
        t = Teacher.query.filter_by(user_id=user.id).first()
        ids = [a.class_id for a in TeacherAssignment.query.filter_by(teacher_id=t.id).all()] if t else []
        rows = ClassGroup.query.filter(ClassGroup.id.in_(ids)).order_by(ClassGroup.name).all() if ids else []
    elif user.role == "student":
        s = Student.query.filter_by(user_id=user.id).first()
        ids = [e.class_id for e in Enrollment.query.filter_by(student_id=s.id).all()] if s else []
        rows = ClassGroup.query.filter(ClassGroup.id.in_(ids)).all() if ids else []
    else:
        rows = ClassGroup.query.order_by(ClassGroup.name).all()
    return jsonify([class_dict(c) for c in rows])

@app.post("/api/classes")
@roles_required("admin")
def class_create():
    data = payload()
    error = required(data, "name", "section", "academic_year", "semester", "department_id")
    if error: return api_error(error)
    try:
        semester = parse_int(data["semester"], "semester")
        dept_id = parse_int(data["department_id"], "department_id")
        if semester > 12: return api_error("Semester must be between 1 and 12.")
        if not db.session.get(Department, dept_id): return api_error("Selected department does not exist.")
        row = ClassGroup(name=str(data["name"]).strip(), section=str(data["section"]).strip(), academic_year=str(data["academic_year"]).strip(), semester=semester, department_id=dept_id)
        db.session.add(row); db.session.flush(); log_activity("created_class", "class", row.id); db.session.commit()
        return jsonify({"class": class_dict(row), "message": "Class created."}), 201
    except ValueError as e: db.session.rollback(); return api_error(str(e))
    except IntegrityError: db.session.rollback(); return api_error("That class/section already exists for this year, semester, and department.")

@app.get("/api/subjects")
@login_required
def subjects_list():
    user = current_user()
    q = Subject.query
    if user.role == "teacher":
        t = Teacher.query.filter_by(user_id=user.id).first()
        assignment_ids = [a.subject_id for a in TeacherAssignment.query.filter_by(teacher_id=t.id).all()] if t else []
        q = q.filter(Subject.id.in_(assignment_ids))
    elif user.role == "student":
        s = Student.query.filter_by(user_id=user.id).first()
        class_ids = [e.class_id for e in Enrollment.query.filter_by(student_id=s.id).all()] if s else []
        assignment_ids = [a.subject_id for a in TeacherAssignment.query.filter(TeacherAssignment.class_id.in_(class_ids)).all()] if class_ids else []
        q = q.filter(Subject.id.in_(assignment_ids))
    return jsonify([{"id": s.id, "code": s.code, "name": s.name, "department_id": s.department_id, "department": s.department.name, "credits": s.credits} for s in q.order_by(Subject.name).all()])

@app.post("/api/subjects")
@roles_required("admin")
def subject_create():
    data = payload(); error = required(data, "code", "name", "department_id")
    if error: return api_error(error)
    try:
        dept = db.session.get(Department, parse_int(data["department_id"], "department_id"))
        if not dept: return api_error("Selected department does not exist.")
        credits = parse_int(data.get("credits", 3), "credits")
        if credits > 10: return api_error("Credits must be between 1 and 10.")
        row = Subject(code=str(data["code"]).strip().upper(), name=str(data["name"]).strip(), department_id=dept.id, credits=credits)
        db.session.add(row); db.session.flush(); log_activity("created_subject", "subject", row.id); db.session.commit()
        return jsonify({"message": "Subject created.", "subject": {"id": row.id, "code": row.code, "name": row.name}}), 201
    except ValueError as e: db.session.rollback(); return api_error(str(e))
    except IntegrityError: db.session.rollback(); return api_error("Subject code must be unique.")

@app.get("/api/teachers")
@roles_required("admin")
def teachers_list():
    return jsonify([teacher_dict(t) for t in Teacher.query.order_by(Teacher.full_name).all()])

@app.post("/api/teachers")
@roles_required("admin")
def teacher_create():
    data = payload(); error = required(data, "employee_number", "full_name", "email", "username", "password", "department_id")
    if error: return api_error(error)
    email = str(data["email"]).strip().lower(); password = str(data["password"])
    if not valid_email(email): return api_error("Enter a valid email address.")
    if len(password) < 10: return api_error("Temporary password must be at least 10 characters.")
    try:
        dept = db.session.get(Department, parse_int(data["department_id"], "department_id"))
        if not dept: return api_error("Selected department does not exist.")
        u = User(username=str(data["username"]).strip().lower(), email=email, role="teacher", is_active=True, must_change_password=True)
        u.set_password(password); db.session.add(u); db.session.flush()
        t = Teacher(user_id=u.id, employee_number=str(data["employee_number"]).strip().upper(), full_name=str(data["full_name"]).strip(), email=email, department_id=dept.id)
        db.session.add(t); db.session.flush(); log_activity("created_teacher", "teacher", t.id); db.session.commit()
        return jsonify({"message": "Teacher account created. Password change is required at first login.", "teacher": teacher_dict(t)}), 201
    except ValueError as e: db.session.rollback(); return api_error(str(e))
    except IntegrityError: db.session.rollback(); return api_error("Username, email, or employee number already exists.")

@app.patch("/api/teachers/<int:teacher_id>")
@roles_required("admin")
def teacher_update(teacher_id):
    teacher = db.session.get(Teacher, teacher_id)
    if not teacher: return api_error("Teacher not found.", 404)
    data = payload()
    if "is_active" in data:
        try: teacher.is_active = parse_bool(data["is_active"])
        except ValueError as e: return api_error(str(e))
        teacher.user.is_active = teacher.is_active
        log_activity("updated_teacher_status", "teacher", teacher.id, "active" if teacher.is_active else "inactive")
        db.session.commit()
        return jsonify({"message": f"Teacher account {'activated' if teacher.is_active else 'deactivated'}.", "teacher": teacher_dict(teacher)})
    return api_error("No supported teacher update was supplied.")

@app.post("/api/users/<int:user_id>/reset-password")
@roles_required("admin")
def reset_user_password(user_id):
    user = db.session.get(User, user_id)
    if not user: return api_error("User account not found.", 404)
    temporary = "Temp" + secrets.token_urlsafe(9) + "9"
    # Return this temporary password once to the authenticated administrator; force rotation at next login.
    user.set_password(temporary)
    user.must_change_password = True
    log_activity("reset_password", "user", user.id, f"Temporary password issued for {user.username}")
    db.session.commit()
    return jsonify({"message": "A one-time temporary password has been generated. Share it securely.", "temporary_password": temporary})

@app.post("/api/assignments")
@roles_required("admin")
def assignment_create():
    data = payload(); error = required(data, "teacher_id", "class_id", "subject_id")
    if error: return api_error(error)
    try:
        values = {k: parse_int(data[k], k) for k in ("teacher_id", "class_id", "subject_id")}
        if not db.session.get(Teacher, values["teacher_id"]): return api_error("Teacher was not found.")
        if not db.session.get(ClassGroup, values["class_id"]): return api_error("Class was not found.")
        if not db.session.get(Subject, values["subject_id"]): return api_error("Subject was not found.")
        row = TeacherAssignment(**values); db.session.add(row); db.session.flush(); log_activity("assigned_teacher", "teacher_assignment", row.id); db.session.commit()
        return jsonify({"message": "Teacher assigned to class and subject."}), 201
    except ValueError as e: db.session.rollback(); return api_error(str(e))
    except IntegrityError: db.session.rollback(); return api_error("That teacher/class/subject assignment already exists.")

# ---------- Student records ----------
@app.get("/api/students")
@login_required
def students_list():
    user = current_user()
    q = Student.query.join(Department)
    if user.role == "student":
        q = q.filter(Student.user_id == user.id)
    elif user.role == "teacher":
        teacher = Teacher.query.filter_by(user_id=user.id).first()
        class_ids = [a.class_id for a in TeacherAssignment.query.filter_by(teacher_id=teacher.id).all()] if teacher else []
        q = q.join(Enrollment).filter(Enrollment.class_id.in_(class_ids)) if class_ids else q.filter(db.false())
    term = request.args.get("q", "").strip()
    if term:
        like = f"%{term}%"
        class_student_ids = db.session.query(Enrollment.student_id).join(ClassGroup, Enrollment.class_id == ClassGroup.id).filter(
            or_(ClassGroup.name.ilike(like), ClassGroup.section.ilike(like), ClassGroup.academic_year.ilike(like))
        )
        q = q.filter(or_(Student.full_name.ilike(like), Student.roll_number.ilike(like), Student.email.ilike(like), Department.name.ilike(like), Student.id.in_(class_student_ids)))
    if request.args.get("department_id"):
        try: q = q.filter(Student.department_id == int(request.args["department_id"]))
        except ValueError: return api_error("Invalid department filter.")
    if request.args.get("semester"):
        try: q = q.filter(Student.semester == int(request.args["semester"]))
        except ValueError: return api_error("Invalid semester filter.")
    if request.args.get("active") != "all": q = q.filter(Student.is_active.is_(True))
    if request.args.get("class_id"):
        try:
            wanted_class_id = int(request.args["class_id"])
            q = q.filter(Student.id.in_(db.session.query(Enrollment.student_id).filter(Enrollment.class_id == wanted_class_id)))
        except ValueError: return api_error("Invalid class filter.")
    total = q.distinct().count()
    try: page = max(1, int(request.args.get("page", 1))); per_page = min(100, max(1, int(request.args.get("per_page", 50))))
    except ValueError: return api_error("Page and per_page must be numbers.")
    sort_fields = {"full_name": Student.full_name, "roll_number": Student.roll_number, "semester": Student.semester, "enrollment_date": Student.enrollment_date}
    sort_by = request.args.get("sort_by", "full_name")
    sort_order = request.args.get("sort_order", "asc").lower()
    if sort_by not in sort_fields or sort_order not in {"asc", "desc"}: return api_error("Invalid sort option.")
    sort_column = sort_fields[sort_by].desc() if sort_order == "desc" else sort_fields[sort_by].asc()
    rows = q.distinct().order_by(sort_column, Student.id.asc()).offset((page-1)*per_page).limit(per_page).all()
    return jsonify({"items": [student_dict(s) for s in rows], "page": page, "per_page": per_page, "total": total})

@app.post("/api/students")
@roles_required("admin")
def student_create():
    data = payload(); error = required(data, "roll_number", "full_name", "email", "department_id", "course", "academic_year", "semester", "username", "password")
    if error: return api_error(error)
    email = str(data["email"]).strip().lower(); password = str(data["password"])
    if not valid_email(email): return api_error("Enter a valid email address.")
    if len(password) < 10: return api_error("Temporary password must be at least 10 characters.")
    try:
        dept_id = parse_int(data["department_id"], "department_id"); sem = parse_int(data["semester"], "semester")
        if sem > 12: return api_error("Semester must be between 1 and 12.")
        if not db.session.get(Department, dept_id): return api_error("Selected department does not exist.")
        dob = parse_date(data["date_of_birth"], "date_of_birth") if data.get("date_of_birth") else None
        enrollment_date = parse_date(data["enrollment_date"], "enrollment_date") if data.get("enrollment_date") else date.today()
        user = User(username=str(data["username"]).strip().lower(), email=email, role="student", is_active=True, must_change_password=True)
        user.set_password(password); db.session.add(user); db.session.flush()
        student = Student(user_id=user.id, roll_number=str(data["roll_number"]).strip().upper(), full_name=str(data["full_name"]).strip(), email=email,
                          phone=(str(data.get("phone", "")).strip() or None), date_of_birth=dob, gender=(str(data.get("gender", "")).strip() or None),
                          department_id=dept_id, course=str(data["course"]).strip(), academic_year=str(data["academic_year"]).strip(), semester=sem, enrollment_date=enrollment_date)
        db.session.add(student); db.session.flush()
        if data.get("class_id"):
            class_id = parse_int(data["class_id"], "class_id")
            class_group = db.session.get(ClassGroup, class_id)
            if not class_group: raise ValueError("Selected class does not exist.")
            if class_group.department_id != dept_id or class_group.semester != sem or class_group.academic_year != str(data["academic_year"]).strip():
                raise ValueError("Selected class must match the student's department, semester, and academic year.")
            db.session.add(Enrollment(student_id=student.id, class_id=class_id, academic_term=str(data.get("academic_term", "2026-27")).strip()))
        log_activity("created_student", "student", student.id); db.session.commit()
        return jsonify({"message": "Student created. Temporary password must be changed at first login.", "student": student_dict(student)}), 201
    except ValueError as e: db.session.rollback(); return api_error(str(e))
    except IntegrityError: db.session.rollback(); return api_error("Roll number, username, email, or enrollment already exists.")

@app.patch("/api/students/<int:student_id>")
@roles_required("admin")
def student_update(student_id):
    s = db.session.get(Student, student_id)
    if not s: return api_error("Student not found.", 404)
    data = payload()
    try:
        for key in ("full_name", "roll_number", "course", "academic_year", "phone", "gender"):
            if key in data: setattr(s, key, (str(data[key]).strip() or None) if key in {"phone", "gender"} else str(data[key]).strip())
        if "email" in data:
            email = str(data["email"]).strip().lower()
            if not valid_email(email): return api_error("Enter a valid email address.")
            s.email = email; s.user.email = email
        if "department_id" in data: s.department_id = parse_int(data["department_id"], "department_id")
        if "semester" in data:
            s.semester = parse_int(data["semester"], "semester")
            if s.semester > 12: return api_error("Semester must be between 1 and 12.")
        if "date_of_birth" in data: s.date_of_birth = parse_date(data["date_of_birth"], "date_of_birth") if data["date_of_birth"] else None
        if "enrollment_date" in data: s.enrollment_date = parse_date(data["enrollment_date"], "enrollment_date")
        if "is_active" in data:
            s.is_active = parse_bool(data["is_active"]); s.user.is_active = s.is_active
        if "class_id" in data and data["class_id"]:
            class_id = parse_int(data["class_id"], "class_id")
            class_group = db.session.get(ClassGroup, class_id)
            if not class_group: return api_error("Selected class does not exist.")
            if class_group.department_id != s.department_id or class_group.semester != s.semester or class_group.academic_year != s.academic_year:
                return api_error("Selected class must match the student's department, semester, and academic year.")
            existing = Enrollment.query.filter_by(student_id=s.id, academic_term=str(data.get("academic_term", "2026-27"))).first()
            if existing: existing.class_id = class_id
            else: db.session.add(Enrollment(student_id=s.id, class_id=class_id, academic_term=str(data.get("academic_term", "2026-27"))))
        s.updated_at = now_utc(); log_activity("updated_student", "student", s.id); db.session.commit()
        return jsonify({"message": "Student record updated.", "student": student_dict(s)})
    except ValueError as e: db.session.rollback(); return api_error(str(e))
    except IntegrityError: db.session.rollback(); return api_error("Email or roll number already exists, or the enrollment conflicts with an existing record.")

@app.delete("/api/students/<int:student_id>")
@roles_required("admin")
def student_deactivate(student_id):
    s = db.session.get(Student, student_id)
    if not s: return api_error("Student not found.", 404)
    s.is_active = False; s.user.is_active = False
    log_activity("deactivated_student", "student", s.id); db.session.commit()
    return jsonify({"message": "Student deactivated. Academic history has been preserved."})

# ---------- Attendance ----------
@app.get("/api/attendance")
@login_required
def attendance_list():
    user = current_user(); q = Attendance.query.join(Student, Attendance.student_id == Student.id).join(Subject, Attendance.subject_id == Subject.id)
    if user.role == "student":
        s = Student.query.filter_by(user_id=user.id).first()
        q = q.filter(Attendance.student_id == s.id) if s else q.filter(db.false())
    elif user.role == "teacher":
        t = Teacher.query.filter_by(user_id=user.id).first()
        pairs = [(a.class_id, a.subject_id) for a in TeacherAssignment.query.filter_by(teacher_id=t.id).all()] if t else []
        if not pairs: return jsonify([])
        q = q.filter(db.or_(*[db.and_(Attendance.class_id == c, Attendance.subject_id == sub) for c, sub in pairs]))
    for param, column in (("student_id", Attendance.student_id), ("class_id", Attendance.class_id), ("subject_id", Attendance.subject_id)):
        if request.args.get(param):
            try: q = q.filter(column == int(request.args[param]))
            except ValueError: return api_error(f"Invalid {param} filter.")
    try:
        if request.args.get("start"): q = q.filter(Attendance.attendance_date >= parse_date(request.args["start"], "start"))
        if request.args.get("end"): q = q.filter(Attendance.attendance_date <= parse_date(request.args["end"], "end"))
    except ValueError as e: return api_error(str(e))
    rows = q.order_by(Attendance.attendance_date.desc(), Student.full_name).limit(2000).all()
    return jsonify([{"id": r.id, "student_id": r.student_id, "student": r.student.full_name, "roll_number": r.student.roll_number,
                     "class_id": r.class_id, "class_name": f"{r.class_group.name} - {r.class_group.section}", "subject_id": r.subject_id,
                     "subject": r.subject.name, "date": r.attendance_date.isoformat(), "status": r.status} for r in rows])

@app.post("/api/attendance")
@roles_required("admin", "teacher")
def attendance_save():
    data = payload(); error = required(data, "class_id", "subject_id", "date")
    if error: return api_error(error)
    try:
        class_id = parse_int(data["class_id"], "class_id"); subject_id = parse_int(data["subject_id"], "subject_id")
        att_date = parse_date(data["date"], "date")
        if att_date > date.today(): return api_error("Attendance cannot be recorded for a future date.")
        if not db.session.get(ClassGroup, class_id) or not db.session.get(Subject, subject_id): return api_error("Selected class or subject does not exist.")
        if not class_has_subject(class_id, subject_id): return api_error("The selected subject is not assigned to this class.")
        user = current_user()
        if user.role == "teacher" and not teacher_can(user.id, class_id, subject_id): return api_error("You are not assigned to this class and subject.", 403)
        if not class_has_subject(class_id, subject_id): return api_error("No teacher assignment links this subject to the selected class.")
        records = data.get("records")
        if not isinstance(records, list) or not records: return api_error("Add at least one student attendance record.")
        ids = [str(row.get("student_id")) for row in records if isinstance(row, dict)]
        if len(ids) != len(records): return api_error("Each attendance record must be an object.")
        if len(set(ids)) != len(ids): return api_error("A student appears more than once in this attendance batch.")
        for row in records:
            sid = parse_int(row.get("student_id"), "student_id")
            status = row.get("status")
            if status not in {"Present", "Absent", "On Leave"}: return api_error("Status must be Present, Absent, or On Leave.")
            if not student_enrolled(sid, class_id): return api_error(f"Student ID {sid} is not enrolled in the selected class.")
        for row in records:
            sid = int(row["student_id"]); status = row["status"]
            existing = Attendance.query.filter_by(student_id=sid, subject_id=subject_id, attendance_date=att_date).first()
            if existing:
                if existing.class_id != class_id: return api_error("Conflicting attendance entry already exists for that student, subject, and date.")
                existing.status = status; existing.recorded_by = user.id
            else:
                db.session.add(Attendance(student_id=sid, class_id=class_id, subject_id=subject_id, attendance_date=att_date, status=status, recorded_by=user.id))
        log_activity("saved_attendance", "attendance_batch", None, f"{len(records)} record(s) for {att_date}")
        db.session.commit()
        return jsonify({"message": f"Attendance saved for {len(records)} student(s).", "count": len(records)})
    except ValueError as e: db.session.rollback(); return api_error(str(e))
    except IntegrityError: db.session.rollback(); return api_error("Duplicate or invalid attendance record. No changes were saved.")
    except SQLAlchemyError: db.session.rollback(); app.logger.exception("Attendance transaction failed"); return api_error("Attendance could not be saved. No changes were committed.", 500)

@app.get("/api/attendance/summary")
@login_required
def attendance_summary():
    user = current_user()
    if user.role == "student":
        own = Student.query.filter_by(user_id=user.id).first()
        rows = [own] if own else []
        attendance_scope = Attendance.query.filter_by(student_id=own.id) if own else Attendance.query.filter(db.false())
    elif user.role == "teacher":
        teacher = Teacher.query.filter_by(user_id=user.id).first()
        pairs = [(a.class_id, a.subject_id) for a in TeacherAssignment.query.filter_by(teacher_id=teacher.id).all()] if teacher else []
        if not pairs:
            return jsonify([])
        attendance_scope = Attendance.query.filter(db.or_(*[db.and_(Attendance.class_id == c, Attendance.subject_id == sub) for c, sub in pairs]))
        ids = [row[0] for row in attendance_scope.with_entities(Attendance.student_id).distinct().all()]
        rows = Student.query.filter(Student.id.in_(ids)).all() if ids else []
    else:
        rows = Student.query.filter_by(is_active=True).all()
        attendance_scope = Attendance.query
    result = []
    for student in rows:
        scoped = attendance_scope.filter(Attendance.student_id == student.id).all()
        eligible = [r for r in scoped if not (app.config["EXCLUDE_APPROVED_LEAVE"] and r.status == "On Leave")]
        p = round(100 * sum(1 for r in eligible if r.status == "Present") / len(eligible), 2) if eligible else None
        result.append({"student_id": student.id, "student": student.full_name, "roll_number": student.roll_number,
                       "attendance_percent": p, "below_threshold": p is not None and p < app.config["ATTENDANCE_THRESHOLD"]})
    result.sort(key=lambda x: (x["attendance_percent"] is None, x["attendance_percent"] if x["attendance_percent"] is not None else 0))
    return jsonify(result)

# ---------- Assessments and marks ----------
@app.get("/api/assessments")
@login_required
def assessments_list():
    user = current_user(); q = Assessment.query
    if user.role == "teacher":
        t = Teacher.query.filter_by(user_id=user.id).first()
        assignments = [(a.class_id, a.subject_id) for a in TeacherAssignment.query.filter_by(teacher_id=t.id).all()] if t else []
        q = q.filter(db.or_(*[db.and_(Assessment.class_id == c, Assessment.subject_id == s) for c, s in assignments])) if assignments else q.filter(db.false())
    elif user.role == "student":
        s = Student.query.filter_by(user_id=user.id).first()
        class_ids = [e.class_id for e in Enrollment.query.filter_by(student_id=s.id).all()] if s else []
        q = q.filter(Assessment.class_id.in_(class_ids)) if class_ids else q.filter(db.false())
    for param, col in (("class_id", Assessment.class_id), ("subject_id", Assessment.subject_id)):
        if request.args.get(param):
            try: q = q.filter(col == int(request.args[param]))
            except ValueError: return api_error(f"Invalid {param} filter.")
    return jsonify([assessment_dict(a) for a in q.order_by(Assessment.assessment_date.desc()).limit(500).all()])

@app.post("/api/assessments")
@roles_required("admin", "teacher")
def assessment_create():
    data = payload(); error = required(data, "name", "class_id", "subject_id", "academic_term", "maximum_marks", "passing_marks", "assessment_date")
    if error: return api_error(error)
    try:
        class_id = parse_int(data["class_id"], "class_id"); subject_id = parse_int(data["subject_id"], "subject_id")
        if not db.session.get(ClassGroup, class_id) or not db.session.get(Subject, subject_id): return api_error("Selected class or subject does not exist.")
        if not class_has_subject(class_id, subject_id): return api_error("The selected subject is not assigned to this class.")
        user = current_user()
        if user.role == "teacher" and not teacher_can(user.id, class_id, subject_id): return api_error("You are not assigned to this class and subject.", 403)
        try: maximum = float(data["maximum_marks"]); passing = float(data["passing_marks"])
        except (ValueError, TypeError): return api_error("Maximum and passing marks must be numbers.")
        if not math.isfinite(maximum) or not math.isfinite(passing) or maximum <= 0 or passing < 0 or passing > maximum: return api_error("Marks must satisfy 0 ≤ passing marks ≤ maximum marks, with maximum above 0.")
        exam_date = parse_date(data["assessment_date"], "assessment_date")
        row = Assessment(name=str(data["name"]).strip(), class_id=class_id, subject_id=subject_id, academic_term=str(data["academic_term"]).strip(),
                         maximum_marks=maximum, passing_marks=passing, assessment_date=exam_date, created_by=user.id)
        db.session.add(row); db.session.flush(); log_activity("created_assessment", "assessment", row.id); db.session.commit()
        return jsonify({"message": "Assessment created.", "assessment": assessment_dict(row)}), 201
    except ValueError as e: db.session.rollback(); return api_error(str(e))
    except IntegrityError: db.session.rollback(); return api_error("An assessment with that name already exists for this class, subject, and term.")

@app.get("/api/marks")
@login_required
def marks_list():
    user = current_user(); q = Mark.query.join(Assessment, Mark.assessment_id == Assessment.id).join(Student, Mark.student_id == Student.id)
    if user.role == "student":
        s = Student.query.filter_by(user_id=user.id).first(); q = q.filter(Mark.student_id == s.id) if s else q.filter(db.false())
    elif user.role == "teacher":
        t = Teacher.query.filter_by(user_id=user.id).first()
        pairs = [(a.class_id, a.subject_id) for a in TeacherAssignment.query.filter_by(teacher_id=t.id).all()] if t else []
        q = q.filter(db.or_(*[db.and_(Assessment.class_id == c, Assessment.subject_id == sub) for c, sub in pairs])) if pairs else q.filter(db.false())
    if request.args.get("assessment_id"):
        try: q = q.filter(Mark.assessment_id == int(request.args["assessment_id"]))
        except ValueError: return api_error("Invalid assessment filter.")
    rows = q.order_by(Student.full_name, Assessment.assessment_date).limit(5000).all()
    out = []
    for m in rows:
        pct = round(m.marks_obtained / m.assessment.maximum_marks * 100, 2)
        out.append({"id": m.id, "assessment_id": m.assessment_id, "assessment": m.assessment.name, "student_id": m.student_id,
                    "student": m.student.full_name, "roll_number": m.student.roll_number, "class_id": m.assessment.class_id,
                    "subject_id": m.assessment.subject_id, "subject": m.assessment.subject.name, "marks_obtained": m.marks_obtained,
                    "maximum_marks": m.assessment.maximum_marks, "passing_marks": m.assessment.passing_marks,
                    "percentage": pct, "grade": grade_for(pct), "result": "Pass" if m.marks_obtained >= m.assessment.passing_marks else "Fail",
                    "remarks": m.teacher_remarks or ""})
    return jsonify(out)

@app.post("/api/marks")
@roles_required("admin", "teacher")
def marks_save():
    data = payload(); error = required(data, "assessment_id", "records")
    if error: return api_error(error)
    try:
        assessment = db.session.get(Assessment, parse_int(data["assessment_id"], "assessment_id"))
        if not assessment: return api_error("Assessment not found.", 404)
        user = current_user()
        if user.role == "teacher" and not teacher_can(user.id, assessment.class_id, assessment.subject_id): return api_error("You are not assigned to this assessment.", 403)
        records = data["records"]
        if not isinstance(records, list) or not records: return api_error("Add at least one mark record.")
        ids = [str(r.get("student_id")) for r in records if isinstance(r, dict)]
        if len(ids) != len(records) or len(set(ids)) != len(ids): return api_error("Each student can appear only once in a marks batch.")
        for r in records:
            sid = parse_int(r.get("student_id"), "student_id")
            if not student_enrolled(sid, assessment.class_id): return api_error(f"Student ID {sid} is not enrolled in this class.")
            if r.get("marks_obtained") is not None and str(r.get("marks_obtained")).strip() != "":
                try: value = float(r["marks_obtained"])
                except (ValueError, TypeError): return api_error("Marks must be numeric; leave blank for an unentered mark.")
                if not math.isfinite(value) or value < 0 or value > assessment.maximum_marks: return api_error(f"Marks must be between 0 and {assessment.maximum_marks}.")
        for r in records:
            sid = int(r["student_id"]); value = r.get("marks_obtained")
            existing = Mark.query.filter_by(assessment_id=assessment.id, student_id=sid).first()
            if value is None or str(value).strip() == "":
                if existing: db.session.delete(existing)
                continue
            value = float(value)
            remarks = (str(r.get("remarks", "")).strip() or None)
            if existing: existing.marks_obtained = value; existing.teacher_remarks = remarks; existing.updated_at = now_utc()
            else: db.session.add(Mark(assessment_id=assessment.id, student_id=sid, marks_obtained=value, teacher_remarks=remarks))
        log_activity("saved_marks", "assessment", assessment.id, f"{len(records)} mark row(s)")
        db.session.commit()
        return jsonify({"message": "Marks saved. Blank entries remain missing, not zero.", "count": len(records)})
    except ValueError as e: db.session.rollback(); return api_error(str(e))
    except IntegrityError: db.session.rollback(); return api_error("A duplicate or invalid mark was detected. No changes were committed.")
    except SQLAlchemyError: db.session.rollback(); app.logger.exception("Marks transaction failed"); return api_error("Marks could not be saved. No changes were committed.", 500)

@app.get("/api/results")
@login_required
def student_results():
    user = current_user(); q = Mark.query.join(Assessment, Mark.assessment_id == Assessment.id).join(Student, Mark.student_id == Student.id)
    if user.role == "student":
        s = Student.query.filter_by(user_id=user.id).first(); q = q.filter(Mark.student_id == s.id) if s else q.filter(db.false())
    elif user.role == "teacher":
        t = Teacher.query.filter_by(user_id=user.id).first(); assignments = [(a.class_id, a.subject_id) for a in TeacherAssignment.query.filter_by(teacher_id=t.id).all()] if t else []
        q = q.filter(db.or_(*[db.and_(Assessment.class_id == c, Assessment.subject_id == sub) for c, sub in assignments])) if assignments else q.filter(db.false())
    if request.args.get("student_id"):
        if user.role == "student": return api_error("You can view only your own results.", 403)
        try: sid = int(request.args["student_id"])
        except ValueError: return api_error("Invalid student ID.")
        if user.role == "teacher":
            student = db.session.get(Student, sid)
            if not student or not any(student_enrolled(sid, c) for c, _ in assignments): return api_error("Student is outside your assigned classes.", 403)
        q = q.filter(Mark.student_id == sid)
    rows = q.order_by(Assessment.academic_term, Assessment.subject_id, Assessment.assessment_date).all()
    grouped = {}
    for m in rows:
        key = (m.student_id, m.assessment.subject_id, m.assessment.academic_term)
        group = grouped.setdefault(key, {"student_id": m.student_id, "student": m.student.full_name, "roll_number": m.student.roll_number,
                                          "subject": m.assessment.subject.name, "subject_code": m.assessment.subject.code,
                                          "academic_term": m.assessment.academic_term, "obtained": 0.0, "maximum": 0.0, "failed_assessments": 0, "assessments_recorded": 0})
        group["obtained"] += m.marks_obtained; group["maximum"] += m.assessment.maximum_marks; group["assessments_recorded"] += 1
        if m.marks_obtained < m.assessment.passing_marks: group["failed_assessments"] += 1
    result = []
    for gdata in grouped.values():
        pct = round(gdata["obtained"] / gdata["maximum"] * 100, 2) if gdata["maximum"] else 0
        gdata["percentage"] = pct; gdata["grade"] = grade_for(pct)
        gdata["result"] = "Fail" if gdata["failed_assessments"] or grade_for(pct) == "F" else "Pass"
        result.append(gdata)
    return jsonify(result)

# ---------- CSV reports ----------
@app.get("/api/reports/students.csv")
@login_required
def report_students_csv():
    user = current_user(); q = Student.query
    if user.role == "student": q = q.filter_by(user_id=user.id)
    elif user.role == "teacher":
        t = Teacher.query.filter_by(user_id=user.id).first(); ids = [a.class_id for a in TeacherAssignment.query.filter_by(teacher_id=t.id).all()] if t else []
        q = q.join(Enrollment).filter(Enrollment.class_id.in_(ids)) if ids else q.filter(db.false())
    rows = q.distinct().order_by(Student.full_name).all()
    output = []
    for s in rows:
        d = student_dict(s); output.append([d["roll_number"], d["full_name"], d["email"], d["phone"], d["date_of_birth"], d["gender"], d["department"], d["course"], d["academic_year"], d["semester"], d["class_name"] or "", d["enrollment_date"], "Active" if d["is_active"] else "Inactive"])
    return csv_response("educloud-students.csv", ["Roll Number", "Full Name", "Email", "Phone", "Date of Birth", "Gender", "Department", "Course", "Academic Year", "Semester", "Class", "Enrollment Date", "Status"], output)

@app.get("/api/reports/attendance.csv")
@login_required
def report_attendance_csv():
    user = current_user(); q = Attendance.query.join(Student)
    if user.role == "student":
        s = Student.query.filter_by(user_id=user.id).first(); q = q.filter(Attendance.student_id == s.id) if s else q.filter(db.false())
    elif user.role == "teacher":
        t = Teacher.query.filter_by(user_id=user.id).first(); pairs = [(a.class_id, a.subject_id) for a in TeacherAssignment.query.filter_by(teacher_id=t.id).all()] if t else []
        q = q.filter(db.or_(*[db.and_(Attendance.class_id == c, Attendance.subject_id == sub) for c, sub in pairs])) if pairs else q.filter(db.false())
    try:
        if request.args.get("start"): q = q.filter(Attendance.attendance_date >= parse_date(request.args["start"], "start"))
        if request.args.get("end"): q = q.filter(Attendance.attendance_date <= parse_date(request.args["end"], "end"))
        for param, column in (("class_id", Attendance.class_id), ("subject_id", Attendance.subject_id)):
            if request.args.get(param): q = q.filter(column == parse_int(request.args[param], param))
    except ValueError as e: return api_error(str(e))
    output = [[r.attendance_date.isoformat(), r.student.roll_number, r.student.full_name, r.class_group.name, r.class_group.section, r.subject.code, r.subject.name, r.status] for r in q.order_by(Attendance.attendance_date, Student.full_name).all()]
    return csv_response("educloud-attendance.csv", ["Date", "Roll Number", "Student", "Class", "Section", "Subject Code", "Subject", "Status"], output)

@app.get("/api/reports/marks.csv")
@login_required
def report_marks_csv():
    user = current_user(); q = Mark.query.join(Assessment, Mark.assessment_id == Assessment.id).join(Student, Mark.student_id == Student.id)
    if user.role == "student":
        s = Student.query.filter_by(user_id=user.id).first(); q = q.filter(Mark.student_id == s.id) if s else q.filter(db.false())
    elif user.role == "teacher":
        t = Teacher.query.filter_by(user_id=user.id).first(); pairs = [(a.class_id, a.subject_id) for a in TeacherAssignment.query.filter_by(teacher_id=t.id).all()] if t else []
        q = q.filter(db.or_(*[db.and_(Assessment.class_id == c, Assessment.subject_id == sub) for c, sub in pairs])) if pairs else q.filter(db.false())
    output = []
    for m in q.order_by(Assessment.assessment_date, Student.full_name).all():
        pct = round(m.marks_obtained / m.assessment.maximum_marks * 100, 2)
        output.append([m.student.roll_number, m.student.full_name, m.assessment.name, m.assessment.subject.code, m.assessment.subject.name,
                       m.assessment.academic_term, m.marks_obtained, m.assessment.maximum_marks, m.assessment.passing_marks, pct, grade_for(pct), "Pass" if m.marks_obtained >= m.assessment.passing_marks else "Fail", m.teacher_remarks or ""])
    return csv_response("educloud-marks.csv", ["Roll Number", "Student", "Assessment", "Subject Code", "Subject", "Term", "Obtained", "Maximum", "Passing", "Percent", "Grade", "Result", "Remarks"], output)

@app.get("/api/reports/class-performance.csv")
@roles_required("admin", "teacher")
def report_class_performance_csv():
    user = current_user()
    query = Mark.query.join(Assessment, Mark.assessment_id == Assessment.id).join(Student, Mark.student_id == Student.id)
    if user.role == "teacher":
        teacher = Teacher.query.filter_by(user_id=user.id).first()
        pairs = [(a.class_id, a.subject_id) for a in TeacherAssignment.query.filter_by(teacher_id=teacher.id).all()] if teacher else []
        query = query.filter(db.or_(*[db.and_(Assessment.class_id == c, Assessment.subject_id == sub) for c, sub in pairs])) if pairs else query.filter(db.false())
    groups = {}
    for mark in query.order_by(Assessment.class_id, Assessment.subject_id, Student.full_name).all():
        assessment = mark.assessment
        key = (mark.student_id, assessment.class_id, assessment.subject_id, assessment.academic_term)
        item = groups.setdefault(key, {"student": mark.student, "assessment": assessment, "obtained": 0.0, "maximum": 0.0, "failed": False, "count": 0})
        item["obtained"] += mark.marks_obtained
        item["maximum"] += assessment.maximum_marks
        item["count"] += 1
        if mark.marks_obtained < assessment.passing_marks: item["failed"] = True
    output = []
    for item in groups.values():
        student, assessment = item["student"], item["assessment"]
        pct = round(item["obtained"] / item["maximum"] * 100, 2) if item["maximum"] else 0
        grade = grade_for(pct)
        result = "Fail" if item["failed"] or grade == "F" else "Pass"
        output.append([assessment.class_group.name, assessment.class_group.section, student.roll_number, student.full_name,
                       assessment.subject.code, assessment.subject.name, assessment.academic_term, item["obtained"],
                       item["maximum"], pct, grade, result, item["count"]])
    return csv_response("educloud-class-performance.csv", ["Class", "Section", "Roll Number", "Student", "Subject Code", "Subject", "Term", "Obtained", "Maximum", "Percentage", "Grade", "Result", "Assessments Recorded"], output)

# ---------- Error handling and initialization ----------
@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Your security token expired. Refresh the page and try again."}), 400
    return "CSRF validation failed. Refresh the page and try again.", 400

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"): return jsonify({"error": "API endpoint not found."}), 404
    return e

@app.errorhandler(429)
def too_many_requests(e):
    return jsonify({"error": "Too many login attempts. Wait a minute and try again."}), 429

@app.teardown_appcontext
def cleanup_session(exception=None):
    if exception: db.session.rollback()
    db.session.remove()

# Create the schema from ORM metadata on first startup. schema.sql documents the normalized
# relational structure for SQLite users; SQLAlchemy metadata is the cross-database source of truth.
with app.app_context():
    if db.engine.dialect.name == "sqlite":
        @event.listens_for(db.engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    if app.config["AUTO_CREATE_DB"]:
        if db.engine.dialect.name == "sqlite":
            from sqlalchemy import inspect
            if not inspect(db.engine).has_table("users"):
                schema_path = os.path.join(BASE_DIR, "schema.sql")
                if os.path.exists(schema_path):
                    raw = db.engine.raw_connection()
                    try:
                        raw.driver_connection.executescript(open(schema_path, encoding="utf-8").read())
                        raw.commit()
                    finally:
                        raw.close()
        db.create_all()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG", "0") == "1")
