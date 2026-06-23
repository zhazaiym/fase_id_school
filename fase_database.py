import cv2
import pickle
import os
import sqlite3
from insightface.app import FaceAnalysis
from database import init_db, save_student

# Базаны текшерип, түзүп алабыз
init_db()

app = FaceAnalysis(providers=['CPUExecutionProvider'])
app.prepare(ctx_id=0, det_size=(640, 640))

FACE_DB_PATH = "face_database/"
count = 0

print("🔄 Папкадагы сүрөттөрдү маалымат базасына (`school.db`) жүктөө башталды...")

# Папканы толук кыдыруу
for root, dirs, files in os.walk(FACE_DB_PATH):
    for filename in files:
        if filename.endswith(('.jpg', '.png', '.jpeg')):
            # Окуучунун атын сүрөттүн өзүнөн алабыз
            name = os.path.splitext(filename)[0].strip().replace(" ", "_")

            # Класстын атын папканын атынан алабыз.
            # Эгер түз эле face_database ичинде болсо, "Белгисиз класс" деп жазат
            folder_name = os.path.basename(root)
            class_name = folder_name if folder_name != "face_database" else "4_a"  # Демейки класс

            photo_path = os.path.join(root, filename)
            img = cv2.imread(photo_path)

            if img is None:
                print(f"❌ {filename} окулбады")
                continue

            faces = app.get(img)
            if len(faces) > 0:
                # database.py файлындагы функция аркылуу түз эле SQLite базага сактайбыз
                save_student(
                    name=name,
                    class_name=class_name,
                    parent_code_input="Катталган эмес",
                    photo_path=photo_path,
                    embedding=faces[0].embedding
                )
                print(f"✅ {name} ({class_name}-класс) базага ийгиликтүү кошулду.")
                count += 1
            else:
                print(f"⚠️ {filename} — сүрөттөн жүз табылган жок!")

print(f"\n🎉 Бүттү! Жалпысынан {count} окуучу `school.db` базасына киргизилди.")
