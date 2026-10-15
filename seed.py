"""Populate a fresh/local EduCloud Manager DB with fictional demo data.

Safe reruns: if the demo administrator already exists, the script exits without
changing records. It never deletes data. Non-SQLite databases require an explicit
ALLOW_DEMO_SEED=1 opt-in, and production mode is blocked entirely.
"""
from datetime import date, timedelta
import os
import sys

from app import (app, db, User, Department, ClassGroup, Student, Teacher, Subject,
                 TeacherAssignment, Enrollment, Attendance, Assessment, Mark)

DEMO_ADMIN = "admin"


def main():
    if os.getenv("FLASK_ENV", "development").lower() == "production":
        print("Refusing to seed while FLASK_ENV=production. Use a separate development database.")
        return 2
    if not app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:") and os.getenv("ALLOW_DEMO_SEED") != "1":
        print("Refusing to seed a non-SQLite database. Set ALLOW_DEMO_SEED=1 only for a disposable demo database.")
        return 2

    with app.app_context():
        if User.query.filter_by(username=DEMO_ADMIN).first():
            print("Demo data already exists (admin account found). No changes were made.")
            return 0
        try:
            # Seed is one transaction: failed runs roll back rather than leaving a partial demo dataset.
            departments = [
                Department(code="DS", name="Computer Science & Data Science"),
                Department(code="IT", name="Information Technology"),
                Department(code="EC", name="Electronics & Communication"),
            ]
            db.session.add_all(departments); db.session.flush()
            classes = [
                ClassGroup(name="CSE-DS", section="A", academic_year="2026-27", semester=4, department_id=departments[0].id),
                ClassGroup(name="IT", section="B", academic_year="2026-27", semester=4, department_id=departments[1].id),
                ClassGroup(name="ECE", section="A", academic_year="2026-27", semester=4, department_id=departments[2].id),
            ]
            db.session.add_all(classes); db.session.flush()

            admin = User(username="admin", email="admin@example.com", role="admin", is_active=True, must_change_password=True)
            admin.set_password("AdminDemo2026!"); db.session.add(admin)
            teacher_names = ["Aarav Mehta", "Nisha Rao", "Kabir Shah", "Mira Kulkarni", "Dev Patel"]
            teacher_users = []
            teachers = []
            for i, name in enumerate(teacher_names, start=1):
                email = f"teacher{i}@example.com"
                u = User(username=f"teacher{i}", email=email, role="teacher", is_active=True, must_change_password=True)
                u.set_password("TeachDemo2026!")
                db.session.add(u); db.session.flush()
                dept_id = departments[min((i-1)//2, 2)].id
                t = Teacher(user_id=u.id, employee_number=f"EMP-{i:03d}", full_name=name, email=email, department_id=dept_id, is_active=True)
                db.session.add(t); db.session.flush()
                teacher_users.append(u); teachers.append(t)

            subject_specs = [
                ("DS101", "Python for Data Science", departments[0].id, 0, 0),
                ("DS102", "Database Systems", departments[0].id, 0, 1),
                ("IT201", "Web Technologies", departments[1].id, 1, 2),
                ("IT202", "Computer Networks", departments[1].id, 1, 3),
                ("EC301", "Digital Electronics", departments[2].id, 2, 4),
                ("EC302", "Microprocessors", departments[2].id, 2, 4),
            ]
            subjects = []
            for code, name, dept_id, class_index, teacher_index in subject_specs:
                s = Subject(code=code, name=name, department_id=dept_id, credits=3)
                db.session.add(s); db.session.flush(); subjects.append(s)
                db.session.add(TeacherAssignment(teacher_id=teachers[teacher_index].id, class_id=classes[class_index].id, subject_id=s.id))

            students = []
            for c_index, class_group in enumerate(classes):
                dept = departments[c_index]
                for local_idx in range(1, 11):
                    number = c_index * 10 + local_idx
                    username = f"student{number:03d}"
                    email = f"{username}@example.com"
                    user = User(username=username, email=email, role="student", is_active=True, must_change_password=True)
                    user.set_password("StudentDemo2026!"); db.session.add(user); db.session.flush()
                    # Intentionally fictional names and reserved 202-555-01xx example phone numbers.
                    first_names = ["Aanya", "Ishaan", "Zoya", "Rehan", "Meera", "Arjun", "Sana", "Vihaan", "Noor", "Rohan"]
                    last_names = ["Sharma", "Khan", "Patel", "Joshi", "Desai", "Rao", "Shaikh", "Kulkarni", "Verma", "Kapoor"]
                    full_name = f"{first_names[(number-1) % len(first_names)]} {last_names[(number*7 + number//10) % len(last_names)]}"
                    student = Student(user_id=user.id, roll_number=f"{dept.code}26{local_idx:03d}", full_name=full_name, email=email,
                                      phone=f"+1-202-555-{100 + number:04d}", date_of_birth=date(2005 + (number % 2), (number % 12)+1, (number % 26)+1),
                                      gender=["Female", "Male", "Prefer not to say"][number % 3], department_id=dept.id, course=dept.name,
                                      academic_year="2026-27", semester=4, enrollment_date=date(2026, 7, 15), is_active=True)
                    db.session.add(student); db.session.flush(); students.append(student)
                    db.session.add(Enrollment(student_id=student.id, class_id=class_group.id, academic_term="2026-27", enrolled_at=date(2026, 7, 15)))

            db.session.flush()
            # Thirty completed weekday dates ending yesterday (clearly historical demo sessions).
            dates = []
            cursor = date.today() - timedelta(days=1)
            while len(dates) < 30:
                if cursor.weekday() < 5:
                    dates.append(cursor)
                cursor -= timedelta(days=1)
            dates.sort()
            teacher_for_subject = {s.id: next(a.teacher.user_id for a in TeacherAssignment.query.filter_by(subject_id=s.id).all()) for s in subjects}
            for class_index, class_group in enumerate(classes):
                class_students = [s for s in students if s.department_id == class_group.department_id]
                class_subjects = [s for s in subjects if s.department_id == class_group.department_id]
                for subj in class_subjects:
                    recorder_id = teacher_for_subject[subj.id]
                    for day_index, day in enumerate(dates):
                        for local_idx, student in enumerate(class_students, start=1):
                            # Selected records have low attendance to demonstrate intervention reporting.
                            if local_idx == 1:
                                status = "Absent" if day_index % 3 != 0 else "Present"
                            elif local_idx == 2:
                                status = "Absent" if day_index % 4 == 0 else "Present"
                            else:
                                score = (day_index * 7 + local_idx * 11 + subj.id) % 19
                                status = "Absent" if score in {0, 1, 2} else ("On Leave" if score == 3 else "Present")
                            db.session.add(Attendance(student_id=student.id, class_id=class_group.id, subject_id=subj.id,
                                                      attendance_date=day, status=status, recorded_by=recorder_id))

            # Two assessments for each subject; missing entries intentionally remain absent from marks table.
            for subj in subjects:
                class_group = next(c for c in classes if c.department_id == subj.department_id)
                class_students = [s for s in students if s.department_id == subj.department_id]
                teacher_user_id = teacher_for_subject[subj.id]
                exams = []
                for exam_index, exam_name in enumerate(("Internal Assessment 1", "Semester Test")):
                    exam = Assessment(name=exam_name, class_id=class_group.id, subject_id=subj.id, academic_term="2026-27",
                                      maximum_marks=50, passing_marks=20, assessment_date=date.today()-timedelta(days=25-exam_index*10), created_by=teacher_user_id)
                    db.session.add(exam); db.session.flush(); exams.append(exam)
                    for local_idx, student in enumerate(class_students, start=1):
                        # Some blank marks demonstrate unentered scores; low marks demonstrate failed assessments.
                        if exam_index == 1 and local_idx == 10:
                            continue
                        if local_idx == 1:
                            score = 17 + exam_index * 2
                        elif local_idx == 2:
                            score = 24 + exam_index * 3
                        else:
                            score = 23 + ((local_idx * 7 + subj.id * 3 + exam_index * 5) % 28)
                        score = min(50, score)
                        remarks = "Needs additional support" if score < 20 else ("Strong work" if score >= 43 else None)
                        db.session.add(Mark(assessment_id=exam.id, student_id=student.id, marks_obtained=score, teacher_remarks=remarks))
            db.session.commit()
            print("EduCloud Manager demo data created successfully.")
            print("Admin: admin / AdminDemo2026!")
            print("Teacher: teacher1 / TeachDemo2026!")
            print("Student: student001 / StudentDemo2026!")
            print("All demo accounts require a password change on first login.")
            print(f"Created {len(students)} students, {len(subjects)} subjects, 30 historical weekday dates of attendance, and two assessments per subject.")
            return 0
        except Exception as exc:
            db.session.rollback()
            print(f"Seeding failed; the transaction was rolled back: {exc}", file=sys.stderr)
            raise

if __name__ == "__main__":
    raise SystemExit(main())
