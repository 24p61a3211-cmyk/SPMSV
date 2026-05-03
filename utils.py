"""Utility functions for Excel processing, PDF generation, and alert management."""

import pandas as pd
from datetime import datetime
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_CENTER


def _normalize_daily_status(raw_status):
    """Normalize status values to Present / Absent."""
    if pd.isna(raw_status):
        return None
    value = str(raw_status).strip().lower()
    if value in {"present", "p", "1", "yes", "true"}:
        return "Present"
    if value in {"absent", "a", "0", "no", "false"}:
        return "Absent"
    return None


def _safe_classes_count(raw_value):
    """Convert classes count to positive integer."""
    if pd.isna(raw_value):
        raise ValueError("ClassesCount is required")
    value = int(raw_value)
    if value <= 0:
        raise ValueError("ClassesCount must be greater than 0")
    return value


def process_attendance_excel(filepath, db, Student, Subject, Attendance, Alert):
    """Process uploaded Excel with attendance data.
    Expected columns: StudentID, Name, Subject, TotalClasses, ClassesAttended"""
    summary = {"processed": 0, "errors": [], "created": 0, "updated": 0, "alerts_generated": 0}
    try:
        df = pd.read_excel(filepath)
    except Exception as e:
        summary["errors"].append(f"Failed to read Excel file: {str(e)}")
        return summary

    df.columns = df.columns.str.strip()
    required = ["StudentID", "Name", "Subject", "TotalClasses", "ClassesAttended"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        summary["errors"].append(f"Missing columns: {', '.join(missing)}")
        return summary

    for idx, row in df.iterrows():
        try:
            sid = str(row["StudentID"]).strip()
            name = str(row["Name"]).strip()
            subj_name = str(row["Subject"]).strip()
            total = int(row["TotalClasses"])
            attended = int(row["ClassesAttended"])

            student = Student.query.filter_by(student_id=sid).first()
            if not student:
                student = Student(student_id=sid, name=name)
                db.session.add(student)
                db.session.flush()
                summary["created"] += 1

            subject = Subject.query.filter(
                (Subject.name == subj_name) | (Subject.code == subj_name)
            ).first()
            if not subject:
                summary["errors"].append(f"Row {idx+2}: Subject '{subj_name}' not found")
                continue

            record = Attendance.query.filter_by(student_id=student.id, subject_id=subject.id).first()
            if record:
                record.total_classes = total
                record.classes_attended = attended
                record.compute_percentage()
                record.updated_at = datetime.utcnow()
                summary["updated"] += 1
            else:
                record = Attendance(student_id=student.id, subject_id=subject.id,
                                    total_classes=total, classes_attended=attended)
                record.compute_percentage()
                db.session.add(record)
                summary["created"] += 1

            if record.percentage < 75:
                existing = Alert.query.filter_by(student_id=student.id, alert_type="low_attendance", is_read=False).first()
                if not existing:
                    db.session.add(Alert(student_id=student.id, alert_type="low_attendance",
                        message=f"Low attendance in {subject.name}: {record.percentage}% (below 75%)"))
                    summary["alerts_generated"] += 1
            summary["processed"] += 1
        except Exception as e:
            summary["errors"].append(f"Row {idx+2}: {str(e)}")

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        summary["errors"].append(f"Database commit failed: {str(e)}")
    return summary


def process_attendance_daily_excel(filepath, db, Student, Subject, Attendance, DailyAttendance, Alert):
    """Process date-wise attendance rows and keep aggregate attendance in sync.

    Expected columns:
    StudentID, Name, Date, Subject, Status, Reason, ClassesCount
    """
    summary = {"processed": 0, "errors": [], "created": 0, "updated": 0, "alerts_generated": 0}
    try:
        df = pd.read_excel(filepath)
    except Exception as e:
        summary["errors"].append(f"Failed to read Excel file: {str(e)}")
        return summary

    df.columns = df.columns.str.strip()
    required = ["StudentID", "Name", "Date", "Subject", "Status", "Reason", "ClassesCount"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        summary["errors"].append(f"Missing columns: {', '.join(missing)}")
        return summary

    touched_pairs = set()
    subject_cache = {s.id: s for s in Subject.query.all()}

    for idx, row in df.iterrows():
        try:
            sid = str(row["StudentID"]).strip()
            name = str(row["Name"]).strip()
            subj_name = str(row["Subject"]).strip()
            parsed_date = pd.to_datetime(row["Date"], errors="coerce")
            if pd.isna(parsed_date):
                raise ValueError("Invalid Date format. Use YYYY-MM-DD")
            attendance_date = parsed_date.date()
            status = _normalize_daily_status(row["Status"])
            if not status:
                raise ValueError("Status must be Present or Absent")
            reason = "" if pd.isna(row["Reason"]) else str(row["Reason"]).strip()
            if status == "Absent" and not reason:
                raise ValueError("Reason is required for Absent status")
            classes_count = _safe_classes_count(row["ClassesCount"])

            if not sid:
                raise ValueError("StudentID is required")
            if not subj_name:
                raise ValueError("Subject is required")

            student = Student.query.filter_by(student_id=sid).first()
            if not student:
                student = Student(student_id=sid, name=name or sid)
                db.session.add(student)
                db.session.flush()
                summary["created"] += 1

            subject = Subject.query.filter(
                (Subject.name == subj_name) | (Subject.code == subj_name)
            ).first()
            if not subject:
                raise ValueError(f"Subject '{subj_name}' not found")

            record = DailyAttendance.query.filter_by(
                student_id=student.id,
                subject_id=subject.id,
                date=attendance_date,
            ).first()
            if record:
                record.status = status
                record.reason = reason if reason else None
                record.classes_count = classes_count
                record.updated_at = datetime.utcnow()
                summary["updated"] += 1
            else:
                record = DailyAttendance(
                    student_id=student.id,
                    subject_id=subject.id,
                    date=attendance_date,
                    status=status,
                    reason=reason if reason else None,
                    classes_count=classes_count,
                )
                db.session.add(record)
                summary["created"] += 1

            touched_pairs.add((student.id, subject.id))
            summary["processed"] += 1
        except Exception as e:
            summary["errors"].append(f"Row {idx + 2}: {str(e)}")

    # Recompute aggregate attendance table from daily logs for affected student-subject pairs.
    for student_id, subject_id in touched_pairs:
        rows = DailyAttendance.query.filter_by(student_id=student_id, subject_id=subject_id).all()
        total_classes = sum((r.classes_count or 0) for r in rows)
        classes_attended = sum((r.classes_count or 0) for r in rows if r.status == "Present")

        aggregate = Attendance.query.filter_by(student_id=student_id, subject_id=subject_id).first()
        if aggregate:
            aggregate.total_classes = total_classes
            aggregate.classes_attended = classes_attended
            aggregate.compute_percentage()
            aggregate.updated_at = datetime.utcnow()
            summary["updated"] += 1
        else:
            aggregate = Attendance(
                student_id=student_id,
                subject_id=subject_id,
                total_classes=total_classes,
                classes_attended=classes_attended,
            )
            aggregate.compute_percentage()
            db.session.add(aggregate)
            summary["created"] += 1

        if aggregate.percentage < 70:
            subject = subject_cache.get(subject_id)
            subject_name = subject.name if subject else "subject"
            alert_message = f"Low attendance in {subject_name}: {aggregate.percentage}% (below 70%)"
            existing = Alert.query.filter_by(
                student_id=student_id,
                alert_type="low_attendance",
                is_read=False,
                message=alert_message,
            ).first()
            if not existing:
                db.session.add(
                    Alert(
                        student_id=student_id,
                        alert_type="low_attendance",
                        message=alert_message,
                    )
                )
                summary["alerts_generated"] += 1

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        summary["errors"].append(f"Database commit failed: {str(e)}")
    return summary


def process_marks_excel(filepath, db, Student, Subject, Marks, Backlog, Alert):
    """Process uploaded Excel with marks data.
    Expected columns: StudentID, Name, Subject, ExamType, MarksObtained, MaxMarks"""
    summary = {"processed": 0, "errors": [], "created": 0, "updated": 0, "alerts_generated": 0}
    try:
        df = pd.read_excel(filepath)
    except Exception as e:
        summary["errors"].append(f"Failed to read Excel file: {str(e)}")
        return summary

    df.columns = df.columns.str.strip()
    required = ["StudentID", "Name", "Subject", "ExamType", "MarksObtained", "MaxMarks"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        summary["errors"].append(f"Missing columns: {', '.join(missing)}")
        return summary

    for idx, row in df.iterrows():
        try:
            sid = str(row["StudentID"]).strip()
            name = str(row["Name"]).strip()
            subj_name = str(row["Subject"]).strip()
            exam_type = str(row["ExamType"]).strip()
            obtained = float(row["MarksObtained"])
            max_m = float(row["MaxMarks"])

            student = Student.query.filter_by(student_id=sid).first()
            if not student:
                student = Student(student_id=sid, name=name)
                db.session.add(student)
                db.session.flush()

            subject = Subject.query.filter(
                (Subject.name == subj_name) | (Subject.code == subj_name)
            ).first()
            if not subject:
                summary["errors"].append(f"Row {idx+2}: Subject '{subj_name}' not found")
                continue

            record = Marks.query.filter_by(student_id=student.id, subject_id=subject.id, exam_type=exam_type).first()
            if record:
                record.marks_obtained = obtained
                record.max_marks = max_m
                record.updated_at = datetime.utcnow()
                summary["updated"] += 1
            else:
                record = Marks(student_id=student.id, subject_id=subject.id,
                               exam_type=exam_type, marks_obtained=obtained, max_marks=max_m)
                db.session.add(record)
                summary["created"] += 1

            if max_m > 0 and (obtained / max_m) < 0.4:
                backlog = Backlog.query.filter_by(student_id=student.id, subject_id=subject.id).first()
                if not backlog:
                    db.session.add(Backlog(student_id=student.id, subject_id=subject.id, status="Active"))
                    db.session.add(Alert(student_id=student.id, alert_type="backlog_risk",
                        message=f"Risk of backlog in {subject.name}: {obtained}/{max_m} in {exam_type}"))
                    summary["alerts_generated"] += 1
            if max_m > 0 and (obtained / max_m) < 0.5:
                marks_alert = f"Low marks risk in {subject.name}: latest score below 50%."
                existing = Alert.query.filter_by(
                    student_id=student.id,
                    alert_type="marks_risk",
                    is_read=False,
                    message=marks_alert
                ).first()
                if not existing:
                    db.session.add(Alert(
                        student_id=student.id,
                        alert_type="marks_risk",
                        message=marks_alert
                    ))
                    summary["alerts_generated"] += 1
            summary["processed"] += 1
        except Exception as e:
            summary["errors"].append(f"Row {idx+2}: {str(e)}")

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        summary["errors"].append(f"Database commit failed: {str(e)}")
    return summary


def generate_student_pdf(student, predictions):
    """Generate a PDF report for a student. Returns BytesIO."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm,
                            topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("T", parent=styles["Title"], fontSize=18,
                                  spaceAfter=6, textColor=colors.HexColor("#1a1a2e"))
    heading_style = ParagraphStyle("H", parent=styles["Heading2"], fontSize=13,
                                    spaceAfter=8, spaceBefore=14, textColor=colors.HexColor("#6c63ff"))
    normal = styles["Normal"]
    elements = []

    elements.append(Paragraph("Smart Parents Monitoring System", title_style))
    elements.append(Paragraph("Student Performance Report", styles["Heading3"]))
    elements.append(HRFlowable(width="100%", color=colors.HexColor("#6c63ff"), thickness=2))
    elements.append(Spacer(1, 12))

    # Student Info
    elements.append(Paragraph("Student Information", heading_style))
    info = [["Student ID", student.student_id], ["Name", student.name],
            ["Department", student.department], ["Semester", str(student.semester)],
            ["Overall Attendance", f"{student.overall_attendance}%"],
            ["Active Backlogs", str(student.active_backlogs_count)],
            ["Risk Level", predictions.get("overall_risk", "N/A")]]
    t = Table(info, colWidths=[2.5*inch, 4*inch])
    t.setStyle(TableStyle([("BACKGROUND", (0,0), (0,-1), colors.HexColor("#f0f0f5")),
        ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 10),
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey), ("PADDING", (0,0), (-1,-1), 8)]))
    elements.append(t)
    elements.append(Spacer(1, 14))

    # Attendance
    elements.append(Paragraph("Attendance Summary", heading_style))
    att = [["Subject", "Total", "Attended", "Percentage", "Risk"]]
    for s in predictions.get("subjects", []):
        att.append([s["name"], str(s["total_classes"]), str(s["classes_attended"]),
                    f"{s['attendance_pct']}%", s["risk"]])
    if len(att) > 1:
        at = Table(att, colWidths=[2.2*inch, 1*inch, 1*inch, 1.1*inch, 1*inch])
        st = [("BACKGROUND",(0,0),(-1,0),colors.HexColor("#6c63ff")),
              ("TEXTCOLOR",(0,0),(-1,0),colors.white),
              ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),9),
              ("GRID",(0,0),(-1,-1),0.5,colors.grey),("PADDING",(0,0),(-1,-1),6),
              ("ALIGN",(1,0),(-1,-1),"CENTER")]
        for i in range(1, len(att)):
            risk = att[i][4]
            c = colors.red if risk == "High" else colors.orange if risk == "Medium" else colors.green
            st.append(("TEXTCOLOR", (4,i), (4,i), c))
        at.setStyle(TableStyle(st))
        elements.append(at)
    elements.append(Spacer(1, 14))

    # Marks
    elements.append(Paragraph("Marks Summary", heading_style))
    mk = [["Subject", "Exam", "Obtained", "Max", "%"]]
    for s in predictions.get("subjects", []):
        for m in s.get("marks", []):
            mk.append([s["name"], m["exam_type"], str(m["obtained"]), str(m["max"]), f"{m['percentage']}%"])
    if len(mk) > 1:
        mt = Table(mk, colWidths=[2*inch, 1.2*inch, 1*inch, 1*inch, 1.1*inch])
        mt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#6c63ff")),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("FONTSIZE",(0,0),(-1,-1),9),("GRID",(0,0),(-1,-1),0.5,colors.grey),
            ("PADDING",(0,0),(-1,-1),6),("ALIGN",(2,0),(-1,-1),"CENTER")]))
        elements.append(mt)
    elements.append(Spacer(1, 14))

    # Predictions
    elements.append(Paragraph("ML Predictions &amp; Suggestions", heading_style))
    for s in predictions.get("subjects", []):
        elements.append(Paragraph(f"<b>{s['name']}</b>: {s['message']}", normal))
        elements.append(Spacer(1, 4))
    elements.append(Spacer(1, 20))

    elements.append(HRFlowable(width="100%", color=colors.grey, thickness=1))
    footer = ParagraphStyle("F", parent=normal, fontSize=8, textColor=colors.grey, alignment=TA_CENTER)
    elements.append(Paragraph(
        f"Generated on {datetime.utcnow().strftime('%d %B %Y, %H:%M UTC')} | SPMS", footer))

    doc.build(elements)
    buffer.seek(0)
    return buffer
