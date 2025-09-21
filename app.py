# app.py
from flask import Flask, request, redirect, session, render_template_string, send_file, url_for
import sqlite3
import io
import re
import plotly.graph_objects as go
from xhtml2pdf import pisa

app = Flask(__name__)
app.secret_key = "supersecret"

# ---------- Teacher credentials ----------
TEACHER_PASSKEYS = {
    "teacher1": "math123",
    "teacher2": "science456",
    "admin": "supersecret"
}

# ---------- Database helpers & init ----------
DB_PATH = "quiz.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    # students
    conn.execute("""
    CREATE TABLE IF NOT EXISTS students (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       username TEXT UNIQUE,
       password TEXT,
       grade TEXT,
       gender TEXT,
       class_section TEXT
    )""")
    # quizzes (store an optional passage text)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS quizzes (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       title TEXT,
       subject TEXT,
       grade TEXT,
       passage TEXT,
       timer INTEGER DEFAULT 0
    )""")
    # questions belonging to quizzes
    conn.execute("""
    CREATE TABLE IF NOT EXISTS questions (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       quiz_id INTEGER,
       text TEXT,
       correct TEXT,
       option_a TEXT,
       option_b TEXT,
       option_c TEXT,
       option_d TEXT,
       qtype TEXT,
       image TEXT
    )""")
    # attempts
    conn.execute("""
    CREATE TABLE IF NOT EXISTS attempts (
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

# ---------- Helpers ----------
def render_page(content):
    # Use .format(content=...) to avoid f-string brace issues in CSS
    base = """
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>Ambassador Quiz App</title>
      <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
      <style>
        body {{
          font-family: Arial, sans-serif;
          margin: 20px;
          background-color: #f9f9f9;
        }}
        h1,h2,h3 {{ color: #2c3e50; }}
        .btn {{
          padding: 8px 15px;
          margin: 5px;
          background: #3498db;
          color: white;
          border: none;
          border-radius: 5px;
          cursor: pointer;
          text-decoration: none;
        }}
        .btn:hover {{ background: #2980b9; }}
        .card {{
          background: white;
          padding: 15px;
          margin: 10px 0;
          border-radius: 8px;
          box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        input, select, textarea {{
          margin: 5px 0;
          padding: 6px;
          width: 100%;
          max-width: 600px;
          border-radius:6px;
          border:1px solid #ddd;
        }}
        .row {{ display:flex; gap:12px; }}
        .col {{ flex:1; }}
        img.responsive {{ max-width:100%; height:auto; border-radius:6px; margin-top:8px; }}
        .muted {{ color:#6b7280; font-size:14px; }}
        @media(max-width:900px){{ .row {{ flex-direction: column; }} }}
      </style>
    </head>
    <body>
      <div class="card">
        {content}
      </div>
    </body>
    </html>
    """.format(content=content)
    return render_template_string(base)

def normalize_words(text):
    return re.findall(r"\w+", (text or "").lower())

def check_similarity(ans, correct, threshold=0.6):
    """Simple keyword overlap similarity (dependency-free)."""
    if not ans or not correct:
        return 0
    a = normalize_words(ans)
    c = normalize_words(correct)
    if not c:
        return 0
    matches = sum(1 for w in c if w in a)
    ratio = matches / len(c)
    return 1 if ratio >= threshold else 0

def make_plot(labels, scores, title, div_id):
    fig = go.Figure([go.Bar(x=list(labels), y=list(scores), marker_color="skyblue")])
    fig.update_layout(title=title, yaxis=dict(title="Avg (%)", range=[0,100]), margin=dict(l=20,r=20,t=40,b=30), height=300)
    return fig.to_html(full_html=False, include_plotlyjs=False, div_id=div_id)

def html_to_pdf_bytes(source_html):
    out = io.BytesIO()
    pisa.CreatePDF(src=source_html, dest=out)
    out.seek(0)
    return out

# ---------- Routes ----------
@app.route("/")
def home():
    # show quizzes (all grades) on homepage
    conn = get_db()
    quizzes = conn.execute("SELECT * FROM quizzes ORDER BY id DESC").fetchall()
    conn.close()
    html = "<h1>Ambassador Quiz App</h1>"
    html += "<p class='muted' style='text-align:center'>Inspire · Inquire · Innovate</p>"
    html += "<div style='text-align:center;margin-bottom:12px'>"
    html += "<a class='btn' href='/signup/student'>Student Sign Up</a> "
    html += "<a class='btn' href='/login/student'>Student Login</a> "
    html += "<a class='btn' href='/login/teacher'>Teacher Login</a></div>"
    html += "<h3>Available Quizzes</h3>"
    if quizzes:
        for q in quizzes:
            html += f"<div style='padding:10px;border:1px solid #eee;margin:8px 0;border-radius:6px;display:flex;justify-content:space-between;align-items:center'>"
            html += f"<div><strong>{q['title']}</strong> <div class='muted'>{q['subject']} • Grade {q['grade']}</div></div>"
            html += f"<div><a class='btn' href='/quiz/{q['id']}'>Take Quiz</a></div></div>"
    else:
        html += "<p class='muted'>No quizzes created yet.</p>"
    return render_page(html)

# ---------- Student signup/login ----------
@app.route("/signup/student", methods=["GET","POST"])
def signup_student():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","").strip()
        grade = request.form.get("grade","").strip()
        gender = request.form.get("gender","").strip()
        class_section = request.form.get("class_section","").strip()
        if not username or not password:
            return render_page("<p>Username & password required</p><a href='/signup/student' class='btn'>Back</a>")
        try:
            conn = get_db()
            conn.execute("INSERT INTO students(username,password,grade,gender,class_section) VALUES (?,?,?,?,?)",
                         (username,password,grade,gender,class_section))
            conn.commit(); conn.close()
            return redirect("/login/student")
        except sqlite3.IntegrityError:
            return render_page("<p>Username already exists!</p><a href='/signup/student' class='btn'>Back</a>")
    form = """
      <h2>Student Signup</h2>
      <form method="post">
        <input name="username" placeholder="Username" required>
        <input name="password" placeholder="Password" required type="password">
        <input name="grade" placeholder="Grade (e.g. 7)">
        <input name="class_section" placeholder="Class / Section (optional)">
        <select name="gender"><option value="">Select Gender</option><option>Male</option><option>Female</option><option>Other</option></select>
        <button class="btn" type="submit">Sign Up</button>
      </form>
    """
    return render_page(form)

@app.route("/login/student", methods=["GET","POST"])
def login_student():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","").strip()
        conn = get_db()
        student = conn.execute("SELECT * FROM students WHERE username=? AND password=?", (username,password)).fetchone()
        conn.close()
        if student:
            session["student_id"] = student["id"]
            session["grade"] = student["grade"]
            return redirect("/quiz/select")
        return render_page("<p>Invalid credentials!</p><a href='/login/student' class='btn'>Back</a>")
    return render_page("""
      <h2>Student Login</h2>
      <form method="post">
        <input name="username" placeholder="Username" required>
        <input name="password" placeholder="Password" type="password" required>
        <button class='btn' type="submit">Login</button>
      </form>
    """)

# ---------- Teacher login ----------
@app.route("/login/teacher", methods=["GET","POST"])
def login_teacher():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","").strip()
        if username in TEACHER_PASSKEYS and TEACHER_PASSKEYS[username] == password:
            session["teacher"] = username
            return redirect("/teacher/dashboard")
        return render_page("<p>Invalid teacher credentials</p><a href='/login/teacher' class='btn'>Back</a>")
    return render_page("""
      <h2>Teacher Login</h2>
      <form method="post">
        <input name="username" placeholder="Teacher username" required>
        <input name="password" placeholder="Passkey" type="password" required>
        <button class='btn' type="submit">Login</button>
      </form>
    """)

# ---------- Teacher create quiz ----------
@app.route("/teacher/create_quiz", methods=["GET","POST"])
def teacher_create_quiz():
    if "teacher" not in session:
        return redirect("/login/teacher")
    if request.method == "POST":
        title = request.form.get("title","").strip()
        subject = request.form.get("subject","").strip()
        grade = request.form.get("grade","").strip()
        passage = request.form.get("passage","").strip()
        # safe parse timer
        timer_raw = request.form.get("timer","").strip()
        try:
            timer = int(timer_raw) if timer_raw else 0
        except ValueError:
            timer = 0
        conn = get_db()
        cur = conn.execute("INSERT INTO quizzes(title,subject,grade,passage,timer) VALUES (?,?,?,?,?)",
                           (title,subject,grade,passage,timer))
        conn.commit(); quiz_id = cur.lastrowid; conn.close()
        return redirect(f"/teacher/add_question/{quiz_id}")
    form = """
      <h2>Create Quiz</h2>
      <form method="post">
        <input name="title" placeholder="Quiz title" required>
        <input name="subject" placeholder="Subject" required>
        <input name="grade" placeholder="Grade (e.g. 7)" required>
        <label>Passage (optional)</label><textarea name="passage" rows="5" placeholder="Paste passage text (optional)"></textarea>
        <input name="timer" placeholder="Timer in seconds (optional)">
        <button class='btn' type="submit">Create Quiz</button>
      </form>
    """
    return render_page(form)

# ---------- Teacher add question (supports image URL) ----------
@app.route("/teacher/add_question/<int:quiz_id>", methods=["GET","POST"])
def teacher_add_question(quiz_id):
    if "teacher" not in session:
        return redirect("/login/teacher")
    conn = get_db()
    quiz = conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    conn.close()
    if not quiz:
        return render_page("<p>Quiz not found</p><a class='btn' href='/teacher/dashboard'>Dashboard</a>")
    if request.method == "POST":
        text = request.form.get("text","").strip()
        correct = request.form.get("correct","").strip()
        qtype = request.form.get("qtype","mcq").strip()
        a = request.form.get("option_a") or None
        b = request.form.get("option_b") or None
        c = request.form.get("option_c") or None
        d = request.form.get("option_d") or None
        image = request.form.get("image_url") or None
        conn = get_db()
        conn.execute("""INSERT INTO questions(quiz_id,text,correct,option_a,option_b,option_c,option_d,qtype,image)
                        VALUES (?,?,?,?,?,?,?,?,?)""", (quiz_id, text, correct, a, b, c, d, qtype, image))
        conn.commit(); conn.close()
        return render_page(f"<p>Question added to quiz '{quiz['title']}'</p>"
                           f"<a class='btn' href='/teacher/add_question/{quiz_id}'>Add Another</a> "
                           f"<a class='btn' href='/teacher/dashboard'>Dashboard</a>")
    form = f"""
      <h2>Add Question to: {quiz['title']}</h2>
      <form method="post">
        <input name="text" placeholder="Question text" required>
        <input name="correct" placeholder="Correct answer (exact text for MCQ; keywords for subjective)" required>
        <select name="qtype"><option value="mcq">MCQ</option><option value="subjective">Subjective</option></select>
        <div style="display:flex;gap:8px"><input name="option_a" placeholder="Option A"><input name="option_b" placeholder="Option B"></div>
        <div style="display:flex;gap:8px"><input name="option_c" placeholder="Option C"><input name="option_d" placeholder="Option D"></div>
        <input name="image_url" placeholder="Image URL (optional)">
        <button class='btn' type="submit">Add Question</button>
      </form>
    """
    return render_page(form)

# ---------- Student: select quiz for their grade ----------
@app.route("/quiz/select")
def student_select_quiz():
    if "student_id" not in session:
        return redirect("/login/student")
    grade = session.get("grade","")
    conn = get_db()
    quizzes = conn.execute("SELECT * FROM quizzes WHERE grade=?", (grade,)).fetchall()
    conn.close()
    if not quizzes:
        return render_page("<h3>No quizzes for your grade yet</h3><a class='btn' href='/'>Home</a>")
    html = "<h2>Select Quiz</h2>"
    for q in quizzes:
        html += f"<div class='card'><strong>{q['title']}</strong><div class='muted'>{q['subject']}</div>"
        html += f"<a class='btn' href='/quiz/{q['id']}'>Start</a></div>"
    return render_page(html)

# ---------- Student attempt quiz (one page with timer auto-submit) ----------
@app.route("/quiz/<int:quiz_id>", methods=["GET","POST"])
def attempt_quiz(quiz_id):
    if "student_id" not in session:
        return redirect("/login/student")
    conn = get_db()
    quiz = conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    questions = conn.execute("SELECT * FROM questions WHERE quiz_id=? ORDER BY id", (quiz_id,)).fetchall()
    conn.close()
    if not quiz:
        return render_page("<p>Quiz not found</p><a class='btn' href='/'>Home</a>")

    if request.method == "POST":
        conn = get_db()
        student_id = session["student_id"]
        for q in questions:
            ans = (request.form.get(str(q["id"])) or "").strip()
            if (q["qtype"] or "").lower() == "mcq":
                correct = 1 if ans.strip().lower() == (q["correct"] or "").strip().lower() else 0
            else:
                correct = check_similarity(ans, q["correct"])
            conn.execute("INSERT INTO attempts(student_id,quiz_id,question_id,student_answer,correct) VALUES (?,?,?,?,?)",
                         (student_id, quiz_id, q["id"], ans, correct))
        conn.commit(); conn.close()
        return render_page("<h3>Quiz submitted — thank you!</h3><a class='btn' href='/'>Home</a>")

    # Build quiz page: show passage (if any) then questions
    page = f"<h2>{quiz['title']} — {quiz['subject']} (Grade {quiz['grade']})</h2>"
    if quiz.get("passage"):
        page += f"<div class='card'><strong>Passage</strong><div style='white-space:pre-wrap'>{quiz['passage']}</div></div>"
    page += "<form method='post'>"
    for q in questions:
        page += "<div class='card'>"
        page += f"<p><strong>Q{q['id']}.</strong> {q['text']}</p>"
        if q.get("image"):
            page += f"<img class='responsive' src='{q['image']}' alt='question image'><br>"
        if (q["qtype"] or "").lower() == "mcq":
            for opt in ["a","b","c","d"]:
                val = q.get(f"option_{opt}")
                if val:
                    page += f"<label><input type='radio' name='{q['id']}' value='{val}'> {val}</label><br>"
        else:
            page += f"<textarea name='{q['id']}' rows='4' style='width:100%'></textarea>"
        page += "</div>"
    page += "<button class='btn' type='submit'>Submit Quiz</button></form>"

    # Timer block (if zero or missing, no timer shown)
    timer_seconds = int(quiz.get("timer") or 0)
    if timer_seconds > 0:
        # timer div first, script after
        page += "<div id='timer' class='muted'></div>"
        # script uses DOMContentLoaded to ensure element present
        page += f"""
        <script>
        document.addEventListener('DOMContentLoaded', function() {{
          var timeLeft = {timer_seconds};
          var timerEl = document.getElementById('timer');
          timerEl.innerText = "Time left: " + timeLeft + "s";
          var interval = setInterval(function() {{
            timeLeft -= 1;
            if (timeLeft >= 0) {{
              timerEl.innerText = "Time left: " + timeLeft + "s";
            }}
            if (timeLeft <= 0) {{
              clearInterval(interval);
              // auto-submit the form
              var form = document.forms[0];
              if (form) {{ form.submit(); }}
            }}
          }}, 1000);
        }});
        </script>
        """

    return render_page(page)

# ---------- Teacher dashboard (charts + links) ----------
@app.route("/teacher/dashboard")
def teacher_dashboard():
    if "teacher" not in session:
        return redirect("/login/teacher")
    conn = get_db()
    # grade-level averages
    grade_rows = conn.execute("""
      SELECT s.grade as label, AVG(a.correct)*100.0 as pct
      FROM attempts a JOIN students s ON a.student_id = s.id
      GROUP BY s.grade
    """).fetchall()
    # subject-level averages (subject is stored in quizzes)
    subject_rows = conn.execute("""
      SELECT qz.subject as label, AVG(a.correct)*100.0 as pct
      FROM attempts a JOIN quizzes qz ON a.quiz_id = qz.id
      GROUP BY qz.subject
    """).fetchall()
    # quiz-level averages
    quiz_rows = conn.execute("""
      SELECT qz.title as label, AVG(a.correct)*100.0 as pct
      FROM attempts a JOIN quizzes qz ON a.quiz_id = qz.id
      GROUP BY qz.id
    """).fetchall()
    quizzes = conn.execute("SELECT * FROM quizzes ORDER BY id DESC").fetchall()
    conn.close()

    grade_chart = "<p class='muted'>No data</p>"
    subject_chart = "<p class='muted'>No data</p>"
    quiz_chart = "<p class='muted'>No data</p>"

    if grade_rows:
        labels = [r["label"] or "N/A" for r in grade_rows]
        vals = [round(r["pct"] or 0,2) for r in grade_rows]
        grade_chart = make_plot(labels, vals, "Average Score by Grade", "grade_plot")
    if subject_rows:
        labels = [r["label"] or "N/A" for r in subject_rows]
        vals = [round(r["pct"] or 0,2) for r in subject_rows]
        subject_chart = make_plot(labels, vals, "Average Score by Subject", "subject_plot")
    if quiz_rows:
        labels = [r["label"] or "N/A" for r in quiz_rows]
        vals = [round(r["pct"] or 0,2) for r in quiz_rows]
        quiz_chart = make_plot(labels, vals, "Average Score by Quiz", "quiz_plot")

    html = "<h2>Teacher Dashboard</h2>"
    html += "<div style='display:flex;gap:12px;flex-wrap:wrap'>"
    html += f"<div style='flex:1 1 320px;background:#fff;padding:12px;border-radius:6px'>{grade_chart}</div>"
    html += f"<div style='flex:1 1 320px;background:#fff;padding:12px;border-radius:6px'>{subject_chart}</div>"
    html += f"<div style='flex:1 1 320px;background:#fff;padding:12px;border-radius:6px'>{quiz_chart}</div>"
    html += "</div>"
    html += "<div style='margin-top:12px'>"
    html += "<a class='btn' href='/teacher/create_quiz'>Create Quiz</a> "
    html += "<a class='btn' href='/teacher/list_quizzes'>Manage Quizzes</a> "
    html += "<a class='btn' href='/teacher/students'>Student History</a> "
    html += "<a class='btn' href='/teacher/download_pdf_all'>Download Attempts (PDF)</a>"
    html += "</div>"
    return render_page(html)

# ---------- Teacher list & view quizzes ----------
@app.route("/teacher/list_quizzes")
def teacher_list_quizzes():
    if "teacher" not in session:
        return redirect("/login/teacher")
    conn = get_db()
    quizzes = conn.execute("SELECT * FROM quizzes ORDER BY id DESC").fetchall()
    conn.close()
    html = "<h2>Quizzes</h2>"
    for q in quizzes:
        html += f"<div style='padding:8px;border:1px solid #eee;margin:8px 0;border-radius:6px;display:flex;justify-content:space-between'>"
        html += f"<div><strong>{q['title']}</strong><div class='muted'>{q['subject']} • Grade {q['grade']}</div></div>"
        html += f"<div><a class='btn' href='/teacher/add_question/{q['id']}'>Add Question</a> <a class='btn' href='/teacher/view_quiz/{q['id']}'>View</a></div></div>"
    html += "<a class='btn' href='/teacher/dashboard'>Back</a>"
    return render_page(html)

@app.route("/teacher/view_quiz/<int:quiz_id>")
def teacher_view_quiz(quiz_id):
    if "teacher" not in session:
        return redirect("/login/teacher")
    conn = get_db()
    quiz = conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    qs = conn.execute("SELECT * FROM questions WHERE quiz_id=? ORDER BY id", (quiz_id,)).fetchall()
    conn.close()
    if not quiz:
        return render_page("<p>Quiz not found</p><a class='btn' href='/teacher/list_quizzes'>Back</a>")
    html = f"<h2>{quiz['title']} — {quiz['subject']}</h2><h3>Questions</h3>"
    if not qs:
        html += "<p class='muted'>No questions yet</p>"
    for q in qs:
        html += f"<div class='card'><strong>Q{q['id']}</strong>: {q['text']}<div class='muted'>type: {q['qtype']} image: {q['image'] or 'none'}</div></div>"
    html += "<a class='btn' href='/teacher/list_quizzes'>Back</a>"
    return render_page(html)

# ---------- Teacher: students & per-student detail ----------
@app.route("/teacher/students")
def teacher_students():
    if "teacher" not in session:
        return redirect("/login/teacher")
    conn = get_db()
    students = conn.execute("SELECT * FROM students ORDER BY grade, class_section, username").fetchall()
    conn.close()
    html = "<h2>Students</h2>"
    for s in students:
        html += f"<div class='card'><div style='display:flex;justify-content:space-between;align-items:center'>"
        html += f"<div><strong>{s['username']}</strong><div class='muted'>Grade: {s['grade']} • Class: {s['class_section']}</div></div>"
        html += f"<div><a class='btn' href='/teacher/student/{s['id']}'>View History</a></div></div></div>"
    html += "<a class='btn' href='/teacher/dashboard'>Back</a>"
    return render_page(html)

@app.route("/teacher/student/<int:student_id>")
def teacher_student_detail(student_id):
    if "teacher" not in session:
        return redirect("/login/teacher")
    conn = get_db()
    student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    attempts = conn.execute("""
      SELECT a.*, q.text AS question_text, qz.title AS quiz_title
      FROM attempts a
      LEFT JOIN questions q ON a.question_id = q.id
      LEFT JOIN quizzes qz ON a.quiz_id = qz.id
      WHERE a.student_id = ?
      ORDER BY a.id DESC
    """, (student_id,)).fetchall()
    summary = conn.execute("""
      SELECT qz.id AS quiz_id, qz.title, SUM(a.correct) AS correct_count, COUNT(a.id) AS total
      FROM attempts a JOIN quizzes qz ON a.quiz_id = qz.id
      WHERE a.student_id = ?
      GROUP BY qz.id
    """, (student_id,)).fetchall()
    conn.close()
    if not student:
        return render_page("<p>Student not found</p><a class='btn' href='/teacher/students'>Back</a>")
    html = f"<h2>History for {student['username']}</h2>"
    html += "<h3>Quiz summaries</h3>"
    if summary:
        for s in summary:
            pct = round((s["correct_count"]/s["total"])*100,2) if s["total"]>0 else 0
            html += f"<div class='card'><strong>{s['title']}</strong> — {s['correct_count']}/{s['total']} correct ({pct}%)</div>"
    else:
        html += "<p class='muted'>No attempts yet</p>"
    html += "<h3>All attempts (recent)</h3>"
    for a in attempts:
        html += f"<div class='card'>Quiz: {a['quiz_title']} — Q: {a['question_text']} — Ans: {a['student_answer']} — Correct: {a['correct']}</div>"
    html += "<a class='btn' href='/teacher/students'>Back</a>"
    return render_page(html)

# ---------- Teacher: download attempts PDF ----------
@app.route("/teacher/download_pdf_all")
def teacher_download_pdf_all():
    if "teacher" not in session:
        return redirect("/login/teacher")
    conn = get_db()
    attempts = conn.execute("""
      SELECT s.username, s.grade, s.class_section, qz.title AS quiz_title, a.correct
      FROM attempts a
      JOIN students s ON a.student_id = s.id
      JOIN quizzes qz ON a.quiz_id = qz.id
      ORDER BY s.grade, s.username
    """).fetchall()
    conn.close()
    html = "<html><head><meta charset='utf-8'><style>table{width:100%;border-collapse:collapse}td,th{border:1px solid #ccc;padding:6px;font-size:11px}</style></head><body>"
    html += "<h2>Student Attempts Report</h2><table><tr><th>Username</th><th>Grade</th><th>Class</th><th>Quiz</th><th>Correct</th></tr>"
    for r in attempts:
        html += f"<tr><td>{r['username']}</td><td>{r['grade']}</td><td>{r['class_section']}</td><td>{r['quiz_title']}</td><td>{r['correct']}</td></tr>"
    html += "</table></body></html>"
    pdf_bytes = html_to_pdf_bytes(html)
    return send_file(pdf_bytes, as_attachment=True, download_name="attempts_report.pdf", mimetype="application/pdf")

# ---------- Logout ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------- Run ----------
if __name__ == "__main__":
    print("Ambassador Quiz App running at http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
