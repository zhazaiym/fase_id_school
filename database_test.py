import sqlite3


def test_database():
    try:
        conn = sqlite3.connect("school.db")
        cursor = conn.cursor()

        # Бардык окуучуларды көрөбүз
        cursor.execute("SELECT * FROM students")
        rows = cursor.fetchall()
        print("Базадагы окуучулар:", rows)

        # Класс боюнча издеп көрөбүз
        class_to_test = "10 b"  # Бул жерге өзүңүз кирип жаткан классты жазыңыз
        cursor.execute("SELECT name, chat_id FROM students WHERE class_name = ?", (class_to_test,))
        students = cursor.fetchall()
        print(f"'{class_to_test}' классындагы окуучулар:", students)

        conn.close()
    except Exception as e:
        print("Ката:", e)


test_database()