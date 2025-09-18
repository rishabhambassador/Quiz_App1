"""
Flask Quiz App
- Teacher & Student signup/login
- Teacher can view students (grade/class/individual)
- Teacher can add quiz questions
- Students can attempt questions for their grade/class

Usage:
    pip install flask
    python flask_quiz_app.py
"""

from flask import Flask, g, render_template_string, request, redirect, url_for, session, flash
import sqlite3
import pathlib
import random
import string
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
DB_PATH = 'data.db'

# ---------- Database helpers ----------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    if not pathlib.Path(DB_PATH).exists():
        db = sqlite3.connect(DB_PATH)
        cur = db.cursor()
        cur.executescript('''
        CREATE TABLE teachers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            passhash TEXT NOT NULL
        );
        CREATE TABLE students(
            student_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            gender TEXT,
            grade TEXT,
            class TEXT
        );
        CREATE TABLE questions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_text TEXT NOT NULL,
            option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT,
            correct TEXT NOT NULL,
            grade TEXT,
            class TEXT
        );
        CREATE TABLE attempts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            question_id INTEGER,
            selected TEXT,
            correct INTEGER
        );
        ''')
        db.commit()
        db.close()

init_db()

# ---------- Base Template ----------
base_html = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Quiz App</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 900px; margin: 20px auto; }
    header { display:flex; justify-content:space-between; align-items:center }
    nav a { margin-right: 10px }
    .card { border:1px solid #ddd; padding:12px; border-radius:8px; margin:10px 0 }
    input, select { width:100%; padding:8px; margin:6px 0 }
    label { font-weight:600 }
    table { border-collapse:collapse; width:100% }
    table th, table td { border:1px solid #ddd; padding:6px }
  </style>
</head>
<body>
<header>
  <h2>Quiz App</h2>
  <nav>
    <a href="{{ url_for('index') }}">Home</a>
    {% if session.get('teacher_id') %}
      <a href="{{ url_for('teacher_dashboard') }}">Teacher Dashboard</a>
      <a href="{{ url_for('teacher_logout') }}">Logout</a>
    {% elif session.get('student_id') %}
      <a href="{{ url_for('student_dashboard') }}">Student Dashboard</a>
      <a href="{{ url_for('student_logout') }}">Logout</a>
    {% else %}
      <a href="{{ url_for('signup_choice') }}">Sign Up</a>
      <a href="{{ url_for('login_choice') }}">Sign In</a>
    {% endif %}
  </nav>
</header>
<hr>
{% with messages = get_flashed_messages() %}
  {% if messages %}
    <ul>{% for m in messages %}<li>{{ m }}</li>{% endfor %}</ul>
  {% endif %}
{% endwith %}
{% block content %}{% endblock %}
</body>
</html>
"""

# ---------- Routes ----------
@app.route('/')
def index():
    return render_template_string(base_html + """
    {% block content %}
      <div class="card">
        <h3>Welcome</h3>
        <p>Teachers can sign up to create quizzes; students sign up to attempt them.</p>
      </div>
    {% endblock %}
    """)

# --- Signup ---
@app.route('/signup')
def signup_choice():
    return render_template_string(base_html + """
    {% block content %}
      <div class="card">
        <h3>Sign Up</h3>
        <p><a href="{{ url_for('signup_teacher') }}">Teacher</a></p>
        <p><a href="{{ url_for('signup_student') }}">Student</a></p>
      </div>
    {% endblock %}
    """)

@app.route('/signup/teacher', methods=['GET','POST'])
def signup_teacher():
    if request.method == 'POST':
        name = request.form.get('name')
        if not name:
            flash('Name required')
            return redirect(url_for('signup_teacher'))
        passkey = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
        passhash = generate_password_hash(passkey)
        db = get_db()
        cur = db.cursor()
        cur.execute('INSERT INTO teachers (name, passhash) VALUES (?,?)', (name, passhash))
        db.commit()
        tid = cur.lastrowid
        return render_template_string(base_html + """
        {% block content %}
          <div class="card">
            <h3>Teacher Created</h3>
            <p>Your Teacher ID: <b>{{ tid }}</b></p>
            <p>Passkey (save this): <b>{{ passkey }}</b></p>
          </div>
        {% endblock %}
        """, tid=tid, passkey=passkey)
    return render_template_string(base_html + """
    {% block content %}
      <div class="card">
        <form method="post">
          <label>Name</label><input name="name" required>
          <button type="submit">Create</button>
        </form>
      </div>
    {% endblock %}
    """)

@app.route('/signup/student', methods=['GET','POST'])
def signup_student():
    if request.method == 'POST':
        sid = request.form['student_id'].strip()
        name = request.form['name'].strip()
        gender = request.form['gender']
        grade = request.form['grade']
        cls = request.form['class']
        if not (sid and name and grade):
            flash('Student ID, Name and Grade required')
            return redirect(url_for('signup_student'))
        db = get_db()
        try:
            db.execute('INSERT INTO students VALUES (?,?,?,?,?)',
                       (sid, name, gender, grade, cls))
            db.commit()
            flash('Student created, now sign in.')
            return redirect(url_for('login_choice'))
        except sqlite3.IntegrityError:
            flash('Student ID already exists')
    return render_template_string(base_html + """
    {% block content %}
      <div class="card">
        <form method="post">
          <label>Student ID</label><input name="student_id" required>
          <label>Name</label><input name="name" required>
          <label>Gender</label>
          <select name="gender"><option>Male</option><option>Female</option><option>Other</option></select>
          <label>Grade</label><input name="grade" required>
          <label>Class</label><input name="class">
          <button type="submit">Create</button>
        </form>
      </div>
    {% endblock %}
    """)

# --- Login ---
@app.route('/login')
def login_choice():
    return render_template_string(base_html + """
    {% block content %}
      <div class="card">
        <h3>Sign In</h3>
        <p><a href="{{ url_for('student_login') }}">Student</a></p>
        <p><a href="{{ url_for('teacher_login') }}">Teacher</a></p>
      </div>
    {% endblock %}
    """)

@app.route('/login/student', methods=['GET','POST'])
def student_login():
    if request.method == 'POST':
        sid = request.form['student_id'].strip()
        db = get_db()
        s = db.execute('SELECT * FROM students WHERE student_id=?', (sid,)).fetchone()
        if s:
            session.clear()
            session['student_id'] = sid
            flash('Signed in as ' + s['name'])
            return redirect(url_for('student_dashboard'))
        flash('Student ID not found')
    return render_template_string(base_html + """
    {% block content %}
      <div class="card">
        <form method="post">
          <label>Student ID</label><input name="student_id" required>
          <button type="submit">Sign In</button>
        </form>
      </div>
    {% endblock %}
    """)

@app.route('/login/teacher', methods=['GET','POST'])
def teacher_login():
    if request.method == 'POST':
        tid = request.form['teacher_id']
        key = request.form['passkey']
        db = get_db()
        t = db.execute('SELECT * FROM teachers WHERE id=?', (tid,)).fetchone()
        if t and check_password_hash(t['passhash'], key):
            session.clear()
            session['teacher_id'] = t['id']
            flash('Signed in as ' + t['name'])
            return redirect(url_for('teacher_dashboard'))
        flash('Invalid credentials')
    return render_template_string(base_html + """
    {% block content %}
      <div class="card">
        <form method="post">
          <label>Teacher ID</label><input name="teacher_id" required>
          <label>Passkey</label><input name="passkey" required>
          <button type="submit">Sign In</button>
        </form>
      </div>
    {% endblock %}
    """)

@app.route('/student/logout')
def student_logout():
    session.pop('student_id', None)
    flash('Logged out')
    return redirect(url_for('index'))

@app.route('/teacher/logout')
def teacher_logout():
    session.pop('teacher_id', None)
    flash('Logged out')
    return redirect(url_for('index'))

# ---------- Teacher Dashboard ----------
def require_teacher(f):
    from functools import wraps
    @wraps(f)
    def inner(*a, **kw):
        if not session.get('teacher_id'):
            flash('Teacher login required')
            return redirect(url_for('teacher_login'))
        return f(*a, **kw)
    return inner

@app.route('/teacher')
@require_teacher
def teacher_dashboard():
    db = get_db()
    groups = db.execute('SELECT grade, class, COUNT(*) AS cnt FROM students GROUP BY grade, class').fetchall()
    t = db.execute('SELECT name FROM teachers WHERE id=?', (session['teacher_id'],)).fetchone()
    return render_template_string(base_html + """
    {% block content %}
      <div class="card">
        <h3>Teacher Dashboard ({{ t.name }})</h3>
        <table>
          <tr><th>Grade</th><th>Class</th><th>Count</th><th></th></tr>
          {% for g in groups %}
            <tr>
              <td>{{ g.grade }}</td><td>{{ g.class }}</td><td>{{ g.cnt }}</td>
              <td><a href="{{ url_for('view_class', grade=g.grade, cls=g.class) }}">View</a></td>
            </tr>
          {% endfor %}
        </table>
        <p><a href="{{ url_for('add_question') }}">Add Question</a></p>
      </div>
    {% endblock %}
    """, groups=groups, t=t)

@app.route('/teacher/class/<grade>/<cls>')
@require_teacher
def view_class(grade, cls):
    db = get_db()
    students = db.execute('SELECT * FROM students WHERE grade=? AND class=?', (grade, cls)).fetchall()
    return render_template_string(base_html + """
    {% block content %}
      <div class="card">
        <h3>Students Grade {{ grade }} - Class {{ cls }}</h3>
        <table>
          <tr><th>ID</th><th>Name</th><th>Gender</th><th></th></tr>
          {% for s in students %}
            <tr>
              <td>{{ s.student_id }}</td>
              <td>{{ s.name }}</td>
              <td>{{ s.gender }}</td>
              <td><a href="{{ url_for('view_student', sid=s.student_id) }}">View</a></td>
            </tr>
          {% endfor %}
        </table>
      </div>
    {% endblock %}
    """, grade=grade, cls=cls, students=students)

@app.route('/teacher/student/<sid>')
@require_teacher
def view_student(sid):
    db = get_db()
    s = db.execute('SELECT * FROM students WHERE student_id=?', (sid,)).fetchone()
    attempts = db.execute('''
        SELECT a.selected,a.correct,q.question_text
        FROM attempts a JOIN questions q ON a.question_id=q.id
        WHERE a.student_id=?''', (sid,)).fetchall()
    return render_template_string(base_html + """
    {% block content %}
      <div class="card">
        <h3>{{ s.name }} ({{ s.student_id }})</h3>
        <p>Grade: {{ s.grade }} | Class: {{ s.class }} | Gender: {{ s.gender }}</p>
        <table>
          <tr><th>Question</th><th>Selected</th><th>Correct?</th></tr>
          {% for a in attempts %}
            <tr><td>{{ a.question_text }}</td><td>{{ a.selected }}</td>
                <td>{{ 'Yes' if a.correct else 'No' }}</td></tr>
          {% endfor %}
        </table>
      </div>
    {% endblock %}
    """, s=s, attempts=attempts)

@app.route('/teacher/add_question', methods=['GET','POST'])
@require_teacher
def add_question():
    if request.method == 'POST':
        db = get_db()
        db.execute('''
          INSERT INTO questions
          (question_text, option_a, option_b, option_c, option_d, correct, grade, class)
          VALUES (?,?,?,?,?,?,?,?)
        ''', (
            request.form['question_text'],
            request.form['option_a'], request.form['option_b'],
            request.form['option_c'], request.form['option_d'],
            request.form['correct'].upper(),
            request.form['grade'], request.form['class']
        ))
        db.commit()
        flash('Question added')
        return redirect(url_for('teacher_dashboard'))
    return render_template_string(base_html + """
    {% block content %}
      <div class="card">
        <form method="post">
          <label>Question</label><input name="question_text" required>
          <label>Option A</label><input name="option_a">
          <label>Option B</label><input name="option_b">
          <label>Option C</label><input name="option_c">
          <label>Option D</label><input name="option_d">
          <label>Correct (A/B/C/D)</label><input name="correct" required>
          <label>Grade</label><input name="grade">
          <label>Class</label><input name="class">
          <button type="submit">Add</button>
        </form>
      </div>
    {% endblock %}
    """)

# ---------- Student ----------
@app.route('/student')
def student_dashboard():
    if not session.get('student_id'):
        flash('Student login required')
        return redirect(url_for('student_login'))
    db = get_db()
    s = db.execute('SELECT * FROM students WHERE student_id=?',
                   (session['student_id'],)).fetchone()
    qs = db.execute('SELECT * FROM questions WHERE grade=? AND class=?',
                    (s['grade'], s['class'])).fetchall()
    return render_template_string(base_html + """
    {% block content %}
      <div class="card">
        <h3>Hello {{ s.name }}</h3>
        <p>Questions for Grade {{ s.grade }} Class {{ s.class }}:</p>
        <ul>
        {% for q in qs %}
          <li><a href="{{ url_for('attempt_question', qid=q.id) }}">{{ q.question_text }}</a></li>
        {% endfor %}
        </ul>
      </div>
    {% endblock %}
    """, s=s, qs=qs)

@app.route('/student/attempt/<int:qid>', methods=['GET','POST'])
def attempt_question(qid):
    if not session.get('student_id'):
        flash('Student login required')
        return redirect(url_for('student_login'))
    db = get_db()
    q = db.execute('SELECT * FROM questions WHERE id=?', (qid,)).fetchone()
    if request.method == 'POST':
        ans = request.form['answer']
        correct = int(ans.upper() == q['correct'].upper())
        db.execute('INSERT INTO attempts (student_id, question_id, selected, correct) VALUES (?,?,?,?)',
                   (session['student_id'], qid, ans.upper(), correct))
        db.commit()
        flash('Answer submitted')
        return redirect(url_for('student_dashboard'))
    return render_template_string(base_html + """
    {% block content %}
      <div class="card">
        <h3>{{ q.question_text }}</h3>
        <form method="post">
          {% for opt in ['a','b','c','d'] %}
            {% if q['option_' + opt] %}
              <label><input type="radio" name="answer" value="{{ opt|upper }}" required>
                {{ q['option_' + opt] }}</label><br>
            {% endif %}
          {% endfor %}
          <button type="submit">Submit</button>
        </form>
      </div>
    {% endblock %}
    """, q=q)
@app.route("/ping")
def ping():
    return "pong"


if __name__ == '__main__':
    app.run(debug=False)
