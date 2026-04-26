"""Machine Learning module for attendance risk prediction and analysis."""

import math


def calculate_attendance_percentage(attended, total):
    """Calculate attendance percentage."""
    if total == 0:
        return 0.0
    return round((attended / total) * 100, 2)


def classify_risk(percentage, threshold=75):
    """
    Classify attendance risk level.
    - Low: >= threshold (75%)
    - Medium: >= 60% and < threshold
    - High: < 60%
    """
    if percentage >= threshold:
        return "Low"
    elif percentage >= 60:
        return "Medium"
    else:
        return "High"


def calculate_required_days(attended, total, threshold=75):
    """
    Calculate the number of consecutive classes a student must attend
    to reach the threshold attendance percentage.

    Formula:
        We need (attended + x) / (total + x) >= threshold/100
        Solving: x >= (threshold * total - 100 * attended) / (100 - threshold)

    Returns:
        Number of required days (0 if already above threshold, -1 if impossible within reason)
    """
    current_pct = calculate_attendance_percentage(attended, total)
    if current_pct >= threshold:
        return 0

    threshold_fraction = threshold / 100.0
    denominator = 1 - threshold_fraction  # 0.25 for 75%

    if denominator <= 0:
        return -1

    required = (threshold_fraction * total - attended) / denominator
    required = math.ceil(required)

    # Cap at a reasonable number (e.g., 200 days)
    if required > 200:
        return -1

    return max(0, required)


def get_risk_color(risk_level):
    """Return CSS color class for risk level."""
    colors = {
        "Low": "success",
        "Medium": "warning",
        "High": "danger",
    }
    return colors.get(risk_level, "secondary")


def predict_student_risk(student):
    """
    Analyze a student's attendance and marks to produce risk predictions.

    Returns a dict with overall risk, per-subject analysis, and suggestions.
    """
    from models import Subject

    attendance_records = student.attendances.all()
    marks_records = student.marks.all()
    backlogs = student.backlogs.filter_by(status="Active").all()

    subject_analysis = []
    risk_scores = []

    for record in attendance_records:
        subject = Subject.query.get(record.subject_id)
        if not subject:
            continue

        pct = calculate_attendance_percentage(record.classes_attended, record.total_classes)
        risk = classify_risk(pct)
        days_needed = calculate_required_days(record.classes_attended, record.total_classes)

        # Build suggestion message
        if days_needed == 0:
            message = f"Attendance is safe at {pct}%. Keep it up to avoid detention."
        elif days_needed == -1:
            message = f"Critical risk! Attendance is only {pct}%. It is mathematically difficult to reach 75%. Please contact the teacher immediately."
        else:
            message = f"To stay on the safe side and avoid detention, the student must attend the next {days_needed} classes consecutively to reach the 75% threshold."

        subject_data = {
            "name": subject.name,
            "code": subject.code,
            "type": subject.subject_type,
            "total_classes": record.total_classes,
            "classes_attended": record.classes_attended,
            "attendance_pct": pct,
            "risk": risk,
            "risk_color": get_risk_color(risk),
            "days_needed": days_needed,
            "message": message,
        }

        # Add marks info if available
        subject_marks = [m for m in marks_records if m.subject_id == record.subject_id]
        if subject_marks:
            subject_data["marks"] = [
                {
                    "exam_type": m.exam_type,
                    "obtained": m.marks_obtained,
                    "max": m.max_marks,
                    "percentage": m.percentage,
                }
                for m in subject_marks
            ]

        subject_analysis.append(subject_data)

        # Score: High=3, Medium=2, Low=1
        risk_scores.append({"High": 3, "Medium": 2, "Low": 1}.get(risk, 1))

    # Overall risk
    if risk_scores:
        avg_score = sum(risk_scores) / len(risk_scores)
        if avg_score >= 2.5:
            overall_risk = "High"
        elif avg_score >= 1.5:
            overall_risk = "Medium"
        else:
            overall_risk = "Low"
    else:
        overall_risk = "Low"

    # Backlog risk
    backlog_count = len(backlogs)
    if backlog_count >= 3:
        backlog_risk = "High"
    elif backlog_count >= 1:
        backlog_risk = "Medium"
    else:
        backlog_risk = "Low"

    # Overall attendance
    overall_attendance = student.overall_attendance

    return {
        "student_id": student.student_id,
        "student_name": student.name,
        "overall_risk": overall_risk,
        "overall_risk_color": get_risk_color(overall_risk),
        "overall_attendance": overall_attendance,
        "backlog_risk": backlog_risk,
        "backlog_risk_color": get_risk_color(backlog_risk),
        "backlog_count": backlog_count,
        "subjects": subject_analysis,
        "total_subjects": len(subject_analysis),
        "high_risk_count": risk_scores.count(3),
        "medium_risk_count": risk_scores.count(2),
        "low_risk_count": risk_scores.count(1),
    }
