"""Smart Parents Monitoring System — Flask Application."""

import calendar
import os
from collections import Counter
from datetime import date, datetime
from flask import (Flask, render_template, redirect, url_for, request,
                   flash, send_file, jsonify)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from werkzeug.utils import secure_filename
from config import Config
from models import db, User, Student, Subject, Attendance, DailyAttendance, Marks, Backlog, Alert
from ml_model import predict_student_risk
from utils import (process_attendance_excel, process_attendance_daily_excel, process_marks_excel,
                   generate_student_pdf)

app = Flask(__name__)
app.config.from_object(Config)

# Ensure folders exist
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(os.path.join(os.path.dirname(__file__), "instance"), exist_ok=True)

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"

ALLOWED_EXTENSIONS = {"xlsx", "xls"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def _parse_month(month_value):
    """Parse YYYY-MM into first day of month."""
    if not month_value:
        return None
    try:
        parsed = datetime.strptime(month_value, "%Y-%m").date()
        return parsed.replace(day=1)
    except ValueError:
        return None


def _parse_date(date_value):
    """Parse YYYY-MM-DD into date."""
    if not date_value:
        return None
    try:
        return datetime.strptime(date_value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _latest_daily_attendance_date():
    """Return latest logged date in daily attendance, fallback to today."""
    latest = DailyAttendance.query.order_by(DailyAttendance.date.desc()).first()
    return latest.date if latest else date.today()


def _latest_marks_by_subject(student):
    """Pick latest marks record per subject for a student."""
    latest_by_subject = {}
    for record in student.marks.order_by(Marks.updated_at.desc(), Marks.id.desc()).all():
        if record.subject_id not in latest_by_subject:
            latest_by_subject[record.subject_id] = record
    return latest_by_subject


def _build_risk_context(students):
    """Build attendance/marks risk context for dashboard summary and filters."""
    subject_map = {s.id: s for s in Subject.query.all()}
    snapshot = []
    attendance_risk_students = []
    marks_risk_students = []
    popup_alerts = []

    for student in students:
        attendance_pct = round(student.overall_attendance, 2)
        attendance_risk = attendance_pct < 70
        latest_marks = _latest_marks_by_subject(student)
        low_mark_subjects = []

        for subject_id, mark in latest_marks.items():
            percentage = mark.percentage
            if percentage < 50:
                subject = subject_map.get(subject_id)
                low_mark_subjects.append({
                    "subject": subject.name if subject else f"Subject {subject_id}",
                    "subject_code": subject.code if subject else "-",
                    "percentage": percentage,
                    "obtained": mark.marks_obtained,
                    "max": mark.max_marks,
                    "exam_type": mark.exam_type,
                })

        low_mark_subjects.sort(key=lambda item: item["percentage"])

        if attendance_risk:
            attendance_risk_students.append({
                "id": student.id,
                "student_id": student.student_id,
                "name": student.name,
                "attendance": attendance_pct,
            })
            popup_alerts.append({
                "type": "attendance",
                "title": "Low Attendance Alert",
                "message": f"{student.name} ({student.student_id}) has {attendance_pct}% attendance.",
            })

        if low_mark_subjects:
            worst = low_mark_subjects[0]
            marks_risk_students.append({
                "id": student.id,
                "student_id": student.student_id,
                "name": student.name,
                "worst_subject": worst["subject"],
                "worst_percentage": worst["percentage"],
                "low_mark_subjects": low_mark_subjects,
            })
            popup_alerts.append({
                "type": "marks",
                "title": "Low Marks Alert",
                "message": (
                    f"{student.name} ({student.student_id}) scored {worst['percentage']}% "
                    f"in {worst['subject']}."
                ),
            })

        if attendance_risk or low_mark_subjects:
            risk_score = (3 if attendance_risk else 0) + len(low_mark_subjects)
            snapshot.append({
                "id": student.id,
                "student_id": student.student_id,
                "name": student.name,
                "attendance": attendance_pct,
                "attendance_risk": attendance_risk,
                "marks_risk": bool(low_mark_subjects),
                "low_mark_subjects": low_mark_subjects,
                "risk_score": risk_score,
            })

    snapshot.sort(key=lambda item: (-item["risk_score"], item["attendance"], item["name"]))
    attendance_risk_students.sort(key=lambda item: (item["attendance"], item["name"]))
    marks_risk_students.sort(key=lambda item: (item["worst_percentage"], item["name"]))

    return {
        "snapshot": snapshot,
        "attendance_risk_students": attendance_risk_students,
        "marks_risk_students": marks_risk_students,
        "attendance_risk_count": len(attendance_risk_students),
        "marks_risk_count": len(marks_risk_students),
        "popup_alerts": popup_alerts,
    }


def _sync_dashboard_risk_alerts(risk_context):
    """Persist low attendance and marks risk alerts (deduplicated)."""
    unread_low_att = {
        (a.student_id, a.message)
        for a in Alert.query.filter_by(alert_type="low_attendance", is_read=False).all()
    }
    unread_marks = {
        (a.student_id, a.message)
        for a in Alert.query.filter_by(alert_type="marks_risk", is_read=False).all()
    }

    changed = False
    attendance_message = "Overall attendance is below 70%. Immediate follow-up needed."
    for student in risk_context["attendance_risk_students"]:
        key = (student["id"], attendance_message)
        if key not in unread_low_att:
            db.session.add(Alert(
                student_id=student["id"],
                alert_type="low_attendance",
                message=attendance_message,
            ))
            unread_low_att.add(key)
            changed = True

    for student in risk_context["marks_risk_students"]:
        for mark in student["low_mark_subjects"]:
            message = f"Low marks risk in {mark['subject']}: latest score below 50%."
            key = (student["id"], message)
            if key not in unread_marks:
                db.session.add(Alert(
                    student_id=student["id"],
                    alert_type="marks_risk",
                    message=message,
                ))
                unread_marks.add(key)
                changed = True

    if changed:
        db.session.commit()


def _build_calendar_summary(month_start):
    """Build day-wise summary for a month from date-wise attendance logs."""
    total_days = calendar.monthrange(month_start.year, month_start.month)[1]
    month_end = month_start.replace(day=total_days)
    records = DailyAttendance.query.filter(
        DailyAttendance.date >= month_start,
        DailyAttendance.date <= month_end,
    ).all()

    day_map = {}
    for record in records:
        item = day_map.setdefault(record.date, {"presence": {}, "total_classes": 0})
        item["total_classes"] += record.classes_count or 0
        existing = item["presence"].get(record.student_id, False)
        item["presence"][record.student_id] = existing or (record.status == "Present")

    days = []
    for dt, payload in sorted(day_map.items()):
        students_count = len(payload["presence"])
        present_students = sum(1 for value in payload["presence"].values() if value)
        absent_students = students_count - present_students
        attendance_pct = round((present_students / students_count) * 100, 2) if students_count else 0.0
        days.append({
            "date": dt.isoformat(),
            "day": dt.day,
            "attendance_pct": attendance_pct,
            "students_count": students_count,
            "present_students": present_students,
            "absent_students": absent_students,
            "total_classes": payload["total_classes"],
        })

    return {
        "month": month_start.strftime("%Y-%m"),
        "days_in_month": total_days,
        "first_weekday": month_start.weekday(),
        "days": days,
    }


def _build_month_insights(month_start):
    """Build graph-ready monthly insights for admin dashboard."""
    total_days = calendar.monthrange(month_start.year, month_start.month)[1]
    month_end = month_start.replace(day=total_days)
    subject_map = {s.id: s for s in Subject.query.all()}

    # 1) Classes by subject in selected month
    month_records = DailyAttendance.query.filter(
        DailyAttendance.date >= month_start,
        DailyAttendance.date <= month_end,
    ).all()
    classes_counter = Counter()
    for record in month_records:
        classes_counter[record.subject_id] += record.classes_count or 0

    classes_by_subject = []
    for subject_id, total_classes in classes_counter.items():
        subject = subject_map.get(subject_id)
        classes_by_subject.append({
            "subject_id": subject_id,
            "subject": subject.name if subject else f"Subject {subject_id}",
            "subject_code": subject.code if subject else "-",
            "total_classes": total_classes,
        })
    classes_by_subject.sort(key=lambda item: (-item["total_classes"], item["subject"]))

    # 2) Low marks by subject using latest record per student-subject pair
    latest_by_pair = {}
    for mark in Marks.query.order_by(Marks.updated_at.desc(), Marks.id.desc()).all():
        key = (mark.student_id, mark.subject_id)
        if key not in latest_by_pair:
            latest_by_pair[key] = mark

    low_pairs = []
    low_marks_counter = Counter()
    low_student_ids = set()
    for (student_id, subject_id), mark in latest_by_pair.items():
        pct = mark.percentage
        if pct < 50:
            low_marks_counter[subject_id] += 1
            low_student_ids.add(student_id)
            low_pairs.append({
                "student_db_id": student_id,
                "subject_id": subject_id,
                "percentage": pct,
                "obtained": mark.marks_obtained,
                "max": mark.max_marks,
            })

    low_marks_by_subject = []
    for subject_id, count in low_marks_counter.items():
        subject = subject_map.get(subject_id)
        low_marks_by_subject.append({
            "subject_id": subject_id,
            "subject": subject.name if subject else f"Subject {subject_id}",
            "subject_code": subject.code if subject else "-",
            "students_count": count,
        })
    low_marks_by_subject.sort(key=lambda item: (-item["students_count"], item["subject"]))

    # 3) Reasons for low marks (absent reasons for low-mark students, selected month only)
    reason_counter = Counter()
    if low_student_ids:
        low_absences = DailyAttendance.query.filter(
            DailyAttendance.date >= month_start,
            DailyAttendance.date <= month_end,
            DailyAttendance.student_id.in_(list(low_student_ids)),
            DailyAttendance.status == "Absent",
        ).all()
        for row in low_absences:
            reason = (row.reason or "No reason provided").strip() or "No reason provided"
            reason_counter[reason] += 1

    low_mark_reasons = [
        {"reason": reason, "count": count}
        for reason, count in reason_counter.most_common(8)
    ]

    # 4) Top affected students (worst latest % first)
    students_map = {}
    if low_student_ids:
        students_map = {
            s.id: s for s in Student.query.filter(Student.id.in_(list(low_student_ids))).all()
        }

    top_affected_students = []
    for item in low_pairs:
        student = students_map.get(item["student_db_id"])
        subject = subject_map.get(item["subject_id"])
        if not student:
            continue
        top_affected_students.append({
            "student_db_id": student.id,
            "student_id": student.student_id,
            "name": student.name,
            "subject": subject.name if subject else f"Subject {item['subject_id']}",
            "subject_code": subject.code if subject else "-",
            "percentage": item["percentage"],
            "obtained": item["obtained"],
            "max": item["max"],
        })
    top_affected_students.sort(key=lambda item: (item["percentage"], item["name"]))

    return {
        "classes_by_subject": classes_by_subject,
        "low_marks_by_subject": low_marks_by_subject,
        "low_mark_reasons": low_mark_reasons,
        "top_affected_students": top_affected_students[:10],
    }


def _build_day_summary(target_date, risk_context=None):
    """Build selected-day dashboard panel summary."""
    records = DailyAttendance.query.filter_by(date=target_date).all()
    reason_counter = Counter()
    student_presence = {}
    student_reasons = {}
    total_classes = 0

    for record in records:
        total_classes += record.classes_count or 0
        student_presence.setdefault(record.student_id, False)
        if record.status == "Present":
            student_presence[record.student_id] = True
        else:
            reason = (record.reason or "No reason provided").strip() or "No reason provided"
            reason_counter[reason] += 1
            student_reasons.setdefault(record.student_id, []).append(reason)

    students_count = len(student_presence)
    present_students = sum(1 for status in student_presence.values() if status)
    absent_students = students_count - present_students
    attendance_pct = round((present_students / students_count) * 100, 2) if students_count else 0.0

    if not students_count:
        status = "no_data"
        status_message = "No attendance logs available for this date."
    elif attendance_pct < 40:
        status = "very_low"
        status_message = f"{attendance_pct}% attendance. Very low attendance on this day."
    elif attendance_pct < 70:
        status = "low"
        status_message = f"{attendance_pct}% attendance. Attendance is below expected levels."
    else:
        status = "healthy"
        status_message = f"{attendance_pct}% attendance. Attendance is in a healthy range."

    absent_ids = [student_id for student_id, is_present in student_presence.items() if not is_present]
    students_map = {
        student.id: student
        for student in Student.query.filter(Student.id.in_(absent_ids)).all()
    } if absent_ids else {}

    absent_list = []
    for student_id in absent_ids:
        student = students_map.get(student_id)
        if not student:
            continue
        reasons = student_reasons.get(student_id, [])
        absent_list.append({
            "id": student.id,
            "student_id": student.student_id,
            "name": student.name,
            "reason": ", ".join(sorted(set(reasons))) if reasons else "No reason provided",
        })

    top_reasons = [{"reason": reason, "count": count} for reason, count in reason_counter.most_common(5)]

    if risk_context is None:
        risk_context = _build_risk_context(Student.query.all())

    return {
        "date": target_date.isoformat(),
        "attendance_pct": attendance_pct,
        "students_count": students_count,
        "present_students": present_students,
        "absent_students": absent_students,
        "total_classes": total_classes,
        "status": status,
        "status_message": status_message,
        "top_reasons": top_reasons,
        "absent_students_list": absent_list,
        "at_risk_slices": {
            "attendance": {
                "count": risk_context["attendance_risk_count"],
                "students": risk_context["attendance_risk_students"][:5],
            },
            "marks": {
                "count": risk_context["marks_risk_count"],
                "students": [
                    {
                        "id": item["id"],
                        "student_id": item["student_id"],
                        "name": item["name"],
                        "worst_subject": item["worst_subject"],
                        "worst_percentage": item["worst_percentage"],
                    }
                    for item in risk_context["marks_risk_students"][:5]
                ],
            },
        },
    }


# ── Auth Routes ──────────────────────────────────────────────
@app.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("parent_dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "parent")
        user = User.query.filter_by(username=username, role=role).first()
        if user and user.check_password(password):
            login_user(user)
            flash(f"Welcome back, {user.name}!", "success")
            if user.is_admin:
                return redirect(url_for("admin_dashboard"))
            return redirect(url_for("parent_dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.", "info")
    return redirect(url_for("login"))


# ── Admin Routes ─────────────────────────────────────────────
@app.route("/admin/dashboard")
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash("Access denied.", "danger")
        return redirect(url_for("parent_dashboard"))

    students = Student.query.all()
    total_students = len(students)
    avg_att = 0.0
    if students:
        all_attendance = [s.overall_attendance for s in students]
        avg_att = round(sum(all_attendance) / len(all_attendance), 1) if all_attendance else 0.0

    risk_context = _build_risk_context(students)
    _sync_dashboard_risk_alerts(risk_context)

    total_alerts = Alert.query.filter_by(is_read=False).count()

    selected_date = _parse_date(request.args.get("date", "").strip()) or _latest_daily_attendance_date()
    selected_month = _parse_month(request.args.get("month", "").strip()) or selected_date.replace(day=1)
    month_summary = _build_calendar_summary(selected_month)
    month_insights = _build_month_insights(selected_month)
    day_summary = _build_day_summary(selected_date, risk_context=risk_context)

    return render_template("admin/dashboard.html",
                           total_students=total_students,
                           avg_attendance=avg_att,
                           total_alerts=total_alerts,
                           attendance_risk_count=risk_context["attendance_risk_count"],
                           marks_risk_count=risk_context["marks_risk_count"],
                           risk_snapshot=risk_context["snapshot"][:8],
                           popup_alerts=risk_context["popup_alerts"][:10],
                           selected_date=selected_date.isoformat(),
                           selected_month=selected_month.strftime("%Y-%m"),
                           month_summary=month_summary,
                           month_insights=month_insights,
                           day_summary=day_summary)


@app.route("/admin/upload", methods=["GET", "POST"])
@login_required
def admin_upload():
    if not current_user.is_admin:
        flash("Access denied.", "danger")
        return redirect(url_for("index"))
    summary = None
    if request.method == "POST":
        file = request.files.get("file")
        upload_type = request.form.get("upload_type", "attendance")
        if not file or file.filename == "":
            flash("Please select a file.", "warning")
        elif not allowed_file(file.filename):
            flash("Only .xlsx and .xls files are allowed.", "danger")
        else:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)
            if upload_type == "attendance":
                summary = process_attendance_excel(filepath, db, Student, Subject, Attendance, Alert)
            elif upload_type == "attendance_daily":
                summary = process_attendance_daily_excel(
                    filepath, db, Student, Subject, Attendance, DailyAttendance, Alert
                )
            else:
                summary = process_marks_excel(filepath, db, Student, Subject, Marks, Backlog, Alert)
            if summary["errors"]:
                flash(f"Processed with {len(summary['errors'])} error(s).", "warning")
            else:
                flash(f"Successfully processed {summary['processed']} records!", "success")
    return render_template("admin/upload.html", summary=summary)


@app.route("/admin/students")
@login_required
def admin_students():
    if not current_user.is_admin:
        flash("Access denied.", "danger")
        return redirect(url_for("index"))
    search = request.args.get("search", "").strip()
    if search:
        students = Student.query.filter(
            (Student.student_id.contains(search)) | (Student.name.contains(search))
        ).all()
    else:
        students = Student.query.all()
    return render_template("admin/students.html", students=students, search=search)


@app.route("/admin/student/<int:id>")
@login_required
def admin_student_detail(id):
    if not current_user.is_admin:
        flash("Access denied.", "danger")
        return redirect(url_for("index"))
    student = Student.query.get_or_404(id)
    predictions = predict_student_risk(student)
    alerts = Alert.query.filter_by(student_id=student.id).order_by(Alert.created_at.desc()).all()
    return render_template("admin/student_detail.html",
                           student=student, predictions=predictions, alerts=alerts)


@app.route("/admin/reports")
@login_required
def admin_reports():
    if not current_user.is_admin:
        flash("Access denied.", "danger")
        return redirect(url_for("index"))
    students = Student.query.all()
    return render_template("admin/reports.html", students=students)


@app.route("/admin/reports/download/<int:id>")
@login_required
def admin_download_report(id):
    if not current_user.is_admin:
        flash("Access denied.", "danger")
        return redirect(url_for("index"))
    student = Student.query.get_or_404(id)
    predictions = predict_student_risk(student)
    pdf_buffer = generate_student_pdf(student, predictions)
    return send_file(pdf_buffer, as_attachment=True,
                     download_name=f"SPMS_Report_{student.student_id}.pdf",
                     mimetype="application/pdf")


@app.route("/admin/add_student", methods=["GET", "POST"])
@login_required
def admin_add_student():
    """Add a new student and auto-create a parent account."""
    if not current_user.is_admin:
        flash("Access denied.", "danger")
        return redirect(url_for("index"))
    subjects = Subject.query.all()
    if request.method == "POST":
        student_id = request.form.get("student_id", "").strip()
        name = request.form.get("name", "").strip()
        department = request.form.get("department", "CSBS").strip()
        semester = int(request.form.get("semester", 3))
        parent_username = request.form.get("parent_username", "").strip()
        parent_password = request.form.get("parent_password", "").strip()
        parent_name = request.form.get("parent_name", "").strip()
        parent_phone = request.form.get("parent_phone", "").strip()
        parent_email = request.form.get("parent_email", "").strip()

        # Validations
        if not student_id or not name:
            flash("Student ID and Name are required.", "warning")
            return render_template("admin/add_student.html", subjects=subjects)
        if Student.query.filter_by(student_id=student_id).first():
            flash(f"Student ID '{student_id}' already exists.", "danger")
            return render_template("admin/add_student.html", subjects=subjects)
        if parent_username and User.query.filter_by(username=parent_username).first():
            flash(f"Parent username '{parent_username}' already taken.", "danger")
            return render_template("admin/add_student.html", subjects=subjects)

        # Create student
        student = Student(student_id=student_id, name=name,
                          department=department, semester=semester)
        db.session.add(student)
        db.session.flush()

        # Create parent account if provided
        if parent_username and parent_password:
            parent = User(
                username=parent_username,
                name=parent_name or f"Parent of {name}",
                role="parent",
                phone=parent_phone,
                email=parent_email,
                student_id=student.id,
            )
            parent.set_password(parent_password)
            db.session.add(parent)

        db.session.commit()
        flash(f"Student '{name}' ({student_id}) added successfully!", "success")
        return redirect(url_for("admin_students"))

    return render_template("admin/add_student.html", subjects=subjects)



@app.route("/parent/dashboard")
@login_required
def parent_dashboard():
    if not current_user.is_parent:
        flash("Access denied.", "danger")
        return redirect(url_for("admin_dashboard"))
    student = current_user.student
    if not student:
        flash("No student linked to your account.", "warning")
        return render_template("parent/dashboard.html", student=None, predictions=None, alerts=[])
    predictions = predict_student_risk(student)
    alerts = Alert.query.filter_by(student_id=student.id, is_read=False).order_by(
        Alert.created_at.desc()).all()
    return render_template("parent/dashboard.html",
                           student=student, predictions=predictions, alerts=alerts)


@app.route("/parent/attendance")
@login_required
def parent_attendance():
    if not current_user.is_parent:
        return redirect(url_for("index"))
    student = current_user.student
    if not student:
        flash("No student linked.", "warning")
        return redirect(url_for("parent_dashboard"))
    records = []
    for a in student.attendances.all():
        subj = Subject.query.get(a.subject_id)
        records.append({"subject": subj.name, "code": subj.code, "type": subj.subject_type,
                         "total": a.total_classes, "attended": a.classes_attended,
                         "percentage": a.percentage})
    return render_template("parent/attendance.html", student=student, records=records)


@app.route("/parent/marks")
@login_required
def parent_marks():
    if not current_user.is_parent:
        return redirect(url_for("index"))
    student = current_user.student
    if not student:
        flash("No student linked.", "warning")
        return redirect(url_for("parent_dashboard"))
    records = []
    for m in student.marks.all():
        subj = Subject.query.get(m.subject_id)
        records.append({"subject": subj.name, "exam_type": m.exam_type,
                         "obtained": m.marks_obtained, "max": m.max_marks,
                         "percentage": m.percentage})
    backlogs = []
    for b in student.backlogs.filter_by(status="Active").all():
        subj = Subject.query.get(b.subject_id)
        backlogs.append({"subject": subj.name, "semester": b.semester, "status": b.status})
    return render_template("parent/marks.html", student=student, records=records, backlogs=backlogs)


@app.route("/parent/predictions")
@login_required
def parent_predictions():
    if not current_user.is_parent:
        return redirect(url_for("index"))
    student = current_user.student
    if not student:
        flash("No student linked.", "warning")
        return redirect(url_for("parent_dashboard"))
    predictions = predict_student_risk(student)
    return render_template("parent/predictions.html", student=student, predictions=predictions)


@app.route("/parent/mark_alert_read/<int:id>")
@login_required
def mark_alert_read(id):
    alert = Alert.query.get_or_404(id)
    alert.is_read = True
    db.session.commit()
    return redirect(request.referrer or url_for("parent_dashboard"))


# ── API Routes (JSON for Charts) ────────────────────────────
@app.route("/api/attendance/<int:student_id>")
@login_required
def api_attendance(student_id):
    student = Student.query.get_or_404(student_id)
    data = []
    for a in student.attendances.all():
        subj = Subject.query.get(a.subject_id)
        data.append({"subject": subj.name, "total": a.total_classes,
                      "attended": a.classes_attended, "percentage": a.percentage})
    return jsonify(data)


@app.route("/api/marks/<int:student_id>")
@login_required
def api_marks(student_id):
    student = Student.query.get_or_404(student_id)
    data = []
    for m in student.marks.all():
        subj = Subject.query.get(m.subject_id)
        data.append({"subject": subj.name, "exam_type": m.exam_type,
                      "obtained": m.marks_obtained, "max": m.max_marks,
                      "percentage": m.percentage})
    return jsonify(data)


@app.route("/api/admin/attendance-calendar")
@login_required
def api_admin_attendance_calendar():
    if not current_user.is_admin:
        return jsonify({"error": "Access denied"}), 403
    month_start = _parse_month(request.args.get("month", "").strip())
    if not month_start:
        month_start = _latest_daily_attendance_date().replace(day=1)
    payload = _build_calendar_summary(month_start)
    payload["insights"] = _build_month_insights(month_start)
    return jsonify(payload)


@app.route("/api/admin/attendance-day")
@login_required
def api_admin_attendance_day():
    if not current_user.is_admin:
        return jsonify({"error": "Access denied"}), 403
    selected_date = _parse_date(request.args.get("date", "").strip())
    if not selected_date:
        selected_date = _latest_daily_attendance_date()
    risk_context = _build_risk_context(Student.query.all())
    return jsonify(_build_day_summary(selected_date, risk_context=risk_context))


# ── DB Init ──────────────────────────────────────────────────
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
