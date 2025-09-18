from flask import Flask, render_template_string, request, redirect, session
import sqlite3
import bcrypt
import difflib

app = Flask(__name__)
app.secret_key = "supersecret"

# ---------------- DB ----------------
def get_db():
    conn = sqlite3.connect("quiz.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS teachers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        passkey_hash TEXT
    );

    CREATE TABLE IF NOT EXISTS students(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        grade TEXT
    );

    CREATE TABLE IF NOT EXISTS questions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_id INTEGER,
        text TEXT,
        qtype TEXT,
        subject TEXT,
        option_a TEXT,
        option_b TEXT,
        option_c TEXT,
        option_d TEXT,
        correct TEXT
    );

    CREATE TABLE IF NOT EXISTS attempts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        question_id INTEGER,
        selected TEXT,
        correct INTEGER,
        UNIQUE(student_id, question_id)
    );
    """)
    conn.commit()

init_db()

# ---------------- Templates ----------------
base_template = """
<!doctype html>
<html>
<head>
<title>Quiz App</title>
<style>
body { font-family: Arial; margin: 20px; }
.nav { background:#007bff; padding:10px; border-radius:10px; }
.nav a { color:white; font-weight:bold; margin:0 10px; text-decoration:none; }
.big-btn {
    font-size:20px; font-weight:bold; padding:12px 24px;
    margin:10px; background-color:#007BFF; color:white;
    border:none; border-radius:8px; cursor:pointer; transition:0.3s;
}
.big-btn:hover { background-color:#0056b3; }
</style>
</head>
<body>
<div class="nav">
    <a href="/">Home</a> | 
    <a href="/signup/teacher">Teacher</a> | 
    <a href="/signup/student">Student</a>
</div>
<hr>
{% block content %}{% endblock %}
</body>
</html>
"""

# ---------------- Routes ----------------
@app.route("/")
def home():
    return render_template_string(
        base_template + """
        {% block content %}
        <h1>Welcome to Quiz App</h1>
        <a href="/signup/teacher"><button class="big-btn">Teacher Sign Up</button></a>
        <a href="/login/teacher"><button class="big-btn">Teacher Login</button></a>
        <a href="/signup/student"><button class="big-btn">Student Sign Up</button></a>
        <a href="/login/student"><button class="big-btn">Student Login</button></a>
        {% endblock %}
        """
    )

# ---------- Teacher signup/login ----------
@app.route("/signup/teacher", methods=["GET","POST"])
def signup_teacher():
    if request.method=="POST":
        name=request.form["name"]
        passkey=request.form["passkey"]
        hashed=bcrypt.hashpw(passkey.encode(), bcrypt.gensalt()).decode()
        conn=get_db()
        try:
            conn.execute("INSERT INTO teachers(name,passkey_hash) VALUES (?,?)",(name,hashed))
            conn.commit()
            return redirect("/login/teacher")
        except:
            return "Teacher already exists."
    return render_template_string(base_template+"""
    {% block content %}
    <h2>Teacher Sign Up</h2>
    <form method="post">
        Name:<input name="name"><br>
        Passkey:<input type="password" name="passkey"><br>
        <button type="submit">Sign Up</button>
    </form>
    {% endblock %}
    """)

@app.route("/login/teacher", methods=["GET","POST"])
def login_teacher():
    if request.method=="POST":
        name=request.form["name"]
        passkey=request.form["passkey"]
        conn=get_db()
        t=conn.execute("SELECT * FROM teachers WHERE name=?",(name,)).fetchone()
        if t and bcrypt.checkpw(passkey.encode(), t["passkey_hash"].encode()):
            session["teacher_id"]=t["id"]
            return redirect("/teacher/dashboard")
        return "Invalid login"
    return render_template_string(base_template+"""
    {% block content %}
    <h2>Teacher Login</h2>
    <form method="post">
        Name:<input name="name"><br>
        Passkey:<input type="password" name="passkey"><br>
        <button type="submit">Login</button>
    </form>
    {% endblock %}
    """)

# ---------- Student signup/login ----------
@app.route("/signup/student", methods=["GET","POST"])
def signup_student():
    if request.method=="POST":
        student_id=request.form["student_id"]
        grade=request.form["grade"]
        conn=get_db()
        conn.execute("INSERT INTO students(student_id, grade) VALUES (?,?)",(student_id,grade))
        conn.commit()
        return redirect("/login/student")
    return render_template_string(base_template+"""
    {% block content %}
    <h2>Student Sign Up</h2>
    <form method="post">
        Student ID:<input name="student_id"><br>
        Grade:<input name="grade"><br>
        <button type="submit">Sign Up</button>
    </form>
    {% endblock %}
    """)

@app.route("/login/student", methods=["GET","POST"])
def login_student():
    if request.method=="POST":
        student_id=request.form["student_id"]
        conn=get_db()
        s=conn.execute("SELECT * FROM students WHERE student_id=?",(student_id,)).fetchone()
        if s:
            session["student_id"]=s["student_id"]
            return redirect("/student/dashboard")
        return "Not found"
    return render_template_string(base_template+"""
    {% block content %}
    <h2>Student Login</h2>
    <form method="post">
        Student ID:<input name="student_id"><br>
        <button type="submit">Login</button>
    </form>
    {% endblock %}
    """)

# ---------- Teacher dashboard ----------
@app.route("/teacher/dashboard")
def teacher_dashboard():
    if "teacher_id" not in session:
        return redirect("/login/teacher")
    conn=get_db()
    data=conn.execute("""
        SELECT s.grade, SUM(a.correct) as correct_count, COUNT(a.id) as total
        FROM attempts a
        JOIN students s ON a.student_id = s.student_id
        GROUP BY s.grade
    """).fetchall()
    grades={row["grade"]: (row["correct_count"]/row["total"]*100) for row in data} if data else {}
    return render_template_string(base_template+"""
    {% block content %}
    <h2>Teacher Dashboard</h2>
    <a href="/teacher/add_question"><button>Add Question</button></a>
    <h3>Performance by Grade</h3>
    <canvas id="gradeChart"></canvas>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
    const ctx=document.getElementById('gradeChart');
    new Chart(ctx,{
        type:'bar',
        data:{
            labels: {{ grades.keys()|list|tojson }},
            datasets:[{
                label:'Avg Score (%)',
                data: {{ grades.values()|list|tojson }},
                backgroundColor:'rgba(54,162,235,0.6)'
            }]
        },
        options:{scales:{y:{beginAtZero:true,max:100}}}
    });
    </script>
    {% endblock %}
    """, grades=grades)

# ---------- Add question ----------
@app.route("/teacher/add_question", methods=["GET","POST"])
def add_question():
    if "teacher_id" not in session: return redirect("/login/teacher")
    if request.method=="POST":
        text=request.form["text"]
        qtype=request.form["qtype"]
        subject=request.form["subject"]
        a,b,c,d,correct=None,None,None,None,None
        if qtype=="mcq":
            a=request.form["a"]; b=request.form["b"]; c=request.form["c"]; d=request.form["d"]; correct=request.form["correct"]
        else:
            correct=request.form["correct_text"]
        conn=get_db()
        conn.execute("INSERT INTO questions(teacher_id,text,qtype,subject,option_a,option_b,option_c,option_d,correct) VALUES (?,?,?,?,?,?,?,?,?)",
                     (session["teacher_id"],text,qtype,subject,a,b,c,d,correct))
        conn.commit()
        return redirect("/teacher/dashboard")
    return render_template_string(base_template+"""
    {% block content %}
    <h2>Add Question</h2>
    <form method="post">
        Question:<input name="text"><br>
        Subject:<input name="subject"><br>
        Type:<select name="qtype" id="qtype" onchange="toggle()">
            <option value="mcq">MCQ</option>
            <option value="desc">Descriptive</option>
        </select><br>
        <div id="mcq">
            A:<input name="a"><br>
            B:<input name="b"><br>
            C:<input name="c"><br>
            D:<input name="d"><br>
            Correct:<input name="correct"><br>
        </div>
        <div id="desc" style="display:none;">
            Correct Answer:<input name="correct_text"><br>
        </div>
        <button type="submit">Save</button>
    </form>
    <script>
    function toggle(){
        let v=document.getElementById("qtype").value;
        document.getElementById("mcq").style.display=(v=="mcq")?"block":"none";
        document.getElementById("desc").style.display=(v=="desc")?"block":"none";
    }
    </script>
    {% endblock %}
    """)

# ---------- Student dashboard ----------
@app.route("/student/dashboard", methods=["GET","POST"])
def student_dashboard():
    if "student_id" not in session: return redirect("/login/student")
    conn=get_db()
    questions=conn.execute("SELECT * FROM questions").fetchall()
    if request.method=="POST":
        qid=request.form["qid"]; ans=request.form["answer"]
        q=conn.execute("SELECT * FROM questions WHERE id=?",(qid,)).fetchone()
        correct=0
        if q["qtype"]=="mcq":
            if ans==q["correct"]: correct=1
        else:
            ratio=difflib.SequenceMatcher(None,ans.lower(),q["correct"].lower()).ratio()
            if ratio>0.7: correct=1
        try:
            conn.execute("INSERT INTO attempts(student_id,question_id,selected,correct) VALUES (?,?,?,?)",
                         (session["student_id"],qid,ans,correct))
            conn.commit()
        except:
            pass
        return redirect("/student/dashboard")
    return render_template_string(base_template+"""
    {% block content %}
    <h2>Student Dashboard</h2>
    {% for q in questions %}
    <form method="post">
        <p>{{ q.text }} ({{ q.subject }})</p>
        {% if q.qtype=="mcq" %}
            <input type="radio" name="answer" value="a">{{ q.option_a }}<br>
            <input type="radio" name="answer" value="b">{{ q.option_b }}<br>
            <input type="radio" name="answer" value="c">{{ q.option_c }}<br>
            <input type="radio" name="answer" value="d">{{ q.option_d }}<br>
        {% else %}
            <textarea name="answer"></textarea><br>
        {% endif %}
        <input type="hidden" name="qid" value="{{ q.id }}">
        <button type="submit">Submit</button>
    </form>
    {% endfor %}
    {% endblock %}
    """, questions=questions)

if __name__=="__main__":
    app.run(debug=True)
