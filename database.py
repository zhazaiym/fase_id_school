import sqlite3
from datetime import datetime

import cursor
import numpy as np
from flet.controls import page


DB_NAME = "school.db"


def init_db():
    conn = sqlite3.connect("school.db")  # Файл атын так жазыңыз
    cursor = conn.cursor()

    # Таблица бар-жогун текшерип, болбосо түзөт
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            name TEXT PRIMARY KEY,
            class_name TEXT,
            parent_id TEXT,
            photo_path TEXT,
            embedding BLOB,
            parent_chat_id TEXT
        )
    """)
    conn.commit()
    conn.close()
    print("✅ База текшерилди жана таблицалар түзүлдү.")


def load_all_students():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT name, parent_chat_id, embedding, class_name FROM students")
    rows = cursor.fetchall()
    conn.close()

    names, chat_ids, embeddings, classes = [], [], [], []
    for row in rows:
        names.append(row[0])
        chat_ids.append(row[1] if row[1] else "Катталган эмес")
        # embedding (BLOB) маалыматын туура иштетүү
        embeddings.append(np.frombuffer(row[2], dtype=np.float32) if row[2] else np.zeros(512))
        classes.append(row[3])

    # БУЛ СЕП ЭҢ МААНИЛҮҮ:
    return names, chat_ids, embeddings, classes

import sqlite3
from datetime import datetime


def log_attendance(name, class_name):
    conn = sqlite3.connect("school.db")
    cur = conn.cursor()

    # Бүгүнкү күндү алабыз (YYYY-MM-DD)
    today = datetime.now().strftime("%Y-%m-%d")

    # 1. Окуучу бүгүн "келди" деп катталганбы текшеребиз
    # Эгер базада ошол ат менен жана бүгүнкү күндө жазуу болсо, кайра жазбайбыз
    cur.execute("""
        SELECT id FROM attendance 
        WHERE name = ? AND status = 'келди' AND date(timestamp) = ? 
        LIMIT 1
    """, (name, today))

    already_exists = cur.fetchone()

    # 2. Эгер мурунтан катталган болсо, эч нерсе кылбайбыз
    if already_exists:
        conn.close()
        return False  # Бул жерде "катталган" деген белги

    # 3. Эгер жаңы болсо, базага жазабыз
    timestamp = datetime.now().strftime("%H:%M")
    cur.execute("INSERT INTO attendance (name, class_name, status, timestamp) VALUES (?, ?, ?, ?)",
                (name, class_name, 'келди', timestamp))

    conn.commit()
    conn.close()
    return True  # Бул жерде "жаңы катталды" деген белги

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
    # Келүү тарыхын алуу
    cur.execute("SELECT name, timestamp FROM attendance WHERE class_name = ? ORDER BY timestamp DESC", (class_name.strip(),))
    data = cur.fetchall()
    conn.close()
    return data

def save_student(name, class_name, parent_chat_id, photo_path, embedding):
    conn = sqlite3.connect("school.db")
    cur = conn.cursor()
    # Базада 5 мамыча бар экенин текшериңиз (name, class_name, parent_chat_id, photo_path, embedding)
    cur.execute("""
        INSERT OR REPLACE INTO students (name, class_name, parent_chat_id, photo_path, embedding) 
        VALUES (?, ?, ?, ?, ?)
    """, (name, class_name, parent_chat_id, photo_path, embedding.tobytes()))
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



