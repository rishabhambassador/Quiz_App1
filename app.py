# app.py
"""
Ambassador Quiz App - single-file (Python-only UI)
Features:
 - Student & Teacher sign-up (teacher requires passkey)
 - Login/logout
 - Placement (calibration)
 - Adaptive quizzes (passage selection by student level)
 - Teachers: create quiz, create passage, add question (attach to passage or standalone)
 - Teacher dashboard with tables (no JS)
 - Export PDF report
 - Reset DB, Seed sample data, Delete quiz
"""
from flask import Flask, request, redirect, session, render_template_string, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import secrets, random, io, os
from fpdf import FPDF

# ------------- CONFIG -------------
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///app.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = secrets.token_hex(24)
db = SQLAlchemy(app)

# teacher passkeys required at signup if selecting Teacher role
TEACHER_PASSKEYS = {"teacher1": "math123", "teacher2": "science456", "admin": "supersecret"}

# ------------- MODELS -------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(300), nullable=False)
    name = db.Column(db.String(200))
    role = db.Column(db.String(30), default="student")  # 'student' or 'teacher'
    grade = db.Column(db.String(50))
    class_section = db.Column(db.String(50))
    gender = db.Column(db.String(30))
    level = db.Column(db.String(50), default="unknown")  # beginner/intermediate/advanced

class Quiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300))
    grade = db.Column(db.String(50))
    subject = db.Column(db.String(100))
    timer_seconds = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Passage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quiz.id"), nullable=False)
    title = db.Column(db.String(300))
    content = db.Column(db.Text)
    difficulty = db.Column(db.String(20), default="medium")  # easy/medium/hard

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, nullable=True)       # optional if standalone
    passage_id = db.Column(db.Integer, nullable=True)    # optional if standalone
    text = db.Column(db.Text)
    qtype = db.Column(db.String(50))  # Understanding/Application/Thinking
    option_a = db.Column(db.String(500))
    option_b = db.Column(db.String(500))
    option_c = db.Column(db.String(500))
    option_d = db.Column(db.String(500))
    correct = db.Column(db.String(500))  # for MCQ store 'A'/'B' etc or keyword for subjective
    difficulty = db.Column(db.String(50), default="medium")  # easy/medium/hard
    marks = db.Column(db.Integer, default=1)
    is_calibration = db.Column(db.Integer, default=0)  # 0/1 - used in placement

class Attempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    quiz_id = db.Column(db.Integer, nullable=True)
    passage_id = db.Column(db.Integer, nullable=True)
    question_id = db.Column(db.Integer)
    student_answer = db.Column(db.Text)
    correct = db.Column(db.Integer)  # 0/1
    time_taken = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# create tables
with app.app_context():
    db.create_all()

# ------------- Helpers -------------
import re
def normalize_words(text):
    if not text:
        return set()
    return set(re.findall(r"\w+", text.lower()))

def subjective_similarity(student_ans, teacher_ans):
    s = normalize_words(student_ans)
    t = normalize_words(teacher_ans)
    if not t:
        return 0.0
    matches = sum(1 for w in t if w in s)
    return matches / len(t)

def grade_level_from_score(score, total):
    if total == 0:
        return "unknown"
    pct = (score / total) * 100
    if pct >= 80:
        return "advanced"
    if pct >= 40:
        return "intermediate"
    return "beginner"

def generate_pdf_bytes(user_rows):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "Student Report - Ambassador Quiz App", ln=True, align="C")
    pdf.ln(6)
    pdf.set_font("Arial", size=10)
    headers = ["User", "Name", "Grade", "Class", "Gender", "Role", "Level", "Attempts", "Correct"]
    widths = [30, 40, 18, 18, 18, 18, 20, 18, 18]
    for h,w in zip(headers,widths):
        pdf.cell(w,8,h,1,0,"C")
    pdf.ln()
    for r in user_rows:
        pdf.cell(widths[0],8,str(r.get("username","")),1)
        pdf.cell(widths[1],8,str(r.get("name","")),1)
        pdf.cell(widths[2],8,str(r.get("grade","") or ""),1)
        pdf.cell(widths[3],8,str(r.get("class","") or ""),1)
        pdf.cell(widths[4],8,str(r.get("gender","") or ""),1)
        pdf.cell(widths[5],8,str(r.get("role","") or ""),1)
        pdf.cell(widths[6],8,str(r.get("level","") or ""),1)
        pdf.cell(widths[7],8,str(r.get("attempts",0)),1,0,"C")
        pdf.cell(widths[8],8,str(r.get("correct",0)),1,1,"C")
    return pdf.output(dest="S").encode("latin1")

# ------------- Templates (simple, no JS) -------------
BASE = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ambassador Quiz App</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style> body{background:#f8fafc;color:#0f1724;font-family:Inter,Arial;} .card{border-radius:8px} .muted{color:#6b7280} table td,table th{vertical-align:middle}</style>
</head><body>
<nav class="navbar navbar-expand-lg" style="background:#0b3b6f"><div class="container-fluid"><a class="navbar-brand text-white" href="/">Ambassador Quiz App</a>
<div class="ms-auto">
{% if session.get('user_id') %}
  <span class="text-white me-2">{{ session.get('username') }} ({{ session.get('role') }})</span>
  <a class="btn btn-light btn-sm" href="/logout">Logout</a>
{% else %}
  <a class="btn btn-light btn-sm" href="/login">Login</a>
  <a class="btn btn-outline-light btn-sm" href="/signup">Sign Up</a>
{% endif %}
</div></div></nav>
<div class="container my-4">{{ content|safe }}</div></body></html>
"""

# ------------- Routes -------------
@app.route("/")
def home():
    content = """
    <div class='card p-4'>
      <div class='d-flex justify-content-between align-items-center'>
        <div>
          <h2>Ambassador Quiz App</h2>
          <p class='muted'>Adaptive quizzes, placement, teacher dashboard — Python-only UI.</p>
        </div>
        <div>
          <a class='btn btn-primary' href='/login'>Login</a>
          <a class='btn btn-outline-primary' href='/signup'>Sign Up</a>
        </div>
      </div>
    </div>"""
    return render_template_string(BASE, content=content)

# ---------- Signup with role selection ----------
@app.route("/signup", methods=["GET","POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        name = request.form.get("name","").strip()
        role = request.form.get("role","student")
        grade = request.form.get("grade","").strip()
        class_section = request.form.get("class_section","").strip()
        gender = request.form.get("gender","").strip()
        teacher_name = request.form.get("teacher_name","").strip()
        teacher_passkey = request.form.get("teacher_passkey","").strip()

        if not username or not password:
            return render_template_string(BASE, content="<div class='card p-3'>Username and password required</div>")

        if User.query.filter_by(username=username).first():
            return render_template_string(BASE, content="<div class='card p-3'>Username exists. <a href='/signup'>Back</a></div>")

        if role == "teacher":
            # require valid teacher passkey for teacher creation
            if TEACHER_PASSKEYS.get(teacher_name) != teacher_passkey:
                return render_template_string(BASE, content="<div class='card p-3'>Invalid teacher passkey. Ask admin.</div>")
            role_final = "teacher"
        else:
            role_final = "student"

        hashed = generate_password_hash(password)
        user = User(username=username, password=hashed, name=name, role=role_final, grade=grade, class_section=class_section, gender=gender)
        db.session.add(user); db.session.commit()
        return redirect("/login")

    content = """
    <div class='card p-3' style='max-width:720px;margin:auto'>
      <h3>Sign Up</h3>
      <form method='post'>
        <input class='form-control mb-2' name='name' placeholder='Full name'>
        <input class='form-control mb-2' name='username' placeholder='Username' required>
        <input class='form-control mb-2' type='password' name='password' placeholder='Password' required>
        <div class='row'><div class='col'><input class='form-control mb-2' name='grade' placeholder='Grade'></div><div class='col'><input class='form-control mb-2' name='class_section' placeholder='Class'></div></div>
        <select class='form-select mb-2' name='gender'><option>Male</option><option>Female</option><option>Other</option></select>
        <div class='mb-2'>
          <label>Role</label>
          <select class='form-select' name='role' id='role_select' onchange="document.getElementById('teacher_fields').style.display=(this.value==='teacher'?'block':'none')">
            <option value='student' selected>Student</option><option value='teacher'>Teacher</option>
          </select>
        </div>
        <div id='teacher_fields' style='display:none'>
          <input class='form-control mb-2' name='teacher_name' placeholder='teacher1 (passkey owner)'>
          <input class='form-control mb-2' name='teacher_passkey' placeholder='Passkey'>
        </div>
        <button class='btn btn-primary' type='submit'>Sign Up</button>
      </form>
    </div>
    <script>/* minimal inline to toggle teacher fields; remains within template */</script>
    """
    return render_template_string(BASE, content=content)

# ---------- Login ----------
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session.clear()
            session["user_id"] = user.id
            session["username"] = user.username
            session["role"] = user.role
            return redirect("/dashboard")
        return render_template_string(BASE, content="<div class='card p-3'>Invalid credentials</div>")
    content = """
    <div class='card p-3' style='max-width:480px;margin:auto'>
      <h3>Login</h3>
      <form method='post'>
        <input class='form-control mb-2' name='username' placeholder='Username' required>
        <input class='form-control mb-2' name='password' placeholder='Password' type='password' required>
        <button class='btn btn-primary' type='submit'>Login</button>
      </form>
      <div class='mt-2'><a href='/signup'>Sign Up</a></div>
    </div>
    """
    return render_template_string(BASE, content=content)

# ---------- Logout ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------- Placement (calibration) ----------
@app.route("/placement", methods=["GET","POST"])
def placement():
    if "user_id" not in session:
        return redirect("/login")
    user = User.query.get(session["user_id"])
    cal_questions = Question.query.filter_by(is_calibration=1).all()
    if not cal_questions:
        return render_template_string(BASE, content="<div class='card p-3'>No calibration questions available. Ask teacher to add them.</div>")

    chosen = random.sample(cal_questions, min(5, len(cal_questions)))
    if request.method == "POST":
        answers = {k: v for k,v in request.form.items() if k.startswith("q_")}
        score = 0; total = 0
        for key, val in answers.items():
            qid = int(key.split("_",1)[1]); q = Question.query.get(qid)
            if not q: continue
            total += 1
            if q.option_a or q.option_b or q.option_c or q.option_d:
                if (val or "").strip().upper() == (q.correct or "").strip().upper():
                    score += 1
            else:
                sim = subjective_similarity(val or "", q.correct or "")
                if sim >= 0.6:
                    score += 1
        level = grade_level_from_score(score, total)
        user.level = level
        db.session.commit()
        return render_template_string(BASE, content=f"<div class='card p-3'>Placement done. Level assigned: <b>{level}</b><br><a class='btn btn-primary mt-2' href='/dashboard'>Go to Dashboard</a></div>")

    html = "<div class='card p-3'><h4>Placement Calibration</h4><form method='post'>"
    for q in chosen:
        html += f"<div class='mb-3'><b>{q.text}</b><div class='muted small'>Type: {q.qtype or 'N/A'}</div>"
        if q.option_a or q.option_b or q.option_c or q.option_d:
            for label,opt in (('A','option_a'),('B','option_b'),('C','option_c'),('D','option_d')):
                val = getattr(q,opt)
                if val:
                    html += f"<div><label><input type='radio' name='q_{q.id}' value='{label}'> {label}. {val}</label></div>"
        else:
            html += f"<textarea class='form-control' name='q_{q.id}' rows='3'></textarea>"
        html += "</div>"
    html += "<button class='btn btn-primary' type='submit'>Submit Placement</button></form></div>"
    return render_template_string(BASE, content=html)

# ---------- Student Dashboard ----------
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")
    user = User.query.get(session["user_id"])
    # summary
    total = db.session.query(Attempt).filter_by(user_id=user.id).count()
    correct = db.session.query(db.func.sum(Attempt.correct)).filter_by(user_id=user.id).scalar() or 0
    accuracy = f"{(correct/total*100):.2f}%" if total>0 else "N/A"

    # recent attempts (limit 20)
    attempts = db.session.query(Attempt).filter_by(user_id=user.id).order_by(Attempt.created_at.desc()).limit(20).all()
    attempt_rows = []
    for a in attempts:
        q = Question.query.get(a.question_id)
        attempt_rows.append({
            "text": q.text if q else "Question",
            "ans": a.student_answer,
            "correct": a.correct,
            "when": a.created_at.strftime("%Y-%m-%d %H:%M")
        })

    # teacher view: summary lists
    teachers_links = ""
    if user.role == "teacher":
        teachers_links = """
          <div class='card p-3 mt-3'>
            <h5>Teacher Actions</h5>
            <a class='btn btn-primary' href='/teacher/create_quiz'>Create Quiz</a>
            <a class='btn btn-outline-secondary' href='/teacher/dashboard'>Teacher Dashboard</a>
            <a class='btn btn-outline-danger' href='/teacher/reset_confirm'>Reset DB</a>
          </div>
        """

    content = f"""
    <div class='card p-3'><h4>Welcome, {user.name or user.username} ({user.role})</h4>
      <div class='muted'>Level: <b>{user.level}</b> • Grade: {user.grade or 'N/A'}</div>
      <div class='mt-2'>Total answered: <b>{total}</b> • Correct: <b>{correct}</b> • Accuracy: <b>{accuracy}</b></div>
      <div class='mt-3'><a class='btn btn-primary' href='/quiz/list'>Take Quiz</a> <a class='btn btn-outline-primary' href='/report'>Download Report (PDF)</a></div>
    </div>
    <div class='card p-3 mt-3'><h5>Recent Attempts</h5>
    """
    if not attempt_rows:
        content += "<p class='muted'>No attempts yet</p>"
    else:
        content += "<table class='table table-sm'><thead><tr><th>Question</th><th>Answer</th><th>Correct</th><th>When</th></tr></thead><tbody>"
        for r in attempt_rows:
            content += f"<tr><td>{r['text']}</td><td>{r['ans'] or ''}</td><td>{'Yes' if r['correct'] else 'No'}</td><td>{r['when']}</td></tr>"
        content += "</tbody></table>"
    content += "</div>" + teachers_links
    return render_template_string(BASE, content=content)

# ---------- Quiz list ----------
@app.route("/quiz/list")
def quiz_list():
    if "user_id" not in session:
        return redirect("/login")
    user = User.query.get(session["user_id"])
    quizzes = Quiz.query.order_by(Quiz.created_at.desc()).all()
    html = "<div class='card p-3'><h4>Available Quizzes</h4>"
    if not quizzes:
        html += "<p class='muted'>No quizzes available</p>"
    else:
        html += "<table class='table table-sm'><thead><tr><th>Title</th><th>Subject</th><th>Grade</th><th>Action</th></tr></thead><tbody>"
        for q in quizzes:
            html += f"<tr><td>{q.title}</td><td>{q.subject or ''}</td><td>{q.grade or 'All'}</td><td><a class='btn btn-primary btn-sm' href='/quiz/start/{q.id}'>Start</a></td></tr>"
        html += "</tbody></table>"
    html += "</div>"
    return render_template_string(BASE, content=html)

# ---------- Start quiz -> choose passage adaptively ----------
@app.route("/quiz/start/<int:quiz_id>")
def quiz_start(quiz_id):
    if "user_id" not in session:
        return redirect("/login")
    return redirect(f"/quiz/{quiz_id}/begin")

@app.route("/quiz/<int:quiz_id>/begin")
def quiz_begin(quiz_id):
    if "user_id" not in session:
        return redirect("/login")
    user = User.query.get(session["user_id"])
    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return render_template_string(BASE, content="<div class='card p-3'>Quiz not found</div>")
    diff_map = {"beginner":"easy","intermediate":"medium","advanced":"hard"}
    desired = diff_map.get(user.level, None)
    passages = []
    if desired:
        passages = Passage.query.filter_by(quiz_id=quiz_id, difficulty=desired).all()
    if not passages:
        passages = Passage.query.filter_by(quiz_id=quiz_id).all()
    if not passages:
        return render_template_string(BASE, content="<div class='card p-3'>No passages in this quiz</div>")
    passage = random.choice(passages)
    return redirect(f"/quiz/{quiz_id}/passage/{passage.id}")

# ---------- Quiz passage (questions selection & submit) ----------
@app.route("/quiz/<int:quiz_id>/passage/<int:passage_id>", methods=["GET","POST"])
def quiz_passage(quiz_id, passage_id):
    if "user_id" not in session:
        return redirect("/login")
    user = User.query.get(session["user_id"])
    quiz = Quiz.query.get(quiz_id); passage = Passage.query.get(passage_id)
    if not quiz or not passage:
        return render_template_string(BASE, content="<div class='card p-3'>Quiz or passage not found</div>")

    if request.method == "POST":
        qids_raw = request.form.get("qids","")
        qids = [int(x) for x in qids_raw.split(",")] if qids_raw else []
        selected = Question.query.filter(Question.id.in_(qids)).all()
        total = 0; correct = 0
        for q in selected:
            total += 1
            ans = request.form.get(f"q_{q.id}", "")
            if q.option_a or q.option_b or q.option_c or q.option_d:
                flag = 1 if (ans or "").strip().upper() == (q.correct or "").strip().upper() else 0
            else:
                sim = subjective_similarity(ans or "", q.correct or "")
                flag = 1 if sim >= 0.6 else 0
            a = Attempt(user_id=user.id, quiz_id=quiz_id, passage_id=passage_id, question_id=q.id, student_answer=ans, correct=int(flag), time_taken=float(request.form.get(f"t_{q.id}",0) or 0))
            db.session.add(a)
            correct += int(flag)
        db.session.commit()
        pct = round((correct/total)*100,2) if total>0 else 0.0
        return render_template_string(BASE, content=f"<div class='card p-3'><h4>Completed</h4><p class='muted'>Correct: {correct}/{total} • Score: {pct}%</p><a class='btn btn-primary mt-2' href='/dashboard'>Back</a></div>")

    # GET: select pool by student level
    if user.level == "beginner":
        pool = Question.query.filter_by(passage_id=passage_id).filter(Question.difficulty.in_(["easy","medium"])).all()
    elif user.level == "intermediate":
        pool = Question.query.filter_by(passage_id=passage_id).filter(Question.difficulty.in_(["medium","hard"])).all()
    elif user.level == "advanced":
        pool = Question.query.filter_by(passage_id=passage_id).filter(Question.difficulty.in_(["hard","medium"])).all()
    else:
        pool = Question.query.filter_by(passage_id=passage_id).all()
    if not pool:
        pool = Question.query.filter_by(passage_id=passage_id).all()
    selected = random.sample(pool, min(5, len(pool)))
    qids = ",".join(str(q.id) for q in selected)

    html = f"<div class='card p-3'><h4>{quiz.title}</h4><div class='muted'>{quiz.subject or 'General'} • Grade {quiz.grade or 'All'}</div></div>"
    html += "<div class='card p-3'><h5>Passage</h5>"
    if passage.title:
        html += f"<h6>{passage.title}</h6>"
    if passage.content:
        html += f"<div class='muted' style='white-space:pre-wrap'>{passage.content}</div>"
    html += "<form method='post'>"
    for q in selected:
        html += f"<div class='mt-3 p-2' style='border-radius:8px;border:1px solid #eef2ff'><p><b>{q.text}</b> <span class='muted small'>({q.qtype or 'N/A'} • {q.difficulty})</span></p>"
        if q.option_a or q.option_b or q.option_c or q.option_d:
            for label, opt in (('A','option_a'),('B','option_b'),('C','option_c'),('D','option_d')):
                val = getattr(q, opt)
                if val:
                    html += f"<div><label><input type='radio' name='q_{q.id}' value='{label}'> {label}. {val}</label></div>"
        else:
            html += f"<textarea class='form-control' name='q_{q.id}' rows='3'></textarea>"
        html += f"<input type='hidden' name='t_{q.id}' value='0'>"
        html += "</div>"
    html += f"<input type='hidden' name='qids' value='{qids}'>"
    html += "<div class='mt-3'><button class='btn btn-primary' type='submit'>Submit Passage</button> <a class='btn btn-outline-secondary' href='/quiz/list'>Exit</a></div></form></div>"
    return render_template_string(BASE, content=html)

# ---------- Teacher Dashboard ----------
@app.route("/teacher/dashboard")
def teacher_dashboard():
    if "user_id" not in session:
        return redirect("/login")
    user = User.query.get(session["user_id"])
    if user.role != "teacher":
        return render_template_string(BASE, content="<div class='card p-3'>Access denied</div>")

    total_students = User.query.filter_by(role="student").count()
    total_quizzes = Quiz.query.count()
    total_attempts = Attempt.query.count()

    # student stats
    rows = db.session.query(
        User.username, User.name, User.grade, User.class_section, User.gender, User.level,
        db.func.count(Attempt.id).label("attempts"),
        db.func.sum(Attempt.correct).label("correct")
    ).outerjoin(Attempt, Attempt.user_id==User.id).group_by(User.id).filter(User.role=="student").all()

    # simple tables for quizzes, passages, questions
    quizzes = Quiz.query.order_by(Quiz.created_at.desc()).all()

    html = f"<div class='card p-3'><h4>Teacher Dashboard</h4><div class='muted'>Overview</div><div class='mt-2'>Students: <b>{total_students}</b> • Quizzes: <b>{total_quizzes}</b> • Attempts: <b>{total_attempts}</b></div></div>"
    html += "<div class='card p-3 mt-3'><h5>Students</h5>"
    if not rows:
        html += "<p class='muted'>No students yet</p>"
    else:
        html += "<table class='table table-sm'><thead><tr><th>User</th><th>Name</th><th>Grade</th><th>Class</th><th>Level</th><th>Attempts</th><th>Correct</th></tr></thead><tbody>"
        for r in rows:
            html += f"<tr><td>{r[0]}</td><td>{r[1] or ''}</td><td>{r[2] or ''}</td><td>{r[3] or ''}</td><td>{r[5] or ''}</td><td>{int(r[6] or 0)}</td><td>{int(r[7] or 0)}</td></tr>"
        html += "</tbody></table>"
    html += "</div>"

    html += "<div class='card p-3 mt-3'><h5>Quizzes</h5>"
    html += "<a class='btn btn-primary' href='/teacher/create_quiz'>Create New Quiz</a>"
    if not quizzes:
        html += "<p class='muted mt-2'>No quizzes</p>"
    else:
        html += "<table class='table table-sm mt-2'><thead><tr><th>Title</th><th>Subject</th><th>Grade</th><th>Created</th><th>Actions</th></tr></thead><tbody>"
        for q in quizzes:
            html += f"<tr><td>{q.title}</td><td>{q.subject or ''}</td><td>{q.grade or ''}</td><td>{q.created_at.strftime('%Y-%m-%d')}</td><td><a class='btn btn-sm btn-outline-primary' href='/teacher/add_passage/{q.id}'>Add Passage</a> <a class='btn btn-sm btn-outline-secondary' href='/teacher/view_quiz/{q.id}'>View</a> <a class='btn btn-sm btn-danger' href='/teacher/delete_quiz/{q.id}'>Delete</a></td></tr>"
        html += "</tbody></table>"
    html += "</div>"

    html += "<div class='card p-3 mt-3'><a class='btn btn-outline-primary' href='/teacher/export_pdf'>Export Students PDF</a> <a class='btn btn-danger ms-2' href='/teacher/reset_confirm'>Reset DB</a></div>"

    return render_template_string(BASE, content=html)

# ---------- Teacher: create quiz ----------
@app.route("/teacher/create_quiz", methods=["GET","POST"])
def teacher_create_quiz():
    if "user_id" not in session:
        return redirect("/login")
    user = User.query.get(session["user_id"])
    if user.role != "teacher":
        return render_template_string(BASE, content="<div class='card p-3'>Access denied</div>")
    if request.method == "POST":
        title = request.form.get("title","").strip()
        grade = request.form.get("grade","").strip()
        subject = request.form.get("subject","").strip()
        timer_seconds = int(request.form.get("timer_seconds") or 0)
        q = Quiz(title=title, grade=grade, subject=subject, timer_seconds=timer_seconds)
        db.session.add(q); db.session.commit()
        return redirect(f"/teacher/add_passage/{q.id}")
    html = "<div class='card p-3'><h5>Create Quiz</h5><form method='post'><input class='form-control mb-2' name='title' placeholder='Title' required><input class='form-control mb-2' name='grade' placeholder='Grade'><input class='form-control mb-2' name='subject' placeholder='Subject'><input class='form-control mb-2' name='timer_seconds' placeholder='Timer seconds per passage'><button class='btn btn-primary' type='submit'>Create</button></form></div>"
    return render_template_string(BASE, content=html)

# ---------- Teacher: add passage ----------
@app.route("/teacher/add_passage/<int:quiz_id>", methods=["GET","POST"])
def teacher_add_passage(quiz_id):
    if "user_id" not in session:
        return redirect("/login")
    user = User.query.get(session["user_id"])
    if user.role != "teacher":
        return render_template_string(BASE, content="<div class='card p-3'>Access denied</div>")
    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return render_template_string(BASE, content="<div class='card p-3'>Quiz not found</div>")
    if request.method == "POST":
        title = request.form.get("title","").strip()
        content = request.form.get("content","").strip()
        difficulty = request.form.get("difficulty","medium")
        p = Passage(quiz_id=quiz_id, title=title, content=content, difficulty=difficulty)
        db.session.add(p); db.session.commit()
        return redirect(f"/teacher/add_question/{p.id}")
    html = f"<div class='card p-3'><h5>Add Passage to {quiz.title}</h5><form method='post'><input class='form-control mb-2' name='title' placeholder='Passage title'><select class='form-select mb-2' name='difficulty'><option value='easy'>easy</option><option selected value='medium'>medium</option><option value='hard'>hard</option></select><textarea class='form-control mb-2' name='content' rows='6' placeholder='Passage text'></textarea><button class='btn btn-primary' type='submit'>Add Passage</button></form></div>"
    return render_template_string(BASE, content=html)

# ---------- Teacher: add question (option to attach to passage or leave standalone) ----------
@app.route("/teacher/add_question/<int:passage_id>", methods=["GET","POST"])
def teacher_add_question(passage_id):
    if "user_id" not in session:
        return redirect("/login")
    user = User.query.get(session["user_id"])
    if user.role != "teacher":
        return render_template_string(BASE, content="<div class='card p-3'>Access denied</div>")

    passage = Passage.query.get(passage_id)
    if not passage:
        return render_template_string(BASE, content="<div class='card p-3'>Passage not found</div>")

    if request.method == "POST":
        text = request.form.get("text","").strip()
        qtype = request.form.get("qtype","Understanding")
        option_a = request.form.get("option_a") or None
        option_b = request.form.get("option_b") or None
        option_c = request.form.get("option_c") or None
        option_d = request.form.get("option_d") or None
        correct = request.form.get("correct","").strip()
        difficulty = request.form.get("difficulty","medium")
        is_cal = 1 if request.form.get("is_calibration") == "on" else 0
        attach_to_passage = request.form.get("attach_to_passage","on") == "on"  # default attach
        q = Question(
            quiz_id = passage.quiz_id if attach_to_passage else None,
            passage_id = passage.id if attach_to_passage else None,
            text = text,
            qtype = qtype,
            option_a = option_a,
            option_b = option_b,
            option_c = option_c,
            option_d = option_d,
            correct = correct,
            difficulty = difficulty,
            is_calibration = is_cal
        )
        db.session.add(q); db.session.commit()
        return render_template_string(BASE, content=f"<div class='card p-3'>Question added. <a class='btn btn-primary' href='/teacher/add_question/{passage_id}'>Add another</a> <a class='btn btn-outline-secondary' href='/teacher/dashboard'>Dashboard</a></div>")

    html = f"<div class='card p-3'><h5>Add Question (Passage: {passage.title or ''})</h5><form method='post'>"
    html += "<textarea class='form-control mb-2' name='text' rows='3' placeholder='Question text'></textarea>"
    html += "<select class='form-select mb-2' name='qtype'><option>Understanding</option><option>Application</option><option>Thinking</option></select>"
    html += "<input class='form-control mb-2' name='correct' placeholder='Correct answer (A/B/C/D or keywords)'>"
    html += "<input class='form-control mb-2' name='option_a' placeholder='Option A'><input class='form-control mb-2' name='option_b' placeholder='Option B'>"
    html += "<input class='form-control mb-2' name='option_c' placeholder='Option C'><input class='form-control mb-2' name='option_d' placeholder='Option D'>"
    html += "<select class='form-select mb-2' name='difficulty'><option>easy</option><option selected>medium</option><option>hard</option></select>"
    html += "<div class='form-check mb-2'><input class='form-check-input' type='checkbox' id='is_cal' name='is_calibration'><label class='form-check-label' for='is_cal'>Use as calibration (placement) question</label></div>"
    html += "<div class='form-check mb-2'><input class='form-check-input' type='checkbox' id='attach_to_passage' name='attach_to_passage' checked><label class='form-check-label' for='attach_to_passage'>Attach this question to the passage</label></div>"
    html += "<button class='btn btn-primary' type='submit'>Add Question</button></form></div>"
    return render_template_string(BASE, content=html)

# ---------- Teacher: view quiz details (passages & standalone questions) ----------
@app.route("/teacher/view_quiz/<int:quiz_id>")
def teacher_view_quiz(quiz_id):
    if "user_id" not in session:
        return redirect("/login")
    user = User.query.get(session["user_id"])
    if user.role != "teacher":
        return render_template_string(BASE, content="<div class='card p-3'>Access denied</div>")
    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return render_template_string(BASE, content="<div class='card p-3'>Quiz not found</div>")
    passages = Passage.query.filter_by(quiz_id=quiz.id).all()
    standalone_questions = Question.query.filter_by(quiz_id=None, passage_id=None).all()
    html = f"<div class='card p-3'><h4>{quiz.title}</h4><div class='muted'>Subject: {quiz.subject or ''}</div></div>"
    html += "<div class='card p-3 mt-3'><h5>Passages</h5>"
    if not passages:
        html += "<p class='muted'>No passages</p>"
    else:
        for p in passages:
            html += f"<div style='border-bottom:1px solid #eef2ff;padding:8px 0'><h6>{p.title} <small class='muted'>({p.difficulty})</small></h6><div style='white-space:pre-wrap'>{p.content}</div>"
            qs = Question.query.filter_by(passage_id=p.id).all()
            if qs:
                html += "<ul>"
                for q in qs:
                    html += f"<li>{q.text} <small class='muted'>({q.difficulty})</small></li>"
                html += "</ul>"
            html += f"<a class='btn btn-sm btn-outline-primary' href='/teacher/add_question/{p.id}'>Add Question</a></div>"
    html += "</div>"

    html += "<div class='card p-3 mt-3'><h5>Standalone Questions</h5>"
    if not standalone_questions:
        html += "<p class='muted'>No standalone questions</p>"
    else:
        html += "<ul>"
        for q in standalone_questions:
            html += f"<li>{q.text} <small class='muted'>({q.difficulty})</small></li>"
        html += "</ul>"
    html += "</div>"
    return render_template_string(BASE, content=html)

# ---------- Export PDF (teacher) ----------
@app.route("/teacher/export_pdf")
def teacher_export_pdf():
    if "user_id" not in session:
        return redirect("/login")
    user = User.query.get(session["user_id"])
    if user.role != "teacher":
        return render_template_string(BASE, content="<div class='card p-3'>Access denied</div>")

    rows = db.session.query(User.username, User.name, User.grade, User.class_section, User.gender, User.role, User.level,
                            db.func.count(Attempt.id).label("attempts"), db.func.sum(Attempt.correct).label("correct")) \
            .outerjoin(Attempt, Attempt.user_id==User.id).group_by(User.id).order_by(User.grade, User.class_section).all()
    data = []
    for r in rows:
        data.append({"username": r[0], "name": r[1], "grade": r[2], "class": r[3], "gender": r[4], "role": r[5], "level": r[6], "attempts": int(r[7] or 0), "correct": int(r[8] or 0)})
    pdfb = generate_pdf_bytes(data)
    return send_file(io.BytesIO(pdfb), download_name="students_report.pdf", as_attachment=True, mimetype="application/pdf")

# ---------- Reset DB ----------
@app.route("/teacher/reset_confirm")
def teacher_reset_confirm():
    if "user_id" not in session:
        return redirect("/login")
    user = User.query.get(session["user_id"])
    if user.role != "teacher":
        return render_template_string(BASE, content="<div class='card p-3'>Access denied</div>")
    content = "<div class='card p-3'><h5>Reset Database</h5><p class='muted'>This will delete ALL students, quizzes, passages, questions and attempts. Type YES to confirm.</p><form method='post' action='/teacher/reset_db'><input class='form-control mb-2' name='confirm'><button class='btn btn-danger' type='submit'>Reset</button> <a class='btn btn-outline-secondary' href='/teacher/dashboard'>Cancel</a></form></div>"
    return render_template_string(BASE, content=content)

@app.route("/teacher/reset_db", methods=["POST"])
def teacher_reset_db():
    if "user_id" not in session:
        return redirect("/login")
    user = User.query.get(session["user_id"])
    if user.role != "teacher":
        return render_template_string(BASE, content="<div class='card p-3'>Access denied</div>")
    if request.form.get("confirm") != "YES":
        return redirect("/teacher/dashboard")
    db.drop_all()
    db.create_all()
    return render_template_string(BASE, content="<div class='card p-3'>Database reset.</div>")

# ---------- Delete quiz ----------
@app.route("/teacher/delete_quiz/<int:quiz_id>", methods=["GET","POST"])
def teacher_delete_quiz(quiz_id):
    if "user_id" not in session:
        return redirect("/login")
    user = User.query.get(session["user_id"])
    if user.role != "teacher":
        return render_template_string(BASE, content="<div class='card p-3'>Access denied</div>")
    q = Quiz.query.get(quiz_id)
    if not q:
        return render_template_string(BASE, content="<div class='card p-3'>Quiz not found</div>")
    if request.method == "POST":
        Attempt.query.filter_by(quiz_id=quiz_id).delete()
        # delete questions associated to passages of this quiz
        passage_ids = [p.id for p in Passage.query.filter_by(quiz_id=quiz_id).all()]
        if passage_ids:
            Question.query.filter(Question.passage_id.in_(passage_ids)).delete(synchronize_session=False)
        Passage.query.filter_by(quiz_id=quiz_id).delete()
        db.session.delete(q); db.session.commit()
        return redirect("/teacher/dashboard")
    return render_template_string(BASE, content=f"<div class='card p-3'><h5>Delete Quiz: {q.title}</h5><form method='post'><button class='btn btn-danger' type='submit'>Confirm Delete</button> <a class='btn btn-outline-secondary' href='/teacher/dashboard'>Cancel</a></form></div>")

# ---------- Report (student) ----------
@app.route("/report")
def report():
    if "user_id" not in session:
        return redirect("/login")
    user = User.query.get(session["user_id"])
    results = db.session.query(Question.text, Question.correct, Attempt.correct).join(Attempt, Attempt.question_id==Question.id).filter(Attempt.user_id==user.id).all()
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, f"Quiz Report - {user.username}", ln=True, align="C")
    pdf.ln(10)
    correct_count = 0
    for text, ans, corr in results:
        status = "Correct" if corr else "Wrong"
        if corr:
            correct_count += 1
        pdf.multi_cell(0, 8, f"Q: {text}\nResult: {status}\nAnswer/key: {ans}\n")
    pdf.ln(5)
    pdf.cell(200, 10, f"Final Score: {correct_count}/{len(results)}", ln=True, align="C")
    filename = f"report_{user.username}.pdf"
    pdf.output(filename)
    return send_file(filename, as_attachment=True)

# ---------- Seed route ----------
@app.route("/_seed")
def seed():
    # quick sample data: one teacher, some students, one quiz, passage & questions
    if User.query.filter_by(username="teacher1").first() is None:
        t = User(username="teacher1", password=generate_password_hash("teachpass"), name="Teacher One", role="teacher")
        db.session.add(t)
    for i in range(1,5):
        if User.query.filter_by(username=f"student{i}").first() is None:
            st = User(username=f"student{i}", password=generate_password_hash("pass123"), name=f"Student {i}", role="student", grade=str(6 + (i%3)), class_section=str((i%2)+1), gender="Male" if i%2==0 else "Female")
            db.session.add(st)
    db.session.commit()

    if Quiz.query.filter_by(title="Sample Quiz").first() is None:
        qz = Quiz(title="Sample Quiz", grade="7", subject="General", timer_seconds=90); db.session.add(qz); db.session.commit()
        p = Passage(quiz_id=qz.id, title="Sample Passage (Easy)", content="Read: 2+2=4", difficulty="easy"); db.session.add(p); db.session.commit()
        qs = [
            Question(quiz_id=qz.id, passage_id=p.id, text="2+2=?", qtype="Understanding", option_a="3", option_b="4", option_c="5", option_d="6", correct="B", difficulty="easy"),
            Question(quiz_id=qz.id, passage_id=p.id, text="What is 7*6?", qtype="Understanding", option_a="42", option_b="36", option_c="44", option_d="48", correct="A", difficulty="easy"),
            Question(quiz_id=qz.id, passage_id=p.id, text="Solve x: 3x+2=11", qtype="Application", correct="3", difficulty="medium"),
            Question(quiz_id=qz.id, passage_id=p.id, text="Explain a prime number", qtype="Thinking", correct="divisible only by 1 and itself", difficulty="hard", is_calibration=1),
        ]
        for qu in qs:
            db.session.add(qu)
        db.session.commit()
    return "Seeded sample data"

# ------------- Startup -------------
if __name__ == "__main__":
    # ensure DB exists
    with app.app_context():
        db.create_all()
    print("Starting Ambassador Quiz App on http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
