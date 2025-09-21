# app.py
from flask import Flask, request, redirect, session, render_template_string, send_file, url_for
import sqlite3
import re
import io
import base64
from pathlib import Path
from werkzeug.utils import secure_filename
import plotly.graph_objects as go
from xhtml2pdf import pisa

app = Flask(__name__)
app.secret_key = "supersecret"

# ---------------- config (no os) ----------------
UPLOAD_DIR = Path("static") / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = "quiz.db"

# simple teacher passkeys
TEACHER_PASSKEYS = {"teacher1": "math123", "teacher2": "science456", "admin": "supersecret"}

# ----------------- DB helpers & init -----------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            grade TEXT,
            gender TEXT,
            class_section TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            subject TEXT,
            grade TEXT,
            time_limit_seconds INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS passages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            text_content TEXT,
            image_path TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER,
            passage_id INTEGER,
            text TEXT,
            correct TEXT,
            option_a TEXT,
            option_b TEXT,
            option_c TEXT,
            option_d TEXT,
            qtype TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            quiz_id INTEGER,
            question_id INTEGER,
            student_answer TEXT,
            correct INTEGER
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ----------------- helpers -----------------
def render_page(content, title="Ambassador Quiz App"):
    # include Plotly via CDN so make_plot can produce HTML fragments
    html = f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8"/>
        <title>{title}</title>
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        <style>
          body{{font-family:Arial, sans-serif; background:#f5f7fb; margin:0; padding:18px;}}
          .card{{max-width:1100px; margin:18px auto; background:#fff; padding:18px; border-radius:10px; box-shadow:0 6px 20px rgba(0,0,0,0.06)}}
          h1,h2{{text-align:center; margin:8px 0}}
          .btn{{display:inline-block;padding:8px 14px;border-radius:6px;background:#2b8cff;color:#fff;text-decoration:none;border:none;cursor:pointer}}
          .muted{{color:#6b7280;font-size:14px}}
          input,textarea,select{{width:100%;padding:8px;margin:8px 0;border-radius:6px;border:1px solid #ddd;box-sizing:border-box}}
          .row{{display:flex;gap:12px}}
          .col{{flex:1}}
          img.responsive{{max-width:100%;height:auto;border-radius:6px;margin-top:8px}}
          .small{{font-size:13px;color:#555}}
          @media(max-width:900px){.row{flex-direction:column}}
        </style>
      </head>
      <body>
        <div class="card">
          {content}
        </div>
      </body>
    </html>
    """
    return render_template_string(html)

def normalize_words(text):
    return re.findall(r"\w+", (text or "").lower())

def check_similarity(ans, correct, threshold=0.6):
    """keyword overlap: matches/len(correct_words) >= threshold => correct"""
    if not ans or not correct:
        return 0
    a = normalize_words(ans)
    c = normalize_words(correct)
    if not c:
        return 0
    matches = sum(1 for w in c if w in a)
    ratio = matches / len(c)
    return 1 if ratio >= threshold else 0

def make_plotly_bar(labels, values, title, div_id):
    fig = go.Figure([go.Bar(x=list(labels), y=list(values), marker_color="skyblue")])
    fig.update_layout(title=title, yaxis=dict(title="Avg (%)", range=[0,100]), margin=dict(l=20,r=20,t=40,b=30), height=300)
    return fig.to_html(full_html=False, include_plotlyjs=False, div_id=div_id)

def html_to_pdf_bytes(source_html: str) -> io.BytesIO:
    """Render HTML string to PDF bytes using xhtml2pdf (pisa). Returns BytesIO."""
    result = io.BytesIO()
    # pisa.CreatePDF accepts src as HTML string
    pisa_status = pisa.CreatePDF(src=source_html, dest=result)
    result.seek(0)
    return result

# ----------------- Public / Home -----------------
@app.route("/")
def home():
    conn = get_db()
    quizzes = conn.execute("SELECT * FROM quizzes ORDER BY id DESC").fetchall()
    conn.close()
    content = "<h1>Ambassador Quiz App</h1><p class='muted' style='text-align:center'>Inspire · Inquire · Innovate</p>"
    content += "<div style='text-align:center;margin-bottom:12px'>"
    content += "<a class='btn' href='/signup/student'>Student Sign Up</a> "
    content += "<a class='btn' href='/login/student'>Student Login</a> "
    content += "<a class='btn' href='/login/teacher'>Teacher Login</a></div>"
    content += "<h3>Available Quizzes</h3>"
    if quizzes:
        for q in quizzes:
            content += f"<div style='padding:10px;border:1px solid #eee;margin:8px 0;border-radius:6px;display:flex;justify-content:space-between;align-items:center'>"
            content += f"<div><strong>{q['title']}</strong><div class='small'>{q['subject']} • Grade {q['grade']}</div></div>"
            content += f"<div><a class='btn' href='/quiz/select/{q['id']}'>Take Quiz</a></div></div>"
    else:
        content += "<p class='muted'>No quizzes created yet.</p>"
    return render_page(content)

# ----------------- Student signup/login -----------------
@app.route("/signup/student", methods=["GET","POST"])
def signup_student():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        grade = request.form["grade"].strip()
        gender = request.form.get("gender","").strip()
        class_section = request.form.get("class_section","").strip()
        try:
            conn = get_db()
            conn.execute("INSERT INTO students(username,password,grade,gender,class_section) VALUES (?,?,?,?,?)",
                         (username,password,grade,gender,class_section))
            conn.commit(); conn.close()
            return redirect("/login/student")
        except sqlite3.IntegrityError:
            return render_page("<h3>Username already exists</h3><a class='btn' href='/signup/student'>Back</a>")
    form = """
      <h2>Student Sign Up</h2>
      <form method="post">
        <input name="username" placeholder="Username" required>
        <input name="password" placeholder="Password" required type="password">
        <input name="grade" placeholder="Grade (e.g. 7)" required>
        <input name="class_section" placeholder="Class/Section (optional)">
        <select name="gender"><option value="">Select Gender</option><option>Male</option><option>Female</option><option>Other</option></select>
        <button class='btn' type="submit">Sign Up</button>
      </form>
    """
    return render_page(form)

@app.route("/login/student", methods=["GET","POST"])
def login_student():
    if request.method=="POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        conn = get_db()
        s = conn.execute("SELECT * FROM students WHERE username=? AND password=?", (username,password)).fetchone()
        conn.close()
        if s:
            session["student_id"] = s["id"]; session["grade"] = s["grade"]
            return redirect("/")
        else:
            return render_page("<h3>Invalid credentials</h3><a class='btn' href='/login/student'>Back</a>")
    return render_page("""
      <h2>Student Login</h2>
      <form method="post">
        <input name="username" placeholder="Username" required>
        <input name="password" placeholder="Password" type="password" required>
        <button class='btn' type="submit">Login</button>
      </form>
    """)

# ----------------- Teacher login -----------------
@app.route("/login/teacher", methods=["GET","POST"])
def login_teacher():
    if request.method=="POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        if username in TEACHER_PASSKEYS and TEACHER_PASSKEYS[username]==password:
            session["teacher"] = username
            return redirect("/teacher/dashboard")
        return render_page("<h3>Invalid teacher credentials</h3><a class='btn' href='/login/teacher'>Back</a>")
    return render_page("""
      <h2>Teacher Login</h2>
      <form method="post">
        <input name="username" placeholder="Teacher username" required>
        <input name="password" placeholder="Passkey" type="password" required>
        <button class='btn' type="submit">Login</button>
      </form>
    """)

# ----------------- Teacher create quiz -----------------
@app.route("/teacher/create_quiz", methods=["GET","POST"])
def teacher_create_quiz():
    if "teacher" not in session: return redirect("/login/teacher")
    if request.method=="POST":
        title = request.form["title"].strip()
        subject = request.form["subject"].strip()
        grade = request.form["grade"].strip()
        time_limit = int(request.form.get("time_limit_seconds") or 0)
        conn = get_db()
        cur = conn.execute("INSERT INTO quizzes(title,subject,grade,time_limit_seconds) VALUES (?,?,?,?)",
                           (title,subject,grade,time_limit))
        conn.commit(); quiz_id = cur.lastrowid; conn.close()
        return redirect(f"/teacher/add_question/{quiz_id}")
    return render_page("""
      <h2>Create Quiz</h2>
      <form method="post">
        <input name="title" placeholder="Quiz title" required>
        <input name="subject" placeholder="Subject" required>
        <input name="grade" placeholder="Grade" required>
        <input name="time_limit_seconds" placeholder="Time limit (seconds, optional)">
        <button class='btn' type="submit">Create Quiz</button>
      </form>
    """)

# ----------------- Teacher create passage -----------------
@app.route("/teacher/create_passage", methods=["GET","POST"])
def teacher_create_passage():
    if "teacher" not in session: return redirect("/login/teacher")
    if request.method=="POST":
        title = request.form.get("title","").strip()
        text_content = request.form.get("text_content","").strip()
        img = request.files.get("image")
        image_path = None
        if img and img.filename:
            fname = secure_filename(img.filename)
            saved = UPLOAD_DIR / fname
            img.save(str(saved))
            image_path = "/" + str(saved).replace("\\","/")
        conn = get_db()
        cur = conn.execute("INSERT INTO passages(title,text_content,image_path) VALUES (?,?,?)",
                           (title,text_content,image_path))
        conn.commit(); pid = cur.lastrowid; conn.close()
        return render_page(f"<h3>Passage created (id={pid})</h3><a class='btn' href='/teacher/dashboard'>Back</a>")
    return render_page("""
      <h2>Create Passage (PISA-style)</h2>
      <form method="post" enctype="multipart/form-data">
        <input name="title" placeholder="Passage title (optional)">
        <textarea name="text_content" rows="6" placeholder="Passage text (optional)"></textarea>
        <label>Upload image (optional):</label><input type="file" name="image">
        <button class='btn' type="submit">Create Passage</button>
      </form>
    """)

# ----------------- Teacher add question -----------------
@app.route("/teacher/add_question/<int:quiz_id>", methods=["GET","POST"])
def teacher_add_question(quiz_id):
    if "teacher" not in session: return redirect("/login/teacher")
    conn = get_db()
    passages = conn.execute("SELECT * FROM passages ORDER BY id DESC").fetchall()
    quizzes = conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    conn.close()
    if request.method=="POST":
        passage_id = request.form.get("passage_id") or None
        passage_id = int(passage_id) if passage_id else None
        text = request.form["text"]
        correct = request.form["correct"]
        qtype = request.form["qtype"]
        a = request.form.get("option_a") or None
        b = request.form.get("option_b") or None
        c = request.form.get("option_c") or None
        d = request.form.get("option_d") or None
        conn = get_db()
        conn.execute("""INSERT INTO questions(quiz_id,passage_id,text,correct,option_a,option_b,option_c,option_d,qtype)
                        VALUES (?,?,?,?,?,?,?,?,?)""", (quiz_id,passage_id,text,correct,a,b,c,d,qtype))
        conn.commit(); conn.close()
        return render_page(f"<h3>Question added to quiz #{quiz_id}</h3><a class='btn' href='/teacher/add_question/{quiz_id}'>Add Another</a> <a class='btn' href='/teacher/dashboard'>Dashboard</a>")
    # build passage select
    sel = "<select name='passage_id'><option value=''>-- no passage --</option>"
    for p in passages:
        title = p["title"] or f"Passage {p['id']}"
        sel += f"<option value='{p['id']}'>{title}</option>"
    sel += "</select>"
    return render_page(f"""
      <h2>Add Question to Quiz #{quiz_id}</h2>
      <form method="post">
        <label>Associate passage (optional)</label>{sel}
        <input name="text" placeholder="Question text" required>
        <input name="correct" placeholder="Correct answer (for MCQ put option text / for subjective put keywords)" required>
        <select name="qtype"><option value="mcq">MCQ</option><option value="subjective">Subjective</option></select>
        <div style="display:flex;gap:8px"><input name="option_a" placeholder="Option A"><input name="option_b" placeholder="Option B"></div>
        <div style="display:flex;gap:8px"><input name="option_c" placeholder="Option C"><input name="option_d" placeholder="Option D"></div>
        <button class='btn' type="submit">Add Question</button>
      </form>
    """)

# ----------------- Student: select quiz (grade) -----------------
@app.route("/quiz/select/<int:quiz_id>")
def quiz_select(quiz_id):
    # simple redirect to take quiz
    return redirect(url_for("take_quiz", quiz_id=quiz_id))

# ----------------- Take quiz (PISA-style one question at a time) -----------------
@app.route("/quiz/take/<int:quiz_id>", methods=["GET","POST"])
def take_quiz(quiz_id):
    if "student_id" not in session:
        return redirect("/login/student")
    conn = get_db()
    quiz = conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    if not quiz:
        conn.close()
        return render_page("<h3>Quiz not found</h3><a class='btn' href='/'>Home</a>")
    questions = conn.execute("SELECT * FROM questions WHERE quiz_id=? ORDER BY passage_id, id", (quiz_id,)).fetchall()
    # collect passages used
    pids = sorted({q["passage_id"] for q in questions if q["passage_id"]})
    passages = {}
    for pid in pids:
        p = conn.execute("SELECT * FROM passages WHERE id=?", (pid,)).fetchone()
        if p:
            passages[pid] = p
    conn.close()

    q_index = int(request.args.get("q", 0))
    if q_index >= len(questions):
        return render_page(f"<h3>Completed: {quiz['title']}</h3><a class='btn' href='/'>Back to Home</a>")

    question = questions[q_index]
    if request.method=="POST":
        ans = (request.form.get("answer") or "").strip()
        if (question["qtype"] or "").lower() == "mcq":
            correct_flag = 1 if ans.lower() == (question["correct"] or "").lower() else 0
        else:
            correct_flag = check_similarity(ans, question["correct"])
        conn = get_db()
        conn.execute("INSERT INTO attempts(student_id,quiz_id,question_id,student_answer,correct) VALUES (?,?,?,?,?)",
                     (session["student_id"], quiz_id, question["id"], ans, correct_flag))
        conn.commit(); conn.close()
        feedback = "✅ Correct!" if correct_flag else f"❌ Incorrect — Correct: {question['correct']}"
        next_q = q_index + 1
        return render_page(f"<h3>{feedback}</h3><a class='btn' href='{url_for('take_quiz', quiz_id=quiz_id, q=next_q)}'>Next</a>")

    # render left (passage) and right (question)
    left_html = "<div class='muted'>No passage for this question.</div>"
    if question["passage_id"]:
        p = passages.get(question["passage_id"])
        if p:
            left_html = f"<h3>{p['title'] or 'Passage'}</h3>"
            if p["text_content"]:
                left_html += f"<div style='white-space:pre-wrap'>{p['text_content']}</div>"
            if p["image_path"]:
                left_html += f"<img class='responsive' src='{p['image_path']}' alt='passage image'>"

    right_html = f"<h3>Q{q_index+1}. {question['text']}</h3><form method='post'>"
    if (question["qtype"] or "").lower() == "mcq":
        for opt in ("a","b","c","d"):
            v = question.get(f"option_{opt}")
            if v:
                right_html += f"<label><input type='radio' name='answer' value='{v}'> {v}</label><br>"
    else:
        right_html += "<textarea name='answer' rows='5' style='width:100%'></textarea><br>"
    right_html += "<button class='btn' type='submit'>Submit Answer</button></form>"

    page = f"""
      <h2>Quiz: {quiz['title']} — {quiz['subject']} (Grade {quiz['grade']})</h2>
      <div class="row" style="margin-top:12px">
        <div class="col" style="flex:2;background:#fff;padding:12px;border-radius:6px">{left_html}</div>
        <div class="col" style="flex:1;background:#fff;padding:12px;border-radius:6px">{right_html}</div>
      </div>
    """
    return render_page(page)

# ----------------- Teacher dashboard (Plotly charts + manage) -----------------
@app.route("/teacher/dashboard")
def teacher_dashboard():
    if "teacher" not in session:
        return redirect("/login/teacher")
    conn = get_db()
    # grade averages
    grade_rows = conn.execute("""
        SELECT s.grade as label, AVG(a.correct)*100.0 as pct
        FROM attempts a JOIN students s ON a.student_id = s.id
        GROUP BY s.grade
    """).fetchall()
    # subject averages (from quizzes)
    subject_rows = conn.execute("""
        SELECT qz.subject as label, AVG(a.correct)*100.0 as pct
        FROM attempts a JOIN quizzes qz ON a.quiz_id = qz.id
        GROUP BY qz.subject
    """).fetchall()
    # quiz averages
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
        grade_chart = make_plotly_bar(labels, vals, "Average Score by Grade", "grade_plot")

    if subject_rows:
        labels = [r["label"] or "N/A" for r in subject_rows]
        vals = [round(r["pct"] or 0,2) for r in subject_rows]
        subject_chart = make_plotly_bar(labels, vals, "Average Score by Subject", "subject_plot")

    if quiz_rows:
        labels = [r["label"] or "N/A" for r in quiz_rows]
        vals = [round(r["pct"] or 0,2) for r in quiz_rows]
        quiz_chart = make_plotly_bar(labels, vals, "Average Score by Quiz", "quiz_plot")

    html = "<h2>Teacher Dashboard</h2>"
    html += "<div style='display:flex;gap:12px;flex-wrap:wrap'>"
    html += f"<div style='flex:1 1 320px;background:#fff;padding:12px;border-radius:6px'>{grade_chart}</div>"
    html += f"<div style='flex:1 1 320px;background:#fff;padding:12px;border-radius:6px'>{subject_chart}</div>"
    html += f"<div style='flex:1 1 320px;background:#fff;padding:12px;border-radius:6px'>{quiz_chart}</div>"
    html += "</div>"
    html += "<div style='margin-top:12px'>"
    html += "<a class='btn' href='/teacher/create_quiz'>Create Quiz</a> "
    html += "<a class='btn' href='/teacher/create_passage'>Create Passage</a> "
    html += "<a class='btn' href='/teacher/list_quizzes'>Manage Quizzes</a> "
    html += "<a class='btn' href='/teacher/students'>Student History</a> "
    html += "<a class='btn' href='/teacher/download_pdf_all'>Download Attempts (PDF)</a>"
    html += "</div>"
    return render_page(html)

# ----------------- Teacher list & view quizzes -----------------
@app.route("/teacher/list_quizzes")
def teacher_list_quizzes():
    if "teacher" not in session: return redirect("/login/teacher")
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
    if "teacher" not in session: return redirect("/login/teacher")
    conn = get_db()
    quiz = conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    qs = conn.execute("SELECT * FROM questions WHERE quiz_id=? ORDER BY passage_id,id", (quiz_id,)).fetchall()
    conn.close()
    if not quiz:
        return render_page("<h3>Quiz not found</h3><a class='btn' href='/teacher/list_quizzes'>Back</a>")
    html = f"<h2>{quiz['title']} — {quiz['subject']} (Grade {quiz['grade']})</h2><h3>Questions</h3>"
    if not qs:
        html += "<p class='muted'>No questions yet</p>"
    for q in qs:
        html += f"<div style='padding:8px;border:1px solid #eee;margin:8px 0;border-radius:6px'><strong>Q{q['id']}</strong>: {q['text']}<div class='muted'>type: {q['qtype']} passage: {q['passage_id'] or 'none'}</div></div>"
    html += "<a class='btn' href='/teacher/list_quizzes'>Back</a>"
    return render_page(html)

# ----------------- Teacher students & per-student detail -----------------
@app.route("/teacher/students")
def teacher_students():
    if "teacher" not in session: return redirect("/login/teacher")
    conn = get_db()
    students = conn.execute("SELECT * FROM students ORDER BY grade, class_section, username").fetchall()
    conn.close()
    html = "<h2>Students</h2>"
    for s in students:
        html += f"<div style='padding:8px;border:1px solid #eee;margin:8px 0;border-radius:6px;display:flex;justify-content:space-between'>"
        html += f"<div><strong>{s['username']}</strong><div class='muted'>Grade:{s['grade']} • Class:{s['class_section']}</div></div>"
        html += f"<div><a class='btn' href='/teacher/student/{s['id']}'>View History</a></div></div>"
    html += "<a class='btn' href='/teacher/dashboard'>Back</a>"
    return render_page(html)

@app.route("/teacher/student/<int:student_id>")
def teacher_student_detail(student_id):
    if "teacher" not in session: return redirect("/login/teacher")
    conn = get_db()
    student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    attempts = conn.execute("""
        SELECT a.*, q.text as question_text, qz.title as quiz_title
        FROM attempts a
        LEFT JOIN questions q ON a.question_id = q.id
        LEFT JOIN quizzes qz ON a.quiz_id = qz.id
        WHERE a.student_id = ?
        ORDER BY a.id DESC
    """, (student_id,)).fetchall()
    summary = conn.execute("""
        SELECT qz.id as quiz_id, qz.title, SUM(a.correct) as correct_count, COUNT(a.id) as total
        FROM attempts a JOIN quizzes qz ON a.quiz_id = qz.id
        WHERE a.student_id = ?
        GROUP BY qz.id
    """, (student_id,)).fetchall()
    conn.close()
    if not student:
        return render_page("<h3>Student not found</h3><a class='btn' href='/teacher/students'>Back</a>")
    html = f"<h2>History: {student['username']}</h2><h3>Quiz Summaries</h3>"
    if summary:
        for s in summary:
            pct = round((s["correct_count"]/s["total"])*100,2) if s["total"]>0 else 0
            html += f"<div class='card'><strong>{s['title']}</strong> — {s['correct_count']}/{s['total']} correct ({pct}%)</div>"
    else:
        html += "<p class='muted'>No attempts yet</p>"
    html += "<h3>All Attempts</h3>"
    for a in attempts:
        html += f"<div style='padding:6px;border:1px solid #eee;margin:6px 0;border-radius:6px'>Quiz: {a['quiz_title']} — Q: {a['question_text']} — Ans: {a['student_answer']} — Correct: {a['correct']}</div>"
    html += "<a class='btn' href='/teacher/students'>Back</a>"
    return render_page(html)

# ----------------- Teacher: download attempts PDF (xhtml2pdf) -----------------
@app.route("/teacher/download_pdf_all")
def teacher_download_pdf_all():
    if "teacher" not in session: return redirect("/login/teacher")
    conn = get_db()
    attempts = conn.execute("""SELECT s.username, s.grade, s.class_section, qz.title as quiz_title, a.correct
                               FROM attempts a
                               JOIN students s ON a.student_id = s.id
                               JOIN quizzes qz ON a.quiz_id = qz.id
                               ORDER BY s.grade, s.username""").fetchall()
    conn.close()
    # build HTML table
    html = "<html><head><meta charset='utf-8'><style>table{width:100%;border-collapse:collapse}td,th{border:1px solid #ccc;padding:6px;font-size:11px}</style></head><body>"
    html += "<h2>Student Attempts Report</h2><table><tr><th>Username</th><th>Grade</th><th>Class</th><th>Quiz</th><th>Correct</th></tr>"
    for r in attempts:
        html += f"<tr><td>{r['username']}</td><td>{r['grade']}</td><td>{r['class_section']}</td><td>{r['quiz_title']}</td><td>{r['correct']}</td></tr>"
    html += "</table></body></html>"
    pdf_bytes = html_to_pdf_bytes(html)
    return send_file(pdf_bytes, as_attachment=True, download_name="attempts_report.pdf", mimetype="application/pdf")

# ----------------- logout -----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ----------------- run -----------------
if __name__ == "__main__":
    print("Ambassador Quiz App running at http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
