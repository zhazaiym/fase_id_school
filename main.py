import cv2
import numpy as np
from insightface.app import FaceAnalysis
import os
from datetime import datetime
from database import load_all_students, log_attendance, init_db
import asyncio
from telegram import Bot

# Боттун токени
TOKEN = "8819848632:AAEAigdVRaYAg9mcmSCi_kEA4MhyO-huLzw"
bot = Bot(token=TOKEN)

app = FaceAnalysis(providers=['CPUExecutionProvider'])
app.prepare(ctx_id=0, det_size=(640, 640))


async def send_telegram_alert(chat_id, name, status, photo_path):
    now = datetime.now().strftime("%H:%M")
    emoji = "✅" if status == "keldi" else "❌"
    action = "мектепке келди" if status == "keldi" else "мектептен кетти"
    caption_text = f"{emoji} {name} {action}!\n⏰ Убакыт: {now}"

    if chat_id and chat_id != "None" and chat_id != "Катталган эмес":
        try:
            if os.path.exists(photo_path):
                await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption=caption_text)
        except Exception as e:
            print(f"❌ Билдирүү жөнөтүүдө ката: {e}")


def recognize(embedding, known_embeddings, known_names, known_chat_ids, threshold=0.4):
    best_name, best_score, best_chat = "Белгисиз", 0.0, None
    for i, emb in enumerate(known_embeddings):
        score = np.dot(embedding, emb) / (np.linalg.norm(embedding) * np.linalg.norm(emb))
        if score > best_score and score > threshold:
            best_score = score
            best_name = known_names[i]
            best_chat = known_chat_ids[i]
    return best_name, best_chat


async def process_frame(frame, status, last_recognition):
    faces = app.get(frame)
    known_names, known_chat_ids, known_embeddings, known_classes = load_all_students()

    for face in faces:
        # 1. Алгач жүздү тааныйбыз
        name, chat_id = recognize(face.embedding, known_embeddings, known_names, known_chat_ids)

        if name == "Белгисиз":
            print("⚠️ Жүз таанылган жок.")
            continue  # "Белгисиз" болсо ары жагын аттап кетет

        print(f"✅ {name} таанылды!")

        # 2. Убакытты текшеребиз (1 мүнөт эрежеси)
        now = datetime.now()
        if name in last_recognition and (now - last_recognition[name]).seconds < 60:
            continue

        # 3. Индексти табабыз
        idx = known_names.index(name)
        class_name = known_classes[idx]

        # 4. Базага жазабыз
        is_new = log_attendance(name, class_name, status)

        # 5. Эгер бул жаңы статус болсо, Telegramга сүрөт жөнөтөбүз
        if is_new:
            last_recognition[name] = now
            photo_path = f"screenshots/{name}_{status}_{now.strftime('%H%M%S')}.jpg"
            cv2.imwrite(photo_path, frame)

            await send_telegram_alert(chat_id, name, status, photo_path)
            print(f"✅ {name} {status} катары катталды.")


async def main_loop():
    cap1 = cv2.VideoCapture(0)
    cap2 = cv2.VideoCapture(1)
    print("🎥 Камералар иштеди...")

    last_recognition = {}

    while True:
        ret1, frame1 = cap1.read()
        ret2, frame2 = cap2.read()

        if ret1:
            await process_frame(frame1, "keldi", last_recognition)
            cv2.imshow("Camera 1 (Keldi)", frame1)

        if ret2:
            await process_frame(frame2, "ketti", last_recognition)
            cv2.imshow("Camera 2 (Ketti)", frame2)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap1.release()
    cap2.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    init_db()  # Базаны башынан түзүү
    asyncio.run(main_loop())