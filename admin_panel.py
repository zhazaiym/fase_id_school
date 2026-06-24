import os
import shutil
import socket
import cv2
import uvicorn
from fastapi import FastAPI, File, Form, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from camera_service import camera_frames, get_face_app, load_known_faces
from database import clear_attendance, delete_student_by_name, get_parent_report, init_db, save_student
from settings import CAMERA_INDEXES, FACE_DIR, SCREENSHOTS_DIR
from views import (
    esc,
    home_view,
    list_view,
    page,
    parent_login_view,
    parent_report_view,
    students_view,
)


init_db()
os.makedirs(FACE_DIR, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
os.makedirs("static", exist_ok=True)

app = FastAPI(title="School Face ID")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/face_database", StaticFiles(directory=FACE_DIR), name="face_database")
app.mount("/screenshots", StaticFiles(directory=SCREENSHOTS_DIR), name="screenshots")
app.mount("/static", StaticFiles(directory="static"), name="static")


def find_free_port(start_port=8000, attempts=20):
    for port in range(start_port, start_port + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port found for the web site")


def safe_filename(name):
    cleaned = "".join(ch for ch in name.strip().replace(" ", "_") if ch.isalnum() or ch in "_-")
    return cleaned or "student"


@app.get("/", response_class=HTMLResponse)
async def home():
    return page("School Face ID", home_view())


@app.get("/list", response_class=HTMLResponse)
async def list_page():
    return page("List / Общий отчет", list_view())


@app.post("/clear-attendance")
async def clear_attendance_log():
    clear_attendance()
    return RedirectResponse(url="/list", status_code=303)


@app.get("/students", response_class=HTMLResponse)
async def students_page():
    return page("Ученики", students_view())


@app.post("/add")
async def add_student(
    name: str = Form(...),
    class_name: str = Form(...),
    parent_name: str = Form(...),
    parent_code: str = Form(...),
    photo: UploadFile = File(...),
):
    safe_name = safe_filename(name)
    photo_path = os.path.join(FACE_DIR, f"{safe_name}.jpg")

    with open(photo_path, "wb") as file:
        shutil.copyfileobj(photo.file, file)

    img = cv2.imread(photo_path)
    faces = get_face_app().get(img) if img is not None else []
    if not faces:
        if os.path.exists(photo_path):
            os.remove(photo_path)
        return HTMLResponse(page("Ошибка", """
            <h1>Лицо не найдено</h1>
            <p>Загрузите фото, где лицо ученика видно ясно.</p>
            <a class="btn light" href="/students">Назад</a>
        """), status_code=400)

    save_student(
        safe_name,
        class_name.strip(),
        parent_code.strip(),
        photo_path.replace("\\", "/"),
        faces[0].embedding,
        parent_name=parent_name,
        parent_code=parent_code,
    )
    load_known_faces(force=True)
    return RedirectResponse(url="/students", status_code=303)


@app.get("/delete/{name}")
async def delete_student(name: str):
    delete_student_by_name(name)
    photo_path = os.path.join(FACE_DIR, f"{safe_filename(name)}.jpg")
    if os.path.exists(photo_path):
        os.remove(photo_path)
    load_known_faces(force=True)
    return RedirectResponse(url="/students", status_code=303)


@app.get("/camera", response_class=HTMLResponse)
async def camera_page():
    return page("Камера", f"""
        <div class="camera-page">
            <div class="camera-tile">
                <img class="camera" src="/camera_feed?status=keldi&camera_index={CAMERA_INDEXES['keldi']}" alt="Камера входа">
            </div>
            <div class="camera-tile">
                <img class="camera" src="/camera_feed?status=ketti&camera_index={CAMERA_INDEXES['ketti']}" alt="Камера выхода">
            </div>
        </div>
    """)


@app.get("/camera_feed")
async def camera_feed(status: str = Query("keldi"), camera_index: int = Query(None)):
    status = "ketti" if status == "ketti" else "keldi"
    allowed_index = CAMERA_INDEXES[status]
    if camera_index is None or camera_index != allowed_index:
        camera_index = allowed_index
    return StreamingResponse(
        camera_frames(status, camera_index),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/parent", response_class=HTMLResponse)
async def parent_page(name: str = Query(""), code: str = Query("")):
    if not name.strip() or not code.strip():
        return page("Кабинет родителя", parent_login_view(name, code))

    rows = []
    for student_name, class_name, status, timestamp in get_parent_report(code, name):
        status_text = "Отчета нет" if not status else ("Пришел" if status == "keldi" else "Ушел")
        rows.append(f"""
        <tr>
            <td>{esc(student_name)}</td>
            <td>{esc(class_name)}</td>
            <td>{esc(status_text)}</td>
            <td>{esc(timestamp or '')}</td>
        </tr>
        """)
    if not rows:
        rows.append("<tr><td colspan='4' class='muted'>По этому коду ученики не найдены</td></tr>")

    return page("Кабинет родителя", parent_report_view(rows))


@app.post("/api/login")
async def api_login(class_name: str = Form(...), password: str = Form(...)):
    if password.strip() == "1234":
        return {"status": "success", "class_name": class_name.strip()}
    return {"status": "error", "message": "Пароль туура эмес"}


@app.get("/api/attendance/{class_name}")
async def api_attendance(class_name: str):
    from database import get_class_attendance

    return [
        {"name": name, "event": status, "time": time_text}
        for name, status, time_text in get_class_attendance(class_name)
    ]


if __name__ == "__main__":
    init_db()
    port = find_free_port(8000)
    print(f"Open site: http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)
