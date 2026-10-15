"""Focused integration tests for core backend workflows and role restrictions."""
import os
os.environ.setdefault("FLASK_ENV", "testing")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-educloud-manager-only")
os.environ.setdefault("DATABASE_URL", "sqlite:///educloud_test.db")
os.environ.setdefault("RATELIMIT_STORAGE_URI", "memory://")

import re
import unittest
from datetime import date, timedelta

from werkzeug.security import check_password_hash
from app import app, db, User, Department, ClassGroup, Subject, Teacher, Student, TeacherAssignment, Enrollment, Attendance, Assessment, Mark
from seed import main as seed_main


class EduCloudTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=True, RATELIMIT_ENABLED=False, SECRET_KEY="test-secret-key-for-educloud-manager-only")
        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.create_all()
            self.department = Department(code="TST", name="Test Department")
            db.session.add(self.department); db.session.flush()
            self.class_group = ClassGroup(name="TEST", section="A", academic_year="2026-27", semester=4, department_id=self.department.id)
            self.subject = Subject(code="TST101", name="Testing Subject", department_id=self.department.id, credits=3)
            db.session.add_all([self.class_group, self.subject]); db.session.flush()
            self.admin = self._user("admin", "admin@example.com", "admin", "AdminTest2026!")
            self.teacher_user = self._user("teacher", "teacher@example.com", "teacher", "TeacherTest2026!")
            self.student_user = self._user("student", "student@example.com", "student", "StudentTest2026!")
            db.session.flush()
            self.teacher = Teacher(user_id=self.teacher_user.id, employee_number="EMP-TST", full_name="Test Teacher", email=self.teacher_user.email, department_id=self.department.id)
            self.student = Student(user_id=self.student_user.id, roll_number="TST001", full_name="Test Student", email=self.student_user.email,
                                   department_id=self.department.id, course="Test Course", academic_year="2026-27", semester=4,
                                   enrollment_date=date(2026, 7, 1), is_active=True)
            db.session.add_all([self.teacher, self.student]); db.session.flush()
            db.session.add(TeacherAssignment(teacher_id=self.teacher.id, class_id=self.class_group.id, subject_id=self.subject.id))
            db.session.add(Enrollment(student_id=self.student.id, class_id=self.class_group.id, academic_term="2026-27", enrolled_at=date(2026, 7, 1)))
            db.session.commit()
            self.ids = {"admin": self.admin.id, "teacher": self.teacher_user.id, "student": self.student_user.id,
                        "teacher_profile": self.teacher.id, "student_profile": self.student.id,
                        "class": self.class_group.id, "subject": self.subject.id, "department": self.department.id}
        self.client = app.test_client()
        self.csrf = self._fetch_csrf()

    def tearDown(self):
        with app.app_context():
            db.session.remove()

    @staticmethod
    def _user(username, email, role, password):
        user = User(username=username, email=email, role=role, is_active=True, must_change_password=False)
        user.set_password(password)
        db.session.add(user)
        return user

    def _fetch_csrf(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        match = re.search(r'<meta name="csrf-token" content="([^"]+)"', response.get_data(as_text=True))
        self.assertIsNotNone(match)
        return match.group(1)

    def _login(self, username, password):
        response = self.client.post("/api/login", json={"username": username, "password": password}, headers={"X-CSRFToken": self.csrf})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.csrf = response.get_json()["csrf_token"]
        return response.get_json()["user"]

    def _post(self, url, payload):
        return self.client.post(url, json=payload, headers={"X-CSRFToken": self.csrf})

    def test_csrf_is_required_for_state_changes(self):
        anonymous = app.test_client()
        anonymous.get("/")
        response = anonymous.post("/api/login", json={"username": "admin", "password": "AdminTest2026!"})
        self.assertEqual(response.status_code, 400)

    def test_startup_unauthenticated_requests_do_not_break_login_csrf(self):
        # The frontend requests /api/me and /api/dashboard before a user logs in.
        # Those 401 responses must not clear the anonymous session's CSRF secret.
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.assertIn(self.client.get("/api/dashboard").status_code, (401, 403))
        user = self._login("admin", "AdminTest2026!")
        self.assertEqual(user["role"], "admin")
        # The token returned after login must also work for a protected POST.
        logout_response = self.client.post("/api/logout", json={}, headers={"X-CSRFToken": self.csrf})
        self.assertEqual(logout_response.status_code, 200, logout_response.get_data(as_text=True))
        self.assertTrue(logout_response.get_json().get("csrf_token"))

    def test_login_success_and_wrong_password(self):
        failed = self.client.post("/api/login", json={"username": "admin", "password": "wrong"}, headers={"X-CSRFToken": self.csrf})
        self.assertEqual(failed.status_code, 401)
        user = self._login("admin", "AdminTest2026!")
        self.assertEqual(user["role"], "admin")
        self.assertFalse(user["must_change_password"])

    def test_private_routes_require_authentication(self):
        response = self.client.get("/api/students")
        self.assertEqual(response.status_code, 401)

    def test_student_create_and_search(self):
        self._login("admin", "AdminTest2026!")
        payload = {"roll_number":"TST002", "full_name":"Second Fictional Student", "email":"second@example.com",
                   "department_id":self.ids["department"], "course":"Test Course", "academic_year":"2026-27", "semester":4,
                   "username":"student2", "password":"StudentTwo2026!", "class_id":self.ids["class"], "academic_term":"2026-27"}
        response = self._post("/api/students", payload)
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        result = self.client.get("/api/students?q=TST002").get_json()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["full_name"], "Second Fictional Student")
        self.assertTrue(result["items"][0]["is_active"])

    def test_student_cannot_create_or_view_other_students(self):
        self._login("student", "StudentTest2026!")
        forbidden = self._post("/api/students", {"roll_number":"HACK001"})
        self.assertEqual(forbidden.status_code, 403)
        own = self.client.get("/api/students").get_json()
        self.assertEqual(own["total"], 1)
        self.assertEqual(own["items"][0]["roll_number"], "TST001")

    def test_attendance_bulk_save_and_duplicate_in_batch_rejected(self):
        self._login("teacher", "TeacherTest2026!")
        payload = {"class_id":self.ids["class"], "subject_id":self.ids["subject"], "date":(date.today()-timedelta(days=1)).isoformat(),
                   "records":[{"student_id":self.ids["student_profile"], "status":"Present"}]}
        response = self._post("/api/attendance", payload)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(self.client.get("/api/attendance").get_json()[0]["status"], "Present")
        payload["records"] = [{"student_id":self.ids["student_profile"], "status":"Present"}, {"student_id":self.ids["student_profile"], "status":"Absent"}]
        duplicate = self._post("/api/attendance", payload)
        self.assertEqual(duplicate.status_code, 400)
        with app.app_context():
            self.assertEqual(Attendance.query.count(), 1)

    def test_teacher_cannot_write_to_another_teacher_assignment(self):
        with app.app_context():
            other_class = ClassGroup(name="OTHER", section="B", academic_year="2026-27", semester=4, department_id=self.ids["department"])
            other_teacher_user = self._user("teacher2", "teacher2@example.com", "teacher", "TeacherTwo2026!")
            db.session.add(other_class); db.session.flush()
            db.session.add(Teacher(user_id=other_teacher_user.id, employee_number="EMP-TST2", full_name="Other Teacher", email=other_teacher_user.email, department_id=self.ids["department"]))
            db.session.flush()
            other_teacher = Teacher.query.filter_by(user_id=other_teacher_user.id).first()
            db.session.add(TeacherAssignment(teacher_id=other_teacher.id, class_id=other_class.id, subject_id=self.ids["subject"]))
            db.session.commit()
            other_class_id = other_class.id
        self._login("teacher", "TeacherTest2026!")
        payload = {"class_id":other_class_id, "subject_id":self.ids["subject"], "date":(date.today()-timedelta(days=1)).isoformat(),
                   "records":[{"student_id":self.ids["student_profile"], "status":"Present"}]}
        response = self._post("/api/attendance", payload)
        self.assertEqual(response.status_code, 403)

    def test_seed_rerun_is_safe(self):
        with app.app_context():
            before = (User.query.count(), Student.query.count(), Attendance.query.count())
        self.assertEqual(seed_main(), 0)
        with app.app_context():
            after = (User.query.count(), Student.query.count(), Attendance.query.count())
        self.assertEqual(after, before)

    def test_marks_validation_grade_and_missing_marks(self):
        self._login("admin", "AdminTest2026!")
        assessment_payload={"name":"Midterm", "class_id":self.ids["class"], "subject_id":self.ids["subject"], "academic_term":"2026-27",
                            "maximum_marks":50, "passing_marks":20, "assessment_date":date.today().isoformat()}
        response=self._post("/api/assessments",assessment_payload)
        self.assertEqual(response.status_code,201,response.get_data(as_text=True))
        assessment_id=response.get_json()["assessment"]["id"]
        too_high=self._post("/api/marks",{"assessment_id":assessment_id,"records":[{"student_id":self.ids["student_profile"],"marks_obtained":51}]})
        self.assertEqual(too_high.status_code,400)
        valid=self._post("/api/marks",{"assessment_id":assessment_id,"records":[{"student_id":self.ids["student_profile"],"marks_obtained":45,"remarks":"Strong"}]})
        self.assertEqual(valid.status_code,200,valid.get_data(as_text=True))
        marks=self.client.get(f"/api/marks?assessment_id={assessment_id}").get_json()
        self.assertEqual(marks[0]["grade"],"A+")
        missing=self._post("/api/marks",{"assessment_id":assessment_id,"records":[{"student_id":self.ids["student_profile"],"marks_obtained":""}]})
        self.assertEqual(missing.status_code,200)
        self.assertEqual(self.client.get(f"/api/marks?assessment_id={assessment_id}").get_json(),[])

    def test_student_csv_export_is_limited_to_own_records(self):
        with app.app_context():
            other_user=self._user("other", "other@example.com", "student", "OtherTest2026!"); db.session.flush()
            other=Student(user_id=other_user.id,roll_number="TST099",full_name="Another Student",email=other_user.email,department_id=self.ids["department"],course="Course",academic_year="2026-27",semester=4,enrollment_date=date(2026,7,1))
            db.session.add(other);db.session.flush()
            assessment=Assessment(name="CSV Test",class_id=self.ids["class"],subject_id=self.ids["subject"],academic_term="2026-27",maximum_marks=50,passing_marks=20,assessment_date=date.today(),created_by=self.ids["admin"])
            db.session.add(assessment);db.session.flush()
            db.session.add_all([Mark(assessment_id=assessment.id,student_id=self.ids["student_profile"],marks_obtained=40),Mark(assessment_id=assessment.id,student_id=other.id,marks_obtained=49)])
            db.session.commit()
        self._login("student", "StudentTest2026!")
        response=self.client.get("/api/reports/marks.csv")
        self.assertEqual(response.status_code,200)
        text=response.get_data(as_text=True)
        self.assertIn("TST001",text)
        self.assertNotIn("TST099",text)

    def test_admin_password_reset_issues_hashed_temporary_password(self):
        self._login("admin", "AdminTest2026!")
        response=self._post(f"/api/users/{self.ids['student']}/reset-password",{})
        self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        temporary=response.get_json()["temporary_password"]
        with app.app_context():
            user=db.session.get(User,self.ids["student"])
            self.assertTrue(user.must_change_password)
            self.assertTrue(check_password_hash(user.password_hash,temporary))
            self.assertNotEqual(user.password_hash,temporary)

    def test_health_check(self):
        response=self.client.get("/api/health")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.get_json()["status"],"ok")


if __name__ == "__main__":
    unittest.main(verbosity=2)
