from flask import Flask, request, redirect, session, render_template_string, send_file
import sqlite3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import io
import base64
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# -----------------------------
# App Config
# -----------------------------
app = Flask(__name__)
app.secret_key = "supersecretkey"

# Teacher credentials
TEACHER_PASSKEYS = {
    "teacher1": "math123",
    "teacher2": "science456",
    "admin": "supersecret"
}

# -----------------------------
# Database
# -----------------------------
def get_db():
    conn = sqlite3.connect("quiz.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    # Students
    conn.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE,
            password TEXT,
            grade TEXT,
            class TEXT,
            gender TEXT
        )
    """)
    # Quizzes
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            grade TEXT,
            subject TEXT
        )
    """)
    # Passages
    conn.execute("""
        CREATE TABLE IF NOT EXISTS passages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER,
            text TEXT
        )
    """)
    # Questions
    conn.execute("""
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
            image_url TEXT
        )
    """)
    # Attempts
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            question_id INTEGER,
            student_answer TEXT,
            correct INTEGER
        )
    """)
    conn.commit()
    conn.close()

init_db()

# -----------------------------
# Helpers
# -----------------------------
def render_page(content):
    base = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Ambassador Quiz App</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 0;
                background: #f4f6f9;
                color: #333;
            }}
            header {{
                background: #2c3e50;
                padding: 15px;
                text-align: center;
                color: white;
                font-size: 24px;
            }}
            .container {{
                padding: 20px;
                max-width: 900px;
                margin: auto;
            }}
            button {{
                background: #3498db;
                color: white;
                padding: 10px 15px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                margin: 5px;
            }}
            button:hover {{
                background: #2980b9;
            }}
            input, select {{
                padding: 8px;
                margin: 5px 0;
                width: 100%;
                max-width: 400px;
            }}
            .card {{
                background: white;
                padding: 15px;
                margin: 15px 0;
                border-radius: 10px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            }}
            .options label {{
                display: block;
                margin: 5px 0;
            }}
        </style>
    </head>
    <body>
        <header>Ambassador Quiz App</header>
        <div class="container">
            {content}
        </div>
    </body>
    </html>
    """
    return render_template_string(base)

def check_subjective(student_ans, correct_ans):
    """ Simple word overlap algorithm """
    student_words = set(str(student_ans).lower().split())
    correct_words = set(str(correct_ans).lower().split())
    if not correct_words:
        return 0
    match_count = len(student_words & correct_words)
    return 1 if match_count >= max(1, len(correct_words)//2) else 0

# -----------------------------
# Routes
# -----------------------------
@app.route("/")
def home():
    return render_page("""
        <h2>Welcome to Ambassador Quiz App</h2>
        <a href='/signup/student'><button>Student Sign Up</button></a>
        <a href='/login/student'><button>Student Login</button></a>
        <a href='/login/teacher'><button>Teacher Login</button></a>
    """)

# ---------- Student Signup ----------
@app.route("/signup/student", methods=["GET","POST"])
def signup_student():
    if request.method == "POST":
        user_id = request.form["user_id"]
        password = request.form["password"]
        grade = request.form["grade"]
        student_class = request.form["class"]
        gender = request.form["gender"]
        try:
            conn = get_db()
            conn.execute("INSERT INTO students (user_id,password,grade,class,gender) VALUES (?,?,?,?,?)",
                         (user_id,password,grade,student_class,gender))
            conn.commit()
            conn.close()
            return redirect("/login/student")
        except:
            return render_page("<p>User ID already exists!</p><a href='/signup/student'><button>Back</button></a>")
    return render_page("""
        <h2>Student Sign Up</h2>
        <form method="post">
            User ID: <input name="user_id" required><br>
            Password: <input type="password" name="password" required><br>
            Grade: <input name="grade" required><br>
            Class: <input name="class" required><br>
            Gender: 
            <select name="gender">
                <option>Male</option>
                <option>Female</option>
                <option>Other</option>
            </select><br>
            <button type="submit">Sign Up</button>
        </form>
    """)

# ---------- Student Login ----------
@app.route("/login/student", methods=["GET","POST"])
def login_student():
    if request.method == "POST":
        user_id = request.form["user_id"]
        password = request.form["password"]
        conn = get_db()
        student = conn.execute("SELECT * FROM students WHERE user_id=? AND password=?",(user_id,password)).fetchone()
        conn.close()
        if student:
            session["student_id"] = student["id"]
            session["grade"] = student["grade"]
            return redirect("/student/dashboard")
        else:
            return render_page("<p>Invalid credentials!</p><a href='/login/student'><button>Back to Login</button></a>")
    return render_page("""
        <h2>Student Login</h2>
        <form method="post">
            User ID: <input name="user_id"><br>
            Password: <input type="password" name="password"><br>
            <button type="submit">Login</button>
        </form>
    """)

# ---------- Teacher Login ----------
@app.route("/login/teacher", methods=["GET","POST"])
def login_teacher():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if username in TEACHER_PASSKEYS and TEACHER_PASSKEYS[username]==password:
            session["teacher"]=username
            return redirect("/teacher/dashboard")
        else:
            return render_page("<p>Invalid credentials!</p><a href='/login/teacher'><button>Back to Login</button></a>")
    return render_page("""
        <h2>Teacher Login</h2>
        <form method="post">
            Username: <input name="username"><br>
            Passkey: <input type="password" name="password"><br>
            <button type="submit">Login</button>
        </form>
    """)

# ---------- Student Dashboard ----------
@app.route("/student/dashboard")
def student_dashboard():
    if "student_id" not in session:
        return redirect("/login/student")
    grade = session["grade"]
    conn = get_db()
    quizzes = conn.execute("SELECT * FROM quizzes WHERE grade=?",(grade,)).fetchall()
    conn.close()
    html = "<h2>Available Quizzes</h2>"
    for q in quizzes:
        html += f"<div class='card'><b>{q['title']} ({q['subject']})</b><br>"
        html += f"<a href='/quiz/{q['id']}'><button>Take Quiz</button></a></div>"
    html += "<a href='/logout'><button>Logout</button></a>"
    return render_page(html)

# ---------- Teacher Dashboard ----------
@app.route("/teacher/dashboard")
def teacher_dashboard():
    if "teacher" not in session:
        return redirect("/login/teacher")

    conn = get_db()
    quizzes = conn.execute("SELECT * FROM quizzes").fetchall()
    data = conn.execute("""
        SELECT s.grade, SUM(a.correct) as correct_count, COUNT(a.id) as total
        FROM attempts a
        JOIN students s ON a.student_id = s.id
        GROUP BY s.grade
    """).fetchall()
    conn.close()

    grades = [row["grade"] for row in data]
    scores = [(row["correct_count"]/row["total"])*100 for row in data] if data else []
    plt.figure(figsize=(5,3))
    plt.bar(grades, scores, color="skyblue")
    plt.ylim(0,100)
    plt.ylabel("Avg Score (%)")
    plt.title("Performance by Grade")
    img = io.BytesIO()
    plt.savefig(img, format="png")
    img.seek(0)
    graph_url = base64.b64encode(img.getvalue()).decode()
    plt.close()

    html = "<h2>Teacher Dashboard</h2>"
    html += "<a href='/teacher/create_quiz'><button>Create Quiz</button></a>"
    html += "<a href='/teacher/export_pdf'><button>Export PDF</button></a><br><br>"
    for q in quizzes:
        html += f"<div class='card'><b>{q['title']} ({q['subject']}, Grade {q['grade']})</b><br>"
        html += f"<a href='/teacher/delete_quiz/{q['id']}'><button>Delete</button></a></div>"
    html += f"<h3>Performance Graph</h3><img src='data:image/png;base64,{graph_url}'/>"
    html += "<br><a href='/logout'><button>Logout</button></a>"
    return render_page(html)

# ---------- Create Quiz ----------
@app.route("/teacher/create_quiz", methods=["GET","POST"])
def create_quiz():
    if "teacher" not in session:
        return redirect("/login/teacher")
    if request.method=="POST":
        title = request.form["title"]
        grade = request.form["grade"]
        subject = request.form["subject"]
        conn = get_db()
        conn.execute("INSERT INTO quizzes (title,grade,subject) VALUES (?,?,?)",(title,grade,subject))
        conn.commit()
        quiz_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return redirect(f"/teacher/add_passage/{quiz_id}")
    return render_page("""
        <h2>Create Quiz</h2>
        <form method="post">
            Title: <input name="title" required><br>
            Grade: <input name="grade" required><br>
            Subject: <input name="subject" required><br>
            <button type="submit">Create</button>
        </form>
    """)

# ---------- Add Passage ----------
@app.route("/teacher/add_passage/<int:quiz_id>", methods=["GET","POST"])
def add_passage(quiz_id):
    if "teacher" not in session:
        return redirect("/login/teacher")
    if request.method=="POST":
        text = request.form["text"]
        conn = get_db()
        conn.execute("INSERT INTO passages (quiz_id,text) VALUES (?,?)",(quiz_id,text))
        conn.commit()
        passage_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return redirect(f"/teacher/add_question/{passage_id}")
    return render_page("""
        <h2>Add Passage</h2>
        <form method="post">
            Passage Text:<br><textarea name="text" rows="5" cols="60"></textarea><br>
            <button type="submit">Add Passage</button>
        </form>
    """)

# ---------- Add Question ----------
@app.route("/teacher/add_question/<int:passage_id>", methods=["GET","POST"])
def add_question(passage_id):
    if "teacher" not in session:
        return redirect("/login/teacher")
    if request.method=="POST":
        text = request.form["text"]
        correct = request.form["correct"]
        qtype = request.form["qtype"]
        option_a = request.form.get("option_a")
        option_b = request.form.get("option_b")
        option_c = request.form.get("option_c")
        option_d = request.form.get("option_d")
        image_url = request.form.get("image_url")
        conn = get_db()
        conn.execute("""
            INSERT INTO questions (passage_id,text,correct,option_a,option_b,option_c,option_d,qtype,image_url)
            VALUES (?,?,?,?,?,?,?,?,?)
        """,(passage_id,text,correct,option_a,option_b,option_c,option_d,qtype,image_url))
        conn.commit()
        conn.close()
        return render_page(f"<p>Question added!</p><a href='/teacher/add_question/{passage_id}'><button>Add Another</button></a> <a href='/teacher/dashboard'><button>Dashboard</button></a>")
    return render_page("""
        <h2>Add Question</h2>
        <form method="post">
            Question: <input name="text" required><br>
            Correct Answer: <input name="correct" required><br>
            Type: <select name="qtype"><option value="mcq">MCQ</option><option value="subjective">Subjective</option></select><br>
            Option A: <input name="option_a"><br>
            Option B: <input name="option_b"><br>
            Option C: <input name="option_c"><br>
            Option D: <input name="option_d"><br>
            Image URL (optional): <input name="image_url"><br>
            <button type="submit">Add Question</button>
        </form>
    """)

# ---------- Take Quiz ----------
@app.route("/quiz/<int:quiz_id>", methods=["GET","POST"])
def take_quiz(quiz_id):
    if "student_id" not in session:
        return redirect("/login/student")
    conn = get_db()
    quiz = conn.execute("SELECT * FROM quizzes WHERE id=?",(quiz_id,)).fetchone()
    passages = conn.execute("SELECT * FROM passages WHERE quiz_id=?",(quiz_id,)).fetchall()
    questions = conn.execute("SELECT * FROM questions WHERE passage_id IN (SELECT id FROM passages WHERE quiz_id=?)",(quiz_id,)).fetchall()
    conn.close()
    if request.method=="POST":
        student_id = session["student_id"]
        conn = get_db()
        for q in questions:
            ans = request.form.get(str(q["id"]))
            if not ans:
                continue
            correct_flag = 0
            if q["qtype"]=="mcq":
                if ans.strip().lower()==str(q["correct"]).strip().lower():
                    correct_flag=1
            else:
                correct_flag = check_subjective(ans,q["correct"])
            conn.execute("INSERT INTO attempts (student_id,question_id,student_answer,correct) VALUES (?,?,?,?)",
                         (student_id,q["id"],ans,int(correct_flag)))
        conn.commit()
        conn.close()
        return render_page("<p>Quiz submitted!</p><a href='/student/dashboard'><button>Back to Dashboard</button></a>")
    q_html = f"<h2>{quiz['title']}</h2><form method='post'>"
    for p in passages:
        q_html += f"<div class='card'><p><b>Passage:</b> {p['text']}</p></div>"
        for q in questions:
            if q["passage_id"]==p["id"]:
                q_html += f"<div class='card'><p>{q['text']}</p>"
                if q["image_url"]:
                    q_html += f"<img src='{q['image_url']}' style='max-width:200px;'><br>"
                if q["qtype"]=="mcq":
                    q_html += "<div class='options'>"
                    for opt in ["a","b","c","d"]:
                        val=q[f"option_{opt}"]
                        if val:
                            q_html+=f"<label><input type='radio' name='{q['id']}' value='{val}'> {val}</label>"
                    q_html+="</div>"
                else:
                    q_html += f"<input name='{q['id']}'><br>"
                q_html+="</div>"
    q_html += "<button type='submit'>Submit Quiz</button></form>"
    return render_page(q_html)

# ---------- Delete Quiz ----------
@app.route("/teacher/delete_quiz/<int:quiz_id>")
def delete_quiz(quiz_id):
    if "teacher" not in session:
        return redirect("/login/teacher")
    conn = get_db()
    conn.execute("DELETE FROM quizzes WHERE id=?",(quiz_id,))
    conn.execute("DELETE FROM passages WHERE quiz_id=?",(quiz_id,))
    conn.execute("DELETE FROM questions WHERE passage_id IN (SELECT id FROM passages WHERE quiz_id=?)",(quiz_id,))
    conn.commit()
    conn.close()
    return redirect("/teacher/dashboard")

# ---------- Export PDF ----------
@app.route("/teacher/export_pdf")
def export_pdf():
    if "teacher" not in session:
        return redirect("/login/teacher")
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements=[]
    styles=getSampleStyleSheet()
    elements.append(Paragraph("Student Performance Report",styles['Title']))
    conn = get_db()
    data = conn.execute("SELECT * FROM students").fetchall()
    conn.close()
    table_data=[["User ID","Grade","Class","Gender"]]
    for row in data:
        table_data.append([row["user_id"],row["grade"],row["class"],row["gender"]])
    table=Table(table_data)
    table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.gray),("TEXTCOLOR",(0,0),(-1,0),colors.whitesmoke),("ALIGN",(0,0),(-1,-1),"CENTER"),("GRID",(0,0),(-1,-1),1,colors.black)]))
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer,as_attachment=True,download_name="student_report.pdf",mimetype="application/pdf")

# ---------- Logout ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# -----------------------------
# Run
# -----------------------------
if __name__=="__main__":
    app.run(debug=True)
