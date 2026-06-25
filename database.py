import sqlite3
import threading
from datetime import datetime

import numpy as np


DB_NAME = "school.db"
attendance_lock = threading.Lock()


def get_connection():
    return sqlite3.connect(DB_NAME)


def ensure_column(cursor, table, column, definition):
    cursor.execute(f"PRAGMA table_info({table})")
    columns = {row[1] for row in cursor.fetchall()}
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            name TEXT PRIMARY KEY,
            class_name TEXT,
            parent_id TEXT,
            photo_path TEXT,
            embedding BLOB,
            parent_name TEXT,
            parent_code TEXT,
            role TEXT DEFAULT 'student'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            class_name TEXT,
            status TEXT,
            timestamp TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS parents (
            code TEXT PRIMARY KEY,
            name TEXT,
            role TEXT DEFAULT 'parent'
        )
    """)

    ensure_column(cursor, "students", "parent_name", "TEXT")
    ensure_column(cursor, "students", "parent_code", "TEXT")
    ensure_column(cursor, "students", "role", "TEXT DEFAULT 'student'")

    conn.commit()
    conn.close()


def save_student(name, class_name, parent_code_input, photo_path, embedding, parent_name="", parent_code=""):
    parent_code = (parent_code or parent_code_input or "").strip()
    parent_name = (parent_name or "").strip()

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO students
            (name, class_name, parent_name, parent_code, role, photo_path, embedding)
        VALUES (?, ?, ?, ?, 'student', ?, ?)
    """, (
        name,
        class_name,
        parent_name,
        parent_code,
        photo_path,
        embedding.astype(np.float32).tobytes(),
    ))
    if parent_code:
        cur.execute("""
            INSERT OR REPLACE INTO parents (code, name, role)
            VALUES (?, ?, 'parent')
        """, (parent_code, parent_name))
    conn.commit()
    conn.close()


def load_all_students():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, parent_code, embedding, class_name FROM students ORDER BY class_name, name")
    rows = cursor.fetchall()
    conn.close()

    names, parent_codes, embeddings, classes = [], [], [], []
    for name, parent_code, embedding, class_name in rows:
        names.append(name)
        parent_codes.append(parent_code or "")
        embeddings.append(np.frombuffer(embedding, dtype=np.float32) if embedding else np.zeros(512, dtype=np.float32))
        classes.append(class_name or "")
    return names, parent_codes, embeddings, classes


def get_all_students_list():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT name, class_name, photo_path, parent_name, parent_code
        FROM students
        ORDER BY class_name, name
    """)
    data = cur.fetchall()
    conn.close()
    return data


def get_student_by_name(name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT name, class_name, photo_path, parent_name, parent_code, embedding
        FROM students
        WHERE name = ?
    """, (name,))
    data = cur.fetchone()
    conn.close()
    return data


def update_student(old_name, name, class_name, parent_name, parent_code, photo_path=None, embedding=None):
    conn = get_connection()
    cur = conn.cursor()

    if old_name != name:
        cur.execute("SELECT 1 FROM students WHERE name = ?", (name,))
        if cur.fetchone() is not None:
            conn.close()
            return False

    fields = [
        "name = ?",
        "class_name = ?",
        "parent_name = ?",
        "parent_code = ?",
    ]
    values = [name, class_name, parent_name, parent_code]

    if photo_path is not None and embedding is not None:
        fields.extend(["photo_path = ?", "embedding = ?"])
        values.extend([photo_path, embedding.astype(np.float32).tobytes()])

    values.append(old_name)
    cur.execute(f"""
        UPDATE students
        SET {", ".join(fields)}
        WHERE name = ?
    """, values)
    changed = cur.rowcount > 0

    cur.execute("""
        UPDATE attendance
        SET name = ?, class_name = ?
        WHERE name = ?
    """, (name, class_name, old_name))

    if parent_code:
        cur.execute("""
            INSERT OR REPLACE INTO parents (code, name, role)
            VALUES (?, ?, 'parent')
        """, (parent_code, parent_name))

    conn.commit()
    conn.close()
    return changed


def get_students_by_class(class_name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT name, parent_code
        FROM students
        WHERE class_name = ?
        ORDER BY name
    """, (class_name.strip(),))
    data = cur.fetchall()
    conn.close()
    return data


def delete_student_by_name(name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM students WHERE name = ?", (name,))
    cur.execute("DELETE FROM attendance WHERE name = ?", (name,))
    conn.commit()
    conn.close()


def clear_attendance():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM attendance")
    cur.execute("DELETE FROM sqlite_sequence WHERE name = 'attendance'")
    conn.commit()
    conn.close()


def has_attendance_today(name, status):
    conn = get_connection()
    cur = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cur.execute("""
        SELECT id
        FROM attendance
        WHERE name = ? AND status = ? AND date(timestamp) = ?
        LIMIT 1
    """, (name, status, today))
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def is_status_change(row, last_status_by_name_and_day, name_index, status_index, timestamp_index):
    name = row[name_index]
    status = row[status_index]
    day = str(row[timestamp_index] or "")[:10]
    key = (name, day)
    if last_status_by_name_and_day.get(key) == status:
        return False
    last_status_by_name_and_day[key] = status
    return True


def log_attendance(name, class_name, status="keldi"):
    if status not in {"keldi", "ketti"}:
        return False

    with attendance_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            today = datetime.now().strftime("%Y-%m-%d")
            cur.execute("""
                SELECT status
                FROM attendance
                WHERE name = ? AND date(timestamp) = ?
                ORDER BY timestamp DESC, id DESC
                LIMIT 1
            """, (name, today))
            row = cur.fetchone()
            last_status = row[0] if row else None

            if last_status == status or (last_status is None and status == "ketti"):
                conn.rollback()
                return False

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("""
                INSERT INTO attendance (name, class_name, status, timestamp)
                VALUES (?, ?, ?, ?)
            """, (name, class_name, status, timestamp))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def get_class_attendance(class_name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT name, status, strftime('%H:%M', timestamp), timestamp
        FROM attendance
        WHERE class_name = ?
        ORDER BY timestamp ASC, id ASC
    """, (class_name.strip(),))
    rows = cur.fetchall()
    conn.close()
    last_status = {}
    data = [row[:3] for row in rows if is_status_change(row, last_status, 0, 1, 3)]
    return list(reversed(data))


def get_recent_attendance(limit=50):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.name, a.class_name, a.status, a.timestamp, s.parent_name, s.parent_code
        FROM attendance a
        LEFT JOIN students s ON s.name = a.name
        ORDER BY a.timestamp ASC, a.id ASC
    """)
    rows = cur.fetchall()
    conn.close()
    last_status = {}
    data = [row for row in rows if is_status_change(row, last_status, 0, 2, 3)]
    return list(reversed(data))[:limit]


def get_parent_report(parent_code, parent_name=""):
    conn = get_connection()
    cur = conn.cursor()
    parent_code = (parent_code or "").strip()
    parent_name = (parent_name or "").strip()

    if not parent_code or not parent_name:
        conn.close()
        return []

    cur.execute("""
        SELECT s.name, s.class_name, a.status, a.timestamp
        FROM students s
        LEFT JOIN attendance a ON a.name = s.name
        WHERE s.parent_code = ? AND lower(trim(s.parent_name)) = lower(trim(?))
        ORDER BY s.name, a.timestamp ASC, a.id ASC
    """, (parent_code, parent_name))
    rows = cur.fetchall()
    conn.close()
    last_status = {}
    data = [
        row for row in rows
        if row[2] is None or is_status_change(row, last_status, 0, 2, 3)
    ]
    return sorted(data, key=lambda row: (row[0], row[3] or ""), reverse=True)
