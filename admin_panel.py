import os
import cv2
import shutil
import uvicorn
from database import init_db

# Программа ишке кирээри менен таблицаларды түзөт
init_db()
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from insightface.app import FaceAnalysis
from database import init_db, save_student, get_all_students_list, delete_student_by_name, get_class_attendance

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

face_app = FaceAnalysis(providers=['CPUExecutionProvider'])
face_app.prepare(ctx_id=0, det_size=(640, 640))

os.makedirs("face_database", exist_ok=True)
app.mount("/face_database", StaticFiles(directory="face_database"), name="face_database")


# admin_panel.py ичиндеги generate_students_html функциясын ушундай кылып өзгөртүңүз:
def generate_students_html():
    students = get_all_students_list()  # Базадан (name, class_name, photo_path, parent_chat_id) келиши керек
    rows = ""
    for student in students:
        # Эгер базадан 3 эле нерсе келип жатса, бул жерди оңдоңуз
        # Сиздин database.py функцияңыз эмнени SELECT кылып жатканы маанилүү
        name, class_name, photo_path, parent_id = student

        rows += f"""
        <tr>
            <td><img src="{photo_path}" width="50"></td>
            <td>{name}</td>
            <td>{class_name}</td>
            <td>{parent_id}</td>
            <td><a href="/delete/{name}" style="color:red;">Өчүрүү</a></td>
        </tr>
        """
    return rows


# Бул функцияны өчүрүү маршруту катары кошуңуз
@app.get("/delete/{name}")
async def delete_student(name: str):
    # database.py ичиндеги функцияны чакырабыз
    delete_student_by_name(name)

    # Сүрөт файлын да өчүрүп койгон туура (милдеттүү эмес, бирок жакшы)
    photo_path = f"face_database/{name}.jpg"
    if os.path.exists(photo_path):
        os.remove(photo_path)

    # Өчүрүлгөндөн кийин башкы бетке кайтарабыз
    return RedirectResponse(url="/", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def home():
    students_table = generate_students_html()
    return f"""
    <html>
    <head><meta charset="UTF-8"><title>Мектеп Администрациясы</title></head>
    <body style="font-family: Arial; max-width: 800px; margin: 30px auto; padding: 20px;">
        <div style="border: 1px solid #ccc; border-radius: 10px; padding: 20px; max-width: 400px; margin: 0 auto 30px auto;">
            <h2>🏫 Жаңы окуучу каттоо</h2>
            <form action="/add" method="post" enctype="multipart/form-data">
                <input name="name" placeholder="Окуучунун аты" style="width:100%; padding:8px; margin:10px 0;" required><br>
                <input name="class_name" placeholder="Классы (Мисалы: 11 m)" style="width:100%; padding:8px; margin:10px 0;" required><br>
                <input type="file" name="photo" accept="image/*" style="margin:10px 0;" required><br><br>
                <button type="submit" style="width:100%; padding:10px; background:#28a745; color:white; border:none; border-radius:5px; cursor:pointer;">✅ Базага кошуу</button>
            </form>
        </div>
        <hr style="border: 0; border-top: 2px solid #eee; margin: 40px 0;">
        <h2>👥 Катталган бардык окуучулар тизмеси</h2>
        <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
            <thead style="background: #f2f2f2;">
                <tr><th>Сүрөтү</th><th>Аты-жөнү</th><th>Классы</th><th>Ата-эне ID</th><th>Аракет</th></tr>
            </thead>
            <tbody>{students_table if students_table else "<tr><td colspan='5' style='text-align:center;'>Тизме бош</td></tr>"}</tbody>
        </table>
    </body>
    </html>
    """


@app.post("/add")
async def add_student(
        name: str = Form(...),
        class_name: str = Form(...),
        photo: UploadFile = File(...)
):
    # 1. Окуучунун атын файл аты үчүн тазалайбыз
    safe_name = name.strip().replace(" ", "_")
    photo_path = f"face_database/{safe_name}.jpg"

    # 2. Сүрөттү сактайбыз
    with open(photo_path, "wb") as f:
        shutil.copyfileobj(photo.file, f)

    # 3. Жүздү таануу
    img = cv2.imread(photo_path)
    faces = face_app.get(img)

    if len(faces) == 0:
        # Эгер жүз табылбаса, сүрөттү өчүрүп ката көрсөтөбүз
        if os.path.exists(photo_path):
            os.remove(photo_path)
        return HTMLResponse("<h3>❌ Жүз таанылган жок! Сураныч, жүзүңүз даана көрүнгөн сүрөт жүктөңүз.</h3>")

    # 4. ӨЗ ID'ңизди ушул жерге жазыңыз
    MY_ID = "1639133042"

    # 5. Базага сактоо
    # Эскертүү: save_student функциясы database.py'де 5 аргумент кабыл алышы керек!
    save_student(safe_name, class_name.strip(), MY_ID, photo_path, faces[0].embedding)

    # 6. Бетти жаңыртуу үчүн башкы бетке кайтарабыз
    return RedirectResponse(url="/", status_code=303)


# --- 🔐 МУГАЛИМДЕР ҮЧҮН API ТАРМАКТАРЫ ---

@app.post("/api/login")
async def api_login(class_name: str = Form(...), password: str = Form(...)):
    # Каалаган класс "1234" паролу менен кире алат
    if password.strip() == "1234":
        return {"status": "success", "class_name": class_name.strip()}
    return {"status": "error", "message": "Пароль туура эмес!"}


@app.get("/api/attendance/{class_name}")
async def api_attendance(class_name: str):
    # Базадан маалыматты алуу
    logs = get_class_attendance(class_name.strip())

    # Эгер логдор бош болсо, анда дароо бош тизме кайтарабыз
    if not logs:
        return []

    formatted_logs = []
    for name, status, time in logs:
        # row: (name, event, time) экендигин базадан текшериңиз
        formatted_logs.append({
            "name": name,
            "event": status,
            "time": time
        })
    return formatted_logs

if __name__ == "__main__":
    init_db()
    uvicorn.run(app, host="127.0.0.1", port=8000)
