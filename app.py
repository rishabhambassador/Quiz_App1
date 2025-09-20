from flask import Flask, request, redirect, session, render_template_string
import sqlite3
import difflib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import io
import base64

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
                        username TEXT UNIQUE,
                        password TEXT,
                        grade TEXT,
                        class TEXT,
                        gender TEXT
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
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f8f9fa;
                margin: 0; padding: 0;
            }}
            .container {{
                max-width: 700px;
                margin: 40px auto;
                padding: 20px;
                background: #fff;
                border-radius: 10px;
                box-shadow: 0 2px 6px rgba(0,0,0,0.2);
            }}
            h1, h2, h3 {{ text-align: center; color: #333; }}
            form {{ margin-top: 15px; }}
            input, select, textarea {{
                width: 100%; padding: 8px; margin: 6px 0;
                border: 1px solid #ccc; border-radius: 5px;
            }}
            .btn {{
                background: #007bff; color: white;
                padding: 10px 15px; border: none;
                border-radius: 5px; cursor: pointer;
                margin-top: 10px;
            }}
            .btn:hover {{ background: #0056b3; }}
            .nav {{ text-align: center; margin-top: 20px; }}
            .nav a {{ margin: 0 10px; }}
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

# ---------- Similarity ----------
def similarity_ratio(ans, correct):
    return difflib.SequenceMatcher(None, ans.lower().strip(), correct.lower().strip()).ratio()

# ---------- Home ----------
@app.route("/")
def home():
    return render_page("""
        <h1>Welcome to Quiz App</h1>
        <div class='nav'>
            <a href='/signup/student'><button class='btn'>Student Sign Up</button></a>
            <a href='/login/student'><button class='btn'>Student Login</button></a>
            <a href='/login/teacher'><button class='btn'>Teacher Login</button></a>
        </div>
    """)

# ---------- Student Signup ----------
@app.route("/signup/student", methods=["GET", "POST"])
def signup_student():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        grade = request.form["grade"]
        class_ = request.form["class"]
        gender = request.form["gender"]
        try:
            conn = get_db()
            conn.execute("INSERT INTO students(username, password, grade, class, gender) VALUES (?, ?, ?, ?, ?)",
                         (username, password, grade, class_, gender))
            conn.commit()
            conn.close()
            return redirect("/login/student")
        except:
            return render_page("<h3>⚠ Username already exists!</h3>")
    return render_page("""
        <h2>Student Signup</h2>
        <form method='post'>
            Username: <input name='username' required><br>
            Password: <input type='password' name='password' required><br>
            Grade: <input name='grade' required><br>
            Class: <input name='class' required><br>
            Gender: 
            <select name='gender' required>
                <option value='Male'>Male</option>
                <option value='Female'>Female</option>
                <option value='Other'>Other</option>
            </select><br>
            <button class='btn' type='submit'>Sign Up</button>
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
            return render_page("<h3>❌ Invalid credentials!</h3>")
    return render_page("""
        <h2>Student Login</h2>
        <form method='post'>
            Username: <input name='username'><br>
            Password: <input type='password' name='password'><br>
            <button class='btn' type='submit'>Login</button>
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
            return render_page("<h3>❌ Invalid teacher credentials!</h3>")
    return render_page("""
        <h2>Teacher Login</h2>
        <form method='post'>
            Username: <input name='username'><br>
            Passkey: <input type='password' name='password'><br>
            <button class='btn' type='submit'>Login</button>
        </form>
    """)

# ---------- Quiz ----------
@app.route("/quiz", methods=["GET", "POST"])
def quiz():
    if "student_id" not in session:
        return redirect("/login/student")

    grade = session.get("grade", "")
    conn = get_db()
    questions = conn.execute(
        "SELECT * FROM questions WHERE grade=? OR grade='' OR grade IS NULL",
        (grade,)
    ).fetchall()
    conn.close()

    if request.method == "POST":
        student_id = session["student_id"]
        recorded = 0
        for q in questions:
            qid = str(q["id"])
            ans = request.form.get(qid)
            if ans is None:
                continue
            if (q["qtype"] or "").lower() == "mcq":
                correct_flag = 1 if ans.strip() == (q["correct"] or "").strip() else 0
            else:
                sim = similarity_ratio(ans, q["correct"] or "")
                correct_flag = 1 if sim >= 0.75 else 0
            conn = get_db()
            conn.execute(
                "INSERT INTO attempts(student_id, question_id, student_answer, correct) VALUES (?, ?, ?, ?)",
                (student_id, q["id"], ans, correct_flag)
            )
            conn.commit()
            conn.close()
            recorded += 1
        return render_page(f"<h3 class='center'>✅ Quiz submitted! ({recorded} answers recorded)</h3>")

    # Render quiz form
    q_html = "<h2 class='center'>Quiz</h2><form method='post'>"
    for q in questions:
        q_html += f"<p><strong>{q['text']}</strong></p>"
        if (q["qtype"] or "").lower() == "mcq":
            for opt in ["a", "b", "c", "d"]:
                val = q[f"option_{opt}"]
                if val:
                    q_html += f"<label><input type='radio' name='{q['id']}' value='{val}'> {val}</label><br>"
        else:
            q_html += f"<textarea name='{q['id']}' placeholder='Your answer' rows='3' style='width:100%;'></textarea><br>"
    q_html += "<div style='margin-top:12px;'><button class='btn' type='submit'>Submit Quiz</button></div></form>"
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
        conn.execute(
            """INSERT INTO questions(text, correct, option_a, option_b, option_c, option_d, subject, qtype, grade)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (text, correct, a, b, c, d, subject, qtype, grade),
        )
        conn.commit()
        conn.close()

        return render_page("""
            <h2>✅ Question Added!</h2>
            <div class='nav'>
                <a href='/teacher/add_question'><button class='btn'>Add Another Question</button></a>
                <a href='/teacher/dashboard'><button class='btn'>Back to Dashboard</button></a>
            </div>
        """)

    return render_page("""
        <h2>Add Question</h2>
        <form method='post'>
            Question Text: <input name='text' required><br>
            Correct Answer: <input name='correct' required><br>
            Subject: <input name='subject' required><br>
            Type (mcq/short): <input name='qtype' required><br>
            Grade: <input name='grade' required><br>
            Option A: <input name='option_a'><br>
            Option B: <input name='option_b'><br>
            Option C: <input name='option_c'><br>
            Option D: <input name='option_d'><br><br>
            <button class='btn' type='submit'>Add</button>
        </form>
        <div class='nav'><a href='/teacher/dashboard'><button class='btn'>⬅ Back to Dashboard</button></a></div>
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
        <div class='nav'>
            <a href='/teacher/add_question'><button class='btn'>Add Question</button></a>
            <a href='/reset_db'><button class='btn'>⚠ Wipe All Data</button></a>
            <a href='/logout'><button class='btn'>Logout</button></a>
        </div>
        <h3>Performance by Grade</h3>
        <img src='data:image/png;base64,{graph_url}'/>
    """)

# ---------- Reset DB (Teacher only) ----------
@app.route("/reset_db")
def reset_db():
    if "teacher" not in session:
        return redirect("/login/teacher")

    conn = get_db()
    conn.execute("DELETE FROM students")
    conn.execute("DELETE FROM questions")
    conn.execute("DELETE FROM attempts")
    conn.commit()
    conn.close()
    return render_page("<h2>✅ All data wiped!</h2><div class='nav'><a href='/teacher/dashboard'><button class='btn'>Back</button></a></div>")

# ---------- Logout ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------- Run ----------
if __name__ == "__main__":
    host = "0.0.0.0"
    port = 5000
    print(f"✅ Server running at http://{host}:{port}")
    app.run(host=host, port=port, debug=False)

