"""Smart Parents Monitoring System — Flask Application."""

import os
from flask import (Flask, render_template, redirect, url_for, request,
                   flash, send_file, jsonify, session)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from werkzeug.utils import secure_filename
from config import Config
from models import db, User, Student, Subject, Attendance, Marks, Backlog, Alert
from ml_model import predict_student_risk
from utils import (process_attendance_excel, process_marks_excel,
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
    avg_att = 0
    if students:
        atts = [s.overall_attendance for s in students]
        avg_att = round(sum(atts) / len(atts), 1) if atts else 0
    total_alerts = Alert.query.filter_by(is_read=False).count()
    low_att_count = 0
    for s in students:
        if s.overall_attendance < 75:
            low_att_count += 1
    subjects = Subject.query.all()
    recent_alerts = Alert.query.order_by(Alert.created_at.desc()).limit(5).all()
    return render_template("admin/dashboard.html",
                           total_students=total_students, avg_attendance=avg_att,
                           total_alerts=total_alerts, low_att_count=low_att_count,
                           subjects=subjects, recent_alerts=recent_alerts, students=students)


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


# ── DB Init ──────────────────────────────────────────────────
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
