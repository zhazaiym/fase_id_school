import sqlite3
from datetime import datetime
import pickle

import cursor
import numpy as np
from flet.controls import page


DB_NAME = "school.db"


def init_db():
    conn = sqlite3.connect("school.db")
    cur = conn.cursor()

    # Төмөнкү саптарды өЧҮРҮП САЛЫҢЫЗ:
    # cur.execute("DROP TABLE IF EXISTS students")
    # cur.execute("DROP TABLE IF EXISTS attendance")

    # Эми таблицаларды ушундай түрдө калтырыңыз:
    cur.execute('''CREATE TABLE IF NOT EXISTS students (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT,
                        class_name TEXT,
                        photo_path TEXT,
                        parent_chat_id TEXT,
                        embedding BLOB
                    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS attendance (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT,
                        class_name TEXT,
                        status TEXT,
                        date TEXT,
                        timestamp TEXT
                    )''')
    conn.commit()
    conn.close()


def load_all_students():
    conn = sqlite3.connect("school.db")
    cur = conn.cursor()
    cur.execute("SELECT name, parent_chat_id, embedding, class_name FROM students")
    rows = cur.fetchall()

    names = []
    chat_ids = []
    embeddings = []
    classes = []

    for row in rows:
        names.append(row[0])
        chat_ids.append(row[1])
        # Байты кайра массивге айландырабыз
        embeddings.append(pickle.loads(row[2]))
        classes.append(row[3])

    conn.close()
    return names, chat_ids, embeddings, classes

import sqlite3
from datetime import datetime


import sqlite3
from datetime import datetime

def log_attendance(name, class_name, status):
    conn = sqlite3.connect("school.db")
    cur = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M")

    # 1. Окуучу бүгүн катталганбы?
    cur.execute("SELECT id, status FROM attendance WHERE name=? AND date=? ORDER BY id DESC LIMIT 1", (name, today))
    row = cur.fetchone()

    if row:
        # Эгер окуучу бүгүн "келди" деп катталган болсо жана азыр "ketti" статусун алса:
        if row[1] == "keldi" and status == "ketti":
            cur.execute("UPDATE attendance SET status=?, timestamp=? WHERE id=?", ("ketti", now_time, row[0]))
            conn.commit()
            conn.close()
            return True # Статус өзгөрдү -> Билдирүү жөнөтүлсүн
        else:
            # Эгер статус өзгөрбөсө (мисалы: кайра "келди" десе), эч нерсе кылба
            conn.close()
            return False
    else:
        # Эгер бул окуучунун бүгүнкү алгачкы жазуусу болсо
        if status == "keldi":
            cur.execute("INSERT INTO attendance (name, class_name, status, date, timestamp) VALUES (?, ?, ?, ?, ?)",
                        (name, class_name, "keldi", today, now_time))
            conn.commit()
            conn.close()
            return True # Жаңы "келди" жазуусу кошулду
        else:
            conn.close()
            return False

    conn.close()
    return False
def get_teacher_chat_id(class_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT teacher_chat_id FROM teachers WHERE class_name = ?", (class_name,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

import sqlite3

def get_students_by_class(class_name):
    conn = sqlite3.connect("school.db")
    cur = conn.cursor()
    # Класс атын так текшериңиз (мисалы, "10b" базада кандай жазылса, ошондой болушу керек)
    cur.execute("SELECT name, parent_chat_id FROM students WHERE class_name = ?", (class_name.strip(),))
    data = cur.fetchall()
    conn.close()
    return data


def get_class_attendance(class_name):
    conn = sqlite3.connect("school.db")
    cur = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")

    # Бүгүнкү күндөгү ошол класстын маалыматтарын алабыз
    cur.execute("SELECT name, timestamp, status FROM attendance WHERE class_name=? AND date=?", (class_name, today))
    data = cur.fetchall()
    conn.close()
    return data


import sqlite3
import pickle  # Бул китепкана массивдерди сактоо үчүн керек


def save_student(name, class_name, chat_id, photo_path, embedding):
    conn = sqlite3.connect("school.db")
    cur = conn.cursor()

    # Эмбеддингди сактоо үчүн аны байт форматына айландырабыз
    embedding_blob = pickle.dumps(embedding)

    cur.execute("""
        INSERT INTO students (name, class_name, parent_chat_id, photo_path, embedding) 
        VALUES (?, ?, ?, ?, ?)
    """, (name, class_name, chat_id, photo_path, embedding_blob))

    conn.commit()
    conn.close()

def get_all_students_list():
    conn = sqlite3.connect("school.db")
    cur = conn.cursor()
    # Эгер таблицада 4 мамыча болсо, ушундай жазыңыз:
    cur.execute("SELECT name, class_name, photo_path, parent_chat_id FROM students")
    data = cur.fetchall()
    conn.close()
    return data



def delete_student_by_name(name):
    # окуучуну өчүрүү коду
    conn = sqlite3.connect("school.db")
    cur = conn.cursor()
    cur.execute("DELETE FROM students WHERE name = ?", (name,))
    conn.commit()
    conn.close()



def update_db_schema():
    conn = sqlite3.connect("school.db")
    cur = conn.cursor()
    try:
        # parent_chat_id мамычасын кошуу
        cur.execute("ALTER TABLE students ADD COLUMN parent_chat_id TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        print("Колонка мурунтан эле бар экен.")
    conn.close()

def fix_database_schema():
    conn = sqlite3.connect("school.db")
    cur = conn.cursor()
    try:
        # parent_chat_id мамычасын кошуп көрөбүз
        cur.execute("ALTER TABLE students ADD COLUMN parent_chat_id TEXT")
        conn.commit()
        print("✅ parent_chat_id мамычасы ийгиликтүү кошулду.")
    except sqlite3.OperationalError:
        print("ℹ️ Мамыча мурунтан эле бар экен, эч нерсе кылуунун кажети жок.")
    conn.close()

# Эскертүү: Бул функцияны программанын эң башында бир эле жолу чакырыңыз

def add_student(e):
    # ... базага сактоо ...
    save_student(...)

    # Төмөнкү сап таблицаны кайра тартат:
    page.controls.clear()  # Же тизмеңизди тазалаңыз
    # ... бетти кайра түзүү ...
    page.update()


def generate_students_html():
    students = get_all_students_list()
    if not students:
        return ""  # Бош болсо эч нерсе кайтарбасын

    rows = ""
    for student in students:
        # student бул жерде кортеж: (name, class_name, photo_path, parent_id)
        name, class_name, photo_path, parent_id = student
        rows += f"""
        <tr>
            <td><img src="{photo_path}" width="50"></td>
            <td>{name}</td>
            <td>{class_name}</td>
            <td>{parent_id}</td>
            <td><a href="/delete/{name}">Өчүрүү</a></td>
        </tr>
        """
    return rows



