# app.py
from flask import Flask, request, redirect, session, render_template_string, send_file, url_for
import sqlite3
import re
import io
import base64
from datetime import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from werkzeug.security import generate_password_hash, check_password_hash
import secrets

# ---------------- App config ----------------
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
DB_PATH = "quiz.db"

# Teacher passkeys (teachers do not sign up)
TEACHER_PASSKEYS = {
    "teacher1": "math123",
    "teacher2": "science456",
    "admin": "supersecret"
}

# ---------------- DB helpers & init ----------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        name TEXT,
        grade TEXT,
        class_section TEXT,
        gender TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS quizzes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        subject TEXT,
        grade TEXT,
        timer_seconds INTEGER DEFAULT 0
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS passages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quiz_id INTEGER,
        title TEXT,
        text_content TEXT,
        image_url TEXT,
        FOREIGN KEY (quiz_id) REFERENCES quizzes(id)
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        passage_id INTEGER,
        text TEXT,
        correct TEXT,
        option_a TEXT,
        option_b TEXT,
        option_c TEXT,
        option_d TEXT,
        qtype TEXT,
        image_url TEXT,
        marks INTEGER DEFAULT 1,
        FOREIGN KEY (passage_id) REFERENCES passages(id)
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        quiz_id INTEGER,
        passage_id INTEGER,
        question_id INTEGER,
        student_answer TEXT,
        correct INTEGER,
        created_at TEXT
    )""")

    conn.commit()
    conn.close()

init_db()

# ---------------- Template (use Jinja to avoid f-string brace issues) ----------------
BASE_TEMPLATE = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>{{title}}</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
      body {{ font-family: Arial, Helvetica, sans-serif; background:#f6f8fb; margin:0; padding:18px; }}
      .topbar {{ max-width:1100px; margin:0 auto 12px; display:flex; justify-content:space-between; align-items:center; }}
      .brand {{ font-weight:bold; font-size:18px; }}
      .nav-btn {{ display:inline-block; padding:8px 12px; margin-left:8px; background:#2b8cff; color:#fff; text-decoration:none; border-radius:6px; }}
      .nav-btn:hover {{ background:#1f6fd6; }}
      .card {{ max-width:1100px; margin:0 auto; background:#fff; padding:18px; border-radius:10px; box-shadow:0 6px 20px rgba(0,0,0,0.06) }}
      h1,h2 {{ text-align:center; margin:6px 0 }}
      .btn {{ display:inline-block; padding:8px 14px; border-radius:6px; background:#2b8cff; color:#fff; text-decoration:none; border:none; cursor:pointer }}
      .btn:hover {{ background:#1f6fd6 }}
      .muted {{ color:#6b7280; font-size:14px }}
      input, textarea, select {{ width:100%; padding:8px; margin:6px 0; border-radius:6px; border:1px solid #ddd; box-sizing:border-box }}
      .row {{ display:flex; gap:12px }}
      .col {{ flex:1 }}
      img.responsive {{ max-width:100%; height:auto; border-radius:6px; margin-top:8px }}
      .small {{ font-size:13px; color:#555 }}
      @media(max-width:900px){{ .row {{ flex-direction: column; }} .topbar {{ padding:8px }} }}
    </style>
  </head>
  <body>
    <div class="topbar">
      <div class="brand">Ambassador Quiz App</div>
      <div class="nav">{{ nav|safe }}</div>
    </div>
    <div class="card">
      {{ content|safe }}
    </div>
  </body>
</html>
"""

def render_page(content, title="Ambassador Quiz App"):
    nav = "<a class='nav-btn' href='/'>Home</a> "
    if session.get("student_id"):
        nav += "<a class='nav-btn' href='/quiz/select'>My Quizzes</a> "
        nav += "<a class='nav-btn' href='/logout'>Logout</a>"
    elif session.get("teacher"):
        nav += "<a class='nav-btn' href='/teacher/dashboard'>Dashboard</a> "
        nav += "<a class='nav-btn' href='/teacher/list_quizzes'>Manage</a> "
        nav += "<a class='nav-btn' href='/logout'>Logout</a>"
    else:
        nav += "<a class='nav-btn' href='/login'>Login</a> <a class='nav-btn' href='/signup'>Student Sign Up</a>"
    return render_template_string(BASE_TEMPLATE, title=title, nav=nav, content=content)

# ---------------- Simple word-overlap similarity for subjective ----------------
def normalize_words(text):
    return re.findall(r"\w+", (text or "").lower())

def check_similarity(ans, correct, threshold=0.6):
    if not ans or not correct:
        return 0
    a = normalize_words(ans)
    c = normalize_words(correct)
    if not c:
        return 0
    matches = sum(1 for w in c if w in a)
    ratio = matches / len(c)
    return 1 if ratio >= threshold else 0

# ---------------- Utility plot ----------------
def make_bar_b64(labels, values, title_text):
    fig, ax = plt.subplots(figsize=(6,3))
    ax.bar(labels, values, color="skyblue")
    ax.set_ylim(0,100)
    ax.set_ylabel("Avg (%)")
    ax.set_title(title_text)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.getvalue()).decode()

# ---------------- Routes ----------------

@app.route("/")
def home():
    conn = get_db()
    quizzes = conn.execute("SELECT * FROM quizzes ORDER BY id DESC").fetchall()
    conn.close()
    content = "<h1>Ambassador Quiz App</h1><p class='muted' style='text-align:center'>Inspire · Inquire · Innovate</p>"
    content += "<div style='text-align:center;margin-bottom:12px'><a class='btn' href='/signup'>Student Sign Up</a> <a class='btn' href='/login'>Login</a></div>"
    content += "<h3>Public Quizzes</h3>"
    if quizzes:
        for q in quizzes:
            content += "<div style='padding:10px;border:1px solid #eee;margin:8px 0;border-radius:6px;display:flex;justify-content:space-between;align-items:center'>"
            content += f"<div><strong>{q['title']}</strong><div class='muted'>{q['subject']} • Grade {q['grade']}</div></div>"
            content += f"<div><a class='btn' href='/quiz/start/{q['id']}'>Take Quiz</a></div></div>"
    else:
        content += "<p class='muted'>No quizzes yet</p>"
    return render_page(content)

# ---------------- Signup / Login ----------------
@app.route("/signup", methods=["GET","POST"])
def signup():
    if request.method == "POST":
        user_id = request.form.get("user_id","").strip()
        password = request.form.get("password","")
        name = request.form.get("name","").strip()
        grade = request.form.get("grade","").strip()
        class_section = request.form.get("class_section","").strip()
        gender = request.form.get("gender","").strip()
        if not user_id or not password:
            return render_page("<p>User ID and password required</p><a class='btn' href='/signup'>Back</a>")
        pw_hash = generate_password_hash(password)
        conn = get_db()
        try:
            conn.execute("INSERT INTO students(username,password,name,grade,class_section,gender) VALUES (?,?,?,?,?,?)",
                         (user_id, pw_hash, name, grade, class_section, gender))
            conn.commit()
            conn.close()
            return redirect("/login")
        except sqlite3.IntegrityError:
            conn.close()
            return render_page("<p>User ID already exists</p><a class='btn' href='/signup'>Back</a>")
    form = """
      <h2>Student Sign Up</h2>
      <form method="post">
        Name: <input name="name" placeholder="Full name"><br>
        User ID: <input name="user_id" placeholder="Unique ID (used to login)" required><br>
        Password: <input type="password" name="password" required><br>
        Grade: <input name="grade" placeholder="Grade (e.g. 7)"><br>
        Class / Section: <input name="class_section" placeholder="Class / Section"><br>
        Gender: <select name="gender"><option value="">Select</option><option>Male</option><option>Female</option><option>Other</option></select><br>
        <button class='btn' type="submit">Sign Up</button>
      </form>
    """
    return render_page(form)

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        role = request.form.get("role","student")
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        if role == "teacher":
            if username in TEACHER_PASSKEYS and TEACHER_PASSKEYS[username] == password:
                session["teacher"] = username
                return redirect("/teacher/dashboard")
            return render_page("<p>Invalid teacher credentials</p><a class='btn' href='/login'>Back</a>")
        else:
            conn = get_db()
            s = conn.execute("SELECT * FROM students WHERE username=?", (username,)).fetchone()
            conn.close()
            if s and check_password_hash(s["password"], password):
                session["student_id"] = s["id"]
                session["student_username"] = s["username"]
                session["grade"] = s["grade"]
                session["class_section"] = s["class_section"]
                return redirect("/quiz/select")
            return render_page("<p>Invalid student credentials</p><a class='btn' href='/login'>Back</a>")
    return render_page("""
      <h2>Login</h2>
      <form method="post">
        Role: <select name="role"><option value="student">Student</option><option value="teacher">Teacher</option></select><br>
        User ID / Teacher name: <input name="username" required><br>
        Password / Passkey: <input type="password" name="password" required><br>
        <button class='btn' type="submit">Login</button>
      </form>
    """)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------------- Teacher: Create / Manage / Dashboard / PDF ----------------
@app.route("/teacher/dashboard")
def teacher_dashboard():
    if "teacher" not in session:
        return redirect("/login")
    conn = get_db()
    grade_rows = conn.execute("""
      SELECT s.grade as label, AVG(a.correct)*100.0 as pct
      FROM attempts a JOIN students s ON a.student_id = s.id
      GROUP BY s.grade
    """).fetchall()
    subject_rows = conn.execute("""
      SELECT qz.subject as label, AVG(a.correct)*100.0 as pct
      FROM attempts a JOIN quizzes qz ON a.quiz_id = qz.id
      GROUP BY qz.subject
    """).fetchall()
    quiz_rows = conn.execute("""
      SELECT qz.title as label, AVG(a.correct)*100.0 as pct
      FROM attempts a JOIN quizzes qz ON a.quiz_id = qz.id
      GROUP BY qz.id
    """).fetchall()
    conn.close()

    def rows_to_img(rows, title_text):
        if not rows:
            return "<p class='muted'>No data</p>"
        labels = [r["label"] or "N/A" for r in rows]
        vals = [round(r["pct"] or 0,2) for r in rows]
        b64 = make_bar_b64(labels, vals, title_text)
        return f"<img src='data:image/png;base64,{b64}'/>"

    grade_img = rows_to_img(grade_rows, "Average Score by Grade")
    subject_img = rows_to_img(subject_rows, "Average Score by Subject")
    quiz_img = rows_to_img(quiz_rows, "Average Score by Quiz")

    html = "<h2>Teacher Dashboard</h2>"
    html += "<div style='display:flex;gap:12px;flex-wrap:wrap'>"
    html += f"<div style='flex:1 1 320px;background:#fff;padding:12px;border-radius:6px'>{grade_img}</div>"
    html += f"<div style='flex:1 1 320px;background:#fff;padding:12px;border-radius:6px'>{subject_img}</div>"
    html += f"<div style='flex:1 1 320px;background:#fff;padding:12px;border-radius:6px'>{quiz_img}</div>"
    html += "</div>"
    html += "<div style='margin-top:12px'><a class='btn' href='/teacher/create_quiz'>Create Quiz</a> <a class='btn' href='/teacher/list_quizzes'>Manage Quizzes</a> <a class='btn' href='/teacher/students'>Student History</a> <a class='btn' href='/teacher/download_pdf_classwise'>Download PDF Report (Class-wise)</a></div>"
    return render_page(html)

@app.route("/teacher/create_quiz", methods=["GET","POST"])
def teacher_create_quiz():
    if "teacher" not in session:
        return redirect("/login")
    if request.method == "POST":
        title = request.form.get("title","").strip()
        subject = request.form.get("subject","").strip()
        grade = request.form.get("grade","").strip()
        timer_raw = request.form.get("timer_seconds","").strip()
        try:
            timer = int(timer_raw) if timer_raw else 0
        except ValueError:
            timer = 0
        conn = get_db()
        cur = conn.execute("INSERT INTO quizzes(title,subject,grade,timer_seconds) VALUES (?,?,?,?)",
                           (title,subject,grade,timer))
        conn.commit(); quiz_id = cur.lastrowid; conn.close()
        return redirect(url_for("teacher_add_passage", quiz_id=quiz_id))
    return render_page("""
      <h2>Create Quiz</h2>
      <form method="post">
        <input name="title" placeholder="Quiz title" required>
        <input name="subject" placeholder="Subject" required>
        <input name="grade" placeholder="Grade (e.g. 7)" required>
        <input name="timer_seconds" placeholder="Timer per passage (seconds, optional)">
        <button class='btn' type="submit">Create Quiz</button>
      </form>
    """)

@app.route("/teacher/add_passage/<int:quiz_id>", methods=["GET","POST"])
def teacher_add_passage(quiz_id):
    if "teacher" not in session:
        return redirect("/login")
    conn = get_db()
    quiz = conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    conn.close()
    if not quiz:
        return render_page("<p>Quiz not found</p><a class='btn' href='/teacher/dashboard'>Back</a>")
    if request.method == "POST":
        title = request.form.get("title","").strip()
        text_content = request.form.get("text_content","").strip()
        image_url = request.form.get("image_url","").strip() or None
        conn = get_db()
        cur = conn.execute("INSERT INTO passages(quiz_id,title,text_content,image_url) VALUES (?,?,?,?)",
                           (quiz_id,title,text_content,image_url))
        conn.commit(); pid = cur.lastrowid; conn.close()
        return redirect(url_for("teacher_add_question", passage_id=pid))
    form = f"""
      <h2>Add Passage to Quiz: {quiz['title']}</h2>
      <form method="post">
        <input name="title" placeholder="Passage title (optional)">
        <label>Passage text</label><textarea name="text_content" rows="6" placeholder="Paste passage text (optional)"></textarea>
        <input name="image_url" placeholder="Image URL for passage (optional)">
        <button class='btn' type="submit">Add Passage</button>
      </form>
      <p class='muted'>After adding passage you'll be redirected to add questions for it.</p>
      <a class='btn' href='/teacher/dashboard'>Dashboard</a>
    """
    return render_page(form)

@app.route("/teacher/add_question/<int:passage_id>", methods=["GET","POST"])
def teacher_add_question(passage_id):
    if "teacher" not in session:
        return redirect("/login")
    conn = get_db()
    passage = conn.execute("SELECT * FROM passages WHERE id=?", (passage_id,)).fetchone()
    conn.close()
    if not passage:
        return render_page("<p>Passage not found</p><a class='btn' href='/teacher/dashboard'>Back</a>")
    if request.method == "POST":
        text = request.form.get("text","").strip()
        correct = request.form.get("correct","").strip()
        qtype = request.form.get("qtype","mcq").strip()
        option_a = request.form.get("option_a") or None
        option_b = request.form.get("option_b") or None
        option_c = request.form.get("option_c") or None
        option_d = request.form.get("option_d") or None
        image_url = request.form.get("image_url","").strip() or None
        marks_raw = request.form.get("marks","1").strip()
        try:
            marks = int(marks_raw)
        except:
            marks = 1
        conn = get_db()
        conn.execute("""INSERT INTO questions(passage_id,text,correct,option_a,option_b,option_c,option_d,qtype,image_url,marks)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""", (passage_id,text,correct,option_a,option_b,option_c,option_d,qtype,image_url,marks))
        conn.commit(); conn.close()
        return render_page(f"<p>Question added to passage '{passage['title'] or passage['id']}'</p>"
                           f"<a class='btn' href='/teacher/add_question/{passage_id}'>Add Another</a> "
                           f"<a class='btn' href='/teacher/view_quiz/{passage['quiz_id']}'>Back to Quiz</a>")
    form = f"""
      <h2>Add Question (Passage: {passage['title'] or passage['id']})</h2>
      <form method="post">
        <input name="text" placeholder="Question text" required>
        <input name="correct" placeholder="Correct answer (for MCQ enter option text; for subjective enter keywords)" required>
        <select name="qtype"><option value="mcq">MCQ</option><option value="subjective">Subjective</option></select>
        <div style="display:flex;gap:8px"><input name="option_a" placeholder="Option A"><input name="option_b" placeholder="Option B"></div>
        <div style="display:flex;gap:8px"><input name="option_c" placeholder="Option C"><input name="option_d" placeholder="Option D"></div>
        <input name="image_url" placeholder="Question image URL (optional)">
        <input name="marks" placeholder="Marks (default 1)">
        <button class='btn' type="submit">Add Question</button>
      </form>
      <a class='btn' href='/teacher/dashboard'>Dashboard</a>
    """
    return render_page(form)

@app.route("/teacher/list_quizzes")
def teacher_list_quizzes():
    if "teacher" not in session:
        return redirect("/login")
    conn = get_db()
    quizzes = conn.execute("SELECT * FROM quizzes ORDER BY id DESC").fetchall()
    conn.close()
    html = "<h2>Quizzes</h2>"
    for q in quizzes:
        html += "<div class='card'><div style='display:flex;justify-content:space-between;align-items:center'><div><strong>{}</strong><div class='muted'>{} • Grade {}</div></div>".format(q['title'], q['subject'], q['grade'])
        html += f"<div><a class='btn' href='/teacher/add_passage/{q['id']}'>Add Passage</a> "
        html += f"<a class='btn' href='/teacher/view_quiz/{q['id']}'>View</a> "
        html += (f"<form method='POST' action='/teacher/delete_quiz/{q['id']}' style='display:inline;margin-left:6px' onsubmit=\"return confirm('Delete this quiz and all its content?');\">"
                 f"<button class='btn' style='background:#e74c3c;color:#fff'>Delete</button></form>")
        html += "</div></div></div>"
    html += "<a class='btn' href='/teacher/dashboard'>Back</a>"
    return render_page(html)

@app.route("/teacher/delete_quiz/<int:quiz_id>", methods=["POST"])
def teacher_delete_quiz(quiz_id):
    if "teacher" not in session:
        return redirect("/login")
    conn = get_db()
    conn.execute("DELETE FROM attempts WHERE question_id IN (SELECT id FROM questions WHERE passage_id IN (SELECT id FROM passages WHERE quiz_id=?))", (quiz_id,))
    conn.execute("DELETE FROM questions WHERE passage_id IN (SELECT id FROM passages WHERE quiz_id=?)", (quiz_id,))
    conn.execute("DELETE FROM passages WHERE quiz_id=?", (quiz_id,))
    conn.execute("DELETE FROM quizzes WHERE id=?", (quiz_id,))
    conn.commit(); conn.close()
    return redirect("/teacher/list_quizzes")

@app.route("/teacher/view_quiz/<int:quiz_id>")
def teacher_view_quiz(quiz_id):
    if "teacher" not in session:
        return redirect("/login")
    conn = get_db()
    quiz = conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    passages = conn.execute("SELECT * FROM passages WHERE quiz_id=? ORDER BY id", (quiz_id,)).fetchall()
    conn.close()
    if not quiz:
        return render_page("<p>Quiz not found</p><a class='btn' href='/teacher/list_quizzes'>Back</a>")
    html = f"<h2>{quiz['title']} — {quiz['subject']}</h2><h3>Passages & Questions</h3>"
    if not passages:
        html += "<p class='muted'>No passages yet</p>"
    for p in passages:
        html += f"<div class='card'><strong>Passage {p['id']}: {p['title'] or ''}</strong>"
        if p['text_content']:
            html += f"<div style='white-space:pre-wrap'>{p['text_content'][:400]}{'...' if len(p['text_content'])>400 else ''}</div>"
        if p['image_url']:
            html += f"<img class='responsive' src='{p['image_url']}' alt='passage image'>"
        html += f"<div class='muted'><a class='btn' href='/teacher/add_question/{p['id']}'>Add Question</a></div></div>"
        conn = get_db()
        qs = conn.execute("SELECT * FROM questions WHERE passage_id=? ORDER BY id", (p['id'],)).fetchall()
        conn.close()
        for q in qs:
            html += f"<div style='padding:8px;border:1px solid #eee;margin:6px 0;border-radius:6px'>Q{q['id']}: {q['text']} <div class='muted'>type:{q['qtype']} marks:{q['marks']}</div></div>"
    html += "<a class='btn' href='/teacher/list_quizzes'>Back</a>"
    return render_page(html)

# ---------------- Student flow ----------------
@app.route("/quiz/select")
def student_select_quiz():
    if "student_id" not in session:
        return redirect("/login")
    grade = session.get("grade","")
    conn = get_db()
    quizzes = conn.execute("SELECT * FROM quizzes WHERE grade=?", (grade,)).fetchall()
    conn.close()
    if not quizzes:
        return render_page("<p>No quizzes for your grade yet</p><a class='btn' href='/'>Home</a>")
    html = "<h2>Select Quiz</h2>"
    for q in quizzes:
        html += f"<div class='card'><strong>{q['title']}</strong><div class='muted'>{q['subject']}</div>"
        html += f"<a class='btn' href='/quiz/start/{q['id']}'>Start</a></div>"
    return render_page(html)

@app.route("/quiz/start/<int:quiz_id>")
def quiz_start(quiz_id):
    return redirect(url_for("quiz_passage", quiz_id=quiz_id, p_index=0))

@app.route("/quiz/<int:quiz_id>/passage/<int:p_index>", methods=["GET","POST"])
def quiz_passage(quiz_id, p_index):
    if "student_id" not in session:
        return redirect("/login")
    conn = get_db()
    quiz = conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    passages = conn.execute("SELECT * FROM passages WHERE quiz_id=? ORDER BY id", (quiz_id,)).fetchall()
    conn.close()
    if not quiz or not passages:
        return render_page("<p>Quiz or passages not found</p><a class='btn' href='/'>Home</a>")
    if p_index < 0 or p_index >= len(passages):
        return render_page("<p>Invalid passage index</p><a class='btn' href='/'>Home</a>")
    passage = passages[p_index]
    conn = get_db()
    questions = conn.execute("SELECT * FROM questions WHERE passage_id=? ORDER BY id", (passage["id"],)).fetchall()
    conn.close()

    if request.method == "POST":
        student_id = session["student_id"]
        now = datetime.utcnow().isoformat()
        conn = get_db()
        for q in questions:
            ans = (request.form.get(f"q_{q['id']}") or "").strip()
            if (q["qtype"] or "").lower() == "mcq":
                correct_flag = 1 if ans.lower() == (q["correct"] or "").lower() else 0
            else:
                correct_flag = check_similarity(ans, q["correct"])
            conn.execute("INSERT INTO attempts(student_id,quiz_id,passage_id,question_id,student_answer,correct,created_at) VALUES (?,?,?,?,?,?,?)",
                         (student_id, quiz_id, passage["id"], q["id"], ans, int(correct_flag), now))
        conn.commit(); conn.close()
        next_index = p_index + 1
        if next_index >= len(passages):
            conn = get_db()
            summary = conn.execute("SELECT SUM(correct) as correct_count, COUNT(id) as total FROM attempts WHERE student_id=? AND quiz_id=?",
                                   (student_id, quiz_id)).fetchone()
            conn.close()
            correct = summary["correct_count"] or 0
            total = summary["total"] or 0
            pct = round((correct/total)*100,2) if total>0 else 0
            html = f"<h2>Quiz Completed: {quiz['title']}</h2><p class='muted'>You answered {correct} out of {total} correctly. Score: {pct}%</p>"
            html += "<a class='btn' href='/quiz/select'>My Quizzes</a> <a class='btn' href='/'>Home</a>"
            return render_page(html)
        return redirect(url_for("quiz_passage", quiz_id=quiz_id, p_index=next_index))

    page = f"<h2>{quiz['title']} — {quiz['subject']} (Grade {quiz['grade']})</h2>"
    page += f"<h3>Passage {p_index+1} of {len(passages)}: {passage['title'] or ''}</h3>"
    if passage["text_content"]:
        page += f"<div class='card'><div style='white-space:pre-wrap'>{passage['text_content']}</div></div>"
    if passage["image_url"]:
        page += f"<div class='card'><img class='responsive' src='{passage['image_url']}' alt='passage image'></div>"
    page += "<form method='post'>"
    for q in questions:
        page += "<div class='card'>"
        page += f"<p><strong>Q{q['id']}.</strong> {q['text']}</p>"
        if q["image_url"]:
            page += f"<img class='responsive' src='{q['image_url']}' alt='question image'><br>"
        if (q["qtype"] or "").lower() == "mcq":
            for opt in ("a","b","c","d"):
                val = q.get(f"option_{opt}")
                if val:
                    page += f"<label><input type='radio' name='q_{q['id']}' value='{val}'> {val}</label><br>"
        else:
            page += f"<textarea name='q_{q['id']}' rows='4' style='width:100%'></textarea>"
        page += "</div>"
    page += "<div style='display:flex;gap:8px'><button class='btn' type='submit'>Submit Passage</button>"
    if p_index > 0:
        page += f"<a class='btn' href='{url_for('quiz_passage', quiz_id=quiz_id, p_index=p_index-1)}'>Previous Passage</a>"
    page += "</div></form>"

    timer_seconds = int(quiz.get("timer_seconds") or 0)
    if timer_seconds > 0:
        page += "<div id='timer' class='muted'></div>"
        page += f"""
        <script>
        document.addEventListener('DOMContentLoaded', function() {{
          var timeLeft = {timer_seconds};
          var timerEl = document.getElementById('timer');
          timerEl.innerText = "Time left: " + timeLeft + "s";
          var interval = setInterval(function() {{
            timeLeft -= 1;
            if (timeLeft >= 0) {{ timerEl.innerText = "Time left: " + timeLeft + "s"; }}
            if (timeLeft <= 0) {{
              clearInterval(interval);
              var form = document.forms[0];
              if (form) form.submit();
            }}
          }}, 1000);
        }});
        </script>
        """

    return render_page(page)

# ---------------- Teacher: students and PDF export ----------------
@app.route("/teacher/students")
def teacher_students():
    if "teacher" not in session:
        return redirect("/login")
    conn = get_db()
    students = conn.execute("SELECT * FROM students ORDER BY grade, class_section, username").fetchall()
    conn.close()
    html = "<h2>Students</h2>"
    for s in students:
        html += f"<div class='card'><div style='display:flex;justify-content:space-between;align-items:center'><div><strong>{s['username']}</strong><div class='muted'>Grade:{s['grade']} • Class:{s['class_section']}</div></div>"
        html += f"<div><a class='btn' href='/teacher/student/{s['id']}'>View History</a></div></div></div>"
    html += "<a class='btn' href='/teacher/dashboard'>Back</a>"
    return render_page(html)

@app.route("/teacher/student/<int:student_id>")
def teacher_student_detail(student_id):
    if "teacher" not in session:
        return redirect("/login")
    conn = get_db()
    student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    attempts = conn.execute("""
      SELECT a.*, q.text AS question_text, p.title AS passage_title, qz.title AS quiz_title
      FROM attempts a
      LEFT JOIN questions q ON a.question_id = q.id
      LEFT JOIN passages p ON a.passage_id = p.id
      LEFT JOIN quizzes qz ON a.quiz_id = qz.id
      WHERE a.student_id = ?
      ORDER BY a.created_at DESC
    """, (student_id,)).fetchall()
    conn.close()
    if not student:
        return render_page("<p>Student not found</p><a class='btn' href='/teacher/students'>Back</a>")
    html = f"<h2>History for {student['username']}</h2>"
    html += "<h3>All Attempts</h3>"
    for a in attempts:
        html += f"<div class='card'>Quiz:{a['quiz_title']} • Passage:{a['passage_title']} • Q:{a['question_text']} • Ans:{a['student_answer']} • Correct:{a['correct']}</div>"
    html += "<a class='btn' href='/teacher/students'>Back</a>"
    return render_page(html)

@app.route("/teacher/download_pdf_classwise")
def teacher_download_pdf_classwise():
    if "teacher" not in session:
        return redirect("/login")
    conn = get_db()
    rows = conn.execute("""
      SELECT s.username, s.name, s.grade, s.class_section, qz.title as quiz_title, a.correct, a.created_at
      FROM attempts a
      JOIN students s ON a.student_id = s.id
      JOIN quizzes qz ON a.quiz_id = qz.id
      ORDER BY s.grade, s.class_section, s.username, a.created_at DESC
    """).fetchall()
    conn.close()
    if not rows:
        return render_page("<p class='muted'>No attempt data available to export.</p><a class='btn' href='/teacher/dashboard'>Back</a>")
    import pandas as pd
    df = pd.DataFrame([dict(r) for r in rows])
    grouped = df.groupby(["grade","class_section","username","name"]).agg(
        attempts=pd.NamedAgg(column="correct", aggfunc="count"),
        total_correct=pd.NamedAgg(column="correct", aggfunc="sum")
    ).reset_index()
    grouped["percent"] = (grouped["total_correct"] / grouped["attempts"] * 100).round(2)
    html = "<html><head><meta charset='utf-8'><style>table{width:100%;border-collapse:collapse}th,td{border:1px solid #ccc;padding:6px;font-size:12px}</style></head><body>"
    html += f"<h1>Classwise Student Report</h1><p>Generated: {datetime.utcnow().isoformat()}</p>"
    for (grade, cls), group in grouped.groupby(["grade","class_section"]):
        html += f"<h2>Grade: {grade} — Class: {cls or 'N/A'}</h2>"
        html += "<table><tr><th>Username</th><th>Name</th><th>Attempts</th><th>Correct</th><th>Percent</th></tr>"
        for _, r in group.iterrows():
            html += f"<tr><td>{r['username']}</td><td>{r['name']}</td><td>{r['attempts']}</td><td>{r['total_correct']}</td><td>{r['percent']}%</td></tr>"
        html += "</table>"
    html += "</body></html>"
    # Convert to PDF bytes using xhtml2pdf/pisa if available, otherwise return HTML as fallback
    try:
        from xhtml2pdf import pisa
        pdf_out = io.BytesIO()
        pisa.CreatePDF(src=html, dest=pdf_out)
        pdf_out.seek(0)
        return send_file(pdf_out, as_attachment=True, download_name="classwise_report.pdf", mimetype="application/pdf")
    except Exception:
        # fallback: return HTML
        return html

# ---------------- Run ----------------
if __name__ == "__main__":
    print("Ambassador Quiz App running at http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
