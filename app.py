from flask import Flask, request, redirect, session, render_template_string, send_file, url_for
import sqlite3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import io
import base64
import re
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from werkzeug.utils import secure_filename
from pathlib import Path

app = Flask(__name__)
app.secret_key = "supersecret"

# teacher passkeys
TEACHER_PASSKEYS = {"teacher1": "math123", "teacher2": "science456", "admin": "supersecret"}

# ensure upload folder exists (no `os` module)
UPLOAD_DIR = Path("static") / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = "quiz.db"

# ---------- DB helpers & init ----------
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
        )
    """)
    # quizzes
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            subject TEXT,
            grade TEXT
        )
    """)
    # passages (for PISA-style reading / image references)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS passages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            text_content TEXT,
            image_path TEXT
        )
    """)
    # questions belong to a quiz and optionally reference a passage
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
    # attempts (store quiz_id for reporting)
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

# ---------- Helpers ----------
def render_page(content, title="Ambassador Quiz App"):
    page = f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8"/>
        <title>{title}</title>
        <style>
          body{{font-family:Arial, sans-serif; background:#f4f6f8; margin:0; padding:20px;}}
          .card{{max-width:1000px; margin:16px auto; background:#fff; padding:18px; border-radius:8px; box-shadow:0 6px 18px rgba(0,0,0,0.06);}}
          h1,h2{{text-align:center;}}
          .btn{{display:inline-block;padding:8px 14px;border-radius:6px;background:#2b8cff;color:#fff;text-decoration:none;border:none;cursor:pointer}}
          .muted{{color:#6b7280;font-size:14px}}
          input,textarea,select{{width:100%;padding:8px;margin:8px 0;border:1px solid #ddd;border-radius:6px;box-sizing:border-box}}
          .row{{display:flex;gap:12px}}
          .col{{flex:1}}
          img.responsive{{max-width:100%;height:auto;border-radius:6px;margin-top:8px}}
          @media(max-width:800px){.row{flex-direction:column}}
        </style>
      </head>
      <body>
        <div class="card">
          {content}
        </div>
      </body>
    </html>
    """
    return render_template_string(page)

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

# ---------- Public routes ----------
@app.route("/")
def home():
    conn = get_db()
    quizzes = conn.execute("SELECT * FROM quizzes ORDER BY id DESC").fetchall()
    conn.close()
    html = "<h1>Ambassador Quiz App</h1><p class='muted' style='text-align:center'>Inspire · Inquire · Innovate</p>"
    html += "<div style='text-align:center;margin-bottom:12px'>"
    html += "<a class='btn' href='/signup/student'>Student Sign Up</a> "
    html += "<a class='btn' href='/login/student'>Student Login</a> "
    html += "<a class='btn' href='/login/teacher'>Teacher Login</a></div>"
    html += "<h3>Available Quizzes</h3>"
    if quizzes:
        for q in quizzes:
            html += f"<div style='padding:10px;border:1px solid #eee;margin:8px 0;border-radius:6px;display:flex;justify-content:space-between;align-items:center'>"
            html += f"<div><strong>{q['title']}</strong> <span class='muted'>(Subject: {q['subject']} • Grade: {q['grade']})</span></div>"
            html += f"<div><a class='btn' href='/quiz/select/{q['id']}'>Take Quiz</a></div></div>"
    else:
        html += "<p class='muted'>No quizzes created yet.</p>"
    return render_page(html)

# ---------- Student signup / login ----------
@app.route("/signup/student", methods=["GET","POST"])
def signup_student():
    if request.method=="POST":
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
            return render_page("<h3>Username taken</h3><a class='btn' href='/signup/student'>Back</a>")
    form = """
      <h2>Student Sign Up</h2>
      <form method="post">
        <input name="username" placeholder="Username" required>
        <input name="password" placeholder="Password" required type="password">
        <input name="grade" placeholder="Grade (e.g. 7)" required>
        <input name="class_section" placeholder="Class/Section (e.g. A)">
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

# ---------- Teacher login ----------
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

# ---------- Teacher: create quiz ----------
@app.route("/teacher/create_quiz", methods=["GET","POST"])
def create_quiz():
    if "teacher" not in session: return redirect("/login/teacher")
    if request.method=="POST":
        title = request.form["title"].strip()
        subject = request.form["subject"].strip()
        grade = request.form["grade"].strip()
        conn = get_db()
        cur = conn.execute("INSERT INTO quizzes(title,subject,grade) VALUES (?,?,?)",(title,subject,grade))
        conn.commit(); quiz_id = cur.lastrowid; conn.close()
        return redirect(f"/teacher/add_question/{quiz_id}")
    return render_page("""
      <h2>Create Quiz</h2>
      <form method="post">
        <input name="title" placeholder="Quiz title" required>
        <input name="subject" placeholder="Subject" required>
        <input name="grade" placeholder="Grade" required>
        <button class='btn' type="submit">Create Quiz</button>
      </form>
    """)

# ---------- Teacher: create passage ----------
@app.route("/teacher/create_passage", methods=["GET","POST"])
def create_passage():
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
      <h2>Create Passage (for a set of questions)</h2>
      <form method="post" enctype="multipart/form-data">
        <input name="title" placeholder="Passage title (optional)">
        <textarea name="text_content" rows="6" placeholder="Paste passage text here (optional)"></textarea>
        <label>Upload image (optional):</label><input type="file" name="image">
        <button class='btn' type="submit">Create Passage</button>
      </form>
    """)

# ---------- Teacher: add question (select quiz and optional passage) ----------
@app.route("/teacher/add_question/<int:quiz_id>", methods=["GET","POST"])
def add_question(quiz_id):
    if "teacher" not in session: return redirect("/login/teacher")
    conn = get_db()
    passages = conn.execute("SELECT * FROM passages ORDER BY id DESC").fetchall()
    conn.close()
    if request.method=="POST":
        passage_id = request.form.get("passage_id") or None
        if passage_id:
            passage_id = int(passage_id)
        text = request.form["text"]
        correct = request.form["correct"]
        qtype = request.form["qtype"]
        a = request.form.get("option_a") or None
        b = request.form.get("option_b") or None
        c = request.form.get("option_c") or None
        d = request.form.get("option_d") or None
        conn = get_db()
        conn.execute("""INSERT INTO questions(quiz_id,passage_id,text,correct,option_a,option_b,option_c,option_d,qtype)
                        VALUES (?,?,?,?,?,?,?,?,?)""",(quiz_id,passage_id,text,correct,a,b,c,d,qtype))
        conn.commit(); conn.close()
        return render_page(f"<p>Question added to quiz #{quiz_id}</p><a class='btn' href='/teacher/add_question/{quiz_id}'>Add Another</a> <a class='btn' href='/teacher/dashboard'>Dashboard</a>")
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
        <input name="correct" placeholder="Correct answer (exact text for MCQ or keywords for descriptive)" required>
        <select name="qtype"><option value="mcq">MCQ</option><option value="subjective">Subjective</option></select>
        <input name="option_a" placeholder="Option A (MCQ)"><input name="option_b" placeholder="Option B (MCQ)">
        <input name="option_c" placeholder="Option C (MCQ)"><input name="option_d" placeholder="Option D (MCQ)">
        <button class='btn' type="submit">Add Question</button>
      </form>
    """)

# ---------- Student: select quiz for their grade ----------
@app.route("/quiz/select")
def select_quiz():
    if "student_id" not in session: return redirect("/login/student")
    grade = session.get("grade","")
    conn = get_db()
    quizzes = conn.execute("SELECT * FROM quizzes WHERE grade=?", (grade,)).fetchall()
    conn.close()
    html = "<h2>Select Quiz</h2>"
    if not quizzes:
        html += "<p class='muted'>No quizzes for your grade yet.</p>"
    for q in quizzes:
        html += f"<div style='padding:10px;border:1px solid #eee;margin:8px 0;border-radius:6px;display:flex;justify-content:space-between;align-items:center'>"
        html += f"<div><strong>{q['title']}</strong> <span class='muted'>({q['subject']})</span></div>"
        html += f"<div><a class='btn' href='/quiz/take/{q['id']}'>Start</a></div></div>"
    return render_page(html)

# ---------- Take quiz (PISA-style: passage left, questions right; one question at a time) ----------
@app.route("/quiz/take/<int:quiz_id>", methods=["GET","POST"])
def take_quiz(quiz_id):
    if "student_id" not in session:
        return redirect("/login/student")
    conn = get_db()
    quiz = conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    if not quiz:
        conn.close()
        return render_page("<h3>Quiz not found</h3><a class='btn' href='/'>Home</a>")
    # load questions ordered by passage_id then id so passage-related questions cluster
    questions = conn.execute("SELECT * FROM questions WHERE quiz_id=? ORDER BY passage_id, id", (quiz_id,)).fetchall()
    # map passage details
    passage_ids = sorted({q["passage_id"] for q in questions if q["passage_id"]})
    passages = {}
    for pid in passage_ids:
        p = conn.execute("SELECT * FROM passages WHERE id=?", (pid,)).fetchone()
        if p:
            passages[pid] = p
    conn.close()

    # per-question index
    q_index = int(request.args.get("q", 0))
    if q_index >= len(questions):
        return render_page(f"<h3>Completed: {quiz['title']}</h3><a class='btn' href='/'>Back to Home</a>")

    question = questions[q_index]
    # handle submission for single question, then show feedback and link to next
    if request.method=="POST":
        ans = (request.form.get("answer") or "").strip()
        if (question["qtype"] or "").lower() in ("mcq","mcq"):
            correct_flag = 1 if ans.lower() == (question["correct"] or "").lower() else 0
        else:
            correct_flag = check_similarity(ans, question["correct"])
        conn = get_db()
        conn.execute("INSERT INTO attempts(student_id, quiz_id, question_id, student_answer, correct) VALUES (?,?,?,?,?)",
                     (session["student_id"], quiz_id, question["id"], ans, correct_flag))
        conn.commit(); conn.close()
        feedback = "✅ Correct!" if correct_flag else f"❌ Incorrect. Correct: {question['correct']}"
        next_q = q_index + 1
        return render_page(f"<h3>{feedback}</h3><a class='btn' href='{url_for('take_quiz', quiz_id=quiz_id, q=next_q)}'>Next</a>")

    # render PISA-style layout: left = passage (if any), right = question & options
    left_html = "<div><p class='muted'>No passage for this question.</p></div>"
    if question["passage_id"]:
        p = passages.get(question["passage_id"])
        if p:
            left_html = f"<h3>{p['title'] or 'Passage'}</h3>"
            if p["text_content"]:
                left_html += f"<div style='white-space:pre-wrap'>{p['text_content']}</div>"
            if p["image_path"]:
                left_html += f"<img class='responsive' src='{p['image_path']}' alt='passage image'>"

    right_html = f"<h3>Q{q_index+1}. {question['text']}</h3>"
    right_html += "<form method='post'>"
    if (question["qtype"] or "").lower() in ("mcq","mcq"):
        for opt in ("a","b","c","d"):
            val = question.get(f"option_{opt}")
            if val:
                right_html += f"<label><input type='radio' name='answer' value='{val}'> {val}</label><br>"
    else:
        right_html += "<textarea name='answer' rows='5' style='width:100%'></textarea><br>"
    right_html += "<button class='btn' type='submit'>Submit Answer</button></form>"

    page = f"""
      <h2>Quiz: {quiz['title']} — {quiz['subject']} (Grade {quiz['grade']})</h2>
      <div class='row' style='margin-top:12px'>
        <div class='col' style='flex:2;background:#fff;padding:12px;border-radius:6px'>{left_html}</div>
        <div class='col' style='flex:1;background:#fff;padding:12px;border-radius:6px'>{right_html}</div>
      </div>
    """
    return render_page(page)

# ---------- Teacher dashboard (enhanced graphs + manage) ----------
@app.route("/teacher/dashboard")
def teacher_dashboard():
    if "teacher" not in session: return redirect("/login/teacher")
    conn = get_db()
    # grade-level averages
    grade_rows = conn.execute("""
        SELECT s.grade as label, AVG(a.correct)*100.0 as pct
        FROM attempts a JOIN students s ON a.student_id = s.id
        GROUP BY s.grade
    """).fetchall()
    # subject-level averages (from quiz)
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
    # list quizzes
    quizzes = conn.execute("SELECT * FROM quizzes ORDER BY id DESC").fetchall()
    conn.close()

    def render_chart(rows, title):
        if not rows:
            return "<p class='muted'>No data</p>"
        labels = [r["label"] or "N/A" for r in rows]
        vals = [round(r["pct"] or 0,2) for r in rows]
        fig, ax = plt.subplots(figsize=(6,2.2))
        ax.bar(range(len(vals)), vals)
        ax.set_ylim(0,100)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
        ax.set_title(title, fontsize=10)
        buf = io.BytesIO(); fig.tight_layout(); plt.savefig(buf, format="png"); buf.seek(0)
        data = base64.b64encode(buf.getvalue()).decode(); plt.close(fig)
        return f"<img src='data:image/png;base64,{data}' style='max-width:100%'>"

    grade_chart = render_chart(grade_rows, "Average Score by Grade")
    subject_chart = render_chart(subject_rows, "Average Score by Subject")
    quiz_chart = render_chart(quiz_rows, "Average Score by Quiz")

    html = "<h2>Teacher Dashboard</h2>"
    html += "<div style='display:flex;gap:12px;flex-wrap:wrap'>"
    html += f"<div style='flex:1 1 300px;background:#fff;padding:12px;border-radius:6px'>{grade_chart}</div>"
    html += f"<div style='flex:1 1 300px;background:#fff;padding:12px;border-radius:6px'>{subject_chart}</div>"
    html += f"<div style='flex:1 1 300px;background:#fff;padding:12px;border-radius:6px'>{quiz_chart}</div>"
    html += "</div>"
    html += "<div style='margin-top:12px'>"
    html += "<a class='btn' href='/teacher/create_quiz'>Create Quiz</a> "
    html += "<a class='btn' href='/teacher/create_passage'>Create Passage</a> "
    html += "<a class='btn' href='/teacher/list_quizzes'>Manage Quizzes</a> "
    html += "<a class='btn' href='/teacher/download_pdf_all'>Download Student Report (PDF)</a>"
    html += "</div>"
    return render_page(html)

# ---------- Teacher: list quizzes & view quiz ----------
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
    html = f"<h2>{quiz['title']} — {quiz['subject']} (Grade {quiz['grade']})</h2>"
    html += "<h3>Questions</h3>"
    if not qs:
        html += "<p class='muted'>No questions</p>"
    for q in qs:
        html += f"<div style='padding:8px;border:1px solid #eee;margin:8px 0;border-radius:6px'>Q{q['id']}: {q['text']} <div class='muted'>type: {q['qtype']}</div></div>"
    html += "<a class='btn' href='/teacher/list_quizzes'>Back</a>"
    return render_page(html)

# ---------- Teacher: per-student detail ----------
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
    # summary per quiz
    summary = conn.execute("""
        SELECT qz.id as quiz_id, qz.title, SUM(a.correct) as correct_count, COUNT(a.id) as total
        FROM attempts a JOIN quizzes qz ON a.quiz_id = qz.id
        WHERE a.student_id = ?
        GROUP BY qz.id
    """, (student_id,)).fetchall()
    conn.close()
    if not student:
        return render_page("<h3>Student not found</h3><a class='btn' href='/teacher/students'>Back</a>")
    html = f"<h2>History for {student['username']}</h2>"
    html += "<h3>Quiz Summaries</h3>"
    if summary:
        for s in summary:
            pct = round((s["correct_count"]/s["total"])*100,2) if s["total"]>0 else 0
            html += f"<div class='card'><strong>{s['title']}</strong> — {s['correct_count']}/{s['total']} correct ({pct}%)</div>"
    else:
        html += "<p class='muted'>No attempts yet</p>"
    html += "<h3>All Attempts (most recent)</h3>"
    for a in attempts:
        html += f"<div style='padding:6px;border:1px solid #eee;margin:6px 0;border-radius:6px'>Quiz: {a['quiz_title']} — Q: {a['question_text']} — Answer: {a['student_answer']} — Correct: {a['correct']}</div>"
    html += "<a class='btn' href='/teacher/students'>Back</a>"
    return render_page(html)

# ---------- Teacher: download all student report (PDF) ----------
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
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    w,h = letter
    y = h - 40
    c.setFont("Helvetica-Bold",14); c.drawString(40,y,"Student Attempts Report"); y -= 24
    c.setFont("Helvetica",10)
    for row in attempts:
        line = f"{row['username']} | Grade: {row['grade']} | Class: {row['class_section']} | Quiz: {row['quiz_title']} | Correct: {row['correct']}"
        c.drawString(40,y,line); y -= 14
        if y < 60:
            c.showPage(); y = h - 40; c.setFont("Helvetica",10)
    c.save()
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="student_attempts_report.pdf", mimetype="application/pdf")

# ---------- Logout ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------- Run ----------
if __name__ == "__main__":
    print("Ambassador Quiz App running at http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
