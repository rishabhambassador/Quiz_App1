from flask import Flask, request, redirect, session, render_template_string
import sqlite3
import bcrypt
import secrets

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
    c.execute('''CREATE TABLE IF NOT EXISTS teachers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        passkey_hash TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS students(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT UNIQUE,
        name TEXT,
        gender TEXT,
        grade TEXT,
        class TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS questions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        grade TEXT,
        class TEXT,
        text TEXT,
        a TEXT, b TEXT, c TEXT, d TEXT,
        correct TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS attempts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        question_id INTEGER,
        selected TEXT,
        correct INTEGER
    )''')
    conn.commit()
    conn.close()

init_db()

# ----------------- Base HTML -----------------
base_html = """
<!DOCTYPE html>
<html>
<head>
<title>Quiz App</title>
<style>
body {font-family: Arial; margin:20px; background:#f8f9fa; color:#333;}
nav {background:#007bff; padding:10px; border-radius:5px;}
nav a {color:white; text-decoration:none; margin-right:15px; font-weight:bold;}
nav a:hover{text-decoration:underline;}
h1,h2,h3{color:#007bff;}
form {background:#fff; padding:15px; border-radius:5px; max-width:500px; margin-bottom:20px; box-shadow:0px 2px 5px rgba(0,0,0,0.1);}
input[type=text], select {width:100%; padding:8px; margin:5px 0 15px 0; border-radius:4px; border:1px solid #ccc;}
input[type=submit]{background:#007bff; color:white; padding:10px 20px; border:none; border-radius:4px; cursor:pointer;}
input[type=submit]:hover{background:#0056b3;}
table{width:100%; border-collapse:collapse; margin-bottom:20px; background:#fff; border-radius:5px; overflow:hidden; box-shadow:0px 2px 5px rgba(0,0,0,0.1);}
table th, table td{border:1px solid #ddd; padding:10px; text-align:left;}
table th{background:#007bff; color:white;}
table tr:nth-child(even){background:#f2f2f2;}
</style>
</head>
<body>
<nav>
<a href="/">Home</a> |
<a href="/teacher">Teacher</a> |
<a href="/student">Student</a> |
{% if session.get('student') or session.get('teacher') %}
<a href="/logout">Logout</a>
{% endif %}
</nav>
<hr>
{{ content|safe }}
</body>
</html>
"""

# ----------------- Routes -----------------

@app.route("/")
def index():
    content = """
    <h1>Welcome to Quiz App</h1>
    <p><a href="/signup/teacher">Teacher Sign Up</a> | <a href="/login/teacher">Teacher Login</a></p>
    <p><a href="/signup/student">Student Sign Up</a> | <a href="/login/student">Student Login</a></p>
    """
    return render_template_string(base_html, content=content)

# --- Teacher Signup ---
@app.route("/signup/teacher", methods=["GET","POST"])
def teacher_signup():
    key = None
    if request.method == "POST":
        name = request.form["name"]
        key = secrets.token_hex(8)  # longer passkey
        hashed = bcrypt.hashpw(key.encode(), bcrypt.gensalt())
        conn = get_db()
        conn.execute("INSERT INTO teachers(name, passkey_hash) VALUES (?,?)", (name, hashed))
        conn.commit()
        conn.close()
    content = """
    <h2>Teacher Sign Up</h2>
    <form method="POST">
        Name: <input type="text" name="name" required><br><br>
        <input type="submit" value="Sign Up">
    </form>
    """
    if key:
        content += f"<p>Your passkey: <strong>{key}</strong></p><p>Save this to login!</p>"
    return render_template_string(base_html, content=content)

# --- Teacher Login ---
@app.route("/login/teacher", methods=["GET","POST"])
def teacher_login():
    error = ""
    if request.method=="POST":
        name = request.form["name"]
        passkey = request.form["passkey"]
        conn = get_db()
        teacher = conn.execute("SELECT * FROM teachers WHERE name=?", (name,)).fetchone()
        conn.close()
        if teacher and bcrypt.checkpw(passkey.encode(), teacher["passkey_hash"]):
            session["teacher"] = {"id": teacher["id"], "name": teacher["name"]}
            return redirect("/teacher")
        else:
            error = "Invalid name or passkey"
    content = f"""
    <h2>Teacher Login</h2>
    <form method="POST">
        Name: <input type="text" name="name" required><br><br>
        Passkey: <input type="text" name="passkey" required><br><br>
        <input type="submit" value="Login">
    </form>
    <p style="color:red">{error}</p>
    """
    return render_template_string(base_html, content=content)

# --- Student Signup ---
@app.route("/signup/student", methods=["GET","POST"])
def student_signup():
    error = ""
    if request.method=="POST":
        student_id = request.form["student_id"]
        name = request.form["name"]
        gender = request.form["gender"]
        grade = request.form["grade"]
        class_name = request.form["class_name"]
        conn = get_db()
        try:
            conn.execute("INSERT INTO students(student_id,name,gender,grade,class) VALUES (?,?,?,?,?)",
                         (student_id,name,gender,grade,class_name))
            conn.commit()
            conn.close()
            return redirect("/login/student")
        except sqlite3.IntegrityError:
            error = "Student ID already exists."
    content = f"""
    <h2>Student Sign Up</h2>
    <form method="POST">
        Student ID: <input type="text" name="student_id" required><br>
        Name: <input type="text" name="name" required><br>
        Gender: <select name="gender"><option>Male</option><option>Female</option></select><br>
        Grade: <input type="text" name="grade" required><br>
        Class: <input type="text" name="class_name" required><br><br>
        <input type="submit" value="Sign Up">
    </form>
    <p style="color:red">{error}</p>
    """
    return render_template_string(base_html, content=content)

# --- Student Login ---
@app.route("/login/student", methods=["GET","POST"])
def student_login():
    error = ""
    if request.method=="POST":
        student_id = request.form["student_id"]
        conn = get_db()
        student = conn.execute("SELECT * FROM students WHERE student_id=?", (student_id,)).fetchone()
        conn.close()
        if student:
            session["student"] = dict(student)
            return redirect("/student")
        else:
            error = "Student not found"
    content = f"""
    <h2>Student Login</h2>
    <form method="POST">
        Student ID: <input type="text" name="student_id" required><br><br>
        <input type="submit" value="Login">
    </form>
    <p style="color:red">{error}</p>
    """
    return render_template_string(base_html, content=content)

# --- Teacher Dashboard ---
@app.route("/teacher")
def teacher_dashboard():
    if "teacher" not in session:
        return redirect("/login/teacher")
    conn = get_db()
    students = conn.execute("SELECT * FROM students").fetchall()
    questions = conn.execute("SELECT * FROM questions").fetchall()
    conn.close()
    student_rows = "".join([f"<tr><td>{s['student_id']}</td><td>{s['name']}</td><td>{s['gender']}</td><td>{s['grade']}</td><td>{s['class']}</td></tr>" for s in students])
    question_rows = "".join([f"<tr><td>{q['grade']}</td><td>{q['class']}</td><td>{q['text']}</td><td>{q['correct']}</td></tr>" for q in questions])
    content = f"""
    <h2>Teacher Dashboard</h2>
    <h3>Add Question</h3>
    <form method="POST" action="/teacher/question">
        Grade: <input type="text" name="grade" required><br>
        Class: <input type="text" name="class_name" required><br>
        Question: <input type="text" name="text" required><br>
        Option A: <input type="text" name="a" required><br>
        Option B: <input type="text" name="b" required><br>
        Option C: <input type="text" name="c" required><br>
        Option D: <input type="text" name="d" required><br>
        Correct Option (a/b/c/d): <input type="text" name="correct" required><br><br>
        <input type="submit" value="Add Question">
    </form>
    <h3>Students</h3>
    <table><tr><th>ID</th><th>Name</th><th>Gender</th><th>Grade</th><th>Class</th></tr>{student_rows}</table>
    <h3>Questions</h3>
    <table><tr><th>Grade</th><th>Class</th><th>Question</th><th>Correct</th></tr>{question_rows}</table>
    """
    return render_template_string(base_html, content=content)

@app.route("/teacher/question", methods=["POST"])
def teacher_add_question():
    if "teacher" not in session:
        return redirect("/login/teacher")
    data = request.form
    conn = get_db()
    conn.execute("INSERT INTO questions(grade,class,text,a,b,c,d,correct) VALUES (?,?,?,?,?,?,?,?)",
                 (data['grade'], data['class_name'], data['text'], data['a'], data['b'], data['c'], data['d'], data['correct']))
    conn.commit()
    conn.close()
    return redirect("/teacher")

# --- Student Dashboard ---
@app.route("/student")
def student_dashboard():
    if "student" not in session:
        return redirect("/login/student")
    student = session["student"]
    conn = get_db()
    questions = conn.execute("SELECT * FROM questions WHERE grade=? AND class=?", (student['grade'], student['class'])).fetchall()
    conn.close()
    question_rows = "".join([f"<tr><td>{q['text']}</td><td><a href='/attempt/{q['id']}'>Attempt</a></td></tr>" for q in questions])
    content = f"""
    <h2>Student Dashboard</h2>
    <h3>Available Questions</h3>
    <table><tr><th>Question</th><th>Action</th></tr>{question_rows}</table>
    """
    return render_template_string(base_html, content=content)

# --- Attempt Question ---
@app.route("/attempt/<int:q_id>", methods=["GET","POST"])
def attempt_question(q_id):
    if "student" not in session:
        return redirect("/login/student")
    conn = get_db()
    q = conn.execute("SELECT * FROM questions WHERE id=?", (q_id,)).fetchone()
    if request.method=="POST":
        selected = request.form['answer']
        correct = 1 if selected==q['correct'] else 0
        conn.execute("INSERT INTO attempts(student_id,question_id,selected,correct) VALUES (?,?,?,?)",
                     (session['student']['student_id'], q_id, selected, correct))
        conn.commit()
        conn.close()
        return redirect("/student")
    conn.close()
    content = f"""
    <h2>Attempt Question</h2>
    <form method="POST">
        <p>{q['text']}</p>
        <input type="radio" name="answer" value="a" required> {q['a']}<br>
        <input type="radio" name="answer" value="b"> {q['b']}<br>
        <input type="radio" name="answer" value="c"> {q['c']}<br>
        <input type="radio" name="answer" value="d"> {q['d']}<br><br>
        <input type="submit" value="Submit">
    </form>
    """
    return render_template_string(base_html, content=content)

# --- Logout ---
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__=="__main__":
    app.run(debug=True)
