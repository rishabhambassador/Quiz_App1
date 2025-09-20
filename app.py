from flask import Flask, request, redirect, session, render_template_string, Response
import sqlite3
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import base64
import difflib

# ReportLab for PDF
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
app.secret_key = "supersecret"

# Teacher passkeys
TEACHER_PASSKEYS = {
    "teacher1": "math123",
    "teacher2": "science456",
    "admin": "supersecret"
}

# ---------- Database ----------
def get_db():
    conn = sqlite3.connect("quiz.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS students (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE,
                        password TEXT,
                        grade TEXT,
                        gender TEXT,
                        class_name TEXT
                    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS questions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        text TEXT,
                        correct TEXT,
                        option_a TEXT,
                        option_b TEXT,
                        option_c TEXT,
                        option_d TEXT,
                        subject TEXT,
                        qtype TEXT,
                        grade TEXT
                    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS attempts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        student_id INTEGER,
                        question_id INTEGER,
                        student_answer TEXT,
                        correct INTEGER
                    )""")
    conn.commit()
    conn.close()

init_db()

# ---------- Helper ----------
def render_page(content):
    base = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Ambassador Quiz App</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f8f9fa;
                margin: 0;
                padding: 0;
            }}
            .container {{
                width: 80%;
                margin: auto;
                padding: 20px;
                text-align: center;
            }}
            .btn {{
                background: #4CAF50;
                color: white;
                border: none;
                padding: 10px 20px;
                margin: 5px;
                border-radius: 5px;
                cursor: pointer;
            }}
            .btn:hover {{
                background: #45a049;
            }}
            input, select {{
                padding: 8px;
                margin: 5px;
                width: 60%;
                border-radius: 5px;
                border: 1px solid #ccc;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            {content}
        </div>
    </body>
    </html>
    """
    return render_template_string(base)

def similarity_ratio(ans, correct):
    return difflib.SequenceMatcher(None, ans.lower().strip(), correct.lower().strip()).ratio()

# ---------- Home ----------
@app.route("/")
def home():
    return render_page("""
        <h1>Welcome to Ambassador Quiz App</h1>
        <a href='/signup/student'><button class='btn'>Student Sign Up</button></a>
        <a href='/login/student'><button class='btn'>Student Login</button></a>
        <a href='/login/teacher'><button class='btn'>Teacher Login</button></a>
    """)

# ---------- Student Signup ----------
@app.route("/signup/student", methods=["GET", "POST"])
def signup_student():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        grade = request.form["grade"]
        gender = request.form["gender"]
        class_name = request.form["class_name"]
        try:
            conn = get_db()
            conn.execute("INSERT INTO students(username, password, grade, gender, class_name) VALUES (?, ?, ?, ?, ?)",
                         (username, password, grade, gender, class_name))
            conn.commit()
            conn.close()
            return redirect("/login/student")
        except:
            return render_page("<p>⚠️ Username already exists!</p><a href='/signup/student'><button class='btn'>Back</button></a>")
    return render_page("""
        <h2>Student Signup - Ambassador Quiz App</h2>
        <form method='post'>
            <input name='username' placeholder='Username' required><br>
            <input type='password' name='password' placeholder='Password' required><br>
            <input name='grade' placeholder='Grade' required><br>
            <select name='gender' required>
                <option value=''>Select Gender</option>
                <option value='Male'>Male</option>
                <option value='Female'>Female</option>
                <option value='Other'>Other</option>
            </select><br>
            <input name='class_name' placeholder='Class' required><br>
            <button type='submit' class='btn'>Sign Up</button>
        </form>
    """)

# ---------- Student Login ----------
@app.route("/login/student", methods=["GET", "POST"])
def login_student():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db()
        student = conn.execute("SELECT * FROM students WHERE username=? AND password=?",
                               (username, password)).fetchone()
        conn.close()
        if student:
            session["student_id"] = student["id"]
            session["grade"] = student["grade"]
            return redirect("/quiz")
        else:
            return render_page("""
                <p>❌ Invalid student credentials!</p>
                <a href='/login/student'><button class='btn'>Back to Login</button></a>
            """)
    return render_page("""
        <h2>Student Login - Ambassador Quiz App</h2>
        <form method='post'>
            <input name='username' placeholder='Username'><br>
            <input type='password' name='password' placeholder='Password'><br>
            <button type='submit' class='btn'>Login</button>
        </form>
    """)

# ---------- Teacher Login ----------
@app.route("/login/teacher", methods=["GET", "POST"])
def login_teacher():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if username in TEACHER_PASSKEYS and TEACHER_PASSKEYS[username] == password:
            session["teacher"] = username
            return redirect("/teacher/dashboard")
        else:
            return render_page("""
                <p>❌ Invalid teacher credentials!</p>
                <a href='/login/teacher'><button class='btn'>Back to Login</button></a>
            """)
    return render_page("""
        <h2>Teacher Login - Ambassador Quiz App</h2>
        <form method='post'>
            <input name='username' placeholder='Username'><br>
            <input type='password' name='password' placeholder='Passkey'><br>
            <button type='submit' class='btn'>Login</button>
        </form>
    """)

# ---------- Quiz ----------
@app.route("/quiz", methods=["GET", "POST"])
def quiz():
    if "student_id" not in session:
        return redirect("/login/student")

    grade = session.get("grade", "")
    conn = get_db()
    questions = conn.execute("SELECT * FROM questions WHERE grade=?", (grade,)).fetchall()
    conn.close()

    if request.method == "POST":
        student_id = session["student_id"]
        for q in questions:
            ans = request.form.get(str(q["id"]))
            if ans is None:
                continue
            if (q["qtype"] or "").lower() == "mcq":
                correct = 1 if ans.strip() == (q["correct"] or "").strip() else 0
            else:
                sim = similarity_ratio(ans, q["correct"] or "")
                correct = 1 if sim > 0.75 else 0
            conn = get_db()
            conn.execute("INSERT INTO attempts(student_id, question_id, student_answer, correct) VALUES (?, ?, ?, ?)",
                         (student_id, q["id"], ans, correct))
            conn.commit()
            conn.close()
        return render_page("""
            <h3>✅ Quiz submitted!</h3>
            <a href='/quiz'><button class='btn'>Back to Quiz</button></a>
            <a href='/'><button class='btn'>Back to Dashboard</button></a>
        """)

    q_html = "<h2>Quiz - Ambassador Quiz App</h2><form method='post'>"
    for q in questions:
        q_html += f"<p><b>{q['text']}</b></p>"
        if (q["qtype"] or "").lower() == "mcq":
            for opt in ["a", "b", "c", "d"]:
                val = q[f"option_{opt}"]
                if val:
                    q_html += f"<input type='radio' name='{q['id']}' value='{val}'> {val}<br>"
        else:
            q_html += f"<input name='{q['id']}' placeholder='Your Answer'><br>"
    q_html += "<button type='submit' class='btn'>Submit</button></form>"
    return render_page(q_html)

# ---------- Add Question ----------
@app.route("/teacher/add_question", methods=["GET", "POST"])
def add_question():
    if "teacher" not in session:
        return redirect("/login/teacher")

    if request.method == "POST":
        text = request.form["text"]
        correct = request.form["correct"]
        subject = request.form["subject"]
        qtype = request.form["qtype"]
        grade = request.form["grade"]
        a = request.form.get("option_a")
        b = request.form.get("option_b")
        c = request.form.get("option_c")
        d = request.form.get("option_d")
        conn = get_db()
        conn.execute("""INSERT INTO questions(text, correct, option_a, option_b, option_c, option_d, subject, qtype, grade)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                     (text, correct, a, b, c, d, subject, qtype, grade))
        conn.commit()
        conn.close()
        return render_page("""
            <p>✅ Question added!</p>
            <a href='/teacher/add_question'><button class='btn'>Add Another</button></a>
            <a href='/teacher/dashboard'><button class='btn'>Back to Dashboard</button></a>
        """)
    return render_page("""
        <h2>Add Question - Ambassador Quiz App</h2>
        <form method='post'>
            <input name='text' placeholder='Question Text' required><br>
            <input name='correct' placeholder='Correct Answer' required><br>
            <input name='subject' placeholder='Subject' required><br>
            <select name='qtype' required>
                <option value='mcq'>MCQ</option>
                <option value='short'>Subjective</option>
            </select><br>
            <input name='grade' placeholder='Grade' required><br>
            <input name='option_a' placeholder='Option A'><br>
            <input name='option_b' placeholder='Option B'><br>
            <input name='option_c' placeholder='Option C'><br>
            <input name='option_d' placeholder='Option D'><br>
            <button type='submit' class='btn'>Add Question</button>
        </form>
    """)

# ---------- Teacher Dashboard ----------
@app.route("/teacher/dashboard")
def teacher_dashboard():
    if "teacher" not in session:
        return redirect("/login/teacher")

    conn = get_db()
    data = conn.execute("""SELECT s.grade, SUM(a.correct) as correct_count, COUNT(a.id) as total
                           FROM attempts a
                           JOIN students s ON a.student_id = s.id
                           GROUP BY s.grade""").fetchall()
    conn.close()

    grades = [row["grade"] for row in data]
    scores = [(row["correct_count"] / row["total"]) * 100 for row in data] if data else []

    plt.figure(figsize=(5,3))
    plt.bar(grades, scores, color="skyblue")
    plt.ylim(0, 100)
    plt.ylabel("Avg Score (%)")
    plt.title("Ambassador Quiz App - Performance by Grade")

    img = io.BytesIO()
    plt.savefig(img, format="png")
    img.seek(0)
    graph_url = base64.b64encode(img.getvalue()).decode()
    plt.close()

    return render_page(f"""
        <h2>📊 Teacher Dashboard - Ambassador Quiz App</h2>
        <img src='data:image/png;base64,{graph_url}'/>
        <br>
        <a href='/teacher/add_question'><button class='btn'>➕ Add Question</button></a>
        <a href='/teacher/download_data'><button class='btn'>⬇️ Download Report (PDF)</button></a>
        <a href='/logout'><button class='btn'>Logout</button></a>
    """)

# ---------- Teacher PDF Report ----------
@app.route("/teacher/download_data")
def download_data():
    if "teacher" not in session:
        return redirect("/login/teacher")

    conn = get_db()
    data = conn.execute("""
        SELECT s.username, s.grade, s.gender, s.class_name,
               q.subject, q.text AS question, a.student_answer, a.correct
        FROM attempts a
        JOIN students s ON a.student_id = s.id
        JOIN questions q ON a.question_id = q.id
        ORDER BY s.grade, s.username
    """).fetchall()
    conn.close()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()

    elements.append(Paragraph("📊 Ambassador Quiz App - Student Performance Report", styles["Title"]))
    elements.append(Spacer(1, 20))

    # Group data by grade
    grade_groups = {}
    for row in data:
        grade = row["grade"]
        if grade not in grade_groups:
            grade_groups[grade] = []
        grade_groups[grade].append(row)

    for grade, rows in grade_groups.items():
        elements.append(Paragraph(f"Grade {grade}", styles["Heading2"]))
        elements.append(Spacer(1, 12))

        table_data = [["Username", "Gender", "Class", "Subject", "Question", "Answer", "Correct"]]
        for row in rows:
            table_data.append([
                row["username"], row["gender"], row["class_name"],
                row["subject"], row["question"], row["student_answer"],
                "✅" if row["correct"] else "❌"
            ])

        table = Table(table_data, repeatRows=1, colWidths=[70, 50, 50, 70, 150, 100, 50])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4CAF50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey])
        ]))

        elements.append(table)
        elements.append(Spacer(1, 24))

    doc.build(elements)
    buffer.seek(0)

    return Response(buffer,
                    mimetype="application/pdf",
                    headers={"Content-Disposition": "attachment;filename=ambassador_quiz_report.pdf"})

# ---------- Logout ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------- Run ----------
if __name__ == "__main__":
    print("🚀 Ambassador Quiz App running at http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)

