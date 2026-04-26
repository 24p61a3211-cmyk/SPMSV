"""Seed script to populate the database with sample data for testing."""

import random
from app import app, db
from models import User, Student, Subject, Attendance, Marks, Backlog, Alert

SUBJECTS = [
    ("CS301", "Discrete Mathematics", "Theory"),
    ("CS302", "Machine Learning", "Theory"),
    ("CS303", "Operating Systems", "Theory"),
    ("CS304", "Business Systems Analysis", "Theory"),
    ("CS305", "Data Structures", "Theory"),
    ("CS306", "Java Lab", "Lab"),
    ("CS307", "Python Lab", "Lab"),
]

STUDENT_NAMES = [
    "Arun Kumar", "Priya Sharma", "Rahul Verma", "Sneha Reddy", "Vikram Singh",
    "Divya Patel", "Karthik Nair", "Anjali Gupta", "Suresh Babu", "Meena Iyer",
    "Rohit Joshi", "Kavya Menon", "Ajay Yadav", "Neha Kulkarni", "Sanjay Mishra",
    "Pooja Desai", "Amit Chauhan", "Lakshmi Rao", "Ravi Shankar", "Deepika Jain",
    "Manoj Kumar", "Swathi Pillai", "Harish Gowda", "Fatima Begum", "Arjun Mehta",
    "Nandini Das", "Prakash Shetty", "Ananya Bose", "Vijay Malhotra", "Ritu Agarwal",
    "Ganesh Prasad", "Sarika Thakur", "Naveen Raj", "Bhavana Hegde", "Tarun Saxena",
]


def seed():
    with app.app_context():
        db.drop_all()
        db.create_all()
        print("Database tables created.")

        # Create admin
        admin = User(username="admin", name="Prof. Rajesh Kumar", role="admin",
                      email="admin@spms.edu")
        admin.set_password("admin123")
        db.session.add(admin)
        print("Admin account created: admin / admin123")

        # Create subjects
        subjects = []
        for code, name, stype in SUBJECTS:
            s = Subject(code=code, name=name, subject_type=stype)
            db.session.add(s)
            subjects.append(s)
        db.session.flush()
        print(f"Created {len(subjects)} subjects.")

        # Create 35 students
        print(f"Generating {len(STUDENT_NAMES)} students...")
        for i, sname in enumerate(STUDENT_NAMES, start=1):
            sid = f"CSBS{str(i).zfill(3)}"

            student = Student(student_id=sid, name=sname, department="CSBS", semester=3)
            db.session.add(student)
            db.session.flush()

            # Create parent account
            parent = User(
                username=f"parent{i}", name=f"Parent of {sname}",
                role="parent", phone=f"98765{10000 + i}",
                email=f"parent{i}@example.com", student_id=student.id
            )
            parent.set_password(f"parent{i}")
            db.session.add(parent)

            # Attendance profile:  1-8 Low, 9-18 Borderline, 19-35 Good
            if i <= 8:
                att_range = (40, 68)
            elif i <= 18:
                att_range = (65, 78)
            else:
                att_range = (76, 98)

            for subj in subjects:
                total = random.randint(80, 100)
                attended = random.randint(int(total * att_range[0] / 100),
                                          int(total * att_range[1] / 100))
                att = Attendance(student_id=student.id, subject_id=subj.id,
                                 total_classes=total, classes_attended=attended)
                att.compute_percentage()
                db.session.add(att)

                for exam in ["Internal 1", "Internal 2", "Semester"]:
                    max_m = 50 if "Internal" in exam else 100
                    perf = attended / total
                    obtained = round(random.uniform(max_m * max(0, perf - 0.2),
                                                     max_m * min(1, perf + 0.1)), 1)
                    obtained = max(0, min(max_m, obtained))
                    db.session.add(Marks(student_id=student.id, subject_id=subj.id,
                                         exam_type=exam, marks_obtained=obtained,
                                         max_marks=max_m))
                    if exam == "Semester" and (obtained / max_m) < 0.4:
                        db.session.add(Backlog(student_id=student.id,
                                               subject_id=subj.id, status="Active"))

            # Generate alerts for at-risk students
            if i <= 8:
                db.session.add(Alert(student_id=student.id, alert_type="low_attendance",
                    message=f"Low attendance detected for {sname}. Please ensure regular attendance."))

            print(f"  [{i}/{len(STUDENT_NAMES)}] {sid} — {sname}")

        db.session.commit()
        print(f"\nSeeding complete! {len(STUDENT_NAMES)} students added.")
        print("\n--- Login Credentials ---")
        print("Admin:   admin / admin123")
        print("Parents: parent1 / parent1, parent2 / parent2, ... parent35 / parent35")
        print("\nRun: python app.py")


if __name__ == "__main__":
    seed()
