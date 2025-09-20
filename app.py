from flask import Flask, request, redirect, session, render_template_string, send_file
import sqlite3
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io, base64
import spacy
from difflib import SequenceMatcher
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
import os

# ------------------ App Config ------------------
app = Flask(__name__)
app.secret_key = "supersecret"

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ✅ Teacher credentials
TEACHER_PASSKEYS = {"teacher1": "math123", "teacher2": "science456", "admin": "supersecret"}

# ✅ NLP model
try:
    nlp = spacy.load("en_core_web_sm")
except:
    nlp = None  # fallback if spaCy not available

# ------------------ Database ------------------
def get_db():
    conn = sqlite3.connect("quiz.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS students (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE,
                        password TEXT,
                        grade TEXT,
                        gender TEXT
                    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS questions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        text TEXT,
                        correct TEXT,
                        option_a TEXT,
                        option_b TEXT,
                        option_c TEXT,
                        option_d TEXT,
                        subject TEXT,
                        qtype TEXT,
                        grade TEXT,
                        section TEXT,
                        subsection TEXT,
                        image_path TEXT
                    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS attempts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        student_id INTEGER,
                        question_id INTEGER,
                        student_answer TEXT,
                        correct INTEGER
                    )""")
    conn.commit()
    conn.close()

init_db()

# ------------------ Helpers ------------------
def render_page(content):
    base = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Ambassador Quiz App</title>
    </head>
    <body style="margin:0;font-family:Arial;background:#f4f6f7;">
        <div style='padding:20px;'>
            {content}
        </div>
    </body>
    </html>
    """
    return render_template_string(base)

def similarity_ratio(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

# ------------------ Home ------------------
@app.route("/")
def home():
    return render_page(f"""
        <div style="text-align:center;">
            <h1 style="color:#2c3e50;">Ambassador Quiz App</h1>
            <h3 style="color:#7f8c8d;">Inspire • Inquire • Innovate</h3>
            <div style="margin-top:30px;">
                <a href='/signup/student'><button style="padding:10px 20px;">Student Sign Up</button></a>
                <a href='/login/student'><button style="padding:10px 20px;">Student Login</button></a>
                <a href='/login/teacher'><button style="padding:10px 20px;">Teacher Login</button></a>
            </div>
        </div>
    """)

# ------------------ Student Signup ------------------
@app.route("/signup/student", methods=["GET", "POST"])
def signup_student():
    if request.method == "POST":
        username, password = request.form["username"], request.form["password"]
        grade, gender = request.form["grade"], request.form["gender"]
        try:
            conn = get_db()
            conn.execute("INSERT INTO students(username,password,grade,gender) VALUES (?,?,?,?)",
                         (username, password, grade, gender))
            conn.commit()
            conn.close()
            return redirect("/login/student")
        except:
            return render_page("<p>⚠️ Username already exists!</p><a href='/signup/student'>Try Again</a>")
    return render_page("""
        <h2>Student Signup</h2>
        <form method='post'>
            Username: <input name='username' required><br><br>
            Password: <input type='password' name='password' required><br><br>
            Grade/Class: <input name='grade' required><br><br>
            Gender: <select name='gender'><option>Male</option><option>Female</option></select><br><br>
            <button type='submit'>Sign Up</button>
        </form>
    """)

# ------------------ Student Login ------------------
@app.route("/login/student", methods=["GET", "POST"])
def login_student():
    if request.method == "POST":
        username, password = request.form["username"], request.form["password"]
        conn = get_db()
        student = conn.execute("SELECT * FROM students WHERE username=? AND password=?", (username, password)).fetchone()
        conn.close()
        if student:
            session["student_id"], session["grade"] = student["id"], student["grade"]
            return redirect("/quiz")
        else:
            return render_page("<p>❌ Invalid credentials!</p><a href='/login/student'>Back to Login</a>")
    return render_page("""
        <h2>Student Login</h2>
        <form method='post'>
            Username: <input name='username'><br><br>
            Password: <input type='password' name='password'><br><br>
            <button type='submit'>Login</button>
        </form>
    """)

# ------------------ Teacher Login ------------------
@app.route("/login/teacher", methods=["GET", "POST"])
def login_teacher():
    if request.method == "POST":
        username, password = request.form["username"], request.form["password"]
        if username in TEACHER_PASSKEYS and TEACHER_PASSKEYS[username] == password:
            session["teacher"] = username
            return redirect("/teacher/dashboard")
        else:
            return render_page("<p>❌ Invalid teacher credentials!</p><a href='/login/teacher'>Back</a>")
    return render_page("""
        <h2>Teacher Login</h2>
        <form method='post'>
            Username: <input name='username'><br><br>
            Passkey: <input type='password' name='password'><br><br>
            <button type='submit'>Login</button>
        </form>
    """)

# ------------------ Quiz ------------------
@app.route("/quiz", methods=["GET", "POST"])
def quiz():
    if "student_id" not in session:
        return redirect("/login/student")

    grade = session.get("grade", "")
    conn = get_db()
    questions = conn.execute("SELECT * FROM questions WHERE grade=? ORDER BY section,subsection,id", (grade,)).fetchall()
    conn.close()

    q_index = int(request.args.get("q", 0))
    if q_index >= len(questions):
        return render_page("<h3>✅ Quiz Completed!</h3><a href='/'>Home</a>")

    q = questions[q_index]

    # Answer Submission
    if request.method == "POST":
        ans = request.form.get("answer", "")
        correct = 0
        if (q["qtype"] or "").lower() == "mcq":
            correct = 1 if ans.strip() == (q["correct"] or "").strip() else 0
        else:
            correct = 1 if similarity_ratio(ans, q["correct"] or "") > 0.75 else 0
        conn = get_db()
        conn.execute("INSERT INTO attempts(student_id,question_id,student_answer,correct) VALUES (?,?,?,?)",
                     (session["student_id"], q["id"], ans, correct))
        conn.commit()
        conn.close()
        return render_page(f"<p>{'✅ Correct!' if correct else '❌ Wrong!'}</p><a href='/quiz?q={q_index+1}'>Next</a>")

    # Quiz UI
    q_html = f"""
    <div style="display:flex;gap:20px;">
        <div style="flex:2;background:#fff;padding:20px;border-radius:8px;">
            <h3>{q['section']} - {q['subsection']}</h3>
            <p><b>Q{q_index+1}:</b> {q['text']}</p>
    """
    if q["image_path"]:
        q_html += f"<img src='{q['image_path']}' style='max-width:100%;border-radius:8px;'>"
    q_html += "</div><div style='flex:1;background:#fff;padding:20px;border-radius:8px;'><form method='post'>"

    if (q["qtype"] or "").lower() == "mcq":
        for opt in ["a", "b", "c", "d"]:
            if q[f"option_{opt}"]:
                q_html += f"<label><input type='radio' name='answer' value='{q[f'option_{opt}']}'> {q[f'option_{opt}']}</label><br>"
    else:
        q_html += "<textarea name='answer' rows='4' style='width:100%;'></textarea>"

    q_html += "<br><button type='submit'>Submit</button></form></div></div>"
    return render_page(q_html)

# ------------------ Teacher Add Question ------------------
@app.route("/teacher/add_question", methods=["GET", "POST"])
def add_question():
    if "teacher" not in session:
        return redirect("/login/teacher")
    if request.method == "POST":
        f = request.files.get("image")
        img_path = None
        if f and f.filename:
            img_path = os.path.join(UPLOAD_FOLDER, f.filename)
            f.save(img_path)
            img_path = "/" + img_path

        conn = get_db()
        conn.execute("""INSERT INTO questions(text,correct,option_a,option_b,option_c,option_d,
                        subject,qtype,grade,section,subsection,image_path)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (request.form["text"], request.form["correct"],
                      request.form.get("option_a"), request.form.get("option_b"),
                      request.form.get("option_c"), request.form.get("option_d"),
                      request.form["subject"], request.form["qtype"],
                      request.form["grade"], request.form["section"],
                      request.form["subsection"], img_path))
        conn.commit()
        conn.close()
        return render_page("<p>✅ Question Added!</p><a href='/teacher/dashboard'>Back to Dashboard</a>")
    return render_page("""
        <h2>Add Question</h2>
        <form method='post' enctype='multipart/form-data'>
            Section: <input name='section'><br><br>
            Subsection: <input name='subsection'><br><br>
            Grade: <input name='grade'><br><br>
            Subject: <input name='subject'><br><br>
            Question Text: <input name='text'><br><br>
            Type: <select name='qtype'><option>MCQ</option><option>Subjective</option></select><br><br>
            Correct Answer: <input name='correct'><br><br>
            Option A: <input name='option_a'><br>
            Option B: <input name='option_b'><br>
            Option C: <input name='option_c'><br>
            Option D: <input name='option_d'><br><br>
            Upload Image (optional): <input type='file' name='image'><br><br>
            <button type='submit'>Add Question</button>
        </form>
    """)

# ------------------ Teacher Dashboard ------------------
@app.route("/teacher/dashboard")
def teacher_dashboard():
    if "teacher" not in session:
        return redirect("/login/teacher")
    conn = get_db()
    data = conn.execute("""SELECT s.grade, SUM(a.correct) as correct_count, COUNT(a.id) as total
                           FROM attempts a JOIN students s ON a.student_id=s.id
                           GROUP BY s.grade""").fetchall()
    conn.close()

    grades, scores = [d["grade"] for d in data], [(d["correct_count"]/d["total"])*100 for d in data] if data else []
    plt.figure(figsize=(5,3))
    plt.bar(grades, scores, color="skyblue")
    plt.ylim(0,100)
    plt.ylabel("Avg Score (%)")
    plt.title("Performance by Grade")
    img = io.BytesIO(); plt.savefig(img, format="png"); img.seek(0)
    graph_url = base64.b64encode(img.getvalue()).decode(); plt.close()

    return render_page(f"""
        <h2>Teacher Dashboard</h2>
        <img src='data:image/png;base64,{graph_url}'/><br><br>
        <a href='/teacher/add_question'><button>Add Question</button></a>
        <a href='/download_pdf'><button>Download Student Data (PDF)</button></a>
    """)

# ------------------ PDF Download ------------------
@app.route("/download_pdf")
def download_pdf():
    if "teacher" not in session: return redirect("/login/teacher")
    conn = get_db()
    students = conn.execute("SELECT * FROM students").fetchall()
    conn.close()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    data = [["ID","Username","Grade","Gender"]]+[[s["id"],s["username"],s["grade"],s["gender"]] for s in students]
    table = Table(data); table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.grey),("TEXTCOLOR",(0,0),(-1,0),colors.whitesmoke),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),("GRID",(0,0),(-1,-1),1,colors.black)
    ]))
    doc.build([Paragraph("Student Data", styles["Title"]), table])
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="students.pdf", mimetype="application/pdf")

# ------------------ Logout ------------------
@app.route("/logout")
def logout():
    session.clear(); return redirect("/")

# ------------------ Run ------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
