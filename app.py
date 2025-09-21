# app.py
from flask import Flask, request, redirect, session, render_template_string, url_for, send_file
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import io
import base64
from fpdf import FPDF
from datetime import datetime
import re
import secrets

# ---------------- App setup ----------------
app = Flask(__name__)
app.secret_key = secrets.token_hex(24)
DB = "ambassador_quiz.db"

# ---------------- Teacher passkeys ----------------
TEACHER_PASSKEYS = {
    "teacher1": "math123",
    "teacher2": "science456",
    "admin": "supersecret"
}

# ---------------- DB helpers ----------------
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT UNIQUE,
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
        grade TEXT,
        subject TEXT,
        timer_seconds INTEGER DEFAULT 0
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS passages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quiz_id INTEGER,
        title TEXT,
        content TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        passage_id INTEGER,
        text TEXT,
        qtype TEXT,
        option_a TEXT,
        option_b TEXT,
        option_c TEXT,
        option_d TEXT,
        correct TEXT,
        image_url TEXT,
        marks INTEGER DEFAULT 1
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

# ---------------- Utilities ----------------
def normalize_words(s):
    return set(re.findall(r"\w+", (s or "").lower()))

def subjective_correct(student_ans, correct_ans, threshold=0.6):
    student_words = normalize_words(student_ans)
    correct_words = normalize_words(correct_ans)
    if not correct_words:
        return False
    matches = sum(1 for w in correct_words if w in student_words)
    return (matches / len(correct_words)) >= threshold

def make_plot_base64(x_labels, y_values, title="Performance"):
    if not x_labels:
        return None
    fig, ax = plt.subplots(figsize=(6,3))
    ax.plot(x_labels, y_values, marker='o', linewidth=2)
    ax.set_title(title)
    ax.set_ylim(0,100)
    ax.set_ylabel("Score %")
    ax.set_xlabel("Attempt")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def make_bar_base64(labels, values, title="Avg by Grade"):
    if not labels:
        return None
    fig, ax = plt.subplots(figsize=(6,3))
    ax.bar(labels, values, color='skyblue')
    ax.set_ylim(0,100)
    ax.set_title(title)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def pdf_base64_student_report():
    conn = get_db()
    rows = conn.execute("""
      SELECT s.user_id, s.name, s.grade, s.class_section, s.gender,
             COUNT(a.id) AS attempts, SUM(a.correct) AS correct
      FROM students s LEFT JOIN attempts a ON s.id = a.student_id
      GROUP BY s.id
      ORDER BY s.grade, s.class_section, s.user_id
    """).fetchall()
    conn.close()
    pdf = FPDF()
    pdf.set_auto_page_break(True, margin=10)
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "Student Report", ln=True, align="C")
    pdf.ln(6)
    pdf.set_font("Arial", size=10)
    # header
    pdf.set_fill_color(240,240,240)
    w = [30, 35, 20, 20, 20, 20, 20]
    headers = ["User ID", "Name", "Grade", "Class", "Gender", "Attempts", "Correct"]
    for i, h in enumerate(headers):
        pdf.cell(w[i], 8, h, border=1, align='C', fill=True)
    pdf.ln()
    for r in rows:
        pdf.cell(w[0], 8, str(r["user_id"] or ""), border=1)
        pdf.cell(w[1], 8, str(r["name"] or ""), border=1)
        pdf.cell(w[2], 8, str(r["grade"] or ""), border=1)
        pdf.cell(w[3], 8, str(r["class_section"] or ""), border=1)
        pdf.cell(w[4], 8, str(r["gender"] or ""), border=1)
        pdf.cell(w[5], 8, str(r["attempts"] or 0), border=1, align='C')
        pdf.cell(w[6], 8, str(r["correct"] or 0), border=1, align='C')
        pdf.ln()
    pdf_bytes = pdf.output(dest='S').encode('latin1')
    return base64.b64encode(pdf_bytes).decode('utf-8')

# ---------------- Templates ----------------
# For safety with Jinja braces, templates are plain strings and variables passed in context.

BASE_HTML = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Ambassador Quiz App</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
      body { font-family: Inter, Arial, sans-serif; background:#f3f7fb; margin:0; color:#1f2937; }
      header { background:#0b2653; color:white; padding:16px 24px; display:flex; justify-content:space-between; align-items:center; }
      header .brand { font-weight:700; font-size:20px; }
      header nav a { color:white; margin-left:10px; text-decoration:none; padding:8px 12px; background:rgba(255,255,255,0.06); border-radius:8px; }
      .container { max-width:1100px; margin:24px auto; padding:0 16px; }
      .card { background:white; border-radius:10px; padding:18px; box-shadow:0 8px 30px rgba(2,6,23,0.06); margin-bottom:16px; }
      .row { display:flex; gap:16px; flex-wrap:wrap; }
      .col { flex:1; min-width:240px; }
      .btn { background:#0b2653; color:white; padding:8px 12px; border-radius:8px; border:none; cursor:pointer; text-decoration:none; display:inline-block; }
      .btn.alt { background:#e6eefc; color:#0b2653; }
      input, select, textarea { width:100%; padding:8px; border-radius:8px; border:1px solid #e6eefc; margin:6px 0 12px; box-sizing:border-box; }
      .muted { color:#64748b; font-size:14px; }
      .small { font-size:13px; color:#475569; }
      .center { text-align:center; }
      .progress { height:10px; background:#eef2ff; border-radius:8px; overflow:hidden; }
      .progress > div { height:100%; background:#0b2653; }
      .timer { background:#0b2653; color:white; padding:6px 10px; border-radius:8px; font-weight:600; display:inline-block; }
      @media(max-width:900px){ header nav{ display:none } .row{ flex-direction:column } }
    </style>
  </head>
  <body>
    <header>
      <div class="brand">Ambassador Quiz App</div>
      <nav>
        <a href="{{ url_for('home') }}">Home</a>
        {% if session.get('student_id') %}
          <a href="{{ url_for('student_dashboard') }}">Student</a>
          <a href="{{ url_for('logout') }}">Logout</a>
        {% elif session.get('teacher') %}
          <a href="{{ url_for('teacher_dashboard') }}">Teacher</a>
          <a href="{{ url_for('logout') }}">Logout</a>
        {% else %}
          <a href="{{ url_for('login') }}">Login</a>
        {% endif %}
      </nav>
    </header>
    <div class="container">
      {{ content|safe }}
    </div>
  </body>
</html>
"""

# ---------------- Routes ----------------

@app.route("/")
def home():
    content = """
    <div class="card center">
      <h1>Welcome to Ambassador Quiz App</h1>
      <p class="muted">Adaptive assessment platform inspired by PISA layout</p>
      <div style="margin-top:16px;">
        <a class="btn" href="/login">Sign In</a>
        <a class="btn alt" href="/signup">Student Sign Up</a>
      </div>
    </div>
    <div class="row">
      <div class="col card">
        <h3>How it works</h3>
        <p class="muted">Teachers create quizzes with passages and questions. Students attempt quizzes passage-by-passage, with a timer and progress indicators. Subjective answers are auto-evaluated using a word-overlap algorithm.</p>
      </div>
      <div class="col card">
        <h3>Quick actions</h3>
        <p><a class="btn" href="/login">Login</a> <a class="btn alt" href="/signup">Sign Up</a></p>
      </div>
    </div>
    """
    return render_template_string(BASE_HTML, content=content)

# ---------- Signup ----------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        user_id = request.form.get("user_id","").strip()
        password = request.form.get("password","")
        name = request.form.get("name","").strip()
        grade = request.form.get("grade","").strip()
        class_section = request.form.get("class_section","").strip()
        gender = request.form.get("gender","").strip()
        if not user_id or not password:
            return render_template_string(BASE_HTML, content="<div class='card'><p class='muted'>User ID and password required</p></div>")
        pw_hash = generate_password_hash(password)
        conn = get_db()
        try:
            conn.execute("INSERT INTO students(user_id,password,name,grade,class_section,gender) VALUES (?,?,?,?,?,?)",
                         (user_id, pw_hash, name, grade, class_section, gender))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return render_template_string(BASE_HTML, content="<div class='card'><p class='muted'>User ID already exists</p><a class='btn' href='/signup'>Back</a></div>")
        conn.close()
        return redirect(url_for('login'))
    content = """
    <div class="card" style="max-width:640px; margin:auto;">
      <h2>Student Sign Up</h2>
      <form method="post">
        Name: <input name="name" placeholder="Full name">
        User ID: <input name="user_id" placeholder="Unique ID" required>
        Password: <input type="password" name="password" placeholder="Password" required>
        Grade: <input name="grade" placeholder="e.g. 7">
        Class / Section: <input name="class_section" placeholder="Class">
        Gender: <select name="gender"><option>Male</option><option>Female</option><option>Other</option></select>
        <button class="btn" type="submit">Sign Up</button>
      </form>
    </div>
    """
    return render_template_string(BASE_HTML, content=content)

# ---------- Login ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        role = request.form.get("role","student")
        if role == "teacher":
            tname = request.form.get("teacher_name")
            passkey = request.form.get("passkey")
            if tname in TEACHER_PASSKEYS and TEACHER_PASSKEYS[tname] == passkey:
                session.clear()
                session["teacher"] = tname
                return redirect(url_for('teacher_dashboard'))
            else:
                content = "<div class='card'><p class='muted'>Invalid teacher credentials</p><a class='btn' href='/login'>Back</a></div>"
                return render_template_string(BASE_HTML, content=content)
        else:
            user_id = request.form.get("user_id","").strip()
            password = request.form.get("password","")
            conn = get_db()
            row = conn.execute("SELECT * FROM students WHERE user_id=?", (user_id,)).fetchone()
            conn.close()
            if row and check_password_hash(row["password"], password):
                session.clear()
                session["student_id"] = row["id"]
                session["student_user_id"] = row["user_id"]
                session["student_name"] = row["name"]
                session["grade"] = row["grade"]
                session["class_section"] = row["class_section"]
                return redirect(url_for('student_dashboard'))
            else:
                content = "<div class='card'><p class='muted'>Invalid student credentials</p><a class='btn' href='/login'>Back</a></div>"
                return render_template_string(BASE_HTML, content=content)
    content = """
    <div class="card" style="max-width:520px;margin:auto;">
      <h2 class="center">Welcome to PISA Pro</h2>
      <p class="muted center">Your adaptive assessment platform</p>
      <form method="post">
        <div style="display:flex;gap:8px;margin-bottom:12px;">
          <label><input type="radio" name="role" value="student" checked> Student</label>
          <label><input type="radio" name="role" value="teacher"> Teacher</label>
        </div>
        <div id="student_fields">
          User ID: <input name="user_id" placeholder="student id"><br>
          Password: <input type="password" name="password" placeholder="password"><br>
        </div>
        <div id="teacher_fields" style="display:none;">
          Teacher name: <input name="teacher_name" placeholder="teacher1"><br>
          Passkey: <input type="password" name="passkey" placeholder="passkey"><br>
        </div>
        <button class="btn" type="submit">Sign In</button>
      </form>
    </div>
    <script>
      const radios = document.querySelectorAll('input[name="role"]');
      const sfields = document.getElementById('student_fields');
      const tfields = document.getElementById('teacher_fields');
      radios.forEach(r => r.addEventListener('change', ()=>{
        if (r.value === 'teacher' && r.checked){ sfields.style.display='none'; tfields.style.display='block'; }
        if (r.value === 'student' && r.checked){ sfields.style.display='block'; tfields.style.display='none'; }
      }));
    </script>
    """
    return render_template_string(BASE_HTML, content=content)

# ---------- Logout ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('home'))

# ---------- Student Dashboard ----------
@app.route("/student/dashboard")
def student_dashboard():
    if "student_id" not in session:
        return redirect(url_for('login'))
    sid = session["student_id"]
    conn = get_db()
    # fetch recent attempts
    attempts = conn.execute("""
      SELECT a.*, q.text as question_text, p.title as passage_title, qz.title as quiz_title
      FROM attempts a
      LEFT JOIN questions q ON a.question_id=q.id
      LEFT JOIN passages p ON a.passage_id=p.id
      LEFT JOIN quizzes qz ON a.quiz_id=qz.id
      WHERE a.student_id=?
      ORDER BY a.created_at DESC
      LIMIT 20
    """, (sid,)).fetchall()
    # summary scores per quiz (average)
    summary = conn.execute("""
      SELECT qz.title, AVG(a.correct)*100.0 as pct
      FROM attempts a JOIN quizzes qz ON a.quiz_id=qz.id
      WHERE a.student_id=?
      GROUP BY qz.id
      ORDER BY qz.id
    """, (sid,)).fetchall()
    conn.close()
    # prepare plot data (simple trend from summary values)
    labels = [r["title"] for r in summary]
    values = [round(r["pct"] or 0,2) for r in summary]
    plot_b64 = make_plot_base64(labels, values, title="Your Quiz Scores") if labels else None

    attempts_html = ""
    for a in attempts:
        attempts_html += f"<div class='card'><b>{a['quiz_title'] or 'Quiz'}</b> • {a['passage_title'] or ''}<div class='muted small'>Q: {a['question_text'] or ''}</div><div class='small'>Answer: {a['student_answer'] or ''} • Correct: {a['correct']}</div></div>"

    content = "<div class='card'><h2>Student Dashboard</h2><div class='muted'>Welcome, {}</div></div>".format(session.get("student_name") or session.get("student_user_id"))
    content += "<div class='row'><div class='col card'>"
    content += "<h3>Performance Trend</h3>"
    if plot_b64:
        content += f"<img src='data:image/png;base64,{plot_b64}' style='max-width:100%;'/>"
    else:
        content += "<p class='muted'>No quiz attempts yet.</p>"
    content += "</div><div class='col card'>"
    content += "<h3>Actions</h3><a class='btn' href='/quiz/list'>Take Quiz</a><br><br><a class='btn alt' href='/logout'>Logout</a>"
    content += "</div></div>"
    content += "<h3>Recent Attempts</h3>" + (attempts_html or "<div class='card'><p class='muted'>No attempts yet</p></div>")
    return render_template_string(BASE_HTML, content=content)

# ---------- List Quizzes (by grade) ----------
@app.route("/quiz/list")
def quiz_list():
    if "student_id" not in session:
        return redirect(url_for('login'))
    grade = session.get("grade")
    conn = get_db()
    quizzes = conn.execute("SELECT * FROM quizzes WHERE grade=? OR grade='' ORDER BY id DESC", (grade,)).fetchall()
    conn.close()
    html = "<div class='card'><h2>Available Quizzes</h2>"
    if not quizzes:
        html += "<p class='muted'>No quizzes for your grade</p>"
    for q in quizzes:
        html += f"<div style='display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #f1f5f9'>"
        html += f"<div><b>{q['title']}</b><div class='muted'>{q['subject']} • Grade {q['grade']}</div></div>"
        html += f"<div><a class='btn' href='/quiz/start/{q['id']}'>Start</a></div></div>"
    html += "</div>"
    return render_template_string(BASE_HTML, content=html)

# ---------- Start Quiz (redirect to passage 0) ----------
@app.route("/quiz/start/<int:quiz_id>")
def quiz_start(quiz_id):
    # confirm student logged in
    if "student_id" not in session:
        return redirect(url_for('login'))
    return redirect(url_for('quiz_passage', quiz_id=quiz_id, p_index=0))

# ---------- Quiz Passage (render passage and its questions) ----------
@app.route("/quiz/<int:quiz_id>/passage/<int:p_index>", methods=["GET", "POST"])
def quiz_passage(quiz_id, p_index):
    if "student_id" not in session:
        return redirect(url_for('login'))
    conn = get_db()
    quiz = conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    passages = conn.execute("SELECT * FROM passages WHERE quiz_id=? ORDER BY id", (quiz_id,)).fetchall()
    if not quiz or not passages:
        conn.close()
        return render_template_string(BASE_HTML, content="<div class='card'><p class='muted'>Quiz not found or empty</p></div>")
    if p_index < 0 or p_index >= len(passages):
        conn.close()
        return redirect(url_for('quiz_start', quiz_id=quiz_id))
    passage = passages[p_index]
    questions = conn.execute("SELECT * FROM questions WHERE passage_id=? ORDER BY id", (passage["id"],)).fetchall()
    conn.close()

    if request.method == "POST":
        student_id = session["student_id"]
        now = datetime.utcnow().isoformat()
        conn = get_db()
        for q in questions:
            ans = (request.form.get(f"q_{q['id']}") or "").strip()
            if not ans:
                # if no answer provided, still record empty attempt? We skip
                continue
            if q["qtype"] == "mcq":
                correct_flag = 1 if ans.strip().lower() == (q["correct"] or "").strip().lower() else 0
            else:
                correct_flag = 1 if subjective_correct(ans, q["correct"]) else 0
            conn.execute("""INSERT INTO attempts(student_id,quiz_id,passage_id,question_id,student_answer,correct,created_at)
                            VALUES (?,?,?,?,?,?,?)""", (student_id, quiz_id, passage["id"], q["id"], ans, int(correct_flag), now))
        conn.commit()
        conn.close()
        next_index = p_index + 1
        if next_index >= len(passages):
            return redirect(url_for('quiz_complete', quiz_id=quiz_id))
        else:
            return redirect(url_for('quiz_passage', quiz_id=quiz_id, p_index=next_index))

    # GET: render passage + questions
    total = len(passages)
    progress_pct = int(((p_index) / total) * 100)
    # timer
    timer = quiz["timer_seconds"] or 0
    # build HTML
    html = f"<div class='card'><h2>{quiz['title']}</h2><div class='muted'>{quiz['subject']} • Grade {quiz['grade']}</div></div>"
    html += "<div class='card'>"
    html += f"<div style='display:flex;justify-content:space-between;align-items:center'><div><h3>Passage {p_index+1} of {total}</h3></div>"
    if timer and timer>0:
        html += f"<div class='timer' id='timer'>Time: {timer}s</div>"
    html += "</div>"
    html += f"<div class='progress' style='margin-top:12px'><div style='width:{progress_pct}%;'></div></div>"
    html += f"<h4 style='margin-top:12px'>{passage['title'] or ''}</h4>"
    if passage['content']:
        html += f"<div class='muted' style='white-space:pre-wrap'>{passage['content']}</div>"
    html += "<form method='post'>"
    for q in questions:
        html += "<div style='margin-top:14px;padding:12px;border-radius:8px;border:1px solid #eef2ff'>"
        html += f"<p><b>{q['text']}</b></p>"
        if q['qtype'] == "mcq":
            for opt in ('option_a','option_b','option_c','option_d'):
                val = q[opt]
                if val:
                    html += f"<label style='display:block;margin-bottom:6px'><input type='radio' name='q_{q['id']}' value='{val}'> {val}</label>"
        else:
            html += f"<textarea name='q_{q['id']}' rows='4' placeholder='Type your answer here...' style='width:100%'></textarea>"
        html += "</div>"
    html += "<div style='margin-top:12px;display:flex;gap:8px'>"
    if p_index > 0:
        html += f"<a class='btn alt' href='{url_for('quiz_passage', quiz_id=quiz_id, p_index=p_index-1)}'>Previous</a>"
    html += "<button class='btn' type='submit'>Submit Passage</button>"
    html += "</div></form></div>"

    # add timer JS if timer set
    if timer and timer>0:
        html += f"""
        <script>
        (function(){{
          var time = {timer};
          var el = document.getElementById('timer');
          var iv = setInterval(function(){{
            time -= 1;
            if (time <= 0) {{ clearInterval(iv); var form = document.forms[0]; if(form) form.submit(); }}
            el.innerText = 'Time: ' + time + 's';
          }}, 1000);
        }})();
        </script>
        """
    return render_template_string(BASE_HTML, content=html)

# ---------- Quiz complete ----------
@app.route("/quiz/<int:quiz_id>/complete")
def quiz_complete(quiz_id):
    if "student_id" not in session:
        return redirect(url_for('login'))
    sid = session["student_id"]
    conn = get_db()
    stats = conn.execute("SELECT COUNT(id) as total, SUM(correct) as correct FROM attempts WHERE student_id=? AND quiz_id=?", (sid, quiz_id)).fetchone()
    conn.close()
    total = stats["total"] or 0
    correct = stats["correct"] or 0
    pct = round((correct / total) * 100, 2) if total>0 else 0
    html = f"<div class='card'><h2>Quiz Completed</h2><p class='muted'>You answered {correct} of {total} items correctly</p><h3>Score: {pct}%</h3>"
    html += "<a class='btn' href='/quiz/list'>Back to quizzes</a></div>"
    return render_template_string(BASE_HTML, content=html)

# ---------- Teacher Dashboard ----------
@app.route("/teacher/dashboard")
def teacher_dashboard():
    if "teacher" not in session:
        return redirect(url_for('login'))
    # show quizzes and aggregated data
    conn = get_db()
    quizzes = conn.execute("SELECT * FROM quizzes ORDER BY id DESC").fetchall()
    grades_data = conn.execute("""
      SELECT s.grade as grade, SUM(a.correct) as correct_count, COUNT(a.id) as total
      FROM attempts a JOIN students s ON a.student_id = s.id
      GROUP BY s.grade
    """).fetchall()
    conn.close()
    labels = [r["grade"] for r in grades_data]
    values = [round((r["correct_count"] or 0) / (r["total"] or 1) * 100,2) for r in grades_data]
    bar_b64 = make_bar_base64(labels, values, title="Performance by Grade") if labels else None
    html = "<div class='card'><h2>Teacher Dashboard</h2></div>"
    html += "<div class='row'><div class='col card'><h3>Quizzes</h3>"
    html += "<a class='btn' href='/teacher/create_quiz'>Create Quiz</a> <a class='btn alt' href='/teacher/export_pdf'>Export PDF</a> <a class='btn' href='/teacher/reset_confirm' style='background:#d9464a'>Reset DB</a>"
    html += "<div style='margin-top:12px'>"
    if quizzes:
        for q in quizzes:
            html += f"<div style='padding:8px;border-bottom:1px solid #f1f5f9;display:flex;justify-content:space-between;align-items:center'><div><b>{q['title']}</b><div class='muted'>{q['subject']} • Grade {q['grade']}</div></div>"
            html += f"<div><a class='btn alt' href='/teacher/view_quiz/{q['id']}'>View</a> <a class='btn' href='/teacher/delete_quiz/{q['id']}' style='background:#ef4444'>Delete</a></div></div>"
    else:
        html += "<p class='muted'>No quizzes created yet</p>"
    html += "</div></div>"
    html += "<div class='col card'><h3>Performance by Grade</h3>"
    if bar_b64:
        html += f"<img src='data:image/png;base64,{bar_b64}' style='max-width:100%;'/>"
    else:
        html += "<p class='muted'>No data yet</p>"
    html += "</div></div>"
    return render_template_string(BASE_HTML, content=html)

# ---------- Create Quiz ----------
@app.route("/teacher/create_quiz", methods=["GET","POST"])
def teacher_create_quiz():
    if "teacher" not in session:
        return redirect(url_for('login'))
    if request.method == "POST":
        title = request.form.get("title","").strip()
        grade = request.form.get("grade","").strip()
        subject = request.form.get("subject","").strip()
        timer = int(request.form.get("timer_seconds") or 0)
        conn = get_db()
        cur = conn.execute("INSERT INTO quizzes(title,grade,subject,timer_seconds) VALUES (?,?,?,?)", (title,grade,subject,timer))
        conn.commit()
        quiz_id = cur.lastrowid
        conn.close()
        return redirect(url_for('teacher_add_passage', quiz_id=quiz_id))
    content = """
    <div class='card'>
      <h2>Create Quiz</h2>
      <form method='post'>
        Title: <input name='title' required>
        Grade: <input name='grade' placeholder='e.g. 7'>
        Subject: <input name='subject'>
        Timer (seconds per passage): <input name='timer_seconds' type='number' min='0' placeholder='optional'>
        <button class='btn' type='submit'>Create Quiz</button>
      </form>
    </div>
    """
    return render_template_string(BASE_HTML, content=content)

# ---------- Add Passage ----------
@app.route("/teacher/<int:quiz_id>/add_passage", methods=["GET","POST"])
def teacher_add_passage(quiz_id):
    if "teacher" not in session:
        return redirect(url_for('login'))
    if request.method == "POST":
        title = request.form.get("title","").strip()
        content = request.form.get("content","").strip()
        conn = get_db()
        cur = conn.execute("INSERT INTO passages(quiz_id,title,content) VALUES (?,?,?)", (quiz_id,title,content))
        conn.commit()
        passage_id = cur.lastrowid
        conn.close()
        return redirect(url_for('teacher_add_question', passage_id=passage_id))
    content = f"""
    <div class='card'>
      <h2>Add Passage</h2>
      <form method='post'>
        Title: <input name='title'>
        Content (passage text): <textarea name='content' rows='6'></textarea>
        <button class='btn' type='submit'>Add Passage & Add Questions</button>
      </form>
    </div>
    """
    return render_template_string(BASE_HTML, content=content)

# For convenience add route alias used after quiz creation
@app.route("/teacher/add_passage/<int:quiz_id>", methods=["GET","POST"])
def teacher_add_passage_alias(quiz_id):
    return teacher_add_passage(quiz_id)

# ---------- Add Question ----------
@app.route("/teacher/add_question/<int:passage_id>", methods=["GET","POST"])
def teacher_add_question(passage_id):
    if "teacher" not in session:
        return redirect(url_for('login'))
    conn = get_db()
    passage = conn.execute("SELECT * FROM passages WHERE id=?", (passage_id,)).fetchone()
    conn.close()
    if not passage:
        return render_template_string(BASE_HTML, content="<div class='card'><p class='muted'>Passage not found</p></div>")
    if request.method == "POST":
        text = request.form.get("text","").strip()
        qtype = request.form.get("qtype","mcq")
        a = request.form.get("option_a") or None
        b = request.form.get("option_b") or None
        c = request.form.get("option_c") or None
        d = request.form.get("option_d") or None
        correct = request.form.get("correct","").strip()
        conn = get_db()
        conn.execute("""INSERT INTO questions(passage_id,text,qtype,option_a,option_b,option_c,option_d,correct)
                        VALUES (?,?,?,?,?,?,?,?)""", (passage_id,text,qtype,a,b,c,d,correct))
        conn.commit()
        conn.close()
        return render_template_string(BASE_HTML, content=f"<div class='card'><p>Question added.</p><a class='btn' href='/teacher/add_question/{passage_id}'>Add Another</a> <a class='btn' href='/teacher/dashboard'>Dashboard</a></div>")
    content = f"""
    <div class='card'>
      <h2>Add Question to Passage: {passage['title'] or passage['id']}</h2>
      <form method='post'>
        Question text: <textarea name='text' rows='3'></textarea>
        Type: <select name='qtype'><option value='mcq'>MCQ</option><option value='subjective'>Subjective</option></select>
        Correct answer / keywords: <input name='correct'>
        <div style='display:flex;gap:8px'>
          <input name='option_a' placeholder='Option A'>
          <input name='option_b' placeholder='Option B'>
        </div>
        <div style='display:flex;gap:8px'>
          <input name='option_c' placeholder='Option C'>
          <input name='option_d' placeholder='Option D'>
        </div>
        <button class='btn' type='submit'>Add Question</button>
      </form>
    </div>
    """
    return render_template_string(BASE_HTML, content=content)

# ---------- View Quiz ----------
@app.route("/teacher/view_quiz/<int:quiz_id>")
def teacher_view_quiz(quiz_id):
    if "teacher" not in session:
        return redirect(url_for('login'))
    conn = get_db()
    quiz = conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    passages = conn.execute("SELECT * FROM passages WHERE quiz_id=? ORDER BY id", (quiz_id,)).fetchall()
    conn.close()
    if not quiz:
        return render_template_string(BASE_HTML, content="<div class='card'><p class='muted'>Quiz not found</p></div>")
    html = f"<div class='card'><h2>{quiz['title']}</h2><div class='muted'>{quiz['subject']} • Grade {quiz['grade']}</div></div>"
    for p in passages:
        html += f"<div class='card'><h3>Passage: {p['title'] or ''}</h3><div class='muted' style='white-space:pre-wrap'>{p['content'] or ''}</div>"
        html += f"<a class='btn' href='/teacher/add_question/{p['id']}'>Add Question</a></div>"
        conn = get_db()
        qs = conn.execute("SELECT * FROM questions WHERE passage_id=? ORDER BY id", (p['id'],)).fetchall()
        conn.close()
        for q in qs:
            html += f"<div style='padding:8px;border-bottom:1px solid #f1f5f9'>{q['text']} <div class='muted small'>Type: {q['qtype']} • Correct: {q['correct']}</div></div>"
    html += "<a class='btn' href='/teacher/dashboard'>Back</a>"
    return render_template_string(BASE_HTML, content=html)

# ---------- Delete Quiz ----------
@app.route("/teacher/delete_quiz/<int:quiz_id>", methods=["GET","POST"])
def teacher_delete_quiz(quiz_id):
    if "teacher" not in session:
        return redirect(url_for('login'))
    if request.method == "POST":
        conn = get_db()
        conn.execute("DELETE FROM attempts WHERE quiz_id=?", (quiz_id,))
        conn.execute("DELETE FROM questions WHERE passage_id IN (SELECT id FROM passages WHERE quiz_id=?)", (quiz_id,))
        conn.execute("DELETE FROM passages WHERE quiz_id=?", (quiz_id,))
        conn.execute("DELETE FROM quizzes WHERE id=?", (quiz_id,))
        conn.commit(); conn.close()
        return redirect(url_for('teacher_dashboard'))
    return render_template_string(BASE_HTML, content=f"<div class='card'><h3>Confirm delete quiz {quiz_id}?</h3><form method='post'><button class='btn' type='submit'>Yes, delete</button> <a class='btn' href='/teacher/dashboard'>Cancel</a></form></div>")

# ---------- Export PDF ----------
@app.route("/teacher/export_pdf")
def teacher_export_pdf():
    if "teacher" not in session:
        return redirect(url_for('login'))
    b64 = pdf_base64_student_report()
    content = "<div class='card'><h2>Student Report</h2>"
    content += f"<p class='muted'>Click below to download PDF</p><a class='btn' href='data:application/pdf;base64,{b64}' download='student_report.pdf'>Download PDF</a>"
    content += "</div>"
    return render_template_string(BASE_HTML, content=content)

# ---------- Reset DB confirmation ----------
@app.route("/teacher/reset_confirm")
def teacher_reset_confirm():
    if "teacher" not in session:
        return redirect(url_for('login'))
    content = """<div class='card'><h2>Reset Database</h2><p class='muted'>This will permanently delete all students, quizzes, passages, questions and attempts.</p>
    <form method='post' action='/teacher/reset_db'><label>Type YES to confirm: <input name='confirm'></label><br><button class='btn' type='submit' style='background:#ef4444'>Reset Database</button> <a class='btn' href='/teacher/dashboard'>Cancel</a></form></div>"""
    return render_template_string(BASE_HTML, content=content)

@app.route("/teacher/reset_db", methods=["POST"])
def teacher_reset_db():
    if "teacher" not in session:
        return redirect(url_for('login'))
    confirm = request.form.get("confirm","")
    if confirm != "YES":
        return redirect(url_for('teacher_dashboard'))
    conn = get_db()
    conn.execute("DELETE FROM attempts")
    conn.execute("DELETE FROM questions")
    conn.execute("DELETE FROM passages")
    conn.execute("DELETE FROM quizzes")
    conn.execute("DELETE FROM students")
    conn.commit()
    conn.close()
    init_db()
    return render_template_string(BASE_HTML, content="<div class='card'><p>Database reset complete.</p><a class='btn' href='/'>Home</a></div>")

# ---------- Simple route for teacher to add passage after quiz creation ----------
@app.route("/teacher/add_passage/<int:quiz_id>", methods=["GET","POST"])
def teacher_add_passage_quick(quiz_id):
    return teacher_add_passage(quiz_id)

# ---------- Utility: route aliases for a few earlier used paths ----------
@app.route("/teacher/add_question_to_passage/<int:passage_id>")
def teacher_add_question_alias(passage_id):
    return redirect(url_for('teacher_add_question', passage_id=passage_id))

# ---------------- Run ----------------
if __name__ == "__main__":
    print("Starting Ambassador Quiz App on http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
