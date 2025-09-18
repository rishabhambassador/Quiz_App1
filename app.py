from flask import Flask, request, redirect, session, render_template_string
import sqlite3
import spacy
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import base64
import os

app = Flask(__name__)
app.secret_key = "supersecret"

# ✅ Teacher passkeys
TEACHER_PASSKEYS = {
    "teacher1": "math123",
    "teacher2": "science456",
    "admin": "supersecret"
}

# ✅ NLP model
nlp = spacy.load("en_core_web_sm")

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
                        grade TEXT
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

# ---------- Helper: Base Layout ----------
def render_page(content):
    base = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Quiz App</title>
    </head>
    <body>
        <div style='margin:20px;'>
            {content}
        </div>
    </body>
    </html>
    """
    return render_template_string(base)

# ---------- Similarity ----------
def check_similarity(ans, correct):
    doc1 = nlp(ans.lower())
    doc2 = nlp(correct.lower())
    return doc1.similarity(doc2)

# ---------- Home ----------
@app.route("/")
def home():
    return render_page("""
        <h1>Welcome to Quiz App</h1>
        <a href='/signup/student'><button>Student Sign Up</button></a>
        <a href='/login/student'><button>Student Login</button></a>
        <a href='/login/teacher'><button>Teacher Login</button></a>
    """)

# ---------- Student Signup ----------
@app.route("/signup/student", methods=["GET", "POST"])
def signup_student():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        grade = request.form["grade"]
        try:
            conn = get_db()
            conn.execute("INSERT INTO students(username, password, grade) VALUES (?, ?, ?)",
                         (username, password, grade))
            conn.commit()
            conn.close()
            return redirect("/login/student")
        except:
            return render_page("<p>Username already exists!</p>")
    return render_page("""
        <h2>Student Signup</h2>
        <form method='post'>
            Username: <input name='username'><br>
            Password: <input type='password' name='password'><br>
            Grade: <input name='grade'><br>
            <button type='submit'>Sign Up</button>
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
            return render_page("<p>Invalid credentials!</p>")
    return render_page("""
        <h2>Student Login</h2>
        <form method='post'>
            Username: <input name='username'><br>
            Password: <input type='password' name='password'><br>
            <button type='submit'>Login</button>
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
            return render_page("<p>Invalid teacher credentials!</p>")
    return render_page("""
        <h2>Teacher Login</h2>
        <form method='post'>
            Username: <input name='username'><br>
            Passkey: <input type='password' name='password'><br>
            <button type='submit'>Login</button>
        </form>
    """)

# ---------- Quiz ----------
@app.route("/quiz", methods=["GET", "POST"])
def quiz():
    if "student_id" not in session:
        return redirect("/login/student")

    grade = session["grade"]
    conn = get_db()
    questions = conn.execute("SELECT * FROM questions WHERE grade=?", (grade,)).fetchall()
    conn.close()

    if request.method == "POST":
        student_id = session["student_id"]
        for q in questions:
            ans = request.form.get(str(q["id"]))
            if not ans:
                continue
            if q["qtype"] == "mcq":
                correct = 1 if ans == q["correct"] else 0
            else:
                sim = check_similarity(ans, q["correct"])
                correct = 1 if sim > 0.75 else 0
            conn = get_db()
            conn.execute("INSERT INTO attempts(student_id, question_id, student_answer, correct) VALUES (?, ?, ?, ?)",
                         (student_id, q["id"], ans, correct))
            conn.commit()
            conn.close()
        return render_page("<p>Quiz submitted!</p>")

    q_html = "<h2>Quiz</h2><form method='post'>"
    for q in questions:
        q_html += f"<p>{q['text']}</p>"
        if q["qtype"] == "mcq":
            for opt in ["a", "b", "c", "d"]:
                val = q[f"option_{opt}"]
                if val:
                    q_html += f"<input type='radio' name='{q['id']}' value='{val}'> {val}<br>"
        else:
            q_html += f"<input name='{q['id']}'><br>"
    q_html += "<button type='submit'>Submit</button></form>"
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
        return render_page("<p>Question added!</p>")
    return render_page("""
        <h2>Add Question</h2>
        <form method='post'>
            Text: <input name='text'><br>
            Correct Answer: <input name='correct'><br>
            Subject: <input name='subject'><br>
            Type (mcq/short): <input name='qtype'><br>
            Grade: <input name='grade'><br>
            Option A: <input name='option_a'><br>
            Option B: <input name='option_b'><br>
            Option C: <input name='option_c'><br>
            Option D: <input name='option_d'><br>
            <button type='submit'>Add</button>
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
    plt.title("Performance by Grade")

    img = io.BytesIO()
    plt.savefig(img, format="png")
    img.seek(0)
    graph_url = base64.b64encode(img.getvalue()).decode()
    plt.close()

    return render_page(f"""
        <h2>Teacher Dashboard</h2>
        <img src='data:image/png;base64,{graph_url}'/>
    """)

# ---------- Logout ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------- Run ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
