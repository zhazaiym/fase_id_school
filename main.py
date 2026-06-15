import cv2
import sqlite3
import time
import threading
from insightface.app import FaceAnalysis

# КОНФИГУРАЦИЯ
COOLDOWN_SECONDS = 300  # 5 мүнөт
THRESHOLD = 0.4

# Инициализация
app = FaceAnalysis(providers=['CPUExecutionProvider'])
app.prepare(ctx_id=0, det_size=(320, 320))

# Глобалдык өзгөрмөлөр
latest_frame = None
last_seen = {}


# Камераны өзүнчө Thread'де окуу (Зависаниени жок кылуунун сыры ушунда)
def camera_thread(cap):
    global latest_frame
    while True:
        ret, frame = cap.read()
        if ret:
            latest_frame = frame


# Базага жазуу функциясы
def log_attendance(name, class_name, status="keldi"):
    conn = sqlite3.connect("school.db")
    cur = conn.cursor()
    cur.execute("INSERT INTO attendance (name, class_name, status, timestamp) VALUES (?, ?, ?, ?)",
                (name, class_name, status, time.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()


def main():
    global latest_frame
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    # Камераны өзүнчө жипте иштетебиз
    threading.Thread(target=camera_thread, args=(cap,), daemon=True).start()

    print("🚀 Система иштеди...")

    while True:
        if latest_frame is None:
            continue

        frame = latest_frame.copy()  # Эң акыркы кадрды алабыз

        # Жүз таануу
        faces = app.get(frame)

        for face in faces:
            # Бул жерде сиздин мурунку таануу логикаңыз кала берет
            name = "Окуучу"  # Жерде таануу кодуңуз болушу керек
            class_name = "10_a"

            now = time.time()
            if name not in last_seen or (now - last_seen[name] > COOLDOWN_SECONDS):
                # Telegram же базага жөнөтүү тоскоолдук жаратпашы үчүн Thread колдонобуз
                threading.Thread(target=log_attendance, args=(name, class_name, "keldi")).start()
                last_seen[name] = now
                print(f"✅ {name} катталды!")

        cv2.imshow("School Camera", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()