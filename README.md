# Smart Parents Monitoring System (SPMS)

![SPMS Logo](static/images/logo.png)

A comprehensive Python Flask web application designed for the CSBS department to help parents monitor their child's academic performance, attendance, and behavioral progress in real-time. The system bridges the communication gap between the college and parents, featuring an ML-powered early warning system for low attendance and potential academic risks.

## 🚀 Features

### 1. Admin Portal (Teachers)
- **Data Upload:** Easily upload Excel (`.xlsx`) files containing student attendance and marks.
- **Student Management:** View the entire student directory, search for specific students, and add new students manually.
- **Comprehensive Dashboards:** View overall department statistics, active alerts, and individual student profiles.
- **Report Generation:** Generate and download PDF reports of student performance.
- **Automated Alerts:** The system automatically flags students with low attendance (<75%) or a high risk of backlogs.

### 2. Parent Portal
- **Real-Time Monitoring:** Parents can log in to view their child's attendance percentage, marks, and active backlogs.
- **Interactive Analytics:** Visual breakdowns of attendance and marks using Chart.js (Bar charts, Doughnut charts, etc.).
- **ML Predictions & Suggestions:** The system analyzes attendance and provides actionable advice (e.g., *"To stay on the safe side and avoid detention, the student must attend the next 12 classes consecutively"*).

## 🛠️ Tech Stack

- **Backend:** Python, Flask, Flask-SQLAlchemy, Flask-Login
- **Frontend:** HTML5, CSS3 (Premium Glassmorphism Design), Bootstrap 5.3
- **Database:** SQLite
- **Machine Learning / Logic:** Scikit-learn ready, custom Python algorithms for risk prediction
- **Data Processing:** Pandas (for Excel processing), ReportLab (for PDF generation)
- **Data Visualization:** Chart.js

---

## ⚙️ How to Execute / Run the Project

### Prerequisites
**Important Note on Python Version:** Please ensure you are using a stable release of Python (e.g., **Python 3.11** or **Python 3.12**). Experimental versions like Python 3.14 may cause errors when installing libraries like `pandas` due to missing pre-built wheels.

### Step 1: Install Dependencies
Open your terminal or command prompt, navigate to the project folder, and run:
```bash
pip install -r requirements.txt
```
*(Note: If you face errors, ensure your Python version is stable as mentioned above).*

### Step 2: Seed the Database
To populate the database with 35 realistic sample students, subjects, and parent accounts, run:
```bash
python seed_data.py
```
This will create the SQLite database (`instance/spms.db`) automatically.

### Step 3: Run the Application
Start the Flask development server by running:
```bash
python app.py
```

### Step 4: Access the Portal
Open your web browser and go to:
**http://localhost:5000**

---

## 🔑 Login Credentials

The `seed_data.py` script automatically creates the following accounts for testing:

**Admin (Teacher) Account:**
- **Username:** `admin`
- **Password:** `admin123`

**Parent Accounts:**
There are 35 parent accounts linked to the 35 sample students. The login format is simple:
- **Parent 1:** Username: `parent1` | Password: `parent1` (Student: Arun Kumar)
- **Parent 2:** Username: `parent2` | Password: `parent2` (Student: Priya Sharma)
- ... up to `parent35` / `parent35`.

*Tip: Students 1 through 8 are generated with intentionally low attendance. Logging in as `parent1` through `parent8` is the best way to test the system's early warning alerts and detention predictions!*

---

## 📁 Project Structure Highlights
- `app.py`: The main Flask application containing all routes.
- `models.py`: Database schema and relationships.
- `ml_model.py`: Algorithms for attendance predictions and risk calculations.
- `utils.py`: Helper functions for processing Excel uploads and generating PDFs.
- `static/css/style.css`: The custom UI design system.
