import cv2
import numpy as np
from insightface.app import FaceAnalysis
import os
from datetime import datetime
from database import load_all_students, log_attendance
import asyncio
from telegram import Bot

# Боттун токени
TOKEN = "8819848632:AAEAigdVRaYAg9mcmSCi_kEA4MhyO-huLzw"
bot = Bot(token=TOKEN)

app = FaceAnalysis(providers=['CPUExecutionProvider'])
app.prepare(ctx_id=0, det_size=(640, 640))


async def send_telegram_alert(chat_id, name, status, photo_path):
    now = datetime.now().strftime("%H:%M")
    # Статуска жараша текст
    emoji = "✅" if status == "keldi" else "❌"
    action = "мектепке келди" if status == "keldi" else "мектептен кетти"

    caption_text = f"{emoji} {name} {action}!\n⏰ Убакыт: {now}"

    if chat_id and chat_id != "None" and chat_id != "Катталган эмес":
        try:
            if os.path.exists(photo_path):
                await bot.send_photo(chat_id=chat_id, photo=open(photo_path, 'rb'), caption=caption_text)
                print(f"DEBUG: Билдирүү жөнөтүлдү: {status}")
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


async def main_loop():
    cap = cv2.VideoCapture(0)
    print("🎥 Камера иштеди...")

    # Акыркы катталган убакытты сактоо (кайталанууну алдын алуу үчүн)
    last_recognition = {}

    while True:
        ret, frame = cap.read()
        if not ret: break

        faces = app.get(frame)
        known_names, known_chat_ids, known_embeddings, known_classes = load_all_students()

        for face in faces:
            name, chat_id = recognize(face.embedding, known_embeddings, known_names, known_chat_ids)

            if name != "Белгисиз":
                # Бир окуучу 1 мүнөт ичинде эки жолу катталбасын
                now = datetime.now()
                if name in last_recognition and (now - last_recognition[name]).seconds < 60:
                    continue

                last_recognition[name] = now

                # Классты аныктоо
                idx = known_names.index(name)
                class_name = known_classes[idx]

                # Статусту аныктоо (Келди/Кетти)
                # Бул жерде логиканы иштетүү үчүн database'деги log_attendance'ди колдонобуз
                # Эскертүү: log_attendance функцияңызды статусту автоматтык түрдө аныктагыдай кылып жаңыртыңыз
                status = "keldi"

                for face in faces:
                    name, chat_id = recognize(face.embedding, known_embeddings, known_names, known_chat_ids)

                    if name != "Белгисиз":
                        # 1. Бир окуучу 1 мүнөт ичинде эки жолу катталбасын (сиздин кодуңуз)
                        now = datetime.now()
                        if name in last_recognition and (now - last_recognition[name]).seconds < 60:
                            continue

                        # 2. Классты аныктоо
                        idx = known_names.index(name)
                        class_name = known_classes[idx]

                        # 3. Базага жазуу (Эми log_attendance бизге True же False кайтарат)
                        is_new = log_attendance(name, class_name)

                        # 4. Эгер бул жаңы каттоо болсо, гана Telegramга жөнөтөбүз
                        if is_new:
                            last_recognition[name] = now  # Убакытты белгилеп кой
                            photo_path = f"screenshots/{name}_{now.strftime('%H%M%S')}.jpg"
                            cv2.imwrite(photo_path, frame)

                            # Telegramга жөнөтүү
                            await send_telegram_alert(chat_id, name, "keldi", photo_path)
                            print(f"✅ {name} келди катары катталды.")
                        else:
                            print(f"ℹ️ {name} бүгүн мурунтан эле катталган.")

                            photo_path = f"screenshots/{name}_{now.strftime('%H%M%S')}.jpg"
                            cv2.imwrite(photo_path, frame)

                            # main.py 83-сап
                            log_attendance(name, class_name, status)
                            await send_telegram_alert(chat_id, name, status, photo_path)
                            print(f"✅ {name} {status} катары катталды.")

                        cv2.imshow("Мектеп Камерасы", frame)
                        if cv2.waitKey(1) & 0xFF == ord('q'): break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    asyncio.run(main_loop())