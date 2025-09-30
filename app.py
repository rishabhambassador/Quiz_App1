# app.py
"""
Ambassador Quiz App (single-file)
- Flask + Flask-SQLAlchemy
- Adaptive placement test & adaptive quizzes
- Teacher dashboard with Chart.js visualizations
- PDF export using fpdf2 (FPDF)
- No 'os' usage; set DATABASE_URL constant manually (or edit in file)
"""
from flask import Flask, request, redirect, session, render_template_string, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import secrets, re, random, base64, io
from fpdf import FPDF
from math import ceil

# ---------------- CONFIG ----------------
# Replace DATABASE_URL with your Postgres URL before deploying to Render.
# Example Postgres URL: "postgresql+psycopg2://user:pass@host:port/dbname"
DATABASE_URL = "sqlite:///ambassador_quiz.db"  # change this to Postgres URL for production

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = secrets.token_hex(24)
db = SQLAlchemy(app)

# ---------------- MODELS ----------------
class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(300), nullable=False)
    name = db.Column(db.String(200))
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
    quiz_id = db.Column(db.Integer, db.ForeignKey("quiz.id") if False else db.Integer)  # fallback to avoid Duck typing in some runtimes
    # We'll keep it simple and not use relationship objects to minimize surprises
    quiz_id = db.Column(db.Integer)
    title = db.Column(db.String(300))
    content = db.Column(db.Text)

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer)
    passage_id = db.Column(db.Integer)
    text = db.Column(db.Text)
    qtype = db.Column(db.String(50))  # 'mcq' or 'subjective'
    option_a = db.Column(db.String(500))
    option_b = db.Column(db.String(500))
    option_c = db.Column(db.String(500))
    option_d = db.Column(db.String(500))
    correct = db.Column(db.Text)
    difficulty = db.Column(db.String(50), default="medium")  # easy/medium/hard
    marks = db.Column(db.Integer, default=1)

class Attempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer)
    quiz_id = db.Column(db.Integer)
    passage_id = db.Column(db.Integer)
    question_id = db.Column(db.Integer)
    student_answer = db.Column(db.Text)
    correct = db.Column(db.Integer)  # 0 or 1
    time_taken = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# create tables
with app.app_context():
    db.create_all()

# teacher passkeys (in-code)
TEACHER_PASSKEYS = {"teacher1": "math123", "teacher2": "science456", "admin": "supersecret"}

# ---------------- helpers ----------------
_word_re = re.compile(r"\w+")

def normalize_words(text):
    if not text:
        return set()
    return set(_word_re.findall(text.lower()))

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

def generate_pdf_bytes(student_rows):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "Student Report - Ambassador Quiz App", ln=True, align="C")
    pdf.ln(6)
    pdf.set_font("Arial", size=10)
    # headers
    headers = ["User ID", "Name", "Grade", "Class", "Gender", "Level", "Attempts", "Correct"]
    widths = [30, 40, 18, 18, 18, 24, 18, 18]
    for h,w in zip(headers,widths):
        pdf.cell(w,8,h,1,0,"C",fill=True)
    pdf.ln()
    for r in student_rows:
        pdf.cell(widths[0],8,str(r.get("user_id","")),1)
        pdf.cell(widths[1],8,str(r.get("name","")),1)
        pdf.cell(widths[2],8,str(r.get("grade","") or ""),1)
        pdf.cell(widths[3],8,str(r.get("class","") or ""),1)
        pdf.cell(widths[4],8,str(r.get("gender","") or ""),1)
        pdf.cell(widths[5],8,str(r.get("level","") or ""),1)
        pdf.cell(widths[6],8,str(r.get("attempts",0)),1,0,"C")
        pdf.cell(widths[7],8,str(r.get("correct",0)),1,1,"C")
    return pdf.output(dest="S").encode("latin1")

# ---------------- templates ----------------
BASE = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ambassador Quiz App</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body{background:#f6fbff;color:#0f1724;font-family:Inter,Arial;}
.navbar{background:#0b2653}
.navbar .navbar-brand{color:#fff}
.card{border-radius:10px}
.muted{color:#64748b}
.tag{padding:6px 8px;border-radius:8px;background:#eef2ff;color:#0b6cf1;font-weight:600}
</style>
</head><body>
<nav class="navbar navbar-expand-lg"><div class="container-fluid"><a class="navbar-brand" href="/">Ambassador Quiz App</a><div class="ms-auto">
{% if session.get('student_id') %}
  <a class="btn btn-light btn-sm" href="/student/dashboard">Student</a> <a class="btn btn-light btn-sm" href="/logout">Logout</a>
{% elif session.get('teacher') %}
  <a class="btn btn-light btn-sm" href="/teacher/dashboard">Teacher</a> <a class="btn btn-light btn-sm" href="/logout">Logout</a>
{% else %}
  <a class="btn btn-light btn-sm" href="/login">Login</a> <a class="btn btn-outline-light btn-sm" href="/signup">Sign Up</a>
{% endif %}
</div></div></nav>
<div class="container my-4">{{ content|safe }}</div>
</body></html>
"""

# ---------- Routes ----------
@app.route("/")
def home():
    content = """
    <div class="card p-4 mb-3">
      <div class="d-flex justify-content-between align-items-center">
        <div>
          <h2>Ambassador Quiz App</h2>
          <p class="muted">Adaptive quizzes with placement tests and a rich teacher dashboard.</p>
        </div>
        <div>
          <a class="btn btn-primary" href="/login">Login</a>
          <a class="btn btn-outline-primary" href="/signup">Student Sign Up</a>
        </div>
      </div>
    </div>
    """
    return render_template_string(BASE, content=content)

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
            return render_template_string(BASE, content="<div class='card p-3'>User ID and password required</div>")
        if Student.query.filter_by(user_id=user_id).first():
            return render_template_string(BASE, content="<div class='card p-3'>User ID exists. <a href='/signup'>Back</a></div>")
        hashed = generate_password_hash(password)
        st = Student(user_id=user_id, password=hashed, name=name, grade=grade, class_section=class_section, gender=gender)
        db.session.add(st); db.session.commit()
        return redirect("/login")
    content = """<div class='card p-3' style='max-width:720px;margin:auto'><h3>Student Sign Up</h3>
    <form method='post'>
    <input class='form-control mb-2' name='name' placeholder='Full name'>
    <input class='form-control mb-2' name='user_id' placeholder='User ID' required>
    <input class='form-control mb-2' type='password' name='password' placeholder='Password' required>
    <div class='row'><div class='col'><input class='form-control mb-2' name='grade' placeholder='Grade'></div><div class='col'><input class='form-control mb-2' name='class_section' placeholder='Class'></div></div>
    <select class='form-select mb-2' name='gender'><option>Male</option><option>Female</option><option>Other</option></select>
    <button class='btn btn-primary' type='submit'>Sign Up</button></form></div>"""
    return render_template_string(BASE, content=content)

# ---------- Login ----------
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        role = request.form.get("role","student")
        if role == "teacher":
            tname = request.form.get("teacher_name","")
            passkey = request.form.get("passkey","")
            if TEACHER_PASSKEYS.get(tname) == passkey:
                session.clear(); session["teacher"] = tname; return redirect("/teacher/dashboard")
            return render_template_string(BASE, content="<div class='card p-3'>Invalid teacher credentials</div>")
        else:
            user_id = request.form.get("user_id","").strip()
            password = request.form.get("password","")
            st = Student.query.filter_by(user_id=user_id).first()
            if st and check_password_hash(st.password, password):
                session.clear(); session["student_id"] = st.id; session["student_user"] = st.user_id; session["grade"] = st.grade
                if not st.level or st.level in ("unknown",""):
                    # route to placement test
                    return redirect("/placement")
                return redirect("/student/dashboard")
            return render_template_string(BASE, content="<div class='card p-3'>Invalid credentials</div>")
    content = """<div class='card p-3' style='max-width:720px;margin:auto'><h3>Login</h3>
    <form method='post'>
      <div class='mb-2'><select name='role' class='form-select'><option value='student' selected>Student</option><option value='teacher'>Teacher</option></select></div>
      <div class='mb-2 student-fields'><input class='form-control' name='user_id' placeholder='User ID'></div>
      <div class='mb-2 student-fields'><input class='form-control' name='password' type='password' placeholder='Password'></div>
      <div style='display:none' id='teacher_fields'>
        <input class='form-control mb-2' name='teacher_name' placeholder='teacher1'>
        <input class='form-control mb-2' name='passkey' type='password' placeholder='passkey'>
      </div>
      <button class='btn btn-primary' type='submit'>Sign In</button>
    </form></div>
    <script>
      const sel = document.querySelector('select[name="role"]');
      sel.addEventListener('change', ()=> {
        const v = sel.value;
        document.querySelectorAll('.student-fields').forEach(n=> n.style.display = v==='student'?'block':'none');
        document.getElementById('teacher_fields').style.display = v==='teacher'?'block':'none';
      });
    </script>"""
    return render_template_string(BASE, content=content)

# ---------- Logout ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------- Placement Test ----------
@app.route("/placement", methods=["GET","POST"])
def placement():
    if "student_id" not in session:
        return redirect("/login")
    sid = session["student_id"]
    student = Student.query.get(sid)
    # pick 5 placement questions mixed by difficulty
    all_questions = Question.query.all()
    if not all_questions:
        return render_template_string(BASE, content="<div class='card p-3'>No questions available for placement. Ask teacher to add questions.</div>")
    # attempt to pick 2 easy,2 medium,1 hard
    chosen = []
    def pick(diff, n):
        pool = [q for q in all_questions if q.difficulty==diff]
        return random.sample(pool, min(n, len(pool)))
    chosen += pick("easy",2); chosen += pick("medium",2); chosen += pick("hard",1)
    if len(chosen) < 5:
        pool = [q for q in all_questions if q not in chosen]
        needed = 5 - len(chosen)
        if pool:
            chosen += random.sample(pool, min(needed, len(pool)))
    if request.method == "POST":
        answers = {}
        for key,val in request.form.items():
            if key.startswith("q_"):
                qid = int(key.split("_",1)[1]); answers[qid] = val
        score = 0; total = 0
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
        return render_template_string(BASE, content=f"<div class='card p-3'>Placement completed. Assigned level: <span class='tag'>{level}</span><br><a class='btn btn-primary mt-2' href='/student/dashboard'>Go to Dashboard</a></div>")
    # GET
    html = "<div class='card p-3'><h4>Placement Test</h4><form method='post'>"
    for q in chosen:
        html += f"<div class='mb-3'><b>{q.text}</b><div class='muted small'>Difficulty: {q.difficulty}</div>"
        if q.qtype == "mcq":
            for opt in ("option_a","option_b","option_c","option_d"):
                val = getattr(q,opt)
                if val:
                    html += f"<div class='form-check'><input class='form-check-input' type='radio' name='q_{q.id}' value='{val}' id='q{q.id}{opt}'><label class='form-check-label' for='q{q.id}{opt}'>{val}</label></div>"
        else:
            html += f"<textarea class='form-control' name='q_{q.id}' rows='3'></textarea>"
        html += "</div>"
    html += "<button class='btn btn-primary' type='submit'>Submit Placement</button></form></div>"
    return render_template_string(BASE, content=html)

# ---------- Student Dashboard ----------
@app.route("/student/dashboard")
def student_dashboard():
    if "student_id" not in session:
        return redirect("/login")
    sid = session["student_id"]
    student = Student.query.get(sid)
    # recent attempts
    attempts = Attempt.query.filter_by(student_id=sid).order_by(Attempt.created_at.desc()).limit(15).all()
    # per-quiz stats for chart
    stats = db.session.query(Quiz.title, db.func.sum(Attempt.correct).label("correct"), db.func.count(Attempt.id).label("total")).join(Attempt, Attempt.quiz_id==Quiz.id).filter(Attempt.student_id==sid).group_by(Quiz.id).all()
    labels = [s[0] for s in stats]; values = [round((s[1] or 0)/(s[2] or 1)*100,2) for s in stats]
    html = f"<div class='card p-3'><h4>Welcome, {student.name or student.user_id}</h4><div class='muted'>Level: <span class='tag'>{student.level}</span></div></div>"
    html += "<div class='row'><div class='col-lg-8'><div class='card p-3'><h5>Recent Attempts</h5>"
    if not attempts:
        html += "<p class='muted'>No attempts yet</p>"
    else:
        for a in attempts:
            q = Question.query.get(a.question_id)
            html += f"<div style='border-bottom:1px solid #eef2ff;padding:8px 0'><b>{q.text if q else 'Question'}</b><div class='muted small'>Answer: {a.student_answer or ''} • Correct: {a.correct}</div></div>"
    html += "</div></div><div class='col-lg-4'><div class='card p-3'><h5>Your Performance</h5><canvas id='myChart'></canvas></div></div></div>"
    html += f"<script>const labels={labels}; const values={values}; new Chart(document.getElementById('myChart'),{{type:'line',data:{{labels:labels,datasets:[{{label:'Score %',data:values,borderColor:'#0b6cf1',backgroundColor:'rgba(11,108,241,0.08)'}}]}},options:{{responsive:true}}}});</script>"
    html += "<div class='mt-3'><a class='btn btn-primary' href='/quiz/list'>Take Quiz</a></div>"
    return render_template_string(BASE, content=html)

# ---------- Quiz list ----------
@app.route("/quiz/list")
def quiz_list():
    if "student_id" not in session:
        return redirect("/login")
    grade = session.get("grade","")
    quizzes = Quiz.query.filter((Quiz.grade==grade) | (Quiz.grade==None) | (Quiz.grade=="")).order_by(Quiz.created_at.desc()).all()
    html = "<div class='card p-3'><h4>Available Quizzes</h4>"
    if not quizzes:
        html += "<p class='muted'>No quizzes available</p>"
    else:
        for q in quizzes:
            html += f"<div class='d-flex justify-content-between align-items-center py-2' style='border-bottom:1px solid #f1f5f9'><div><b>{q.title}</b><div class='muted'>{q.subject} • Grade {q.grade}</div></div><div><a class='btn btn-primary' href='/quiz/start/{q.id}'>Start</a></div></div>"
    html += "</div>"
    return render_template_string(BASE, content=html)

# ---------- Start quiz ----------
@app.route("/quiz/start/<int:quiz_id>")
def quiz_start(quiz_id):
    if "student_id" not in session:
        return redirect("/login")
    return redirect(f"/quiz/{quiz_id}/passage/0")

# ---------- Quiz passage (adaptive) ----------
@app.route("/quiz/<int:quiz_id>/passage/<int:index>", methods=["GET","POST"])
def quiz_passage(quiz_id, index):
    if "student_id" not in session:
        return redirect("/login")
    student = Student.query.get(session["student_id"])
    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return render_template_string(BASE, content="<div class='card p-3'>Quiz not found</div>")
    passages = Passage.query.filter_by(quiz_id=quiz_id).order_by(Passage.id).all()
    if not passages:
        return render_template_string(BASE, content="<div class='card p-3'>No passages</div>")
    if index < 0 or index >= len(passages):
        return redirect(f"/quiz/{quiz_id}/passage/0")
    passage = passages[index]
    # question pool filtered by student.level
    if student.level == "beginner":
        pool = Question.query.filter_by(passage_id=passage.id).filter(Question.difficulty.in_(["easy","medium"])).all()
    elif student.level == "intermediate":
        pool = Question.query.filter_by(passage_id=passage.id).filter(Question.difficulty.in_(["medium","hard"])).all()
    elif student.level == "advanced":
        pool = Question.query.filter_by(passage_id=passage.id).filter(Question.difficulty.in_(["hard","medium"])).all()
    else:
        pool = Question.query.filter_by(passage_id=passage.id).all()
    if not pool:
        pool = Question.query.filter_by(passage_id=passage.id).all()
    selected = random.sample(pool, min(5, len(pool)))
    if request.method == "POST":
        total_time = 0.0
        for q in selected:
            key = f"q_{q.id}"
            ans = request.form.get(key,"")
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
        next_index = index + 1
        if next_index >= len(passages):
            return redirect(f"/quiz/{quiz_id}/complete")
        return redirect(f"/quiz/{quiz_id}/passage/{next_index}")
    # render page
    total = len(passages)
    progress_pct = int((index / total) * 100)
    timer = quiz.timer_seconds or 0
    html = f"<div class='card p-3'><h4>{quiz.title}</h4><div class='muted'>{quiz.subject} • Grade {quiz.grade}</div></div>"
    html += "<div class='card p-3'><div class='d-flex justify-content-between align-items-center'><h5>Passage</h5>"
    if timer and timer>0:
        html += f"<div class='tag' id='timer'>Time: {timer}s</div>"
    html += "</div>"
    html += f"<div class='progress my-2' style='height:10px'><div class='progress-bar' role='progressbar' style='width:{progress_pct}%;background:linear-gradient(90deg,#0b6cf1,#7c3aed)'></div></div>"
    if passage.title:
        html += f"<h6>{passage.title}</h6>"
    if passage.content:
        html += f"<div class='muted' style='white-space:pre-wrap'>{passage.content}</div>"
    html += "<form method='post'>"
    for q in selected:
        html += f"<div class='mt-3 p-2' style='border-radius:8px;border:1px solid #eef2ff'><p><b>{q.text}</b> <span class='muted small'>({q.difficulty})</span></p>"
        if q.qtype == "mcq":
            for opt in ("option_a","option_b","option_c","option_d"):
                val = getattr(q,opt)
                if val:
                    html += f"<div class='form-check'><input class='form-check-input' type='radio' name='q_{q.id}' value='{val}' id='q{q.id}{opt}'><label class='form-check-label' for='q{q.id}{opt}'>{val}</label></div>"
        else:
            html += f"<textarea class='form-control' name='q_{q.id}' rows='3'></textarea>"
        html += f"<input type='hidden' name='t_{q.id}' value='0'>"
        html += "</div>"
    html += "<div class='mt-3'><button class='btn btn-primary' type='submit'>Submit Passage</button> <a class='btn btn-outline-secondary' href='/quiz/list'>Exit</a></div></form>"
    if timer and timer>0:
        html += f"<script>(function(){{var time={timer}; var el=document.getElementById('timer'); var iv=setInterval(function(){{time-=1; if(time<=0){{clearInterval(iv); document.forms[0].submit();}} el.innerText='Time: ' + time + 's';}},1000); }})();</script>"
    html += "</div>"
    return render_template_string(BASE, content=html)

# ---------- Quiz complete ----------
@app.route("/quiz/<int:quiz_id>/complete")
def quiz_complete(quiz_id):
    if "student_id" not in session:
        return redirect("/login")
    sid = session["student_id"]
    total = db.session.query(db.func.count(Attempt.id)).filter_by(student_id=sid, quiz_id=quiz_id).scalar() or 0
    correct = db.session.query(db.func.sum(Attempt.correct)).filter_by(student_id=sid, quiz_id=quiz_id).scalar() or 0
    pct = round((correct/total)*100,2) if total>0 else 0.0
    html = f"<div class='card p-3'><h4>Quiz Completed</h4><p class='muted'>Correct: {correct} / {total}</p><h5>Score: {pct}%</h5><a class='btn btn-primary' href='/student/dashboard'>Back</a></div>"
    return render_template_string(BASE, content=html)

# ---------- Teacher Dashboard ----------
@app.route("/teacher/dashboard")
def teacher_dashboard():
    if "teacher" not in session:
        return redirect("/login")
    # compute many aggregates
    grade_stats = db.session.query(Student.grade, db.func.count(Attempt.id).label("attempts"), db.func.sum(Attempt.correct).label("correct")).join(Attempt, Attempt.student_id==Student.id).group_by(Student.grade).all()
    class_stats = db.session.query(Student.class_section, db.func.count(Attempt.id), db.func.sum(Attempt.correct)).join(Attempt, Attempt.student_id==Student.id).group_by(Student.class_section).all()
    gender_stats = db.session.query(Student.gender, db.func.count(Attempt.id), db.func.sum(Attempt.correct)).join(Attempt, Attempt.student_id==Student.id).group_by(Student.gender).all()
    diff_stats = db.session.query(Question.difficulty, db.func.count(Attempt.id), db.func.sum(Attempt.correct)).join(Attempt, Attempt.question_id==Question.id).group_by(Question.difficulty).all()
    level_dist = db.session.query(Student.level, db.func.count(Student.id)).group_by(Student.level).all()
    time_score = db.session.query(Student.user_id, db.func.avg(Attempt.time_taken).label("avg_time"), (db.func.sum(Attempt.correct)*100.0/db.func.count(Attempt.id)).label("pct")).join(Attempt, Attempt.student_id==Student.id).group_by(Student.user_id).all()
    quizzes = Quiz.query.order_by(Quiz.created_at.desc()).all()
    # prepare data arrays
    def make_chart_pairs(rows):
        labels=[]; values=[]
        for r in rows:
            labels.append(r[0] or "N/A")
            attempts = r[1] or 0
            correct = r[2] or 0
            pct = round((correct/attempts*100) if attempts>0 else 0,2)
            values.append(pct)
        return labels, values
    grade_labels, grade_vals = make_chart_pairs(grade_stats)
    class_labels, class_vals = make_chart_pairs(class_stats)
    gender_labels, gender_vals = make_chart_pairs(gender_stats)
    diff_labels = [r[0] for r in diff_stats]; diff_vals = [round((r[2] or 0)/(r[1] or 1)*100,2) if r[1] else 0 for r in diff_stats]
    level_labels = [r[0] for r in level_dist]; level_vals = [r[1] for r in level_dist]
    time_score_rows = [{"user_id": r[0], "avg_time": round(r[1] or 0,2), "pct": round(r[2] or 0,2)} for r in time_score]
    html = "<div class='card p-3'><h4>Teacher Dashboard</h4><div class='muted'>Comprehensive insights</div></div>"
    html += "<div class='row g-3'><div class='col-md-4'><div class='card p-3'><h5>Quizzes</h5><div class='small muted'>Count: %d</div><a class='btn btn-primary mt-2' href='/teacher/create_quiz'>Create Quiz</a></div></div>" % len(quizzes)
    html += "<div class='col-md-4'><div class='card p-3'><h5>Levels</h5><div class='muted'>Distribution</div>"
    for l,v in zip(level_labels, level_vals): html += f"<div class='tag me-2'>{l}: {v}</div>"
    html += "</div></div>"
    html += "<div class='col-md-4'><div class='card p-3'><h5>Export / Reset</h5><a class='btn btn-outline-primary' href='/teacher/export_pdf'>Export PDF</a> <a class='btn btn-danger ms-2' href='/teacher/reset_confirm'>Reset DB</a></div></div></div>"
    html += "<div class='row g-3 mt-3'><div class='col-lg-6'><div class='card p-3'><h6>Performance by Grade</h6><canvas id='gradeChart'></canvas></div></div>"
    html += "<div class='col-lg-6'><div class='card p-3'><h6>Performance by Class</h6><canvas id='classChart'></canvas></div></div></div>"
    html += "<div class='row g-3 mt-3'><div class='col-lg-6'><div class='card p-3'><h6>Difficulty Success</h6><canvas id='diffChart'></canvas></div></div>"
    html += "<div class='col-lg-6'><div class='card p-3'><h6>Gender Breakdown</h6><canvas id='genderChart'></canvas></div></div></div>"
    html += "<div class='card p-3 mt-3'><h6>Avg Time vs Score</h6><table class='table table-sm'><thead><tr><th>User</th><th>Avg Time (s)</th><th>Score %</th></tr></thead><tbody>"
    for r in time_score_rows: html += f"<tr><td>{r['user_id']}</td><td>{r['avg_time']}</td><td>{r['pct']}</td></tr>"
    html += "</tbody></table></div>"
    # Charts JS
    html += f"<script>const gradeLabels={grade_labels};const gradeVals={grade_vals};const classLabels={class_labels};const classVals={class_vals};const diffLabels={diff_labels};const diffVals={diff_vals};const genderLabels={gender_labels};const genderVals={gender_vals}; new Chart(document.getElementById('gradeChart'),{{type:'bar',data:{{labels:gradeLabels,datasets:[{{label:'Avg %',data:gradeVals,backgroundColor:['#7c3aed','#0b6cf1','#06b6d4','#f97316']}}]}},options:{{responsive:true}}}}); new Chart(document.getElementById('classChart'),{{type:'bar',data:{{labels:classLabels,datasets:[{{label:'Avg %',data:classVals,backgroundColor:['#06b6d4','#7c3aed','#0b6cf1','#f97316']}}]}},options:{{responsive:true}}}}); new Chart(document.getElementById('diffChart'),{{type:'pie',data:{{labels:diffLabels,datasets:[{{data:diffVals,backgroundColor:['#7c3aed','#0b6cf1','#06b6d4']}}]}},options:{{responsive:true}}}}); new Chart(document.getElementById('genderChart'),{{type:'doughnut',data:{{labels:genderLabels,datasets:[{{data:genderVals,backgroundColor:['#f97316','#0b6cf1','#7c3aed']}}]}},options:{{responsive:true}}}});</script>"
    return render_template_string(BASE, content=html)

# ---------- Teacher: create quiz / add passage / add question ----------
@app.route("/teacher/create_quiz", methods=["GET","POST"])
def teacher_create_quiz():
    if "teacher" not in session: return redirect("/login")
    if request.method == "POST":
        title = request.form.get("title","").strip()
        grade = request.form.get("grade","").strip()
        subject = request.form.get("subject","").strip()
        timer = int(request.form.get("timer_seconds") or 0)
        q = Quiz(title=title, grade=grade, subject=subject, timer_seconds=timer)
        db.session.add(q); db.session.commit()
        return redirect(f"/teacher/add_passage/{q.id}")
    html = "<div class='card p-3'><h5>Create Quiz</h5><form method='post'><input class='form-control mb-2' name='title' placeholder='Title' required><input class='form-control mb-2' name='grade' placeholder='Grade'><input class='form-control mb-2' name='subject' placeholder='Subject'><input class='form-control mb-2' name='timer_seconds' placeholder='Timer seconds per passage'><button class='btn btn-primary' type='submit'>Create</button></form></div>"
    return render_template_string(BASE, content=html)

@app.route("/teacher/add_passage/<int:quiz_id>", methods=["GET","POST"])
def teacher_add_passage(quiz_id):
    if "teacher" not in session: return redirect("/login")
    quiz = Quiz.query.get(quiz_id)
    if not quiz: return render_template_string(BASE, content="<div class='card p-3'>Quiz not found</div>")
    if request.method == "POST":
        title = request.form.get("title","").strip()
        content = request.form.get("content","").strip()
        p = Passage(quiz_id=quiz_id, title=title, content=content)
        db.session.add(p); db.session.commit()
        return redirect(f"/teacher/add_question/{p.id}")
    html = f"<div class='card p-3'><h5>Add Passage to {quiz.title}</h5><form method='post'><input class='form-control mb-2' name='title' placeholder='Passage title'><textarea class='form-control mb-2' name='content' rows='6' placeholder='Passage text'></textarea><button class='btn btn-primary' type='submit'>Add Passage</button></form></div>"
    return render_template_string(BASE, content=html)

@app.route("/teacher/add_question/<int:passage_id>", methods=["GET","POST"])
def teacher_add_question(passage_id):
    if "teacher" not in session: return redirect("/login")
    passage = Passage.query.get(passage_id)
    if not passage: return render_template_string(BASE, content="<div class='card p-3'>Passage not found</div>")
    if request.method == "POST":
        text = request.form.get("text","").strip()
        qtype = request.form.get("qtype","mcq")
        a = request.form.get("option_a") or None
        b = request.form.get("option_b") or None
        c = request.form.get("option_c") or None
        d = request.form.get("option_d") or None
        correct = request.form.get("correct","").strip()
        difficulty = request.form.get("difficulty","medium")
        q = Question(quiz_id=passage.quiz_id, passage_id=passage_id, text=text, qtype=qtype, option_a=a, option_b=b, option_c=c, option_d=d, correct=correct, difficulty=difficulty)
        db.session.add(q); db.session.commit()
        return render_template_string(BASE, content=f"<div class='card p-3'>Question added. <a class='btn btn-primary' href='/teacher/add_question/{passage_id}'>Add another</a> <a class='btn btn-outline-secondary' href='/teacher/dashboard'>Dashboard</a></div>")
    html = f"<div class='card p-3'><h5>Add Question to Passage: {passage.title or ''}</h5><form method='post'><textarea class='form-control mb-2' name='text' rows='3' placeholder='Question text'></textarea><select class='form-select mb-2' name='qtype'><option value='mcq'>MCQ</option><option value='subjective'>Subjective</option></select><input class='form-control mb-2' name='correct' placeholder='Correct answer / keywords'><input class='form-control mb-2' name='option_a' placeholder='Option A'><input class='form-control mb-2' name='option_b' placeholder='Option B'><input class='form-control mb-2' name='option_c' placeholder='Option C'><input class='form-control mb-2' name='option_d' placeholder='Option D'><select class='form-select mb-2' name='difficulty'><option>easy</option><option selected>medium</option><option>hard</option></select><button class='btn btn-primary' type='submit'>Add Question</button></form></div>"
    return render_template_string(BASE, content=html)

# ---------- Export PDF ----------
@app.route("/teacher/export_pdf")
def teacher_export_pdf():
    if "teacher" not in session: return redirect("/login")
    rows = db.session.query(Student.user_id, Student.name, Student.grade, Student.class_section, Student.gender, Student.level, db.func.count(Attempt.id).label("attempts"), db.func.sum(Attempt.correct).label("correct")).outerjoin(Attempt, Attempt.student_id==Student.id).group_by(Student.id).order_by(Student.grade, Student.class_section).all()
    data = []
    for r in rows:
        data.append({"user_id": r[0], "name": r[1], "grade": r[2], "class": r[3], "gender": r[4], "level": r[5], "attempts": int(r[6] or 0), "correct": int(r[7] or 0)})
    pdfb = generate_pdf_bytes(data)
    b64 = base64.b64encode(pdfb).decode("utf-8")
    content = f"<div class='card p-3'><h5>Export</h5><p class='muted'>Download the student report PDF</p><a class='btn btn-primary' href='data:application/pdf;base64,{b64}' download='students_report.pdf'>Download PDF</a></div>"
    return render_template_string(BASE, content=content)

# ---------- Reset DB ----------
@app.route("/teacher/reset_confirm")
def teacher_reset_confirm():
    if "teacher" not in session: return redirect("/login")
    content = "<div class='card p-3'><h5>Reset Database</h5><p class='muted'>This will delete ALL students, quizzes, passages, questions and attempts. Type YES to confirm.</p><form method='post' action='/teacher/reset_db'><input class='form-control mb-2' name='confirm'><button class='btn btn-danger' type='submit'>Reset</button> <a class='btn btn-outline-secondary' href='/teacher/dashboard'>Cancel</a></form></div>"
    return render_template_string(BASE, content=content)

@app.route("/teacher/reset_db", methods=["POST"])
def teacher_reset_db():
    if "teacher" not in session: return redirect("/login")
    if request.form.get("confirm") != "YES":
        return redirect("/teacher/dashboard")
    # destructive
    Attempt.query.delete(); Question.query.delete(); Passage.query.delete(); Quiz.query.delete(); Student.query.delete()
    db.session.commit()
    db.create_all()
    return render_template_string(BASE, content="<div class='card p-3'>Database reset.</div>")

# ---------- Delete quiz ----------
@app.route("/teacher/delete_quiz/<int:quiz_id>", methods=["GET","POST"])
def teacher_delete_quiz(quiz_id):
    if "teacher" not in session: return redirect("/login")
    q = Quiz.query.get(quiz_id)
    if not q: return render_template_string(BASE, content="<div class='card p-3'>Quiz not found</div>")
    if request.method == "POST":
        Attempt.query.filter_by(quiz_id=quiz_id).delete()
        Question.query.filter(Question.passage_id.in_([p.id for p in Passage.query.filter_by(quiz_id=quiz_id)])).delete()
        Passage.query.filter_by(quiz_id=quiz_id).delete()
        db.session.delete(q); db.session.commit()
        return redirect("/teacher/dashboard")
    return render_template_string(BASE, content=f"<div class='card p-3'><h5>Delete Quiz: {q.title}</h5><form method='post'><button class='btn btn-danger' type='submit'>Confirm Delete</button> <a class='btn btn-outline-secondary' href='/teacher/dashboard'>Cancel</a></form></div>")

# ---------- Seed sample (dev only) ----------
@app.route("/_seed", methods=["GET"])
def seed():
    # creates sample students, quiz, passage, questions
    if Student.query.count() == 0:
        for i in range(1,6):
            st = Student(user_id=f"student{i}", password=generate_password_hash("pass123"), name=f"Student {i}", grade=str(6 + (i%3)), class_section=str((i%2)+1), gender="Male" if i%2==0 else "Female")
            db.session.add(st)
    qz = Quiz(title="Sample Quiz", grade="7", subject="Math", timer_seconds=90); db.session.add(qz); db.session.commit()
    p = Passage(quiz_id=qz.id, title="Sample Passage", content="Read carefully.")
    db.session.add(p); db.session.commit()
    qs = [
        Question(quiz_id=qz.id, passage_id=p.id, text="2+2=?", qtype="mcq", option_a="3", option_b="4", option_c="5", option_d="6", correct="4", difficulty="easy"),
        Question(quiz_id=qz.id, passage_id=p.id, text="What is 7*6?", qtype="mcq", option_a="42", option_b="36", option_c="44", option_d="48", correct="42", difficulty="easy"),
        Question(quiz_id=qz.id, passage_id=p.id, text="Solve x: 3x+2=11", qtype="subjective", correct="3", difficulty="medium"),
        Question(quiz_id=qz.id, passage_id=p.id, text="Explain what a prime number is", qtype="subjective", correct="divisible only by 1 and itself", difficulty="hard"),
    ]
    for q in qs:
        db.session.add(q)
    db.session.commit()
    return "Seeded"

# ---------- Run ----------
if __name__ == "__main__":
    print("Starting Ambassador Quiz App on http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)

