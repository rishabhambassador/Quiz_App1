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
import os

app = Flask(__name__)
app.secret_key = "supersecret"

DB_PATH = "quiz.db"
UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Simple teacher passkeys
TEACHER_PASSKEYS = {"teacher1": "math123", "teacher2": "science456", "admin": "supersecret"}

# ------------------ DB helpers & init ------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    # quizzes table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            subject TEXT,
            grade TEXT,
            time_limit_seconds INTEGER DEFAULT 0
        )
    """)
    # questions belong to a quiz (quiz_id)
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
            image_path TEXT,
            section TEXT,
            subsection TEXT
        )
    """)
    # students
    conn.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            grade TEXT,
            gender TEXT,
            class_name TEXT
        )
    """)
    # attempts store quiz_id as well (for reporting)
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

def ensure_columns():
    # In case user had older DB schema, ensure necessary columns exist.
    conn = get_db()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(questions)")
    qcols = [r[1] for r in cur.fetchall()]
    if "quiz_id" not in qcols:
        try:
            cur.execute("ALTER TABLE questions ADD COLUMN quiz_id INTEGER")
        except:
            pass
    if "section" not in qcols:
        try:
            cur.execute("ALTER TABLE questions ADD COLUMN section TEXT")
            cur.execute("ALTER TABLE questions ADD COLUMN subsection TEXT")
        except:
            pass

    cur.execute("PRAGMA table_info(attempts)")
    acols = [r[1] for r in cur.fetchall()]
    if "quiz_id" not in acols:
        try:
            cur.execute("ALTER TABLE attempts ADD COLUMN quiz_id INTEGER")
        except:
            pass
    conn.commit()
    conn.close()

init_db()
ensure_columns()

# ------------------ Helpers ------------------
def render_page(content, title="Ambassador Quiz App"):
    base = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>{title}</title>
      <style>
        body{{font-family:Arial, sans-serif; background:#f4f6f8; margin:0; padding:20px;}}
        .card{{max-width:1000px; margin:16px auto; background:white; padding:18px; border-radius:8px; box-shadow:0 6px 18px rgba(0,0,0,0.08)}}
        h1,h2{{margin:0 0 12px 0; text-align:center;}}
        .btn{{display:inline-block;padding:8px 14px;border-radius:6px;border:none;background:#2b8cff;color:white;cursor:pointer;text-decoration:none}}
        .muted{{color:#6b7280;font-size:14px}}
        input,select,textarea{{width:100%;padding:8px;margin:8px 0;border-radius:6px;border:1px solid #ddd;box-sizing:border-box}}
        .row{{display:flex;gap:12px}}
        .col{{flex:1}}
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
    return render_template_string(base)

def normalize_words(text):
    return re.findall(r"\w+", (text or "").lower())

def check_similarity(ans, correct, threshold=0.6):
    # Keyword overlap ratio: matches / len(correct_words)
    if not (ans and correct):
        return 0
    ans_words = normalize_words(ans)
    correct_words = normalize_words(correct)
    if not correct_words:
        return 0
    matches = sum(1 for w in correct_words if w in ans_words)
    ratio = matches / len(correct_words)
    return 1 if ratio >= threshold else 0

# ------------------ Public / Home ------------------
@app.route("/")
def home():
    content = """
      <h1>Ambassador Quiz App</h1>
      <p class="muted">Inspire · Inquire · Innovate</p>
      <div style="text-align:center;margin-top:18px;">
        <a class="btn" href="/signup/student">Student Sign Up</a>
        <a class="btn" href="/login/student">Student Login</a>
        <a class="btn" href="/login/teacher">Teacher Login</a>
      </div>
      <hr>
      <h3>Available Quizzes</h3>
    """
    # list quizzes
    conn = get_db()
    quizzes = conn.execute("SELECT * FROM quizzes ORDER BY id DESC").fetchall()
    conn.close()
    if quizzes:
        for q in quizzes:
            content += f"<div style='padding:10px;border:1px solid #eee;margin:8px 0;border-radius:6px;display:flex;justify-content:space-between;align-items:center'>"
            content += f"<div><strong>{q['title']}</strong> <span class='muted'>(Subject: {q['subject']}, Grade: {q['grade']})</span></div>"
            content += f"<div><a class='btn' href='/take_quiz/{q['id']}'>Take Quiz</a></div></div>"
    else:
        content += "<p class='muted'>No quizzes created yet.</p>"
    return render_page(content)

# ------------------ Student: Signup/Login ------------------
@app.route("/signup/student", methods=["GET","POST"])
def signup_student():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        grade = request.form["grade"].strip()
        gender = request.form.get("gender","").strip()
        class_name = request.form.get("class_name","").strip()
        try:
            conn = get_db()
            conn.execute("INSERT INTO students(username,password,grade,gender,class_name) VALUES (?,?,?,?,?)",
                         (username,password,grade,gender,class_name))
            conn.commit(); conn.close()
            return redirect("/login/student")
        except sqlite3.IntegrityError:
            return render_page("<h3>Username already taken</h3><a href='/signup/student' class='btn'>Back</a>")
    form = """
      <h2>Student Sign Up</h2>
      <form method="post">
        <input name="username" placeholder="Username" required>
        <input name="password" type="password" placeholder="Password" required>
        <input name="grade" placeholder="Grade (e.g. 5)" required>
        <input name="class_name" placeholder="Class (e.g. A)">
        <select name="gender"><option value=''>Select Gender</option><option>Male</option><option>Female</option><option>Other</option></select>
        <button class="btn" type="submit">Sign Up</button>
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
            return render_page("<h3>Invalid credentials</h3><a href='/login/student' class='btn'>Back</a>")
    form = """
      <h2>Student Login</h2>
      <form method="post">
        <input name="username" placeholder="Username" required>
        <input name="password" type="password" placeholder="Password" required>
        <button class="btn" type="submit">Login</button>
      </form>
    """
    return render_page(form)

# ------------------ Teacher: Login ------------------
@app.route("/login/teacher", methods=["GET","POST"])
def login_teacher():
    if request.method=="POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        if username in TEACHER_PASSKEYS and TEACHER_PASSKEYS[username]==password:
            session["teacher"] = username
            return redirect("/teacher/dashboard")
        else:
            return render_page("<h3>Invalid teacher credentials</h3><a href='/login/teacher' class='btn'>Back</a>")
    return render_page("""
      <h2>Teacher Login</h2>
      <form method="post">
        <input name="username" placeholder="Teacher username" required>
        <input name="password" type="password" placeholder="Passkey" required>
        <button class="btn" type="submit">Login</button>
      </form>
    """)

# ------------------ Teacher: Create Quiz ------------------
@app.route("/teacher/create_quiz", methods=["GET","POST"])
def create_quiz():
    if "teacher" not in session: return redirect("/login/teacher")
    if request.method=="POST":
        title = request.form["title"].strip()
        subject = request.form["subject"].strip()
        grade = request.form["grade"].strip()
        time_limit = int(request.form.get("time_limit_seconds") or 0)
        conn = get_db()
        cur = conn.execute("INSERT INTO quizzes(title,subject,grade,time_limit_seconds) VALUES (?,?,?,?)",
                           (title,subject,grade,time_limit))
        conn.commit()
        quiz_id = cur.lastrowid
        conn.close()
        return redirect(f"/teacher/add_question?quiz_id={quiz_id}")
    return render_page("""
      <h2>Create Quiz</h2>
      <form method="post">
        <input name="title" placeholder="Quiz Title" required>
        <input name="subject" placeholder="Subject (e.g. Math)" required>
        <input name="grade" placeholder="Grade (e.g. 5)" required>
        <input name="time_limit_seconds" placeholder="Time limit in seconds (optional)">
        <button class="btn" type="submit">Create Quiz</button>
      </form>
    """)

# ------------------ Teacher: Add Question to Specific Quiz ------------------
@app.route("/teacher/add_question", methods=["GET","POST"])
def add_question():
    if "teacher" not in session: return redirect("/login/teacher")
    quiz_id = request.args.get("quiz_id") or request.form.get("quiz_id")
    conn = get_db()
    quizzes = conn.execute("SELECT * FROM quizzes ORDER BY id DESC").fetchall()
    conn.close()
    if request.method=="POST":
        quiz_id = int(request.form["quiz_id"])
        text = request.form["text"]
        correct = request.form["correct"]
        qtype = request.form["qtype"]
        option_a = request.form.get("option_a") or None
        option_b = request.form.get("option_b") or None
        option_c = request.form.get("option_c") or None
        option_d = request.form.get("option_d") or None
        section = request.form.get("section") or ""
        subsection = request.form.get("subsection") or ""
        # handle uploaded image (optional)
        img = request.files.get("image")
        image_path = None
        if img and img.filename:
            fname = f"q_{quiz_id}_{img.filename}"
            saved = os.path.join(UPLOAD_FOLDER, fname)
            img.save(saved)
            image_path = "/" + saved.replace("\\","/")
        conn = get_db()
        conn.execute("""INSERT INTO questions(quiz_id,text,correct,option_a,option_b,option_c,option_d,qtype,image_path,section,subsection)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                     (quiz_id,text,correct,option_a,option_b,option_c,option_d,qtype,image_path,section,subsection))
        conn.commit(); conn.close()
        # After adding, allow add another to same quiz
        return render_page(f"""
            <h3>Question added to quiz #{quiz_id}</h3>
            <a class="btn" href="/teacher/add_question?quiz_id={quiz_id}">Add Another</a>
            <a class="btn" href="/teacher/dashboard">Back to Dashboard</a>
        """)
    # GET form
    quiz_select_html = "<select name='quiz_id' required>"
    for q in quizzes:
        sel = "selected" if str(q["id"])==str(quiz_id) else ""
        quiz_select_html += f"<option value='{q['id']}' {sel}>{q['title']} (Grade {q['grade']})</option>"
    quiz_select_html += "</select>"

    return render_page(f"""
      <h2>Add Question to Quiz</h2>
      <form method="post" enctype="multipart/form-data">
        <label>Choose Quiz</label>{quiz_select_html}
        <input name="text" placeholder="Question text" required>
        <input name="correct" placeholder="Correct answer (for MCQ put option text)" required>
        <select name="qtype"><option value="mcq">MCQ</option><option value="subjective">Subjective</option></select>
        <div style="display:flex;gap:8px"><input name="option_a" placeholder="Option A"><input name="option_b" placeholder="Option B"></div>
        <div style="display:flex;gap:8px"><input name="option_c" placeholder="Option C"><input name="option_d" placeholder="Option D"></div>
        <input name="section" placeholder="Section (optional)"><input name="subsection" placeholder="Subsection (optional)">
        <label>Image (optional)</label><input type="file" name="image">
        <button class="btn" type="submit">Add Question</button>
      </form>
    """)

# ------------------ Student: Take Quiz (per-question flow) ------------------
@app.route("/take_quiz/<int:quiz_id>", methods=["GET","POST"])
def take_quiz(quiz_id):
    if "student_id" not in session:
        return redirect("/login/student")
    conn = get_db()
    quiz = conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    questions = conn.execute("SELECT * FROM questions WHERE quiz_id=? ORDER BY id", (quiz_id,)).fetchall()
    conn.close()
    if not quiz:
        return render_page("<h3>Quiz not found</h3><a href='/' class='btn'>Back</a>")
    q_index = int(request.args.get("q", 0))
    if q_index >= len(questions):
        # finished: show summary link
        return render_page(f"<h3>Quiz completed: {quiz['title']}</h3><a class='btn' href='/'>Back to Home</a>")
    question = questions[q_index]
    # Handle submission
    if request.method=="POST":
        ans = request.form.get("answer","").strip()
        if (question["qtype"] or "").lower() == "mcq":
            correct = 1 if ans.lower() == (question["correct"] or "").lower() else 0
        else:
            correct = check_similarity(ans, question["correct"])
        conn = get_db()
        conn.execute("INSERT INTO attempts(student_id,quiz_id,question_id,student_answer,correct) VALUES (?,?,?,?,?)",
                     (session["student_id"], quiz_id, question["id"], ans, correct))
        conn.commit(); conn.close()
        # Show feedback page (correct/incorrect) and Next button
        feedback = "✅ Correct!" if correct else f"❌ Incorrect — Correct: {question['correct']}"
        next_q = q_index + 1
        return render_page(f"""
            <h3>{feedback}</h3>
            <a class='btn' href='{url_for('take_quiz', quiz_id=quiz_id, q=next_q)}'>Next</a>
        """)
    # render single-question page (two-pane)
    left = f"<h3>{question['section'] or 'Section' } — {question['subsection'] or ''}</h3><p><b>Q{q_index+1}.</b> {question['text']}</p>"
    if question["image_path"]:
        left += f"<img src='{question['image_path']}' style='max-width:100%;border-radius:6px;margin-top:8px'>"
    right = "<form method='post'>"
    if (question["qtype"] or "").lower() == "mcq":
        for opt in ("a","b","c","d"):
            v = question.get(f"option_{opt}")
            if v:
                right += f"<label><input type='radio' name='answer' value='{v}'> {v}</label><br>"
    else:
        right += "<textarea name='answer' rows='4' style='width:100%;'></textarea><br>"
    right += "<button class='btn' type='submit'>Submit Answer</button></form>"
    page = f"""
      <h2>Quiz: {quiz['title']} (Subject: {quiz['subject']}, Grade: {quiz['grade']})</h2>
      <div style="display:flex;gap:16px">
        <div style="flex:2;background:#fff;padding:12px;border-radius:8px">{left}</div>
        <div style="flex:1;background:#fff;padding:12px;border-radius:8px">{right}</div>
      </div>
    """
    return render_page(page)

# ------------------ Teacher Dashboard (richer graphs) ------------------
@app.route("/teacher/dashboard")
def teacher_dashboard():
    if "teacher" not in session:
        return redirect("/login/teacher")
    conn = get_db()
    # Grades: avg score per grade
    grade_rows = conn.execute("""
        SELECT s.grade as label, AVG(a.correct)*100.0 as pct
        FROM attempts a
        JOIN students s ON a.student_id = s.id
        GROUP BY s.grade
    """).fetchall()
    # Subjects: avg score per subject (join questions)
    subject_rows = conn.execute("""
        SELECT q.subject as label, AVG(a.correct)*100.0 as pct
        FROM attempts a
        JOIN questions q ON a.question_id = q.id
        GROUP BY q.subject
    """).fetchall()
    # Quizzes: avg score per quiz
    quiz_rows = conn.execute("""
        SELECT z.title as label, AVG(a.correct)*100.0 as pct
        FROM attempts a
        JOIN quizzes z ON a.quiz_id = z.id
        GROUP BY z.id
    """).fetchall()
    conn.close()

    def plot_rows(rows, title):
        labels = [r["label"] or "N/A" for r in rows]
        vals = [round(r["pct"] or 0,2) for r in rows]
        if not labels:
            return "<p class='muted'>No data</p>"
        fig, ax = plt.subplots(figsize=(6,2.5))
        ax.bar(range(len(vals)), vals)
        ax.set_ylim(0,100)
        ax.set_xticks(range(len(vals)))
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.set_ylabel("Avg %")
        ax.set_title(title)
        buf = io.BytesIO(); fig.tight_layout(); plt.savefig(buf, format="png"); buf.seek(0)
        data = base64.b64encode(buf.getvalue()).decode(); plt.close(fig)
        return f"<img src='data:image/png;base64,{data}' style='max-width:100%'>"

    grade_chart = plot_rows(grade_rows, "Average Score by Grade")
    subject_chart = plot_rows(subject_rows, "Average Score by Subject")
    quiz_chart = plot_rows(quiz_rows, "Average Score by Quiz")

    content = f"""
      <h2>Teacher Dashboard</h2>
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <div style="flex:1 1 300px;background:#fff;padding:12px;border-radius:8px">{grade_chart}</div>
        <div style="flex:1 1 300px;background:#fff;padding:12px;border-radius:8px">{subject_chart}</div>
        <div style="flex:1 1 300px;background:#fff;padding:12px;border-radius:8px">{quiz_chart}</div>
      </div>
      <div style="margin-top:12px">
        <a class="btn" href="/teacher/create_quiz">Create Quiz</a>
        <a class="btn" href="/teacher/add_question">Add Question</a>
        <a class="btn" href="/teacher/list_quizzes">Manage Quizzes</a>
        <a class="btn" href="/download/pdf_all">Download Student Data (PDF)</a>
      </div>
    """
    return render_page(content)

# ------------------ Teacher: list/manage quizzes ------------------
@app.route("/teacher/list_quizzes")
def list_quizzes():
    if "teacher" not in session: return redirect("/login/teacher")
    conn = get_db()
    quizzes = conn.execute("SELECT * FROM quizzes ORDER BY id DESC").fetchall()
    conn.close()
    html = "<h2>All Quizzes</h2>"
    if not quizzes:
        html += "<p class='muted'>No quizzes yet.</p>"
    for q in quizzes:
        html += f"<div style='padding:8px;border:1px solid #eee;margin:8px 0;border-radius:6px;display:flex;justify-content:space-between'>"
        html += f"<div><strong>{q['title']}</strong><div class='muted'>{q['subject']} • Grade {q['grade']}</div></div>"
        html += f"<div><a class='btn' href='/teacher/add_question?quiz_id={q['id']}'>Add Question</a> "
        html += f"<a class='btn' href='/teacher/view_quiz/{q['id']}'>View</a></div></div>"
    html += "<a class='btn' href='/teacher/dashboard'>Back</a>"
    return render_page(html)

@app.route("/teacher/view_quiz/<int:quiz_id>")
def view_quiz(quiz_id):
    if "teacher" not in session: return redirect("/login/teacher")
    conn = get_db()
    quiz = conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    qs = conn.execute("SELECT * FROM questions WHERE quiz_id=? ORDER BY id", (quiz_id,)).fetchall()
    conn.close()
    if not quiz:
        return render_page("<h3>Quiz not found</h3><a href='/teacher/list_quizzes' class='btn'>Back</a>")
    html = f"<h2>{quiz['title']} — {quiz['subject']} (Grade {quiz['grade']})</h2>"
    html += "<h3>Questions</h3>"
    if not qs:
        html += "<p class='muted'>No questions in this quiz yet.</p>"
    for q in qs:
        html += f"<div style='padding:8px;border:1px solid #eee;margin:8px 0;border-radius:6px'>Q{q['id']}: {q['text']}"
        if q["image_path"]:
            html += f"<div><img src='{q['image_path']}' style='max-width:200px'></div>"
        html += "</div>"
    html += "<a class='btn' href='/teacher/list_quizzes'>Back to Quizzes</a>"
    return render_page(html)

# ------------------ Download PDF All Students (classwise) ------------------
@app.route("/download/pdf_all")
def download_pdf_all():
    if "teacher" not in session: return redirect("/login/teacher")
    conn = get_db()
    students = conn.execute("SELECT * FROM students ORDER BY grade, class_name, username").fetchall()
    conn.close()
    fname = "students_all.pdf"
    c = canvas.Canvas(fname, pagesize=letter)
    w, h = letter
    c.setFont("Helvetica-Bold", 14); c.drawString(40, h-40, "Student Data (Classwise)")
    y = h-70; c.setFont("Helvetica", 10)
    for s in students:
        c.drawString(40, y, f"ID:{s['id']}  Username:{s['username']}  Grade:{s['grade']}  Class:{s['class_name']}  Gender:{s['gender']}")
        y -= 16
        if y < 60:
            c.showPage(); y = h-50; c.setFont("Helvetica", 10)
    c.save()
    return send_file(fname, as_attachment=True)

# ------------------ Logout ------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ------------------ Run ------------------
if __name__ == "__main__":
    print("🚀 Ambassador Quiz App running at http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
