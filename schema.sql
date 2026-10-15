-- EduCloud Manager SQLite schema. app.py's SQLAlchemy metadata is the cross-database source of truth.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, username VARCHAR(80) NOT NULL UNIQUE, email VARCHAR(160) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL, role VARCHAR(20) NOT NULL CHECK(role IN ('admin','teacher','student')),
  is_active BOOLEAN NOT NULL DEFAULT 1, must_change_password BOOLEAN NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_users_username ON users(username);
CREATE INDEX IF NOT EXISTS ix_users_email ON users(email);
CREATE INDEX IF NOT EXISTS ix_users_role ON users(role);
CREATE TABLE IF NOT EXISTS departments (
  id INTEGER PRIMARY KEY, code VARCHAR(16) NOT NULL UNIQUE, name VARCHAR(120) NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS classes (
  id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, section VARCHAR(20) NOT NULL DEFAULT 'A',
  academic_year VARCHAR(20) NOT NULL, semester INTEGER NOT NULL CHECK(semester BETWEEN 1 AND 12),
  department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE RESTRICT,
  UNIQUE(name, section, academic_year, semester, department_id)
);
CREATE TABLE IF NOT EXISTS students (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE RESTRICT,
  roll_number VARCHAR(40) NOT NULL UNIQUE, full_name VARCHAR(140) NOT NULL, email VARCHAR(160) NOT NULL UNIQUE,
  phone VARCHAR(30), date_of_birth DATE, gender VARCHAR(30),
  department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE RESTRICT,
  course VARCHAR(120) NOT NULL, academic_year VARCHAR(20) NOT NULL,
  semester INTEGER NOT NULL CHECK(semester BETWEEN 1 AND 12), enrollment_date DATE NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT 1, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_students_roll_number ON students(roll_number);
CREATE INDEX IF NOT EXISTS ix_students_full_name ON students(full_name);
CREATE TABLE IF NOT EXISTS teachers (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE RESTRICT,
  employee_number VARCHAR(40) NOT NULL UNIQUE, full_name VARCHAR(140) NOT NULL, email VARCHAR(160) NOT NULL UNIQUE,
  department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE RESTRICT, is_active BOOLEAN NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_teachers_full_name ON teachers(full_name);
CREATE TABLE IF NOT EXISTS subjects (
  id INTEGER PRIMARY KEY, code VARCHAR(24) NOT NULL UNIQUE, name VARCHAR(140) NOT NULL,
  department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE RESTRICT,
  credits INTEGER NOT NULL DEFAULT 3 CHECK(credits BETWEEN 1 AND 10)
);
CREATE TABLE IF NOT EXISTS teacher_assignments (
  id INTEGER PRIMARY KEY, teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
  class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT, UNIQUE(teacher_id,class_id,subject_id)
);
CREATE TABLE IF NOT EXISTS enrollments (
  id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE RESTRICT,
  academic_term VARCHAR(40) NOT NULL DEFAULT '2026-27', enrolled_at DATE NOT NULL,
  UNIQUE(student_id,class_id,academic_term)
);
CREATE TABLE IF NOT EXISTS attendance (
  id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE RESTRICT,
  subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
  attendance_date DATE NOT NULL, status VARCHAR(20) NOT NULL CHECK(status IN ('Present','Absent','On Leave')),
  recorded_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT, created_at DATETIME NOT NULL,
  UNIQUE(student_id,subject_id,attendance_date)
);
CREATE INDEX IF NOT EXISTS ix_attendance_attendance_date ON attendance(attendance_date);
CREATE INDEX IF NOT EXISTS ix_attendance_class_subject_date ON attendance(class_id,subject_id,attendance_date);
CREATE TABLE IF NOT EXISTS assessments (
  id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL,
  class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE RESTRICT,
  subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
  academic_term VARCHAR(40) NOT NULL, maximum_marks FLOAT NOT NULL CHECK(maximum_marks > 0),
  passing_marks FLOAT NOT NULL CHECK(passing_marks >= 0 AND passing_marks <= maximum_marks),
  assessment_date DATE NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  UNIQUE(name,class_id,subject_id,academic_term)
);
CREATE TABLE IF NOT EXISTS marks (
  id INTEGER PRIMARY KEY, assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
  student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  marks_obtained FLOAT NOT NULL CHECK(marks_obtained >= 0), teacher_remarks VARCHAR(500), updated_at DATETIME NOT NULL,
  UNIQUE(assessment_id,student_id)
);
CREATE TABLE IF NOT EXISTS activity_logs (
  id INTEGER PRIMARY KEY, actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  action VARCHAR(100) NOT NULL, entity_type VARCHAR(80) NOT NULL, entity_id VARCHAR(80),
  details VARCHAR(500), created_at DATETIME NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_activity_logs_created_at ON activity_logs(created_at);
