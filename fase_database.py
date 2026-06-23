import os

import cv2
from insightface.app import FaceAnalysis

from database import init_db, save_student
from settings import FACE_DIR


def import_photos_to_database(face_db_path=FACE_DIR, default_class="4_a"):
    init_db()

    app = FaceAnalysis(providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))

    count = 0
    print(f"Loading photos from {face_db_path} into school.db...")

    for root, _, files in os.walk(face_db_path):
        for filename in files:
            if not filename.lower().endswith((".jpg", ".jpeg", ".png")):
                continue

            name = os.path.splitext(filename)[0].strip().replace(" ", "_")
            folder_name = os.path.basename(root)
            class_name = folder_name if folder_name != os.path.basename(face_db_path) else default_class
            photo_path = os.path.join(root, filename)
            img = cv2.imread(photo_path)

            if img is None:
                print(f"Skip {filename}: cannot read image")
                continue

            faces = app.get(img)
            if not faces:
                print(f"Skip {filename}: face not found")
                continue

            save_student(
                name=name,
                class_name=class_name,
                parent_code_input="",
                photo_path=photo_path.replace("\\", "/"),
                embedding=faces[0].embedding,
            )
            print(f"Added {name} ({class_name})")
            count += 1

    print(f"Done. Added {count} students.")
    return count


if __name__ == "__main__":
    import_photos_to_database()
