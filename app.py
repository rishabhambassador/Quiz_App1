from flask import Flask, request, redirect, session, render_template_string, send_file
import sqlite3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import io
import base64
from fpdf import FPDF

app = Flask(__name__)
app.secret_key = "supersecret"

# ✅ Teacher passkeys
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
                        userid TEXT UNIQUE,
                        password TEXT,
                        grade TEXT,
                        class TEXT,
                        gender TEXT
                    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS quizzes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT,
                        grade TEXT,
                        subject TEXT,
                        passage TEXT
                    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS questions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        quiz_id INTEGER,
                        text TEXT,
                        correct TEXT,
                        option_a TEXT,
                        option_b TEXT,
                        option_c TEXT,
                        option_d TEXT,
                        qtype TEXT,
                        image BLOB
                    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS attempts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        student_id INTEGER,
                        quiz_id INTEGER,
                        question_id INTEGER,
                        student_answer TEXT,
                        correct INTEGER
                    )""")
    conn.commit()
    conn.close()

init_db()

# ---------- Helper: Base Layout ----------
def render_page(content):
    base = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Ambassador Quiz App</title>
        <style>
            body {{ font-family: Arial, sans-serif; background:#f8f9fa; margin:0; padding:0; }}
            header {{ background:#007BFF; color:white; padding:15px; text-align:center; }}
            nav a {{ margin:0 10px; color:white; text-decoration:none; }}
            .container {{ padding:20px; }}
            .card {{ background:white; padding:20px; margin:15px auto; border-radius:8px; box-shadow:0 0 5px rgba(0,0,0,0.1); width:80%; }}
            button {{ padding:8px 15px; margin:5px; border:none; border-radius:5px; background:#007BFF; color:white; cursor:pointer; }}
            button:hover {{ background:#0056b3; }}
            input, select, textarea {{ padding:5px; margin:5px 0; width:100%; }}
        </style>
    </head>
    <body>
        <header>
            <h1>Ambassador Quiz App</h1>
            <nav>
                <a href='/'>Home</a>
                <a href='/logout'>Logout</a>
            </nav>
        </header>
        <div class="container">
            {content}
        </div>
    </body>
    </html>
    """
    return render_template_string(base)

# ---------- Similarity Algorithm ----------
def check_similarity(ans, correct):
    ans_words = set(ans.lower().split())
    correct_words = set(correct.lower().split())
    if not correct_words:
        return 0
    overlap = len(ans_words & correct_words)
    return overlap / len(correct_words)

# ---------- Home ----------
@app.route("/")
def home():
    return render_page("""
        <div class='card'>
            <h2>Welcome</h2>
            <a href='/signup/student'><button>Student Sign Up</button></a>
            <a href='/login/student'><button>Student Login</button></a>
            <a href='/login/teacher'><button>Teacher Login</button></a>
        </div>
    """)

# ---------- Student Signup ----------
@app.route("/signup/student", methods=["GET", "POST"])
def signup_student():
    if request.method == "POST":
        userid = request.form["userid"]
        password = request.form["password"]
        grade = request.form["grade"]
        class_ = request.form["class"]
        gender = request.form["gender"]
        try:
            conn = get_db()
            conn.execute("INSERT INTO students(userid, password, grade, class, gender) VALUES (?, ?, ?, ?, ?)",
                         (userid, password, grade, class_, gender))
            conn.commit()
            conn.close()
            return redirect("/login/student")
        except:
            return render_page("<p>User ID already exists!</p><a href='/signup/student'><button>Back</button></a>")
    return render_page("""
        <div class='card'>
        <h2>Student Sign Up</h2>
        <form method='post'>
            User ID: <input name='userid' required><br>
            Password: <input type='password' name='password' required><br>
            Grade: <input name='grade' required><br>
            Class: <input name='class' required><br>
            Gender: 
            <select name='gender'>
                <option>Male</option>
                <option>Female</option>
                <option>Other</option>
            </select><br>
            <button type='submit'>Sign Up</button>
        </form>
        </div>
    """)

# ---------- Student Login ----------
@app.route("/login/student", methods=["GET", "POST"])
def login_student():
    if request.method == "POST":
        userid = request.form["userid"]
        password = request.form["password"]
        conn = get_db()
        student = conn.execute("SELECT * FROM students WHERE userid=? AND password=?", (userid, password)).fetchone()
        conn.close()
        if student:
            session["student_id"] = student["id"]
            session["grade"] = student["grade"]
            return redirect("/quiz/select")
        else:
            return render_page("<p>Invalid credentials!</p><a href='/login/student'><button>Back to Login</button></a>")
    return render_page("""
        <div class='card'>
        <h2>Student Login</h2>
        <form method='post'>
            User ID: <input name='userid'><br>
            Password: <input type='password' name='password'><br>
            <button type='submit'>Login</button>
        </form>
        </div>
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
            return render_page("<p>Invalid teacher credentials!</p><a href='/login/teacher'><button>Back</button></a>")
    return render_page("""
        <div class='card'>
        <h2>Teacher Login</h2>
        <form method='post'>
            Username: <input name='username'><br>
            Passkey: <input type='password' name='password'><br>
            <button type='submit'>Login</button>
        </form>
        </div>
    """)

# ---------- Quiz Selection ----------
@app.route("/quiz/select")
def quiz_select():
    if "student_id" not in session:
        return redirect("/login/student")
    grade = session["grade"]
    conn = get_db()
    quizzes = conn.execute("SELECT * FROM quizzes WHERE grade=?", (grade,)).fetchall()
    conn.close()
    html = "<div class='card'><h2>Select Quiz</h2>"
    for q in quizzes:
        html += f"<p><b>{q['title']}</b> - {q['subject']} <a href='/quiz/{q['id']}'><button>Start</button></a></p>"
    html += "</div>"
    return render_page(html)

# ---------- Quiz Attempt ----------
@app.route("/quiz/<int:quiz_id>", methods=["GET", "POST"])
def quiz(quiz_id):
    if "student_id" not in session:
        return redirect("/login/student")
    conn = get_db()
    quiz = conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    questions = conn.execute("SELECT * FROM questions WHERE quiz_id=?", (quiz_id,)).fetchall()
    conn.close()
    if request.method == "POST":
        student_id = session["student_id"]
        conn = get_db()
        for q in questions:
            ans = request.form.get(str(q["id"]))
            if not ans:
                continue
            if q["qtype"] == "mcq":
                correct = 1 if ans == q["correct"] else 0
            else:
                sim = check_similarity(ans, q["correct"])
                correct = 1 if sim >= 0.6 else 0
            conn.execute("INSERT INTO attempts(student_id, quiz_id, question_id, student_answer, correct) VALUES (?, ?, ?, ?, ?)",
                         (student_id, quiz_id, q["id"], ans, correct))
        conn.commit()
        conn.close()
        return render_page("<p>Quiz submitted!</p><a href='/quiz/select'><button>Back to Quizzes</button></a>")
    q_html = f"<div class='card'><h2>{quiz['title']}</h2><p>{quiz['passage']}</p><form method='post'>"
    for q in questions:
        q_html += f"<p>{q['text']}</p>"
        if q["qtype"] == "mcq":
            for opt in ["a", "b", "c", "d"]:
                val = q[f"option_{opt}"]
                if val:
                    q_html += f"<input type='radio' name='{q['id']}' value='{val}'> {val}<br>"
        else:
            q_html += f"<textarea name='{q['id']}' rows='3'></textarea><br>"
    q_html += "<button type='submit'>Submit Quiz</button></form></div>"
    return render_page(q_html)

# ---------- Teacher Dashboard ----------
@app.route("/teacher/dashboard")
def teacher_dashboard():
    if "teacher" not in session:
        return redirect("/login/teacher")
    conn = get_db()
    data = conn.execute("""SELECT s.grade, COUNT(a.id) as attempts, SUM(a.correct) as correct_count
                           FROM attempts a
                           JOIN students s ON a.student_id = s.id
                           GROUP BY s.grade""").fetchall()
    conn.close()
    grades = [row["grade"] for row in data]
    scores = [(row["correct_count"]/row["attempts"])*100 if row["attempts"] else 0 for row in data]
    plt.figure(figsize=(5,3))
    plt.bar(grades, scores, color="skyblue")
    plt.ylim(0, 100)
    plt.ylabel("Avg Score (%)")
    plt.title("Performance by Grade")
    img = io.BytesIO()
    plt.savefig(img, format="png")
    img.seek(0)
    graph_url = base64.b64encode(img.getvalue()).decode()
    plt.close()
    return render_page(f"""
        <div class='card'>
        <h2>Teacher Dashboard</h2>
        <a href='/teacher/create_quiz'><button>Create Quiz</button></a>
        <a href='/teacher/delete_quiz'><button>Delete Quiz</button></a>
        <a href='/teacher/reset_db'><button style='background:red;'>Reset Database</button></a>
        <br><br>
        <img src='data:image/png;base64,{graph_url}'/>
        </div>
    """)

# ---------- Create Quiz ----------
@app.route("/teacher/create_quiz", methods=["GET", "POST"])
def create_quiz():
    if "teacher" not in session:
        return redirect("/login/teacher")
    if request.method == "POST":
        title = request.form["title"]
        grade = request.form["grade"]
        subject = request.form["subject"]
        passage = request.form["passage"]
        conn = get_db()
        conn.execute("INSERT INTO quizzes(title, grade, subject, passage) VALUES (?, ?, ?, ?)",
                     (title, grade, subject, passage))
        quiz_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
        conn.commit()
        conn.close()
        return redirect(f"/teacher/add_question/{quiz_id}")
    return render_page("""
        <div class='card'>
        <h2>Create Quiz</h2>
        <form method='post'>
            Title: <input name='title' required><br>
            Grade: <input name='grade' required><br>
            Subject: <input name='subject' required><br>
            Passage (if any): <textarea name='passage'></textarea><br>
            <button type='submit'>Create</button>
        </form>
        </div>
    """)

# ---------- Add Question ----------
@app.route("/teacher/add_question/<int:quiz_id>", methods=["GET", "POST"])
def add_question(quiz_id):
    if "teacher" not in session:
        return redirect("/login/teacher")
    if request.method == "POST":
        text = request.form["text"]
        correct = request.form["correct"]
        qtype = request.form["qtype"]
        a = request.form.get("option_a")
        b = request.form.get("option_b")
        c = request.form.get("option_c")
        d = request.form.get("option_d")
        conn = get_db()
        conn.execute("""INSERT INTO questions(quiz_id, text, correct, option_a, option_b, option_c, option_d, qtype)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                     (quiz_id, text, correct, a, b, c, d, qtype))
        conn.commit()
        conn.close()
        return render_page(f"<p>Question added!</p><a href='/teacher/add_question/{quiz_id}'><button>Add Another</button></a><a href='/teacher/dashboard'><button>Back to Dashboard</button></a>")
    return render_page(f"""
        <div class='card'>
        <h2>Add Question</h2>
        <form method='post'>
            Text: <textarea name='text'></textarea><br>
            Correct Answer: <input name='correct'><br>
            Type: <select name='qtype'><option value='mcq'>MCQ</option><option value='short'>Subjective</option></select><br>
            Option A: <input name='option_a'><br>
            Option B: <input name='option_b'><br>
            Option C: <input name='option_c'><br>
            Option D: <input name='option_d'><br>
            <button type='submit'>Add</button>
        </form>
        </div>
    """)

# ---------- Delete Quiz ----------
@app.route("/teacher/delete_quiz", methods=["GET", "POST"])
def delete_quiz():
    if "teacher" not in session:
        return redirect("/login/teacher")
    conn = get_db()
    quizzes = conn.execute("SELECT * FROM quizzes").fetchall()
    if request.method == "POST":
        quiz_id = request.form["quiz_id"]
        conn.execute("DELETE FROM attempts WHERE quiz_id=?", (quiz_id,))
        conn.execute("DELETE FROM questions WHERE quiz_id=?", (quiz_id,))
        conn.execute("DELETE FROM quizzes WHERE id=?", (quiz_id,))
        conn.commit()
        conn.close()
        return redirect("/teacher/dashboard")
    html = "<div class='card'><h2>Delete Quiz</h2><form method='post'><select name='quiz_id'>"
    for q in quizzes:
        html += f"<option value='{q['id']}'>{q['title']} ({q['subject']}, Grade {q['grade']})</option>"
    html += "</select><br><button type='submit'>Delete</button></form></div>"
    return render_page(html)

# ---------- Reset Database ----------
@app.route("/teacher/reset_db", methods=["GET", "POST"])
def reset_db():
    if "teacher" not in session:
        return redirect("/login/teacher")
    if request.method == "POST":
        confirm = request.form.get("confirm")
        if confirm == "YES":
            conn = get_db()
            conn.execute("DROP TABLE IF EXISTS students")
            conn.execute("DROP TABLE IF EXISTS quizzes")
            conn.execute("DROP TABLE IF EXISTS questions")
            conn.execute("DROP TABLE IF EXISTS attempts")
            conn.commit()
            conn.close()
            init_db()
            return render_page("<p>Database reset successfully!</p><a href='/teacher/dashboard'><button>Back</button></a>")
        else:
            return redirect("/teacher/dashboard")
    return render_page("""
        <div class='card'>
        <h2>⚠️ Reset Database</h2>
        <p>This will erase all student, quiz, and attempt data.</p>
        <form method='post'>
            Type YES to confirm: <input name='confirm'>
            <button type='submit' style='background:red;'>Reset</button>
        </form>
        </div>
    """)

# ---------- Logout ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------- Run ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
