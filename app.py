# app.py
"""
Ambassador Quiz App - single-file
Features:
 - Flask + Flask-SQLAlchemy
 - Teacher: create regular or passage-based quizzes, mark as placement optional
 - Student: signup/login, placement optional, quiz attempt with timer, screen-lock anti-cheat, practice mode
 - Teacher dashboard with colorful matplotlib charts embedded as base64
 - PDF export using fpdf2 (base64 data link)
 - All HTML/CSS/JS inline via render_template_string
 - No use of os module; set DATABASE_URL constant below for production
"""

from flask import Flask, request, redirect, session, render_template_string, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import secrets, re, random, base64, io
from fpdf import FPDF
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---------------- CONFIG ----------------
# Change DATABASE_URL to your Postgres DB for production (Render)
# Example: "postgresql+psycopg2://user:pass@host:port/dbname"
DATABASE_URL = "sqlite:///ambassador_quiz.db"

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = secrets.token_hex(32)
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
    is_passage_based = db.Column(db.Integer, default=0)  # 0 false, 1 true
    is_placement = db.Column(db.Integer, default=0)  # optional diagnostic flag
    use_level_filter = db.Column(db.Integer, default=0)  # if true, filter questions by student.level
    timer_seconds = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Passage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, nullable=True)
    title = db.Column(db.String(300))
    content = db.Column(db.Text)

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, nullable=True)    # For regular questions (non-passage), quiz_id used
    passage_id = db.Column(db.Integer, nullable=True) # For passage-based questions
    text = db.Column(db.Text)
    qtype = db.Column(db.String(50))  # 'mcq' or 'subjective'
    option_a = db.Column(db.String(500))
    option_b = db.Column(db.String(500))
    option_c = db.Column(db.String(500))
    option_d = db.Column(db.String(500))
    correct = db.Column(db.Text)  # store correct option text or keywords for subjective
    difficulty = db.Column(db.String(50), default="medium")  # easy/medium/hard
    marks = db.Column(db.Integer, default=1)

class Attempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer)
    quiz_id = db.Column(db.Integer)
    passage_id = db.Column(db.Integer, nullable=True)
    question_id = db.Column(db.Integer)
    student_answer = db.Column(db.Text)
    correct = db.Column(db.Integer)  # 0 or 1
    time_taken = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

# ---------------- Teacher passkeys ----------------
TEACHER_PASSKEYS = {"teacher1": "math123", "teacher2": "science456", "admin": "supersecret"}

# ---------------- Utilities ----------------
_word_re = re.compile(r"\w+")

def normalize_words(txt):
    if not txt: return set()
    return set(_word_re.findall(txt.lower()))

def subjective_similarity(student_ans, teacher_ans):
    s = normalize_words(student_ans or "")
    t = normalize_words(teacher_ans or "")
    if not t: return 0.0
    matches = sum(1 for w in t if w in s)
    return matches / len(t)

def assign_level_by_score(score, total):
    if total == 0:
        return "unknown"
    pct = (score*100.0)/total
    if pct >= 80:
        return "advanced"
    if pct >= 40:
        return "intermediate"
    return "beginner"

def make_plot_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.getvalue()).decode('ascii')

def student_report_pdf_bytes(rows):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "Student Report - Ambassador Quiz App", ln=True, align="C")
    pdf.ln(6)
    pdf.set_font("Arial", size=10)
    headers = ["User ID", "Name", "Grade", "Class", "Gender", "Level", "Attempts", "Correct"]
    widths = [30, 40, 18, 18, 18, 24, 18, 18]
    for h,w in zip(headers,widths):
        pdf.cell(w,8,h,1,0,'C')
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
    return pdf.output(dest='S').encode('latin1')

# ---------------- Base HTML ----------------
BASE_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Ambassador Quiz App</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    /* Minimal inline CSS to avoid external dependencies */
    :root { --brand:#0b2653; --accent:#7c3aed; --muted:#64748b; --bg:#f6fbff; }
    body { font-family:Inter,Arial,Helvetica,sans-serif; margin:0; background:var(--bg); color:#0f1724; }
    header { background:var(--brand); color:white; padding:14px 18px; display:flex; align-items:center; justify-content:space-between; }
    a { color:inherit; text-decoration:none; }
    .container { max-width:1100px; margin:22px auto; padding:0 16px; }
    .card { background:white; border-radius:10px; padding:16px; box-shadow:0 8px 30px rgba(2,6,23,0.06); margin-bottom:16px; }
    .row { display:flex; gap:16px; flex-wrap:wrap; }
    .col { flex:1; min-width:240px; }
    .btn { display:inline-block; padding:8px 12px; border-radius:8px; background:var(--brand); color:white; border:none; cursor:pointer; text-decoration:none; margin:4px 0; }
    .btn.alt { background:#eef2ff; color:var(--brand); }
    input, textarea, select { width:100%; padding:8px; margin:6px 0 12px; border-radius:8px; border:1px solid #e6eefc; box-sizing:border-box; }
    .muted { color:var(--muted); font-size:14px; }
    .small { font-size:13px; color:#475569; }
    .tag { padding:6px 8px; border-radius:8px; background:#eef2ff; color:var(--brand); font-weight:600; display:inline-block; margin:2px; }
    .progress { height:10px; background:#eef2ff; border-radius:8px; overflow:hidden; margin-top:8px; }
    .progress > div { height:100%; background:linear-gradient(90deg,var(--brand),var(--accent)); }
    .warning { background:#fef3c7; border-left:4px solid #f59e0b; padding:8px; border-radius:6px; }
    footer { text-align:center; color:var(--muted); font-size:13px; margin:28px 0; }
    @media(max-width:900px){ .row{ flex-direction:column } header nav{display:none} }
  </style>
</head>
<body>
<header>
  <div style="font-weight:700;font-size:18px">Ambassador Quiz App</div>
  <nav>
    {% if session.get('student_id') %}
      <a class="btn alt" href="/student/dashboard">Student</a>
      <a class="btn alt" href="/logout">Logout</a>
    {% elif session.get('teacher') %}
      <a class="btn alt" href="/teacher/dashboard">Teacher</a>
      <a class="btn alt" href="/logout">Logout</a>
    {% else %}
      <a class="btn alt" href="/login">Login</a>
      <a class="btn alt" href="/signup">Sign Up</a>
    {% endif %}
  </nav>
</header>
<div class="container">
  {{ content|safe }}
</div>
<footer>Ambassador Quiz App — single-file deployment</footer>
</body>
</html>
"""

# ---------------- Routes ----------------

@app.route("/")
def home():
    content = """
    <div class="card">
      <h1>Welcome to Ambassador Quiz App</h1>
      <p class="muted">Create quizzes (regular or passage-based), perform placement tests, and view rich teacher analytics.</p>
      <p><a class="btn" href="/login">Login</a> <a class="btn alt" href="/signup">Student Sign Up</a></p>
    </div>
    <div class="row">
      <div class="col card">
        <h3>How it works</h3>
        <p class="muted">Teachers create quizzes and questions. Students take quizzes passage-by-passage (if configured) with timers and anti-cheat protections.</p>
      </div>
      <div class="col card">
        <h3>Quick actions</h3>
        <p><a class="btn" href="/login">Sign In</a> <a class="btn alt" href="/signup">Sign Up</a></p>
      </div>
    </div>
    """
    return render_template_string(BASE_HTML, content=content)

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
            return render_template_string(BASE_HTML, content="<div class='card'>User ID and password are required.</div>")
        if Student.query.filter_by(user_id=user_id).first():
            return render_template_string(BASE_HTML, content="<div class='card'>User ID already exists. <a href='/signup'>Back</a></div>")
        hashed = generate_password_hash(password)
        st = Student(user_id=user_id, password=hashed, name=name, grade=grade, class_section=class_section, gender=gender)
        db.session.add(st); db.session.commit()
        return redirect(url_for("login"))
    content = """
    <div class="card" style="max-width:720px;margin:auto">
      <h2>Student Sign Up</h2>
      <form method="post">
        Name: <input name="name" placeholder="Full name">
        User ID: <input name="user_id" placeholder="Unique user id" required>
        Password: <input type="password" name="password" required>
        <div style="display:flex;gap:8px"><input name="grade" placeholder="Grade"><input name="class_section" placeholder="Class/section"></div>
        Gender: <select name="gender"><option>Male</option><option>Female</option><option>Other</option></select>
        <button class="btn" type="submit">Sign Up</button>
      </form>
    </div>
    """
    return render_template_string(BASE_HTML, content=content)

# ---------- Login ----------
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        role = request.form.get("role","student")
        if role == "teacher":
            tname = request.form.get("teacher_name","")
            passkey = request.form.get("passkey","")
            if TEACHER_PASSKEYS.get(tname) == passkey:
                session.clear(); session["teacher"] = tname; return redirect(url_for("teacher_dashboard"))
            return render_template_string(BASE_HTML, content="<div class='card'>Invalid teacher credentials. <a href='/login'>Back</a></div>")
        else:
            user_id = request.form.get("user_id","").strip()
            password = request.form.get("password","")
            st = Student.query.filter_by(user_id=user_id).first()
            if st and check_password_hash(st.password, password):
                session.clear()
                session["student_id"] = st.id
                session["student_user_id"] = st.user_id
                session["grade"] = st.grade
                # If level unknown, suggest placement (not forced)
                if not st.level or st.level in ("unknown",""):
                    return redirect(url_for("student_dashboard"))
                return redirect(url_for("student_dashboard"))
            return render_template_string(BASE_HTML, content="<div class='card'>Invalid student credentials. <a href='/login'>Back</a></div>")
    content = """
    <div class="card" style="max-width:720px;margin:auto">
      <h2>Sign In</h2>
      <form method="post">
        Role: <select name="role"><option value="student">Student</option><option value="teacher">Teacher</option></select>
        <div class="student-fields"><input name="user_id" placeholder="User ID"><input type="password" name="password" placeholder="Password"></div>
        <div id="teacher_fields" style="display:none"><input name="teacher_name" placeholder="Teacher name"><input type="password" name="passkey" placeholder="Passkey"></div>
        <button class="btn" type="submit">Sign In</button>
      </form>
    </div>
    <script>
      const sel = document.querySelector('select[name="role"]');
      sel.addEventListener('change', ()=> {
        if(sel.value==='teacher'){ document.querySelectorAll('.student-fields input').forEach(i=>i.style.display='none'); document.getElementById('teacher_fields').style.display='block'; }
        else{ document.querySelectorAll('.student-fields input').forEach(i=>i.style.display='block'); document.getElementById('teacher_fields').style.display='none'; }
      });
    </script>
    """
    return render_template_string(BASE_HTML, content=content)

# ---------- Logout ----------
@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("home"))

# ---------- Student Dashboard ----------
@app.route("/student/dashboard")
def student_dashboard():
    if "student_id" not in session:
        return redirect(url_for("login"))
    sid = session["student_id"]
    st = Student.query.get(sid)
    # Suggest placement if unknown
    placement_notice = ""
    if not st.level or st.level in ("unknown",""):
        placement_notice = "<div class='card'><p class='muted'>We recommend taking a short placement test to set your level. <a href='/placement'>Take placement test</a></p></div>"
    # recent attempts
    attempts = Attempt.query.filter_by(student_id=sid).order_by(Attempt.created_at.desc()).limit(15).all()
    attempts_html = ""
    for a in attempts:
        q = Question.query.get(a.question_id)
        attempts_html += f"<div style='border-bottom:1px solid #f1f5f9;padding:10px 0'><b>{(q.text if q else 'Question')}</b><div class='muted small'>Answer: {a.student_answer or ''} • Correct: {a.correct}</div></div>"
    # available quizzes
    grade = st.grade or ""
    quizzes = Quiz.query.filter((Quiz.grade==grade) | (Quiz.grade==None) | (Quiz.grade=="")).order_by(Quiz.created_at.desc()).all()
    quiz_list_html = ""
    for q in quizzes:
        quiz_list_html += f"<div style='display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #f1f5f9'><div><b>{q.title}</b><div class='muted'>{q.subject} • Grade {q.grade} • {'Passage' if q.is_passage_based else 'Regular'}</div></div><div><a class='btn' href='/quiz/start/{q.id}'>Start</a></div></div>"
    content = f"""
    <div class='card'><h2>Welcome, {st.name or st.user_id}</h2><div class='muted'>Level: <span class='tag'>{st.level}</span></div></div>
    {placement_notice}
    <div class='row'>
      <div class='col card'><h3>Available Quizzes</h3>{quiz_list_html or '<p class=\"muted\">No quizzes available</p>'}</div>
      <div class='col card'><h3>Recent Attempts</h3>{attempts_html or '<p class=\"muted\">No attempts yet</p>'}</div>
    </div>
    """
    return render_template_string(BASE_HTML, content=content)

# ---------- Placement Test (optional) ----------
@app.route("/placement", methods=["GET","POST"])
def placement():
    if "student_id" not in session:
        return redirect(url_for("login"))
    sid = session["student_id"]
    st = Student.query.get(sid)
    # pick up to 5 sample questions across difficulties
    all_qs = Question.query.all()
    if not all_qs:
        return render_template_string(BASE_HTML, content="<div class='card'>No questions available for placement. Ask a teacher to add questions.</div>")
    chosen = []
    def pick(diff, n):
        pool = [q for q in all_qs if q.difficulty==diff]
        return random.sample(pool, min(n, len(pool)))
    chosen += pick("easy",2); chosen += pick("medium",2); chosen += pick("hard",1)
    if len(chosen) < 5:
        pool = [q for q in all_qs if q not in chosen]
        if pool:
            chosen += random.sample(pool, min(5 - len(chosen), len(pool)))
    if request.method == "POST":
        answers = {int(k.split("_",1)[1]):v for k,v in request.form.items() if k.startswith("q_")}
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
                if sim >= 0.6: score += 1
        level = assign_level_by_score(score, total)
        st.level = level
        db.session.commit()
        return render_template_string(BASE_HTML, content=f"<div class='card'><h3>Placement complete</h3><p class='muted'>Assigned level: <span class='tag'>{level}</span></p><a class='btn' href='/student/dashboard'>Go to Dashboard</a></div>")
    q_html = "<form method='post'>"
    for q in chosen:
        q_html += f"<div class='card'><b>{q.text}</b><div class='muted small'>Difficulty: {q.difficulty}</div>"
        if q.qtype == "mcq":
            for opt in ("option_a","option_b","option_c","option_d"):
                val = getattr(q,opt)
                if val:
                    q_html += f"<div><label><input type='radio' name='q_{q.id}' value='{val}'> {val}</label></div>"
        else:
            q_html += f"<textarea name='q_{q.id}' rows='3' placeholder='Your answer...'></textarea>"
        q_html += "</div>"
    q_html += "<button class='btn' type='submit'>Submit Placement</button></form>"
    return render_template_string(BASE_HTML, content=q_html)

# ---------- Quiz start redirect ----------
@app.route("/quiz/start/<int:quiz_id>")
def quiz_start(quiz_id):
    if "student_id" not in session:
        return redirect(url_for("login"))
    return redirect(url_for("quiz_passage", quiz_id=quiz_id, p_index=0))

# ---------- Quiz passage / regular question page ----------
@app.route("/quiz/<int:quiz_id>/passage/<int:p_index>", methods=["GET","POST"])
def quiz_passage(quiz_id, p_index):
    if "student_id" not in session:
        return redirect(url_for("login"))
    student = Student.query.get(session["student_id"])
    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return render_template_string(BASE_HTML, content="<div class='card'>Quiz not found</div>")
    # load passages if passage_based else create synthetic single passage that contains regular questions
    if quiz.is_passage_based:
        passages = Passage.query.filter_by(quiz_id=quiz_id).order_by(Passage.id).all()
        if not passages:
            return render_template_string(BASE_HTML, content="<div class='card'>No passages in this quiz</div>")
        if p_index < 0 or p_index >= len(passages):
            return redirect(url_for("quiz_passage", quiz_id=quiz_id, p_index=0))
        passage = passages[p_index]
        questions = Question.query.filter_by(passage_id=passage.id).order_by(Question.id).all()
    else:
        # regular quiz: consider all questions with quiz_id
        passage = None
        questions_all = Question.query.filter_by(quiz_id=quiz_id).order_by(Question.id).all()
        # pack into "pages" of up to 5 questions
        page_size = 5
        pages = [questions_all[i:i+page_size] for i in range(0, len(questions_all), page_size)] if questions_all else [[]]
        if p_index < 0 or p_index >= len(pages):
            return redirect(url_for("quiz_passage", quiz_id=quiz_id, p_index=0))
        questions = pages[p_index]
    # Adaptive: if quiz.use_level_filter, filter questions by student.level
    if quiz.use_level_filter and student.level and student.level!="unknown":
        filtered = [q for q in questions if q.difficulty in ( "easy","medium","hard" ) and (
            (student.level=="beginner" and q.difficulty in ("easy","medium")) or
            (student.level=="intermediate" and q.difficulty in ("medium","hard")) or
            (student.level=="advanced" and q.difficulty in ("hard","medium"))
        )]
        if filtered:
            questions = filtered
    # pick up to 5 questions to display
    display_questions = questions[:5]
    # POST: handle submission (grading)
    if request.method == "POST":
        # detect if this is practice mode submission (practice flag)
        practice = request.form.get("practice","") == "1"
        now = datetime.utcnow()
        for q in display_questions:
            ans = request.form.get(f"q_{q.id}", "").strip()
            tkey = f"t_{q.id}"
            time_taken = float(request.form.get(tkey) or 0.0)
            correct_flag = 0
            if q.qtype == "mcq":
                correct_flag = 1 if ans.strip().lower() == (q.correct or "").strip().lower() else 0
            else:
                sim = subjective_similarity(ans or "", q.correct or "")
                correct_flag = 1 if sim >= 0.6 else 0
            if not practice:
                a = Attempt(student_id=student.id, quiz_id=quiz_id, passage_id=(passage.id if passage else None),
                            question_id=q.id, student_answer=ans, correct=int(correct_flag),
                            time_taken=time_taken, created_at=now)
                db.session.add(a)
        db.session.commit()
        # progress
        # determine next index
        if quiz.is_passage_based:
            next_index = p_index + 1
            if next_index >= len(Passage.query.filter_by(quiz_id=quiz_id).all()):
                return redirect(url_for("quiz_complete", quiz_id=quiz_id))
            else:
                # after timed submission, allow practice mode for same page if practice parameter present
                if request.form.get("practice","") == "1":
                    return render_template_string(BASE_HTML, content="<div class='card'><p class='muted'>Practice answers recorded (not graded). Continue to next passage.</p><a class='btn' href='{}'>Next Passage</a></div>".format(url_for("quiz_passage", quiz_id=quiz_id, p_index=next_index)))
                return redirect(url_for("quiz_passage", quiz_id=quiz_id, p_index=next_index))
        else:
            # regular pages
            # compute number of pages
            all_questions = Question.query.filter_by(quiz_id=quiz_id).order_by(Question.id).all()
            page_size = 5
            pages = [all_questions[i:i+page_size] for i in range(0, len(all_questions), page_size)] if all_questions else [[]]
            next_index = p_index + 1
            if next_index >= len(pages):
                return redirect(url_for("quiz_complete", quiz_id=quiz_id))
            else:
                if request.form.get("practice","") == "1":
                    return render_template_string(BASE_HTML, content="<div class='card'><p class='muted'>Practice mode — answers not graded. Continue.</p><a class='btn' href='{}'>Next</a></div>".format(url_for("quiz_passage", quiz_id=quiz_id, p_index=next_index)))
                return redirect(url_for("quiz_passage", quiz_id=quiz_id, p_index=next_index))
    # GET: render page with JS for timer and anti-cheat
    total_pages = (len(Passage.query.filter_by(quiz_id=quiz_id).all()) if quiz.is_passage_based else max(1, ((len(Question.query.filter_by(quiz_id=quiz_id).all())+4)//5)))
    progress_pct = int((p_index/ max(1, total_pages)) * 100)
    # inline JS: timer, warning, fullscreen & visibility detection
    timer_seconds = quiz.timer_seconds or 0
    # warning threshold: 60s or 10% whichever smaller? Use 60s default
    warning_seconds = 60 if timer_seconds>=60 else max(5, int(timer_seconds*0.1))
    # Build questions HTML
    q_html = "<form method='post' id='quizForm'>"
    for q in display_questions:
        q_html += "<div style='margin-top:12px;padding:10px;border-radius:8px;border:1px solid #eef2ff'>"
        q_html += f"<p><b>{q.text}</b> <span class='muted small'>({q.difficulty})</span></p>"
        if q.qtype == "mcq":
            for opt in ("option_a","option_b","option_c","option_d"):
                val = getattr(q,opt)
                if val:
                    q_html += f"<div><label><input type='radio' name='q_{q.id}' value='{val}'> {val}</label></div>"
        else:
            q_html += f"<textarea name='q_{q.id}' rows='3' placeholder='Type your answer...' style='width:100%'></textarea>"
        q_html += f"<input type='hidden' name='t_{q.id}' value='0'>"
        q_html += "</div>"
    # submission buttons: normal + practice
    q_html += "<div style='margin-top:12px;display:flex;gap:8px'><button class='btn' type='submit'>Submit</button><button class='btn alt' type='button' onclick=\"document.getElementById('practiceFlag').value='1';document.getElementById('quizForm').submit();\">Practice Mode</button></div>"
    q_html += "<input type='hidden' id='practiceFlag' name='practice' value='0'></form>"
    # page HTML
    passage_title = (passage.title if passage else ("Page %d" % (p_index+1)))
    passage_content = (passage.content if passage else "")
    time_lock_js = ""
    if timer_seconds and timer_seconds>0:
        time_lock_js = f"""
<script>
let timeLeft = {timer_seconds};
let warningAt = {warning_seconds};
let warned = false;
let violations = 0;
const maxViolations = 3; // after 3 visibility violations auto-submit
function updateTimer() {{
    let mm = Math.floor(timeLeft/60);
    let ss = timeLeft%60;
    document.getElementById('timer').innerText = mm + ':' + (ss<10? '0'+ss : ss);
    if(timeLeft==warningAt && !warned) {{
        warned = true;
        alert('⚠️ Only ' + warningAt + ' seconds remaining!');
    }}
    if(timeLeft<=0) {{
        clearInterval(ti);
        alert('⏰ Time is up — your answers will be auto-submitted. You may then continue in practice mode.');
        // set practice=0 and submit
        document.getElementById('practiceFlag').value='0';
        document.getElementById('quizForm').submit();
    }}
    timeLeft -= 1;
}}
let ti = setInterval(updateTimer, 1000);
document.addEventListener('visibilitychange', function() {{
    if(document.hidden) {{
        violations += 1;
        alert('🚨 Warning: you left the quiz tab/window. Violation ' + violations + '. Stay focused on the quiz!');
        if(violations >= maxViolations) {{
            alert('Too many violations — auto-submitting answers now.');
            document.getElementById('quizForm').submit();
        }}
    }}
}});
// Request fullscreen on page load for exam-like environment
function goFull() {{
  const el = document.documentElement;
  if(el.requestFullscreen) el.requestFullscreen();
  else if(el.mozRequestFullScreen) el.mozRequestFullScreen();
  else if(el.webkitRequestFullscreen) el.webkitRequestFullscreen();
  else if(el.msRequestFullscreen) el.msRequestFullscreen();
}}
window.onload = function(){{
  try {{ goFull(); }} catch(e){{ console.log(e); }}
  updateTimer();
}};
</script>
"""
    # combine content
    content = f"""
    <div class='card'><h3>{quiz.title}</h3><div class='muted'>{quiz.subject} • Grade {quiz.grade} • {'Passage-based' if quiz.is_passage_based else 'Regular'}</div></div>
    <div class='card'>
      <div style='display:flex;justify-content:space-between;align-items:center'>
        <div><h4>{passage_title}</h4></div>
        <div><span id='timer' class='tag'>{timer_seconds>0 and (str(timer_seconds//60)+':'+str(timer_seconds%60).zfill(2)) or 'No timer'}</span></div>
      </div>
      <div class='muted' style='white-space:pre-wrap;margin-top:8px'>{passage_content}</div>
      <div class='progress'><div style='width:{progress_pct}%;'></div></div>
      <div style='margin-top:12px'>{q_html}</div>
    </div>
    {time_lock_js}
    """
    return render_template_string(BASE_HTML, content=content)

# convenience route to map start -> passage 0
@app.route("/quiz/<int:quiz_id>/start")
def qstart(quiz_id):
    return redirect(url_for("quiz_passage", quiz_id=quiz_id, p_index=0))

# ---------- Quiz complete ----------
@app.route("/quiz/<int:quiz_id>/complete")
def quiz_complete(quiz_id):
    if "student_id" not in session:
        return redirect(url_for("login"))
    sid = session["student_id"]
    total = db.session.query(db.func.count(Attempt.id)).filter_by(student_id=sid, quiz_id=quiz_id).scalar() or 0
    correct = db.session.query(db.func.sum(Attempt.correct)).filter_by(student_id=sid, quiz_id=quiz_id).scalar() or 0
    pct = round((correct/total)*100,2) if total>0 else 0.0
    content = f"<div class='card'><h3>Quiz Complete</h3><p class='muted'>You answered {correct} of {total} correctly.</p><h4>Score: {pct}%</h4><a class='btn' href='/student/dashboard'>Back to Dashboard</a></div>"
    return render_template_string(BASE_HTML, content=content)

# ---------- Teacher Dashboard ----------
@app.route("/teacher/dashboard")
def teacher_dashboard():
    if "teacher" not in session:
        return redirect(url_for("login"))
    # Aggregates: grade-level, class-level, gender, difficulty success rates, level distribution, time vs score
    # Grade performance
    grade_rows = db.session.query(Student.grade, db.func.sum(Attempt.correct).label("correct"), db.func.count(Attempt.id).label("total")).join(Attempt, Attempt.student_id==Student.id).group_by(Student.grade).all()
    grades = [r[0] or "N/A" for r in grade_rows]
    grade_pcts = [ round((r[1] or 0)/ (r[2] or 1) * 100,2) for r in grade_rows ]
    # Class performance
    class_rows = db.session.query(Student.class_section, db.func.sum(Attempt.correct).label("correct"), db.func.count(Attempt.id).label("total")).join(Attempt, Attempt.student_id==Student.id).group_by(Student.class_section).all()
    classes = [r[0] or "N/A" for r in class_rows]
    class_pcts = [ round((r[1] or 0)/ (r[2] or 1) * 100,2) for r in class_rows ]
    # Gender breakdown
    gender_rows = db.session.query(Student.gender, db.func.sum(Attempt.correct).label("correct"), db.func.count(Attempt.id).label("total")).join(Attempt, Attempt.student_id==Student.id).group_by(Student.gender).all()
    genders = [r[0] or "N/A" for r in gender_rows]
    gender_pcts = [ round((r[1] or 0)/ (r[2] or 1) * 100,2) for r in gender_rows ]
    # Difficulty success
    diff_rows = db.session.query(Question.difficulty, db.func.sum(Attempt.correct).label("correct"), db.func.count(Attempt.id).label("total")).join(Attempt, Attempt.question_id==Question.id).group_by(Question.difficulty).all()
    diffs = [r[0] or "N/A" for r in diff_rows]
    diff_pcts = [ round((r[1] or 0)/ (r[2] or 1) * 100,2) for r in diff_rows ]
    # Level distribution
    level_rows = db.session.query(Student.level, db.func.count(Student.id)).group_by(Student.level).all()
    level_labels = [r[0] or "N/A" for r in level_rows]
    level_counts = [r[1] for r in level_rows]
    # Time vs score per student
    ts_rows = db.session.query(Student.user_id, db.func.avg(Attempt.time_taken).label("avg_time"), (db.func.sum(Attempt.correct)*100.0/db.func.count(Attempt.id)).label("pct")).join(Attempt, Attempt.student_id==Student.id).group_by(Student.user_id).all()
    # server-side charts via matplotlib -> base64 images
    plots_html = ""
    # grade plot
    if grades:
        fig, ax = plt.subplots(figsize=(5,2.5))
        ax.bar(grades, grade_pcts, color=['#7c3aed','#0b6cf1','#06b6d4','#f97316'][:len(grades)])
        ax.set_ylim(0,100); ax.set_title("Performance by Grade (%)"); ax.set_ylabel("Avg %")
        plots_html += f"<div class='card'><img src='data:image/png;base64,{make_plot_base64(fig)}' style='max-width:100%'/></div>"
    # class plot
    if classes:
        fig, ax = plt.subplots(figsize=(5,2.5))
        ax.bar(classes, class_pcts)
        ax.set_ylim(0,100); ax.set_title("Performance by Class (%)")
        plots_html += f"<div class='card'>{''}<img src='data:image/png;base64,{make_plot_base64(fig)}' style='max-width:100%'/></div>"
    # difficulty pie
    if diffs:
        fig, ax = plt.subplots(figsize=(4,3))
        ax.pie(diff_pcts, labels=diffs, autopct='%1.1f%%'); ax.set_title("Difficulty Success (%)")
        plots_html += f"<div class='card'><img src='data:image/png;base64,{make_plot_base64(fig)}' style='max-width:100%'/></div>"
    # level distribution
    if level_labels:
        fig, ax = plt.subplots(figsize=(4,3))
        ax.pie(level_counts, labels=level_labels, autopct='%1.1f%%'); ax.set_title("Level Distribution")
        plots_html += f"<div class='card'><img src='data:image/png;base64,{make_plot_base64(fig)}' style='max-width:100%'/></div>"
    # Time vs score table
    ts_html = "<table style='width:100%;border-collapse:collapse'><tr><th style='text-align:left'>User</th><th>Avg time (s)</th><th>Score %</th></tr>"
    for r in ts_rows:
        ts_html += f"<tr><td style='padding:6px;border-bottom:1px solid #f1f5f9'>{r[0]}</td><td style='padding:6px;border-bottom:1px solid #f1f5f9'>{round(r[1] or 0,2)}</td><td style='padding:6px;border-bottom:1px solid #f1f5f9'>{round(r[2] or 0,2)}</td></tr>"
    ts_html += "</table>"
    # quizzes list
    quizzes = Quiz.query.order_by(Quiz.created_at.desc()).all()
    qlist_html = ""
    for q in quizzes:
        qlist_html += f"<div style='padding:8px;border-bottom:1px solid #f1f5f9'><b>{q.title}</b> <div class='muted small'>{q.subject} • Grade {q.grade} • {'Passage' if q.is_passage_based else 'Regular'} • Placement:{'Yes' if q.is_placement else 'No'}</div><div style='margin-top:6px'><a class='btn alt' href='/teacher/view_quiz/{q.id}'>View</a> <a class='btn' href='/teacher/delete_quiz/{q.id}'>Delete</a></div></div>"
    content = f"""
    <div class='card'><h2>Teacher Dashboard</h2><div class='muted'>Comprehensive analytics</div></div>
    <div class='row'>
      <div class='col card'><h3>Quizzes</h3><a class='btn' href='/teacher/create_quiz'>Create Quiz</a> <a class='btn alt' href='/teacher/export_pdf'>Export PDF</a> <a class='btn' href='/teacher/reset_confirm' style='background:#ef4444'>Reset DB</a><div style='margin-top:12px'>{qlist_html}</div></div>
      <div class='col card'><h3>Analytics</h3>{plots_html}<div style='margin-top:12px'>{ts_html}</div></div>
    </div>
    """
    return render_template_string(BASE_HTML, content=content)

# ---------- Teacher: create quiz ----------
@app.route("/teacher/create_quiz", methods=["GET","POST"])
def teacher_create_quiz():
    if "teacher" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        title = request.form.get("title","").strip()
        grade = request.form.get("grade","").strip()
        subject = request.form.get("subject","").strip()
        is_passage_based = 1 if request.form.get("is_passage_based")=="1" else 0
        is_placement = 1 if request.form.get("is_placement")=="1" else 0
        use_level = 1 if request.form.get("use_level_filter")=="1" else 0
        timer = int(request.form.get("timer_seconds") or 0)
        q = Quiz(title=title, grade=grade, subject=subject, is_passage_based=is_passage_based, is_placement=is_placement, use_level_filter=use_level, timer_seconds=timer)
        db.session.add(q); db.session.commit()
        return redirect(url_for("teacher_add_passage", quiz_id=q.id) if is_passage_based else url_for("teacher_add_regular_questions", quiz_id=q.id))
    content = """
    <div class='card' style='max-width:760px;margin:auto'><h3>Create Quiz</h3>
    <form method='post'>
      <input name='title' placeholder='Title' class='form-control' required>
      <div style='display:flex;gap:8px'><input name='grade' placeholder='Grade' class='form-control'><input name='subject' placeholder='Subject' class='form-control'></div>
      <div style='display:flex;gap:8px;margin-top:8px'><label><input type='checkbox' name='is_passage_based' value='1'> Passage-based</label><label><input type='checkbox' name='is_placement' value='1'> Placement test</label><label><input type='checkbox' name='use_level_filter' value='1'> Use level filter</label></div>
      <input name='timer_seconds' placeholder='Timer seconds per page (optional)' class='form-control'>
      <button class='btn' type='submit'>Create Quiz</button>
    </form></div>
    """
    return render_template_string(BASE_HTML, content=content)

# ---------- Teacher: add passage ----------
@app.route("/teacher/add_passage/<int:quiz_id>", methods=["GET","POST"])
def teacher_add_passage(quiz_id):
    if "teacher" not in session:
        return redirect(url_for("login"))
    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return render_template_string(BASE_HTML, content="<div class='card'>Quiz not found</div>")
    if request.method == "POST":
        title = request.form.get("title","").strip()
        content = request.form.get("content","").strip()
        p = Passage(quiz_id=quiz_id, title=title, content=content)
        db.session.add(p); db.session.commit()
        return redirect(url_for("teacher_add_question", passage_id=p.id))
    content = f"""
    <div class='card'><h3>Add Passage to {quiz.title}</h3>
    <form method='post'>
      <input name='title' placeholder='Passage title' class='form-control'>
      <textarea name='content' rows='6' placeholder='Passage content' class='form-control'></textarea>
      <button class='btn' type='submit'>Add Passage & Add Questions</button>
    </form></div>
    """
    return render_template_string(BASE_HTML, content=content)

# ---------- Teacher: add question to passage ----------
@app.route("/teacher/add_question/<int:passage_id>", methods=["GET","POST"])
def teacher_add_question(passage_id):
    if "teacher" not in session:
        return redirect(url_for("login"))
    p = Passage.query.get(passage_id)
    if not p:
        return render_template_string(BASE_HTML, content="<div class='card'>Passage not found</div>")
    if request.method == "POST":
        text = request.form.get("text","").strip()
        qtype = request.form.get("qtype","mcq")
        a = request.form.get("option_a") or None
        b = request.form.get("option_b") or None
        c = request.form.get("option_c") or None
        d = request.form.get("option_d") or None
        correct = request.form.get("correct","").strip()
        difficulty = request.form.get("difficulty","medium")
        q = Question(quiz_id=p.quiz_id, passage_id=passage_id, text=text, qtype=qtype, option_a=a, option_b=b, option_c=c, option_d=d, correct=correct, difficulty=difficulty)
        db.session.add(q); db.session.commit()
        return render_template_string(BASE_HTML, content=f"<div class='card'>Question added. <a class='btn' href='/teacher/add_question/{passage_id}'>Add another</a> <a class='btn alt' href='/teacher/dashboard'>Dashboard</a></div>")
    content = f"""
    <div class='card'><h3>Add Question to passage: {p.title}</h3>
    <form method='post'>
      <textarea name='text' rows='3' placeholder='Question text' class='form-control'></textarea>
      <select name='qtype' class='form-control'><option value='mcq'>MCQ</option><option value='subjective'>Subjective</option></select>
      <input name='correct' placeholder='Correct answer / keywords' class='form-control'>
      <div style='display:flex;gap:8px'><input name='option_a' placeholder='Option A' class='form-control'><input name='option_b' placeholder='Option B' class='form-control'></div>
      <div style='display:flex;gap:8px'><input name='option_c' placeholder='Option C' class='form-control'><input name='option_d' placeholder='Option D' class='form-control'></div>
      <select name='difficulty' class='form-control'><option>easy</option><option selected>medium</option><option>hard</option></select>
      <button class='btn' type='submit'>Add Question</button>
    </form></div>
    """
    return render_template_string(BASE_HTML, content=content)

# ---------- Teacher: add regular (non-passage) questions to quiz ----------
@app.route("/teacher/add_regular/<int:quiz_id>", methods=["GET","POST"])
def teacher_add_regular_questions(quiz_id):
    if "teacher" not in session:
        return redirect(url_for("login"))
    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return render_template_string(BASE_HTML, content="<div class='card'>Quiz not found</div>")
    if request.method == "POST":
        text = request.form.get("text","").strip()
        qtype = request.form.get("qtype","mcq")
        a = request.form.get("option_a") or None
        b = request.form.get("option_b") or None
        c = request.form.get("option_c") or None
        d = request.form.get("option_d") or None
        correct = request.form.get("correct","").strip()
        difficulty = request.form.get("difficulty","medium")
        q = Question(quiz_id=quiz_id, passage_id=None, text=text, qtype=qtype, option_a=a, option_b=b, option_c=c, option_d=d, correct=correct, difficulty=difficulty)
        db.session.add(q); db.session.commit()
        return render_template_string(BASE_HTML, content=f"<div class='card'>Question added. <a class='btn' href='/teacher/add_regular/{quiz_id}'>Add another</a> <a class='btn alt' href='/teacher/dashboard'>Dashboard</a></div>")
    content = f"""
    <div class='card'><h3>Add Regular Question to {quiz.title}</h3>
    <form method='post'>
      <textarea name='text' rows='3' placeholder='Question text' class='form-control'></textarea>
      <select name='qtype' class='form-control'><option value='mcq'>MCQ</option><option value='subjective'>Subjective</option></select>
      <input name='correct' placeholder='Correct answer/keywords' class='form-control'>
      <div style='display:flex;gap:8px'><input name='option_a' placeholder='Option A' class='form-control'><input name='option_b' placeholder='Option B' class='form-control'></div>
      <div style='display:flex;gap:8px'><input name='option_c' placeholder='Option C' class='form-control'><input name='option_d' placeholder='Option D' class='form-control'></div>
      <select name='difficulty' class='form-control'><option>easy</option><option selected>medium</option><option>hard</option></select>
      <button class='btn' type='submit'>Add Question</button>
    </form></div>
    """
    return render_template_string(BASE_HTML, content=content)

# ---------- Teacher: view quiz ----------
@app.route("/teacher/view_quiz/<int:quiz_id>")
def teacher_view_quiz(quiz_id):
    if "teacher" not in session:
        return redirect(url_for("login"))
    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return render_template_string(BASE_HTML, content="<div class='card'>Quiz not found</div>")
    passages = Passage.query.filter_by(quiz_id=quiz_id).all() if quiz.is_passage_based else []
    questions = Question.query.filter_by(quiz_id=quiz_id, passage_id=None).all() if not quiz.is_passage_based else []
    html = f"<div class='card'><h3>{quiz.title}</h3><div class='muted'>{quiz.subject} • Grade {quiz.grade} • {'Passage' if quiz.is_passage_based else 'Regular'}</div></div>"
    if quiz.is_passage_based:
        for p in passages:
            html += f"<div class='card'><h4>Passage: {p.title}</h4><div class='muted' style='white-space:pre-wrap'>{p.content}</div><a class='btn' href='/teacher/add_question/{p.id}'>Add question</a>"
            qs = Question.query.filter_by(passage_id=p.id).all()
            for q in qs:
                html += f"<div style='padding:6px;border-bottom:1px solid #f1f5f9'>{q.text}<div class='muted small'>Type:{q.qtype} • Correct:{q.correct}</div></div>"
            html += "</div>"
    else:
        for q in questions:
            html += f"<div class='card'><b>{q.text}</b><div class='muted small'>Type:{q.qtype} • Correct:{q.correct}</div></div>"
    html += "<a class='btn' href='/teacher/dashboard'>Back</a>"
    return render_template_string(BASE_HTML, content=html)

# ---------- Teacher: delete quiz ----------
@app.route("/teacher/delete_quiz/<int:quiz_id>", methods=["GET","POST"])
def teacher_delete_quiz(quiz_id):
    if "teacher" not in session:
        return redirect(url_for("login"))
    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return render_template_string(BASE_HTML, content="<div class='card'>Quiz not found</div>")
    if request.method == "POST":
        Attempt.query.filter_by(quiz_id=quiz_id).delete()
        Question.query.filter(Question.passage_id.in_([p.id for p in Passage.query.filter_by(quiz_id=quiz_id)])).delete()
        Passage.query.filter_by(quiz_id=quiz_id).delete()
        Question.query.filter_by(quiz_id=quiz_id, passage_id=None).delete()
        db.session.delete(quiz); db.session.commit()
        return redirect(url_for("teacher_dashboard"))
    return render_template_string(BASE_HTML, content=f"<div class='card'><h3>Confirm Delete Quiz: {quiz.title}</h3><form method='post'><button class='btn' type='submit' style='background:#ef4444'>Delete</button> <a class='btn alt' href='/teacher/dashboard'>Cancel</a></form></div>")

# ---------- Teacher: export PDF ----------
@app.route("/teacher/export_pdf")
def teacher_export_pdf():
    if "teacher" not in session:
        return redirect(url_for("login"))
    rows = db.session.query(Student.user_id, Student.name, Student.grade, Student.class_section, Student.gender, Student.level, db.func.count(Attempt.id).label("attempts"), db.func.sum(Attempt.correct).label("correct")).outerjoin(Attempt, Attempt.student_id==Student.id).group_by(Student.id).order_by(Student.grade, Student.class_section).all()
    data = []
    for r in rows:
        data.append({"user_id": r[0], "name": r[1], "grade": r[2], "class": r[3], "gender": r[4], "level": r[5], "attempts": int(r[6] or 0), "correct": int(r[7] or 0)})
    pdfb = student_report_pdf_bytes(data)
    b64 = base64.b64encode(pdfb).decode('ascii')
    content = f"<div class='card'><h3>Export PDF</h3><p class='muted'>Click to download student report</p><a class='btn' href='data:application/pdf;base64,{b64}' download='students_report.pdf'>Download PDF</a></div>"
    return render_template_string(BASE_HTML, content=content)

# ---------- Teacher: reset DB ----------
@app.route("/teacher/reset_confirm")
def teacher_reset_confirm():
    if "teacher" not in session:
        return redirect(url_for("login"))
    content = "<div class='card'><h3>Reset Database</h3><p class='muted'>This will permanently delete all students, quizzes, questions, passages, and attempts. Type YES to confirm.</p><form method='post' action='/teacher/reset_db'><input name='confirm' placeholder='Type YES to confirm'><button class='btn' type='submit' style='background:#ef4444'>Reset</button> <a class='btn alt' href='/teacher/dashboard'>Cancel</a></form></div>"
    return render_template_string(BASE_HTML, content=content)

@app.route("/teacher/reset_db", methods=["POST"])
def teacher_reset_db():
    if "teacher" not in session:
        return redirect(url_for("login"))
    if request.form.get("confirm") != "YES":
        return redirect(url_for("teacher_dashboard"))
    Attempt.query.delete(); Question.query.delete(); Passage.query.delete(); Quiz.query.delete(); Student.query.delete()
    db.session.commit(); db.create_all()
    return render_template_string(BASE_HTML, content="<div class='card'><p>Database reset complete.</p><a class='btn' href='/'>Home</a></div>")

# ---------- Seed route for dev ----------
@app.route("/_seed")
def seed():
    # Create sample data for quick testing
    if Student.query.count() == 0:
        for i in range(1,7):
            uid = f"stud{i}"
            if not Student.query.filter_by(user_id=uid).first():
                st = Student(user_id=uid, password=generate_password_hash("pass123"), name=f"Student {i}", grade=str(6 + (i%3)), class_section=str((i%2)+1), gender="Male" if i%2==0 else "Female")
                db.session.add(st)
    if Quiz.query.count() == 0:
        qz = Quiz(title="Sample Passage Quiz", grade="7", subject="Math", is_passage_based=1, timer_seconds=120)
        db.session.add(qz); db.session.commit()
        p = Passage(quiz_id=qz.id, title="Sample Passage", content="Read the passage carefully. Solve the following.")
        db.session.add(p); db.session.commit()
        qs = [
            Question(quiz_id=qz.id, passage_id=p.id, text="2+2=?", qtype="mcq", option_a="3", option_b="4", option_c="5", option_d="6", correct="4", difficulty="easy"),
            Question(quiz_id=qz.id, passage_id=p.id, text="5*6=?", qtype="mcq", option_a="30", option_b="26", option_c="56", option_d="40", correct="30", difficulty="easy"),
            Question(quiz_id=qz.id, passage_id=p.id, text="Solve x: 3x+2=11", qtype="subjective", correct="3", difficulty="medium"),
            Question(quiz_id=qz.id, passage_id=p.id, text="Explain prime numbers", qtype="subjective", correct="divisible only by 1 and itself", difficulty="hard"),
        ]
        for q in qs:
            db.session.add(q)
    if Quiz.query.filter_by(title="Regular Quiz").first() is None:
        qz2 = Quiz(title="Regular Quiz", grade="8", subject="Science", is_passage_based=0, timer_seconds=90)
        db.session.add(qz2); db.session.commit()
        qreg = Question(quiz_id=qz2.id, passage_id=None, text="What is H2O?", qtype="mcq", option_a="Water", option_b="Oxygen", option_c="Hydrogen", option_d="Helium", correct="Water", difficulty="easy")
        db.session.add(qreg)
    db.session.commit()
    return "Seeded sample data"

# ---------------- Run ----------------
if __name__ == "__main__":
    print("Starting Ambassador Quiz App on http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
