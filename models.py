"""Database models for Smart Parents Monitoring System."""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """Unified user model for both Admin and Parent roles."""
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'admin' or 'parent'
    phone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship
    student = db.relationship("Student", backref="parent", uselist=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_parent(self):
        return self.role == "parent"


class Student(db.Model):
    """Student record."""
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    department = db.Column(db.String(50), default="CSBS")
    semester = db.Column(db.Integer, default=3)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    attendances = db.relationship("Attendance", backref="student", lazy="dynamic", cascade="all, delete-orphan")
    daily_attendance_records = db.relationship(
        "DailyAttendance", backref="student", lazy="dynamic", cascade="all, delete-orphan"
    )
    marks = db.relationship("Marks", backref="student", lazy="dynamic", cascade="all, delete-orphan")
    backlogs = db.relationship("Backlog", backref="student", lazy="dynamic", cascade="all, delete-orphan")
    alerts = db.relationship("Alert", backref="student", lazy="dynamic", cascade="all, delete-orphan")

    @property
    def overall_attendance(self):
        """Calculate overall attendance percentage across all subjects."""
        records = self.attendances.all()
        if not records:
            return 0.0
        total_classes = sum(r.total_classes for r in records)
        total_attended = sum(r.classes_attended for r in records)
        if total_classes == 0:
            return 0.0
        return round((total_attended / total_classes) * 100, 2)

    @property
    def active_backlogs_count(self):
        return self.backlogs.filter_by(status="Active").count()


class Subject(db.Model):
    """Subject/Course in the CSBS department."""
    __tablename__ = "subjects"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    subject_type = db.Column(db.String(20), default="Theory")  # Theory or Lab

    # Relationships
    attendances = db.relationship("Attendance", backref="subject", lazy="dynamic")
    daily_attendance_records = db.relationship("DailyAttendance", backref="subject", lazy="dynamic")
    marks_records = db.relationship("Marks", backref="subject", lazy="dynamic")
    backlogs_records = db.relationship("Backlog", backref="subject", lazy="dynamic")


class Attendance(db.Model):
    """Attendance record per student per subject."""
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)
    total_classes = db.Column(db.Integer, default=0)
    classes_attended = db.Column(db.Integer, default=0)
    percentage = db.Column(db.Float, default=0.0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("student_id", "subject_id", name="uq_student_subject_attendance"),
    )

    def compute_percentage(self):
        if self.total_classes > 0:
            self.percentage = round((self.classes_attended / self.total_classes) * 100, 2)
        else:
            self.percentage = 0.0


class DailyAttendance(db.Model):
    """Date-wise attendance log per student per subject."""
    __tablename__ = "daily_attendance"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False)  # Present / Absent
    reason = db.Column(db.String(255), nullable=True)
    classes_count = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint(
            "student_id", "subject_id", "date", name="uq_daily_attendance_student_subject_date"
        ),
    )


class Marks(db.Model):
    """Marks record per student per subject per exam type."""
    __tablename__ = "marks"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)
    exam_type = db.Column(db.String(30), nullable=False)  # 'Internal 1', 'Internal 2', 'Semester'
    marks_obtained = db.Column(db.Float, default=0.0)
    max_marks = db.Column(db.Float, default=100.0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("student_id", "subject_id", "exam_type", name="uq_student_subject_exam"),
    )

    @property
    def percentage(self):
        if self.max_marks > 0:
            return round((self.marks_obtained / self.max_marks) * 100, 2)
        return 0.0


class Backlog(db.Model):
    """Backlog record per student per subject."""
    __tablename__ = "backlogs"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)
    semester = db.Column(db.String(10), default="3")
    status = db.Column(db.String(20), default="Active")  # Active or Cleared
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("student_id", "subject_id", name="uq_student_subject_backlog"),
    )


class Alert(db.Model):
    """Alert/notification for a student."""
    __tablename__ = "alerts"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    alert_type = db.Column(db.String(30), nullable=False)  # low_attendance, marks_risk, backlog_risk, performance_drop
    message = db.Column(db.String(500), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
