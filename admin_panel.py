import os
import asyncio
import secrets
from pathlib import Path
import socket
from typing import Optional
import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from camera_service import LivenessState, camera_frames, get_face_app, load_known_faces, recognize_frame, \
    warm_up_face_models
from database import (
    clear_attendance,
    delete_student_by_name,
    get_all_students_list,
    get_class_attendance,
    get_parent_report,
    get_recent_attendance,
    get_student_by_name,
    init_db,
    save_student,
    update_student,
)
from settings import (
    ADMIN_TOKEN,
    ALLOWED_ORIGINS,
    APP_AUTO_PORT,
    APP_HOST,
    APP_PORT,
    CAMERA_INDEXES,
    FACE_DIR,
    MAX_UPLOAD_BYTES,
    PRODUCTION,
    SCREENSHOTS_DIR,
    TEACHER_PASSWORD,
)
from views import (
    edit_student_view,
    esc,
    home_view,
    list_view,
    page,
    parent_login_view,
    parent_report_view,
    role_picker_view,
    students_view,
    teacher_login_view,
)

init_db()
os.makedirs(FACE_DIR, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
os.makedirs("static", exist_ok=True)

# Random per-process session token. Issued to the browser as a cookie only
# after a correct TEACHER_PASSWORD is submitted at /teacher-login.
TEACHER_SESSION_TOKEN = secrets.token_hex(32)
TEACHER_COOKIE_NAME = "teacher_session"

app = FastAPI(title="School Face ID")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if PRODUCTION else ["*"],
    allow_credentials=PRODUCTION,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/face_database", StaticFiles(directory=FACE_DIR), name="face_database")
app.mount("/screenshots", StaticFiles(directory=SCREENSHOTS_DIR), name="screenshots")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=()")
    response.headers.setdefault("Cache-Control", "no-store" if request.url.path.startswith("/api/") else "private")
    supplied_admin_token = request.query_params.get("admin_token") or ""
    if ADMIN_TOKEN and secrets.compare_digest(supplied_admin_token, ADMIN_TOKEN):
        response.set_cookie(
            "admin_token",
            ADMIN_TOKEN,
            httponly=True,
            secure=PRODUCTION,
            samesite="strict",
            max_age=8 * 60 * 60,
        )
    return response


@app.on_event("startup")
async def startup_tasks():
    warm_up_face_models()


def find_free_port(start_port=8000, attempts=20):
    for port in range(start_port, start_port + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port found for the web site")


def get_lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def safe_filename(name):
    cleaned = "".join(ch for ch in name.strip().replace(" ", "_") if ch.isalnum() or ch in "_-")
    return cleaned or "student"


def require_admin(request: Request):
    if not ADMIN_TOKEN:
        return
    supplied = (
            request.headers.get("X-Admin-Token")
            or request.query_params.get("admin_token")
            or request.cookies.get("admin_token")
            or ""
    )
    if not secrets.compare_digest(supplied, ADMIN_TOKEN):
        raise HTTPException(status_code=403, detail="Admin access denied")


def is_teacher(request: Request):
    supplied = request.cookies.get(TEACHER_COOKIE_NAME) or ""
    return secrets.compare_digest(supplied, TEACHER_SESSION_TOKEN)


def require_teacher_page(request: Request):
    """For HTML pages: bounce unauthenticated visitors to the login screen."""
    if not is_teacher(request):
        return RedirectResponse(url="/teacher-login", status_code=303)
    return None


def require_teacher_action(request: Request):
    """For POST actions (add/edit/delete/clear): reject without a session."""
    if not is_teacher(request):
        raise HTTPException(status_code=403, detail="Teacher login required")


async def uploaded_image(upload: UploadFile):
    content_type = (upload.content_type or "").lower()
    if content_type and not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are allowed")

    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image is too large")

    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Cannot read image")
    return image


def save_student_photo(image, safe_name):
    photo_path = Path(FACE_DIR) / f"{safe_name}.jpg"
    if not cv2.imwrite(str(photo_path), image):
        raise HTTPException(status_code=500, detail="Cannot save student photo")
    return str(photo_path).replace("\\", "/")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    if is_teacher(request):
        return page("School Face ID", home_view())
    return page("School Face ID", role_picker_view())


@app.get("/teacher-login", response_class=HTMLResponse)
async def teacher_login_page(request: Request):
    if is_teacher(request):
        return RedirectResponse(url="/", status_code=303)
    return page("Мугалим кирүүсү", teacher_login_view())


@app.post("/teacher-login")
async def teacher_login(password: str = Form(...)):
    if not secrets.compare_digest(password.strip(), TEACHER_PASSWORD):
        return HTMLResponse(page("Мугалим кирүүсү", teacher_login_view(error=True)), status_code=401)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        TEACHER_COOKIE_NAME,
        TEACHER_SESSION_TOKEN,
        httponly=True,
        secure=PRODUCTION,
        samesite="strict",
        max_age=12 * 60 * 60,
    )
    return response


@app.get("/teacher-logout")
async def teacher_logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(TEACHER_COOKIE_NAME)
    return response


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/list", response_class=HTMLResponse)
async def list_page(request: Request):
    redirect = require_teacher_page(request)
    if redirect:
        return redirect
    return page("List / Общий отчет", list_view())


@app.post("/clear-attendance")
async def clear_attendance_log(request: Request):
    require_teacher_action(request)
    require_admin(request)
    clear_attendance()
    return RedirectResponse(url="/list", status_code=303)


@app.get("/students", response_class=HTMLResponse)
async def students_page(request: Request):
    redirect = require_teacher_page(request)
    if redirect:
        return redirect
    return page("Ученики", students_view())


@app.get("/edit/{name}", response_class=HTMLResponse)
async def edit_student_page(request: Request, name: str):
    redirect = require_teacher_page(request)
    if redirect:
        return redirect
    student = get_student_by_name(name)
    if student is None:
        return HTMLResponse(page("Ошибка", """
            <h1>Ученик не найден</h1>
            <a class="btn light" href="/students">Назад</a>
        """), status_code=404)
    return page("Изменить ученика", edit_student_view(student))


@app.post("/edit/{old_name}")
async def edit_student(
        request: Request,
        old_name: str,
        name: str = Form(...),
        class_name: str = Form(...),
        parent_name: str = Form(...),
        parent_code: str = Form(...),
        photo: Optional[UploadFile] = File(None),
):
    require_teacher_action(request)
    require_admin(request)
    student_name = name.strip()
    safe_name = safe_filename(student_name)
    class_name = class_name.strip()
    parent_name = parent_name.strip()
    parent_code = parent_code.strip()
    photo_path = None
    embedding = None

    old_student = get_student_by_name(old_name)
    if old_student is None:
        return HTMLResponse(page("Ошибка", """
            <h1>Ученик не найден</h1>
            <a class="btn light" href="/students">Назад</a>
        """), status_code=404)

    if photo is not None and photo.filename:
        img = await uploaded_image(photo)
        faces = get_face_app().get(img)
        if not faces:
            return HTMLResponse(page("Ошибка", """
                <h1>Лицо не найдено</h1>
                <p>Загрузите фото, где лицо ученика видно ясно.</p>
                <a class="btn light" href="/students">Назад</a>
            """), status_code=400)
        embedding = faces[0].embedding
        photo_path = save_student_photo(img, safe_name)

    if not update_student(old_name, student_name, class_name, parent_name, parent_code, photo_path, embedding):
        return HTMLResponse(page("Ошибка", """
            <h1>Не удалось сохранить</h1>
            <p>Возможно, ученик с таким именем уже есть.</p>
            <a class="btn light" href="/students">Назад</a>
        """), status_code=400)

    old_photo_path = old_student[2]
    if photo_path and old_photo_path and old_photo_path != photo_path and os.path.exists(old_photo_path):
        os.remove(old_photo_path)

    load_known_faces(force=True)
    return RedirectResponse(url="/students", status_code=303)


@app.post("/add")
async def add_student(
        request: Request,
        name: str = Form(...),
        class_name: str = Form(...),
        parent_name: str = Form(...),
        parent_code: str = Form(...),
        photo: UploadFile = File(...),
):
    require_teacher_action(request)
    require_admin(request)
    student_name = name.strip()
    safe_name = safe_filename(student_name)
    class_name = class_name.strip()
    parent_name = parent_name.strip()
    parent_code = parent_code.strip()
    img = await uploaded_image(photo)
    faces = get_face_app().get(img)
    if not faces:
        return HTMLResponse(page("Ошибка", """
            <h1>Лицо не найдено</h1>
            <p>Загрузите фото, где лицо ученика видно ясно.</p>
            <a class="btn light" href="/students">Назад</a>
        """), status_code=400)
    photo_path = save_student_photo(img, safe_name)

    save_student(
        student_name,
        class_name,
        parent_code,
        photo_path,
        faces[0].embedding,
        parent_name=parent_name,
        parent_code=parent_code,
    )
    load_known_faces(force=True)
    return RedirectResponse(url="/students", status_code=303)


@app.post("/delete/{name}")
async def delete_student(request: Request, name: str):
    require_teacher_action(request)
    require_admin(request)
    student = get_student_by_name(name)
    delete_student_by_name(name)
    photo_path = student[2] if student else os.path.join(FACE_DIR, f"{safe_filename(name)}.jpg")
    if os.path.exists(photo_path):
        os.remove(photo_path)
    load_known_faces(force=True)
    return RedirectResponse(url="/students", status_code=303)


@app.get("/camera", response_class=HTMLResponse)
async def camera_page(request: Request):
    redirect = require_teacher_page(request)
    if redirect:
        return redirect
    return page("Камера", """
<style>

html,body{
    margin:0;
    padding:0;
    width:100%;
    height:100%;
    overflow:hidden;
    background:#000;
}

main{
    margin:0 !important;
    padding:0 !important;
    max-width:none !important;
    width:100vw !important;
    height:100vh !important;
}

.camera-wrapper{

    position:fixed;

    left:0;
    top:0;

    width:100vw;
    height:100vh;

    display:grid;

    grid-template-columns:1fr 1fr;

    background:#000;

}

.camera-panel{

    position:relative;

    overflow:hidden;

    border-right:2px solid #1f2937;

}

.camera-panel:last-child{

    border-right:none;

}

.camera-panel img{

    width:100%;

    height:100%;

    object-fit:cover;

    display:block;

    background:#000;

}

.camera-title{

    position:absolute;

    left:20px;

    bottom:20px;

    color:#fff;

    padding:10px 18px;

    border-radius:50px;

    font-size:18px;

    font-weight:bold;

    z-index:20;

}

.green{

    background:#16a34a;

}

.red{

    background:#dc2626;

}

.camera-toolbar{

    position:fixed;

    left:20px;

    right:20px;

    top:20px;

    z-index:100;

    display:flex;

    gap:10px;

}

</style>


<div class="camera-toolbar">

    <a class="btn light" href="/">
        Назад
    </a>

    <button
        class="btn green"
        onclick="window.location.reload()">

        Камераны кайра жүктөө

    </button>

</div>


<div class="camera-wrapper">

    <div class="camera-panel">

        <img
            src="/camera_feed?status=keldi"
            id="cameraInStream"
        >

        <div class="camera-title green">

            Приход (Кирүү)

        </div>

    </div>


    <div class="camera-panel">

        <img
            src="/camera_feed?status=ketti"
            id="cameraOutStream"
        >

        <div class="camera-title red">

            Уход (Чыгуу)

        </div>

    </div>

</div>

""")


@app.get("/camera_feed")
async def camera_feed(request: Request, status: str = Query("keldi"), camera_index: int = Query(None)):
    require_teacher_action(request)
    status = "ketti" if status == "ketti" else "keldi"

    allowed_index = CAMERA_INDEXES[status]

    print(f"STATUS={status} CAMERA={allowed_index}")

    return StreamingResponse(
        camera_frames(status, allowed_index),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


browser_liveness_states = {
    "keldi": LivenessState(),
    "ketti": LivenessState(),
}


@app.post("/api/recognize-camera-frame")
async def recognize_camera_frame(status: str = Form("keldi"), frame: UploadFile = File(...)):
    status = "ketti" if status == "ketti" else "keldi"
    data = await frame.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Frame is too large")
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return {"people": []}

    people = await asyncio.to_thread(recognize_frame, image, status, browser_liveness_states[status])
    return {
        "people": [
            {
                "name": name,
                "class_name": class_name,
                "status": status,
                "status_text": "Пришел" if status == "keldi" else "Ушел",
            }
            for name, class_name, _ in people
            if name != "not_in_database"
        ]
    }


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
    if password.strip() == TEACHER_PASSWORD:
        return {"status": "success", "class_name": class_name.strip()}
    return {"status": "error", "message": "Неверный пароль"}


@app.get("/api/attendance/{class_name}")
async def api_attendance(class_name: str):
    return [
        {"name": name, "status": status, "status_text": "Пришел" if status == "keldi" else "Ушел", "time": time_text}
        for name, status, time_text in get_class_attendance(class_name)
    ]


@app.get("/api/health")
async def api_health():
    return {
        "status": "ok",
        "service": "school-face-id",
        "production": PRODUCTION,
        "camera_indexes": CAMERA_INDEXES,
        "students": len(get_all_students_list()),
        "recent_attendance": len(get_recent_attendance(500)),
        "max_upload_bytes": MAX_UPLOAD_BYTES,
    }


@app.get("/api/students")
async def api_students(class_name: str = Query("")):
    students = []
    for name, student_class, photo_path, parent_name, parent_code in get_all_students_list():
        if class_name.strip() and student_class != class_name.strip():
            continue
        students.append({
            "name": name,
            "class_name": student_class,
            "photo_path": photo_path,
            "parent_name": parent_name,
            "parent_code": parent_code,
        })
    return students


@app.get("/api/recent-attendance")
async def api_recent_attendance(limit: int = Query(50, ge=1, le=500)):
    return [
        {
            "name": name,
            "class_name": class_name,
            "status": status,
            "status_text": "Пришел" if status == "keldi" else "Ушел",
            "timestamp": timestamp,
            "parent_name": parent_name,
            "parent_code": parent_code,
        }
        for name, class_name, status, timestamp, parent_name, parent_code in get_recent_attendance(limit)
    ]


@app.get("/api/parent-report")
async def api_parent_report(name: str = Query(...), code: str = Query(...)):
    return [
        {
            "student_name": student_name,
            "class_name": class_name,
            "status": status,
            "status_text": "Отчета нет" if not status else ("Пришел" if status == "keldi" else "Ушел"),
            "timestamp": timestamp,
        }
        for student_name, class_name, status, timestamp in get_parent_report(code, name)
    ]


if __name__ == "__main__":
    init_db()
    port = find_free_port(APP_PORT) if APP_AUTO_PORT else APP_PORT
    lan_ip = get_lan_ip()
    print(f"Open on this computer: http://127.0.0.1:{port}")
    print(f"Open from phone on same Wi-Fi: http://{lan_ip}:{port}")

    # settings.py файлындагы APP_HOST ("0.0.0.0") колдонулду
    uvicorn.run(app, host=APP_HOST, port=port)