from flask import Flask, request, redirect, session, render_template_string, send_file
import sqlite3
import secrets
import plotly.express as px
import pandas as pd
from xhtml2pdf import pisa
from io import BytesIO

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
DB_PATH = "db.sqlite"

# ----------------- Database -----------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    # Students
    c.execute("""CREATE TABLE IF NOT EXISTS students(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, username TEXT UNIQUE, password TEXT,
        grade TEXT, gender TEXT, class_section TEXT
    )""")

    # Teachers
    c.execute("""CREATE TABLE IF NOT EXISTS teachers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, username TEXT UNIQUE, password TEXT
    )""")

    # Quizzes
    c.execute("""CREATE TABLE IF NOT EXISTS quizzes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, grade TEXT, subject TEXT, teacher_id INTEGER
    )""")

    # Passages
    c.execute("""CREATE TABLE IF NOT EXISTS passages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quiz_id INTEGER, passage_text TEXT
    )""")

    # Questions
    c.execute("""CREATE TABLE IF NOT EXISTS questions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        passage_id INTEGER, type TEXT,
        question_text TEXT, options TEXT,
        correct_answer TEXT, marks INTEGER
    )""")

    # Answers
    c.execute("""CREATE TABLE IF NOT EXISTS answers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER, quiz_id INTEGER,
        question_id INTEGER, answer TEXT, score INTEGER
    )""")

    conn.commit()
    conn.close()

# ----------------- Helper Functions -----------------
def render_page(content):
    base = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Ambassador Quiz App</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background:#f9f9f9; }}
            .nav {{ margin-bottom:20px; }}
            .nav a {{ margin-right:15px; text-decoration:none; color:blue; }}
            .card {{ background:white; padding:20px; border-radius:10px; box-shadow:0 2px 5px rgba(0,0,0,0.1); margin:10px 0; }}
            button {{ padding:8px 12px; border:none; border-radius:5px; }}
            .delete-btn {{ background:red; color:white; }}
            .mcq-option {{ display:block; margin:5px 0; }}
        </style>
    </head>
    <body>
        <div class="nav">
            <a href="/">Home</a>
            {"<a href='/logout'>Logout</a>" if 'student' in session or 'teacher' in session else ""}
        </div>
        {content}
    </body>
    </html>
    """
    return render_template_string(base)

def word_overlap_similarity(ans, correct):
    ans_words = set(ans.lower().split())
    correct_words = set(correct.lower().split())
    overlap = len(ans_words & correct_words)
    return overlap / max(len(correct_words), 1)

# ----------------- Routes -----------------
@app.route("/")
def home():
    return render_page("""
        <div class="card">
            <h1>Welcome to Ambassador Quiz App</h1>
            <p><a href='/student_signup'>Student Signup</a> | <a href='/login'>Login</a></p>
        </div>
    """)

@app.route("/student_signup", methods=["GET","POST"])
def student_signup():
    if request.method=="POST":
        name=request.form["name"]
        username=request.form["username"]
        password=request.form["password"]
        grade=request.form["grade"]
        gender=request.form["gender"]
        class_section=request.form["class"]
        conn=get_db(); c=conn.cursor()
        try:
            c.execute("INSERT INTO students(name,username,password,grade,gender,class_section) VALUES (?,?,?,?,?,?)",
                      (name,username,password,grade,gender,class_section))
            conn.commit()
        except:
            return render_page("<div class='card'><p>Username already exists</p><a href='/student_signup'>Try again</a></div>")
        conn.close()
        return redirect("/login")
    return render_page("""
        <div class="card">
        <h2>Student Signup</h2>
        <form method="POST">
            Name:<br><input name="name"><br>
            Username:<br><input name="username"><br>
            Password:<br><input type="password" name="password"><br>
            Grade:<br><input name="grade"><br>
            Gender:<br><select name="gender"><option>Male</option><option>Female</option></select><br>
            Class Section:<br><input name="class"><br><br>
            <button type="submit">Signup</button>
        </form>
        </div>
    """)

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        username=request.form["username"]; password=request.form["password"]; role=request.form["role"]
        conn=get_db(); c=conn.cursor()
        if role=="student":
            c.execute("SELECT * FROM students WHERE username=? AND password=?",(username,password))
            user=c.fetchone()
            if user:
                session["student"]=dict(user)
                return redirect("/student_dashboard")
        else:
            c.execute("SELECT * FROM teachers WHERE username=? AND password=?",(username,password))
            user=c.fetchone()
            if user:
                session["teacher"]=dict(user)
                return redirect("/teacher_dashboard")
        return render_page("<div class='card'><p>Invalid credentials</p><a href='/login'>Back to Login</a></div>")
    return render_page("""
        <div class="card">
        <h2>Login</h2>
        <form method="POST">
            Username:<br><input name="username"><br>
            Password:<br><input type="password" name="password"><br>
            Role:<br>
            <select name="role">
                <option value="student">Student</option>
                <option value="teacher">Teacher</option>
            </select><br><br>
            <button type="submit">Login</button>
        </form>
        </div>
    """)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ----------------- Teacher -----------------
@app.route("/teacher_dashboard")
def teacher_dashboard():
    if "teacher" not in session: return redirect("/login")
    tid=session["teacher"]["id"]
    conn=get_db(); c=conn.cursor()
    c.execute("SELECT * FROM quizzes WHERE teacher_id=?",(tid,))
    quizzes=c.fetchall()
    conn.close()
    quiz_list=""
    for q in quizzes:
        quiz_list+=f"""
        <div class='card'>
            <b>{q['title']}</b> ({q['grade']} - {q['subject']})<br>
            <a href='/add_passage/{q['id']}'>Add Passage & Questions</a>
            <form method="POST" action="/teacher/delete_quiz/{q['id']}" style="display:inline;" onsubmit="return confirm('Delete this quiz?');">
                <button type="submit" class="delete-btn">Delete</button>
            </form>
        </div>
        """
    return render_page(f"""
        <div class="card">
        <h2>Teacher Dashboard</h2>
        <p><a href='/create_quiz'>Create New Quiz</a></p>
        {quiz_list if quiz_list else "<p>No quizzes yet.</p>"}
        </div>
    """)

@app.route("/create_quiz", methods=["GET","POST"])
def create_quiz():
    if "teacher" not in session: return redirect("/login")
    if request.method=="POST":
        title=request.form["title"]; grade=request.form["grade"]; subject=request.form["subject"]
        tid=session["teacher"]["id"]
        conn=get_db(); c=conn.cursor()
        c.execute("INSERT INTO quizzes(title,grade,subject,teacher_id) VALUES (?,?,?,?)",(title,grade,subject,tid))
        conn.commit(); conn.close()
        return redirect("/teacher_dashboard")
    return render_page("""
        <div class="card">
        <h2>Create Quiz</h2>
        <form method="POST">
            Title:<br><input name="title"><br>
            Grade:<br><input name="grade"><br>
            Subject:<br><input name="subject"><br><br>
            <button type="submit">Create</button>
        </form>
        </div>
    """)

@app.route("/add_passage/<int:quiz_id>", methods=["GET","POST"])
def add_passage(quiz_id):
    if "teacher" not in session: return redirect("/login")
    if request.method=="POST":
        passage=request.form["passage"]
        conn=get_db(); c=conn.cursor()
        c.execute("INSERT INTO passages(quiz_id,passage_text) VALUES (?,?)",(quiz_id,passage))
        conn.commit(); conn.close()
        return redirect(f"/add_question/{quiz_id}")
    return render_page(f"""
        <div class="card">
        <h2>Add Passage</h2>
        <form method="POST">
            <textarea name="passage" rows="5" cols="60"></textarea><br>
            <button type="submit">Save Passage</button>
        </form>
        </div>
    """)

@app.route("/add_question/<int:quiz_id>", methods=["GET","POST"])
def add_question(quiz_id):
    if "teacher" not in session: return redirect("/login")
    conn=get_db(); c=conn.cursor()
    c.execute("SELECT * FROM passages WHERE quiz_id=?",(quiz_id,))
    passages=c.fetchall()
    if request.method=="POST":
        passage_id=request.form["passage_id"]; qtype=request.form["type"]
        qtext=request.form["question"]; options=request.form.get("options","")
        answer=request.form["answer"]; marks=int(request.form["marks"])
        c.execute("INSERT INTO questions(passage_id,type,question_text,options,correct_answer,marks) VALUES (?,?,?,?,?,?)",
                  (passage_id,qtype,qtext,options,answer,marks))
        conn.commit(); conn.close()
        return redirect(f"/add_question/{quiz_id}")
    passage_opts="".join([f"<option value='{p['id']}'>Passage {p['id']}</option>" for p in passages])
    return render_page(f"""
        <div class="card">
        <h2>Add Question</h2>
        <form method="POST">
            Passage:<br>
            <select name="passage_id">{passage_opts}</select><br>
            Type:<br>
            <select name="type" id="qtype" onchange="toggleOptions()">
                <option>MCQ</option>
                <option>Subjective</option>
            </select><br>
            Question:<br><textarea name="question"></textarea><br>
            <div id="mcq">
                Options (comma separated):<br><input name="options"><br>
            </div>
            Correct Answer:<br><input name="answer"><br>
            Marks:<br><input name="marks" type="number" value="1"><br><br>
            <button type="submit">Add</button>
        </form>
        <script>
        function toggleOptions() {{
            var t=document.getElementById("qtype").value;
            document.getElementById("mcq").style.display=(t=="MCQ")?"block":"none";
        }}
        toggleOptions();
        </script>
        </div>
    """)

@app.route("/teacher/delete_quiz/<int:quiz_id>", methods=["POST"])
def delete_quiz(quiz_id):
    if "teacher" not in session: return redirect("/login")
    conn=get_db(); c=conn.cursor()
    c.execute("DELETE FROM questions WHERE passage_id IN (SELECT id FROM passages WHERE quiz_id=?)",(quiz_id,))
    c.execute("DELETE FROM passages WHERE quiz_id=?",(quiz_id,))
    c.execute("DELETE FROM quizzes WHERE id=?",(quiz_id,))
    conn.commit(); conn.close()
    return redirect("/teacher_dashboard")

# ----------------- Student -----------------
@app.route("/student_dashboard")
def student_dashboard():
    if "student" not in session: return redirect("/login")
    conn=get_db(); c=conn.cursor()
    c.execute("SELECT * FROM quizzes")
    quizzes=c.fetchall(); conn.close()
    quiz_links="".join([f"<div class='card'><a href='/take_quiz/{q['id']}'>{q['title']} ({q['subject']})</a></div>" for q in quizzes])
    return render_page(f"""
        <div class="card">
        <h2>Student Dashboard</h2>
        {quiz_links if quiz_links else "<p>No quizzes yet.</p>"}
        </div>
    """)

@app.route("/take_quiz/<int:quiz_id>", methods=["GET","POST"])
def take_quiz(quiz_id):
    if "student" not in session: return redirect("/login")
    sid=session["student"]["id"]
    conn=get_db(); c=conn.cursor()
    c.execute("SELECT * FROM passages WHERE quiz_id=?",(quiz_id,))
    passages=c.fetchall()
    output="<h2>Quiz</h2>"
    for p in passages:
        output+=f"<div class='card'><p><b>Passage:</b><br>{p['passage_text']}</p>"
        c.execute("SELECT * FROM questions WHERE passage_id=?",(p["id"],))
        questions=c.fetchall()
        for q in questions:
            output+=f"<form method='POST' action='/submit_answer/{quiz_id}/{q['id']}'>"
            output+=f"<p>{q['question_text']}</p>"
            if q["type"]=="MCQ":
                for opt in q["options"].split(","):
                    output+=f"<label class='mcq-option'><input type='radio' name='answer' value='{opt.strip()}'> {opt.strip()}</label>"
            else:
                output+="<textarea name='answer'></textarea>"
            output+="<br><button type='submit'>Submit</button></form>"
        output+="</div>"
    conn.close()
    return render_page(output)

@app.route("/submit_answer/<int:quiz_id>/<int:qid>", methods=["POST"])
def submit_answer(quiz_id,qid):
    if "student" not in session: return redirect("/login")
    sid=session["student"]["id"]
    ans=request.form["answer"]
    conn=get_db(); c=conn.cursor()
    c.execute("SELECT * FROM questions WHERE id=?",(qid,))
    q=c.fetchone()
    score=0
    if q["type"]=="MCQ":
        if ans.strip().lower()==q["correct_answer"].strip().lower():
            score=q["marks"]
    else:
        sim=word_overlap_similarity(ans,q["correct_answer"])
        if sim>=0.5:
            score=q["marks"]
    c.execute("INSERT INTO answers(student_id,quiz_id,question_id,answer,score) VALUES (?,?,?,?,?)",(sid,quiz_id,qid,ans,score))
    conn.commit(); conn.close()
    return render_page(f"<div class='card'><p>Answer submitted. Score: {score}</p><a href='/student_dashboard'>Back</a></div>")

# ----------------- Run -----------------
if __name__=="__main__":
    init_db()
    app.run(debug=True)
