# app.py
"""
Ambassador Quiz App - single-file Flask + SQLAlchemy app with:
 - Postgres-ready configuration (edit DATABASE_URL below)
 - Adaptive placement test (4-5 diagnostic questions)
 - Adaptive quizzes by student.level (beginner/intermediate/advanced)
 - Teacher dashboard with colorful charts (Chart.js) + many metrics
 - PDF export via FPDF (base64 data URI)
 - No 'os' module usage (replace DATABASE_URL constant manually)
"""

from flask import Flask, request, redirect, session, render_template_string, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import secrets
import re
import base64
import io
from fpdf import FPDF
import random
import math

# ---------------- CONFIG ----------------
# Replace DATABASE_URL with your Postgres URL when deploying on Render:
# e.g. "postgresql+psycopg2://username:password@host:port/dbname"
# For local testing you may leave the default (sqlite).
DATABASE_URL = "sqlite:///ambassador_quiz.db"  # <<--- EDIT this for production (Render Postgres URL)

# App
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = secrets.token_hex(24)
db = SQLAlchemy(app)

# ---------------- MODELS ----------------
class Student(db.Model):
    __tablename__ = "students"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    name = db.Column(db.String(200))
    grade = db.Column(db.String(50))
    class_section = db.Column(db.String(50))
    gender = db.Column(db.String(50))
    level = db.Column(db.String(50), default="unknown")  # beginner/intermediate/advanced

class Quiz(db.Model):
    __tablename__ = "quizzes"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300))
    grade = db.Column(db.String(50))
    subject = db.Column(db.String(100))
    timer_seconds = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Passage(db.Model):
    __tablename__ = "passages"
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quizzes.id"))
    title = db.Column(db.String(300))
    content = db.Column(db.Text)

class Question(db.Model):
    __tablename__ = "questions"
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quizzes.id"))
    passage_id = db.Column(db.Integer, db.ForeignKey("passages.id"))
    text = db.Column(db.Text)
    qtype = db.Column(db.String(50))  # 'mcq' or 'subjective'
    option_a = db.Column(db.String(500))
    option_b = db.Column(db.String(500))
    option_c = db.Column(db.String(500))
    option_d = db.Column(db.String(500))
    correct = db.Column(db.Text)  # for mcq store option text, for subjective store expected keywords/answer
    difficulty = db.Column(db.String(50), default="medium")  # easy/medium/hard
    marks = db.Column(db.Integer, default=1)

class Attempt(db.Model):
    __tablename__ = "attempts"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"))
    quiz_id = db.Column(db.Integer, db.ForeignKey("quizzes.id"))
    passage_id = db.Column(db.Integer, db.ForeignKey("passages.id"))
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"))
    student_answer = db.Column(db.Text)
    correct = db.Column(db.Integer)  # 0 or 1
    time_taken = db.Column(db.Float, default=0.0)  # seconds
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Initialize DB (create tables)
with app.app_context():
    db.create_all()

# Teacher passkeys (in-code)
TEACHER_PASSKEYS = {
    "teacher1": "math123",
    "teacher2": "science456",
    "admin": "supersecret"
}

# ---------------- Utilities ----------------

def normalize_words(s):
    return set(re.findall(r"\w+", (s or "").lower()))

def subjective_similarity(student_ans, teacher_ans):
    """Return fraction of teacher-answer words present in student answer."""
    s = normalize_words(student_ans)
    t = normalize_words(teacher_ans)
    if not t:
        return 0.0
    matches = sum(1 for w in t if w in s)
    return matches / len(t)

def grade_level_from_score(score, total):
    """Map placement test score to level."""
    if total == 0:
        return "unknown"
    pct = (score / total) * 100
    if pct >= 80:
        return "advanced"
    elif pct >= 40:
        return "intermediate"
    else:
        return "beginner"

def fpdf_bytes_for_student_report(rows):
    """Given rows (list of dicts) produce PDF bytes via FPDF."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "Student Report - Ambassador Quiz App", ln=True, align="C")
    pdf.ln(6)
    pdf.set_font("Arial", size=10)
    # header
    pdf.set_fill_color(230,230,230)
    headers = ["User ID", "Name", "Grade", "Class", "Gender", "Level", "Attempts", "Correct"]
    widths = [30, 40, 18, 20, 18, 24, 20, 20]
    for h,w in zip(headers,widths):
        pdf.cell(w,8,h,1,0,'C',1)
    pdf.ln()
    for r in rows:
        pdf.cell(widths[0],8,str(r.get("user_id","")),1)
        pdf.cell(widths[1],8,str(r.get("name","")),1)
        pdf.cell(widths[2],8,str(r.get("grade","") or ""),1)
        pdf.cell(widths[3],8,str(r.get("class","") or ""),1)
        pdf.cell(widths[4],8,str(r.get("gender","") or ""),1)
        pdf.cell(widths[5],8,str(r.get("level","") or ""),1)
        pdf.cell(widths[6],8,str(r.get("attempts",0)),1,0,'C')
        pdf.cell(widths[7],8,str(r.get("correct",0)),1,1,'C')
    return pdf.output(dest="S").encode("latin1")

# ---------------- Routes & Views ----------------

BASE_TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Ambassador Quiz App</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <!-- Bootstrap 5 CDN -->
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background:#f6fbff; color:#0f1724; }
    .hero { background: linear-gradient(90deg,#0b6cf1,#7c3aed); color:white; padding:28px; border-radius:12px; }
    .card-custom { border-radius:10px; box-shadow:0 6px 18px rgba(15,23,42,0.06); }
    .muted { color:#6b7280; }
    .small { font-size:13px; color:#475569; }
    .progress-custom { height:10px; border-radius:8px; overflow:hidden; background:#eef2ff; }
    .timer { background:#0b6cf1; color:white; padding:6px 10px; border-radius:8px; display:inline-block; font-weight:600;}
    .chart-card { min-height:240px; }
    .tag { padding:6px 8px; border-radius:8px; background:#eef2ff; color:#0b6cf1; font-weight:600; }
  </style>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark" style="background:#0b2653">
  <div class="container-fluid">
    <a class="navbar-brand" href="/">Ambassador Quiz App</a>
    <div class="collapse navbar-collapse">
      <ul class="navbar-nav ms-auto">
        {% if session.get('student_id') %}
          <li class="nav-item"><a class="nav-link" href="/student/dashboard">Student</a></li>
          <li class="nav-item"><a class="nav-link" href="/logout">Logout</a></li>
        {% elif session.get('teacher') %}
          <li class="nav-item"><a class="nav-link" href="/teacher/dashboard">Teacher</a></li>
          <li class="nav-item"><a class="nav-link" href="/logout">Logout</a></li>
        {% else %}
          <li class="nav-item"><a class="nav-link" href="/login">Login</a></li>
          <li class="nav-item"><a class="nav-link" href="/signup">Sign Up</a></li>
        {% endif %}
      </ul>
    </div>
  </div>
</nav>
<div class="container my-4">
  {{ content|safe }}
</div>
<!-- Bootstrap JS -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

# ---------- Home ----------
@app.route("/")
def home():
    content = """
    <div class="hero d-flex justify-content-between align-items-center mb-4">
      <div>
        <h1 class="display-6">Ambassador Quiz App</h1>
        <p class="muted">Adaptive assessment platform — placement tests, adaptive quizzes, and detailed analytics for teachers.</p>
      </div>
      <div class="text-end">
        <a href="/login" class="btn btn-light">Sign In</a>
        <a href="/signup" class="btn btn-outline-light">Student Sign Up</a>
      </div>
    </div>
    <div class="row g-4">
      <div class="col-lg-8">
        <div class="card card-custom p-3">
          <h4>How it works</h4>
          <p class="muted">Teachers create quizzes with passages and difficulty-tagged questions. Students take a short placement test (4-5 items) which assigns a level — quizzes adapt to that level. Subjective answers are auto-checked by word-overlap similarity.</p>
        </div>
      </div>
      <div class="col-lg-4">
        <div class="card card-custom p-3">
          <h5>Quick Links</h5>
          <a class="btn btn-primary mb-2 w-100" href="/login">Login</a>
          <a class="btn btn-outline-primary w-100" href="/signup">Student Sign Up</a>
        </div>
      </div>
    </div>
    """
    return render_template_string(BASE_TEMPLATE, content=content)

# ---------- Signup ----------
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
            return render_template_string(BASE_TEMPLATE, content="<div class='card p-3'>User ID and password required.</div>")
        hashed = generate_password_hash(password)
        st = Student(user_id=user_id, password=hashed, name=name, grade=grade, class_section=class_section, gender=gender)
        try:
            db.session.add(st)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return render_template_string(BASE_TEMPLATE, content=f"<div class='card p-3'>User ID exists. <a href='/signup'>Back</a></div>")
        return redirect("/login")
    content = """
    <div class="card p-3" style="max-width:780px;margin:auto">
      <h3>Student Sign Up</h3>
      <form method="post">
        <div class="mb-2"><input class="form-control" name="name" placeholder="Full name"></div>
        <div class="mb-2"><input class="form-control" name="user_id" placeholder="User ID (unique)" required></div>
        <div class="mb-2"><input class="form-control" type="password" name="password" placeholder="Password" required></div>
        <div class="row"><div class="col"><input class="form-control" name="grade" placeholder="Grade"></div><div class="col"><input class="form-control" name="class_section" placeholder="Class/Section"></div></div>
        <div class="mb-2"><select class="form-control" name="gender"><option>Male</option><option>Female</option><option>Other</option></select></div>
        <button class="btn btn-primary" type="submit">Sign Up</button>
      </form>
    </div>
    """
    return render_template_string(BASE_TEMPLATE, content=content)

# ---------- Login ----------
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        role = request.form.get("role","student")
        if role == "teacher":
            tname = request.form.get("teacher_name","")
            passkey = request.form.get("passkey","")
            if TEACHER_PASSKEYS.get(tname) == passkey:
                session.clear()
                session["teacher"] = tname
                return redirect("/teacher/dashboard")
            else:
                return render_template_string(BASE_TEMPLATE, content="<div class='card p-3'>Invalid teacher credentials. <a href='/login'>Back</a></div>")
        else:
            user_id = request.form.get("user_id","").strip()
            password = request.form.get("password","")
            st = Student.query.filter_by(user_id=user_id).first()
            if st and check_password_hash(st.password, password):
                session.clear()
                session["student_id"] = st.id
                session["student_user_id"] = st.user_id
                session["grade"] = st.grade
                return redirect("/placement/check") if st.level in (None,"unknown","") else redirect("/student/dashboard")
            else:
                return render_template_string(BASE_TEMPLATE, content="<div class='card p-3'>Invalid student credentials. <a href='/login'>Back</a></div>")
    content = """
    <div class="card p-3" style="max-width:640px;margin:auto">
      <h3>Sign In</h3>
      <form method="post">
        <div class="mb-2"><label class="form-label">Role</label>
          <select name="role" class="form-select"><option value="student" selected>Student</option><option value="teacher">Teacher</option></select></div>
        <div class="mb-2 student-fields"><input class="form-control" name="user_id" placeholder="User ID"></div>
        <div class="mb-2 student-fields"><input class="form-control" type="password" name="password" placeholder="Password"></div>
        <div style="display:none" id="teacher_fields">
          <div class="mb-2"><input class="form-control" name="teacher_name" placeholder="Teacher name"></div>
          <div class="mb-2"><input class="form-control" type="password" name="passkey" placeholder="Passkey"></div>
        </div>
        <button class="btn btn-primary" type="submit">Sign In</button>
      </form>
    </div>
    <script>
      const select = document.querySelector('select[name="role"]');
      select.addEventListener('change', function(){
        const val = this.value;
        document.querySelectorAll('.student-fields').forEach(n=>n.style.display = val==='student' ? 'block' : 'none');
        document.getElementById('teacher_fields').style.display = val==='teacher' ? 'block' : 'none';
      });
    </script>
    """
    return render_template_string(BASE_TEMPLATE, content=content)

# ---------- Logout ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------- Placement Test ----------
# When a student first logs in (unknown level) they'll be routed here to take 4-5 diagnostic questions.
@app.route("/placement/check", methods=["GET","POST"])
def placement_check():
    if "student_id" not in session:
        return redirect("/login")
    sid = session["student_id"]
    student = Student.query.get(sid)
    # choose 5 placement questions across difficulties and subjects for student's grade
    # For simplicity: pick 5 random questions from quizzes matching student grade if available,
    # otherwise global random questions. Use difficulty mix: 2 easy, 2 medium, 1 hard.
    if request.method == "POST":
        # process answers
        answers = {}
        for key, val in request.form.items():
            if key.startswith("q_"):
                qid = int(key.split("_",1)[1])
                answers[qid] = val
        # grade them
        score = 0
        total = 0
        for qid, ans in answers.items():
            q = Question.query.get(qid)
            if not q: continue
            total += 1
            if q.qtype == "mcq":
                if (ans or "").strip().lower() == (q.correct or "").strip().lower():
                    score += 1
            else:
                sim = subjective_similarity(ans or "", q.correct or "")
                if sim >= 0.6:
                    score += 1
        level = grade_level_from_score(score, total)
        student.level = level
        db.session.commit()
        return render_template_string(BASE_TEMPLATE, content=f"<div class='card p-3'><h3>Placement complete</h3><p class='muted'>Assigned level: <span class='tag'>{level}</span></p><a class='btn' href='/student/dashboard'>Go to Dashboard</a></div>")
    # GET prepare placement questions
    # find candidate questions
    q_candidates = []
    # prefer those for the student's grade
    if student.grade:
        q_candidates = Question.query.join(Quiz, Question.quiz_id==Quiz.id).filter((Quiz.grade==student.grade) | (Quiz.grade==None)).all()
    if not q_candidates:
        q_candidates = Question.query.all()
    # pick difficulties: 2 easy,2 medium,1 hard if available
    def pick_by_diff(diff, n):
        pool = [q for q in q_candidates if q.difficulty==diff]
        return random.sample(pool, min(n, len(pool)))
    chosen = []
    chosen += pick_by_diff("easy",2)
    chosen += pick_by_diff("medium",2)
    chosen += pick_by_diff("hard",1)
    # if not enough, fill with random
    if len(chosen) < 5:
        rest = [q for q in q_candidates if q not in chosen]
        needed = 5 - len(chosen)
        if rest:
            chosen += random.sample(rest, min(needed, len(rest)))
    # build HTML
    if not chosen:
        # If there are no questions at all, ask to return to dashboard
        return render_template_string(BASE_TEMPLATE, content="<div class='card p-3'>No questions available to run placement. Please ask teacher to add questions. <a class='btn' href='/student/dashboard'>Dashboard</a></div>")
    html = "<div class='card p-3'><h3>Placement Test (diagnostic)</h3><p class='muted'>Answer these 4-5 questions to determine your level</p><form method='post'>"
    for q in chosen:
        html += f"<div class='mb-2'><b>{q.text}</b><div class='small muted'>Difficulty: {q.difficulty}</div>"
        if q.qtype == "mcq":
            for opt in ("option_a","option_b","option_c","option_d"):
                val = getattr(q,opt)
                if val:
                    html += f"<div class='form-check'><input class='form-check-input' type='radio' name='q_{q.id}' value='{val}' id='q{q.id}{opt}'><label class='form-check-label' for='q{q.id}{opt}'>{val}</label></div>"
        else:
            html += f"<textarea class='form-control' name='q_{q.id}' rows='3'></textarea>"
        html += "</div>"
    html += "<button class='btn btn-primary' type='submit'>Submit Placement</button></form></div>"
    return render_template_string(BASE_TEMPLATE, content=html)

# ---------- Student Dashboard ----------
@app.route("/student/dashboard")
def student_dashboard():
    if "student_id" not in session:
        return redirect("/login")
    sid = session["student_id"]
    student = Student.query.get(sid)
    # recent attempts
    attempts = Attempt.query.filter_by(student_id=sid).order_by(Attempt.created_at.desc()).limit(15).all()
    # per-quiz aggregated percent
    quiz_stats = db.session.query(Quiz.id, Quiz.title, db.func.sum(Attempt.correct).label("correct"), db.func.count(Attempt.id).label("total")).join(Attempt, Attempt.quiz_id==Quiz.id).filter(Attempt.student_id==sid).group_by(Quiz.id).all()
    labels = [q.title for q in quiz_stats]
    values = [round((q.correct or 0) / (q.total or 1) * 100,2) for q in quiz_stats]
    chart_data = {"labels": labels, "values": values}
    # simple HTML
    html = f"<div class='card p-3'><h3>Welcome, {student.name or student.user_id}</h3><div class='muted'>Level: <span class='tag'>{student.level}</span></div></div>"
    html += "<div class='row g-3'><div class='col-lg-8'>"
    html += "<div class='card p-3'><h5>Your recent attempts</h5>"
    if not attempts:
        html += "<p class='muted'>No attempts yet</p>"
    else:
        for a in attempts:
            q = Question.query.get(a.question_id)
            html += f"<div style='border-bottom:1px solid #eef2ff;padding:8px 0;'><b>{q.text if q else 'Question'}</b><div class='small muted'>Answer: {a.student_answer or ''} • Correct: {a.correct}</div></div>"
    html += "</div></div>"
    html += "<div class='col-lg-4'><div class='card p-3'><h5>Your performance</h5><canvas id='perfChart'></canvas></div></div></div>"
    html += "<script>const perfLabels = %s; const perfValues = %s; const ctx = document.getElementById('perfChart').getContext('2d'); new Chart(ctx,{type:'line',data:{labels:perfLabels,datasets:[{label:'Score %',data:perfValues, borderColor:'#0b6cf1', backgroundColor:'rgba(11,108,241,0.08)'}]}});</script>" % (chart_data["labels"], chart_data["values"])
    html += "<div style='margin-top:16px'><a class='btn btn-primary' href='/quiz/list'>Take Quiz</a></div>"
    return render_template_string(BASE_TEMPLATE, content=html)

# ---------- Quiz list ----------
@app.route("/quiz/list")
def quiz_list():
    if "student_id" not in session:
        return redirect("/login")
    grade = session.get("grade") or ""
    # show quizzes matching student's grade or global
    quizzes = Quiz.query.filter((Quiz.grade == grade) | (Quiz.grade == "") | (Quiz.grade == None)).order_by(Quiz.created_at.desc()).all()
    html = "<div class='card p-3'><h3>Available Quizzes</h3>"
    if not quizzes:
        html += "<p class='muted'>No quizzes available</p>"
    else:
        for q in quizzes:
            html += f"<div style='display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #f1f5f9'><div><b>{q.title}</b><div class='muted'>{q.subject} • Grade {q.grade}</div></div><div><a class='btn btn-primary' href='/quiz/start/{q.id}'>Start</a></div></div>"
    html += "</div>"
    return render_template_string(BASE_TEMPLATE, content=html)

# ---------- Start quiz (redirect to first passage) ----------
@app.route("/quiz/start/<int:quiz_id>")
def quiz_start(quiz_id):
    if "student_id" not in session:
        return redirect("/login")
    return redirect(f"/quiz/{quiz_id}/passage/0")

# ---------- Quiz passage route (adaptive question selection) ----------
@app.route("/quiz/<int:quiz_id>/passage/<int:index>", methods=["GET","POST"])
def quiz_passage(quiz_id, index):
    if "student_id" not in session:
        return redirect("/login")
    student = Student.query.get(session["student_id"])
    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return render_template_string(BASE_TEMPLATE, content="<div class='card p-3'>Quiz not found</div>")
    passages = Passage.query.filter_by(quiz_id=quiz_id).order_by(Passage.id).all()
    if not passages:
        return render_template_string(BASE_TEMPLATE, content="<div class='card p-3'>No passages in this quiz</div>")
    if index < 0 or index >= len(passages):
        return redirect(f"/quiz/{quiz_id}/passage/0")
    passage = passages[index]
    # determine question pool for this passage filtered by student.level
    level = student.level or "medium"
    # mapping: beginner->easy/medium, intermediate->medium/hard mix, advanced->hard
    def question_query_for_level(level):
        if level == "beginner":
            return Question.query.filter_by(passage_id=passage.id).filter(Question.difficulty.in_(["easy","medium"]))
        elif level == "intermediate":
            return Question.query.filter_by(passage_id=passage.id).filter(Question.difficulty.in_(["medium","hard"]))
        elif level == "advanced":
            return Question.query.filter_by(passage_id=passage.id).filter(Question.difficulty.in_(["hard","medium"]))
        else:
            return Question.query.filter_by(passage_id=passage.id)
    qpool = question_query_for_level(level).all()
    if not qpool:
        # fallback to any questions
        qpool = Question.query.filter_by(passage_id=passage.id).all()
    # For adaptive behavior within passage: pick up to 5 questions, prefer student's level
    selected_questions = random.sample(qpool, min(5, len(qpool)))
    if request.method == "POST":
        # record answers for submitted questions
        total_time = 0.0
        for q in selected_questions:
            key = f"q_{q.id}"
            ans = request.form.get(key, "")
            # optional time inputs
            tkey = f"t_{q.id}"
            tval = request.form.get(tkey)
            time_taken = float(tval) if tval else 0.0
            total_time += time_taken
            if q.qtype == "mcq":
                correct_flag = 1 if (ans or "").strip().lower() == (q.correct or "").strip().lower() else 0
            else:
                sim = subjective_similarity(ans or "", q.correct or "")
                correct_flag = 1 if sim >= 0.6 else 0
            a = Attempt(student_id=student.id, quiz_id=quiz_id, passage_id=passage.id, question_id=q.id, student_answer=ans, correct=int(correct_flag), time_taken=time_taken)
            db.session.add(a)
        db.session.commit()
        # proceed to next passage or finish
        next_index = index + 1
        if next_index >= len(passages):
            return redirect(f"/quiz/{quiz_id}/complete")
        else:
            return redirect(f"/quiz/{quiz_id}/passage/{next_index}")
    # Render passage and questions
    total = len(passages)
    progress_pct = int((index / total) * 100)
    timer = quiz.timer_seconds or 0
    html = f"<div class='card p-3'><h3>{quiz.title}</h3><div class='muted'>{quiz.subject} • Grade {quiz.grade}</div></div>"
    html += "<div class='card p-3'><div class='d-flex justify-content-between align-items-center'><h5>Passage</h5>"
    if timer and timer>0:
        html += f"<div class='timer' id='timer'>Time: {timer}s</div>"
    html += "</div>"
    html += f"<div class='progress-custom' style='margin-top:10px'><div style='width:{progress_pct}%; height:100%; background:linear-gradient(90deg,#0b6cf1,#7c3aed)'></div></div>"
    html += f"<h6 class='mt-3'>{passage.title or ''}</h6><div class='muted' style='white-space:pre-wrap'>{passage.content or ''}</div>"
    html += "<form method='post'>"
    # show selected questions
    for q in selected_questions:
        html += "<div class='mt-3 p-2' style='border-radius:8px;border:1px solid #eef2ff'>"
        html += f"<p><b>{q.text}</b> <span class='small muted'>({q.difficulty})</span></p>"
        if q.qtype == "mcq":
            for opt in ("option_a","option_b","option_c","option_d"):
                val = getattr(q,opt)
                if val:
                    html += f"<div class='form-check'><input class='form-check-input' type='radio' name='q_{q.id}' value='{val}' id='q{q.id}{opt}'><label class='form-check-label' for='q{q.id}{opt}'>{val}</label></div>"
        else:
            html += f"<textarea class='form-control' name='q_{q.id}' rows='3'></textarea>"
        # hidden time field (frontend can set with JS if you implement per-question timers)
        html += f"<input type='hidden' name='t_{q.id}' value='0'>"
        html += "</div>"
    html += "<div class='mt-3'><button class='btn btn-primary' type='submit'>Submit Passage</button> <a class='btn btn-outline-secondary' href='/quiz/list'>Exit</a></div>"
    html += "</form>"
    if timer and timer>0:
        html += f"""
        <script>
          (function(){{
            var time = {timer};
            var el = document.getElementById('timer');
            var iv = setInterval(function(){{
              time -= 1;
              if (time <= 0) {{ clearInterval(iv); var f = document.forms[0]; if(f) f.submit(); }}
              el.innerText = 'Time: ' + time + 's';
            }},1000);
          }})();
        </script>
        """
    return render_template_string(BASE_TEMPLATE, content=html)

# ---------- Quiz complete ----------
@app.route("/quiz/<int:quiz_id>/complete")
def quiz_complete(quiz_id):
    if "student_id" not in session:
        return redirect("/login")
    sid = session["student_id"]
    # compute stats for student on this quiz
    total = db.session.query(db.func.count(Attempt.id)).filter_by(student_id=sid, quiz_id=quiz_id).scalar() or 0
    correct = db.session.query(db.func.sum(Attempt.correct)).filter_by(student_id=sid, quiz_id=quiz_id).scalar() or 0
    pct = round((correct / total) * 100,2) if total>0 else 0.0
    html = f"<div class='card p-3'><h3>Quiz Completed</h3><p class='muted'>You answered {correct} of {total} items correctly</p><h4>Score: {pct}%</h4><a class='btn btn-primary' href='/student/dashboard'>Back to Dashboard</a></div>"
    return render_template_string(BASE_TEMPLATE, content=html)

# ---------- Teacher Dashboard (colorful & informative) ----------
@app.route("/teacher/dashboard")
def teacher_dashboard():
    if "teacher" not in session:
        return redirect("/login")
    # Aggregate data for many metrics
    # 1) Grade-level performance
    grade_rows = db.session.query(Student.grade,
                                  db.func.count(Attempt.id).label("attempts"),
                                  db.func.sum(Attempt.correct).label("correct")).join(Attempt, Attempt.student_id==Student.id).group_by(Student.grade).all()
    # 2) Class-wise
    class_rows = db.session.query(Student.class_section,
                                  db.func.count(Attempt.id).label("attempts"),
                                  db.func.sum(Attempt.correct).label("correct")).join(Attempt, Attempt.student_id==Student.id).group_by(Student.class_section).all()
    # 3) Gender breakdown
    gender_rows = db.session.query(Student.gender,
                                   db.func.count(Attempt.id).label("attempts"),
                                   db.func.sum(Attempt.correct).label("correct")).join(Attempt, Attempt.student_id==Student.id).group_by(Student.gender).all()
    # 4) Difficulty success rates
    diff_rows = db.session.query(Question.difficulty,
                                 db.func.count(Attempt.id).label("attempts"),
                                 db.func.sum(Attempt.correct).label("correct")).join(Attempt, Attempt.question_id==Question.id).group_by(Question.difficulty).all()
    # 5) Level distribution
    level_rows = db.session.query(Student.level, db.func.count(Student.id)).group_by(Student.level).all()
    # 6) Time vs score (per student average)
    time_score = db.session.query(Student.user_id,
                                  db.func.avg(Attempt.time_taken).label("avg_time"),
                                  (db.func.sum(Attempt.correct) * 100.0 / db.func.count(Attempt.id)).label("pct")).join(Attempt, Attempt.student_id==Student.id).group_by(Student.user_id).all()
    # Prepare JSON-able structures for Chart.js
    def pct_list(rows):
        labels = []
        values = []
        for r in rows:
            labels.append(r[0] or "N/A")
            attempts = r[1] or 0
            correct = r[2] or 0
            values.append(round((correct / attempts * 100) if attempts>0 else 0,2))
        return labels, values
    grade_labels, grade_vals = pct_list(grade_rows)
    class_labels, class_vals = pct_list(class_rows)
    gender_labels, gender_vals = pct_list(gender_rows)
    diff_labels = [r[0] for r in diff_rows]
    diff_vals = [round((r[2] or 0) / (r[1] or 1) * 100,2) if r[1] else 0 for r in diff_rows]
    level_labels = [r[0] for r in level_rows]
    level_vals = [r[1] for r in level_rows]
    # time vs score table
    time_score_rows = [{"user_id": r[0], "avg_time": round(r[1] or 0,2), "pct": round(r[2] or 0,2)} for r in time_score]
    # list quizzes
    quizzes = Quiz.query.order_by(Quiz.created_at.desc()).all()
    # build HTML
    html = "<div class='card p-3'><h3>Teacher Dashboard</h3><div class='small muted'>Comprehensive insights</div></div>"
    # info cards
    html += "<div class='row g-3'>"
    html += f"<div class='col-md-4'><div class='card p-3'><h5>Quizzes</h5><div class='small muted'>{len(quizzes)} total</div><a class='btn btn-primary mt-2' href='/teacher/create_quiz'>Create Quiz</a></div></div>"
    html += f"<div class='col-md-4'><div class='card p-3'><h5>Levels</h5><div class='small muted'>Distribution of student levels</div><div class='mt-2'>{''.join([f'<span class=\"tag me-2\">{label}: {val}</span>' for label,val in zip(level_labels, level_vals)])}</div></div></div>"
    html += f"<div class='col-md-4'><div class='card p-3'><h5>Export</h5><div class='small muted'>Download classwise report</div><a class='btn btn-outline-primary mt-2' href='/teacher/export_pdf'>Export PDF</a> <a class='btn btn-outline-danger mt-2' href='/teacher/reset_confirm'>Reset DB</a></div></div>"
    html += "</div>"
    # charts row
    html += "<div class='row g-3 mt-3'>"
    # grade chart
    html += "<div class='col-lg-6'><div class='card chart-card p-3'><h6>Performance by Grade</h6><canvas id='gradeChart'></canvas></div></div>"
    # class chart
    html += "<div class='col-lg-6'><div class='card chart-card p-3'><h6>Performance by Class</h6><canvas id='classChart'></canvas></div></div>"
    html += "</div>"
    # second row: difficulty and gender
    html += "<div class='row g-3 mt-3'><div class='col-lg-6'><div class='card p-3'><h6>Difficulty Success Rates</h6><canvas id='diffChart'></canvas></div></div>"
    html += "<div class='col-lg-6'><div class='card p-3'><h6>Gender Breakdown</h6><canvas id='genderChart'></canvas></div></div></div>"
    # time vs score table
    html += "<div class='card p-3 mt-3'><h6>Avg Time vs Score (per student)</h6><div class='table-responsive'><table class='table table-sm'><thead><tr><th>User ID</th><th>Avg Time (s)</th><th>Score %</th></tr></thead><tbody>"
    for ts in time_score_rows:
        html += f"<tr><td>{ts['user_id']}</td><td>{ts['avg_time']}</td><td>{ts['pct']}</td></tr>"
    html += "</tbody></table></div></div>"
    # JS for charts
    html += f"""
    <script>
      const gradeLabels = {grade_labels};
      const gradeVals = {grade_vals};
      const classLabels = {class_labels};
      const classVals = {class_vals};
      const diffLabels = {diff_labels};
      const diffVals = {diff_vals};
      const genderLabels = {gender_labels};
      const genderVals = {gender_vals};
      // Grade Chart
      new Chart(document.getElementById('gradeChart'), {{ type:'bar', data:{{ labels:gradeLabels, datasets:[{{label:'Avg %', data:gradeVals, backgroundColor:['#7c3aed','#0b6cf1','#06b6d4','#f97316'] }}] }}, options: {{ responsive:true }} }});
      // Class Chart
      new Chart(document.getElementById('classChart'), {{ type:'bar', data:{{ labels:classLabels, datasets:[{{label:'Avg %', data:classVals, backgroundColor:['#06b6d4','#7c3aed','#0b6cf1','#f97316'] }}] }}, options: {{ responsive:true }} }});
      // Difficulty
      new Chart(document.getElementById('diffChart'), {{ type:'pie', data:{{ labels:diffLabels, datasets:[{{data:diffVals, backgroundColor:['#7c3aed','#0b6cf1','#06b6d4']}}]}}, options:{{ responsive:true }} }});
      // Gender
      new Chart(document.getElementById('genderChart'), {{ type:'doughnut', data:{{ labels:genderLabels, datasets:[{{data:genderVals, backgroundColor:['#f97316','#0b6cf1','#7c3aed']}}]}}, options:{{ responsive:true }} }});
    </script>
    """
    return render_template_string(BASE_TEMPLATE, content=html)

# ---------- Teacher: Create Quiz ----------
@app.route("/teacher/create_quiz", methods=["GET","POST"])
def teacher_create_quiz():
    if "teacher" not in session:
        return redirect("/login")
    if request.method == "POST":
        title = request.form.get("title","").strip()
        grade = request.form.get("grade","").strip()
        subject = request.form.get("subject","").strip()
        timer = int(request.form.get("timer_seconds") or 0)
        q = Quiz(title=title, grade=grade, subject=subject, timer_seconds=timer)
        db.session.add(q); db.session.commit()
        return redirect(f"/teacher/add_passage/{q.id}")
    content = """
    <div class='card p-3' style='max-width:700px;margin:auto'>
      <h4>Create Quiz</h4>
      <form method='post'>
        <div class='mb-2'><input class='form-control' name='title' placeholder='Title' required></div>
        <div class='mb-2'><input class='form-control' name='grade' placeholder='Grade (e.g. 7)'></div>
        <div class='mb-2'><input class='form-control' name='subject' placeholder='Subject'></div>
        <div class='mb-2'><input class='form-control' name='timer_seconds' placeholder='Timer seconds per passage (optional)'></div>
        <button class='btn btn-primary' type='submit'>Create Quiz</button>
      </form>
    </div>
    """
    return render_template_string(BASE_TEMPLATE, content=content)

# ---------- Teacher: Add Passage ----------
@app.route("/teacher/add_passage/<int:quiz_id>", methods=["GET","POST"])
def teacher_add_passage(quiz_id):
    if "teacher" not in session:
        return redirect("/login")
    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return render_template_string(BASE_TEMPLATE, content="<div class='card p-3'>Quiz not found</div>")
    if request.method == "POST":
        title = request.form.get("title","").strip()
        content = request.form.get("content","").strip()
        p = Passage(quiz_id=quiz_id, title=title, content=content)
        db.session.add(p); db.session.commit()
        return redirect(f"/teacher/add_question/{p.id}")
    html = f"""
    <div class='card p-3'>
      <h4>Add Passage to: {quiz.title}</h4>
      <form method='post'>
        <div class='mb-2'><input class='form-control' name='title' placeholder='Passage title'></div>
        <div class='mb-2'><textarea class='form-control' name='content' rows='6' placeholder='Passage content'></textarea></div>
        <button class='btn btn-primary' type='submit'>Add Passage</button>
      </form>
    </div>
    """
    return render_template_string(BASE_TEMPLATE, content=html)

# ---------- Teacher: Add Question ----------
@app.route("/teacher/add_question/<int:passage_id>", methods=["GET","POST"])
def teacher_add_question(passage_id):
    if "teacher" not in session:
        return redirect("/login")
    passage = Passage.query.get(passage_id)
    if not passage:
        return render_template_string(BASE_TEMPLATE, content="<div class='card p-3'>Passage not found</div>")
    if request.method == "POST":
        text = request.form.get("text","").strip()
        qtype = request.form.get("qtype","mcq")
        a = request.form.get("option_a") or None
        b = request.form.get("option_b") or None
        c = request.form.get("option_c") or None
        d = request.form.get("option_d") or None
        correct = request.form.get("correct","").strip()
        difficulty = request.form.get("difficulty") or "medium"
        q = Question(quiz_id=passage.quiz_id, passage_id=passage_id, text=text, qtype=qtype, option_a=a, option_b=b, option_c=c, option_d=d, correct=correct, difficulty=difficulty)
        db.session.add(q); db.session.commit()
        return render_template_string(BASE_TEMPLATE, content=f"<div class='card p-3'>Question added. <a class='btn' href='/teacher/add_question/{passage_id}'>Add another</a> <a class='btn' href='/teacher/dashboard'>Dashboard</a></div>")
    html = f"""
    <div class='card p-3'>
      <h4>Add Question to Passage: {passage.title or ''}</h4>
      <form method='post'>
        <div class='mb-2'><textarea class='form-control' name='text' rows='3' placeholder='Question text'></textarea></div>
        <div class='mb-2'><select class='form-select' name='qtype'><option value='mcq'>MCQ</option><option value='subjective'>Subjective</option></select></div>
        <div class='mb-2'><input class='form-control' name='correct' placeholder='Correct answer / keywords'></div>
        <div class='mb-2'><input class='form-control' name='option_a' placeholder='Option A'></div>
        <div class='mb-2'><input class='form-control' name='option_b' placeholder='Option B'></div>
        <div class='mb-2'><input class='form-control' name='option_c' placeholder='Option C'></div>
        <div class='mb-2'><input class='form-control' name='option_d' placeholder='Option D'></div>
        <div class='mb-2'><select class='form-select' name='difficulty'><option value='easy'>Easy</option><option value='medium' selected>Medium</option><option value='hard'>Hard</option></select></div>
        <button class='btn btn-primary' type='submit'>Add Question</button>
      </form>
    </div>
    """
    return render_template_string(BASE_TEMPLATE, content=html)

# ---------- Teacher: Export PDF (base64 data link) ----------
@app.route("/teacher/export_pdf")
def teacher_export_pdf():
    if "teacher" not in session:
        return redirect("/login")
    # aggregate per-student
    rows = db.session.query(Student.user_id, Student.name, Student.grade, Student.class_section, Student.gender, Student.level, db.func.count(Attempt.id).label("attempts"), db.func.sum(Attempt.correct).label("correct")).outerjoin(Attempt, Attempt.student_id==Student.id).group_by(Student.id).order_by(Student.grade, Student.class_section, Student.user_id).all()
    rows_data = []
    for r in rows:
        rows_data.append({"user_id": r[0], "name": r[1], "grade": r[2], "class": r[3], "gender": r[4], "level": r[5], "attempts": int(r[6] or 0), "correct": int(r[7] or 0)})
    pdf_bytes = fpdf_bytes_for_student_report(rows_data)
    b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    content = "<div class='card p-3'><h4>Export Student Report</h4><p class='muted'>Click to download the PDF</p>"
    content += f"<a class='btn btn-primary' href='data:application/pdf;base64,{b64}' download='students_report.pdf'>Download PDF</a></div>"
    return render_template_string(BASE_TEMPLATE, content=content)

# ---------- Teacher: Reset confirm / reset ----------
@app.route("/teacher/reset_confirm")
def teacher_reset_confirm():
    if "teacher" not in session:
        return redirect("/login")
    content = "<div class='card p-3'><h4>Reset Database</h4><p class='muted'>This will delete students (all), quizzes, passages, questions and attempts. Type YES to confirm.</p><form method='post' action='/teacher/reset_db'><div class='mb-2'><input class='form-control' name='confirm' placeholder='Type YES to confirm'></div><button class='btn btn-danger' type='submit'>Reset Database</button> <a class='btn btn-outline-secondary' href='/teacher/dashboard'>Cancel</a></form></div>"
    return render_template_string(BASE_TEMPLATE, content=content)

@app.route("/teacher/reset_db", methods=["POST"])
def teacher_reset_db():
    if "teacher" not in session:
        return redirect("/login")
    confirm = request.form.get("confirm","")
    if confirm != "YES":
        return redirect("/teacher/dashboard")
    # destructive:
    Attempt.query.delete()
    Question.query.delete()
    Passage.query.delete()
    Quiz.query.delete()
    Student.query.delete()
    db.session.commit()
    db.create_all()
    return render_template_string(BASE_TEMPLATE, content="<div class='card p-3'>Database reset complete. <a class='btn' href='/'>Home</a></div>")

# ---------- Teacher: Delete quiz (POST) ----------
@app.route("/teacher/delete_quiz/<int:quiz_id>", methods=["GET","POST"])
def teacher_delete_quiz(quiz_id):
    if "teacher" not in session:
        return redirect("/login")
    q = Quiz.query.get(quiz_id)
    if not q:
        return render_template_string(BASE_TEMPLATE, content="<div class='card p-3'>Quiz not found</div>")
    if request.method == "POST":
        # cascade delete attempts and questions/passages then quiz
        Attempt.query.filter_by(quiz_id=quiz_id).delete()
        Question.query.filter(Question.passage_id.in_(db.session.query(Passage.id).filter_by(quiz_id=quiz_id))).delete()
        Passage.query.filter_by(quiz_id=quiz_id).delete()
        db.session.delete(q)
        db.session.commit()
        return redirect("/teacher/dashboard")
    return render_template_string(BASE_TEMPLATE, content=f"<div class='card p-3'><h4>Confirm delete quiz: {q.title}</h4><form method='post'><button class='btn btn-danger' type='submit'>Delete</button> <a class='btn btn-outline-secondary' href='/teacher/dashboard'>Cancel</a></form></div>")

# ---------- Simple endpoints to create sample data (for dev/testing) ----------
@app.route("/_seed_sample", methods=["GET"])
def seed_sample():
    # only allow in local setups
    # create sample quizzes, passages, questions, students
    # note: calling this repeatedly may create duplicates
    # create students
    for i in range(1,7):
        uid = f"student{i}"
        if not Student.query.filter_by(user_id=uid).first():
            st = Student(user_id=uid, password=generate_password_hash("pass123"), name=f"Student {i}", grade=str((i%3)+6), class_section=f"{(i%2)+1}", gender="Male" if i%2==0 else "Female")
            db.session.add(st)
    # create quiz
    qz = Quiz(title="Sample Math Quiz", grade="7", subject="Math", timer_seconds=120)
    db.session.add(qz); db.session.commit()
    # passage
    p = Passage(quiz_id=qz.id, title="Passage 1", content="Read the passage and answer the questions.")
    db.session.add(p); db.session.commit()
    # questions
    qs = [
        Question(quiz_id=qz.id, passage_id=p.id, text="2+2=?", qtype="mcq", option_a="3", option_b="4", option_c="5", option_d="6", correct="4", difficulty="easy"),
        Question(quiz_id=qz.id, passage_id=p.id, text="What is 10*5?", qtype="mcq", option_a="50", option_b="15", option_c="100", option_d="55", correct="50", difficulty="easy"),
        Question(quiz_id=qz.id, passage_id=p.id, text="Solve for x: 2x+3=7", qtype="subjective", correct="2", difficulty="medium"),
        Question(quiz_id=qz.id, passage_id=p.id, text="Describe what a prime number is", qtype="subjective", correct="number divisible only by 1 and itself", difficulty="hard"),
    ]
    for qq in qs:
        db.session.add(qq)
    db.session.commit()
    return "Sample seeded"

# ---------------- Run ----------------
if __name__ == "__main__":
    print("Ambassador Quiz App starting. Edit DATABASE_URL at top to use Postgres on Render.")
    app.run(host="0.0.0.0", port=5000, debug=True)
