import asyncio
import os
import threading
import time
from datetime import datetime
import cv2
import numpy as np
from insightface.app import FaceAnalysis
from telegram import Bot
from telegram.error import BadRequest, Forbidden, InvalidToken, NetworkError, TelegramError, TimedOut
from telegram.request import HTTPXRequest

from config import BOT_TOKEN, DEFAULT_CHAT_ID
from database import get_teacher_chat_id, has_attendance_today, init_db, load_all_students, log_attendance

for proxy_name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(proxy_name, None)

TOKEN = BOT_TOKEN
SCREENSHOTS_DIR = "screenshots"
UNKNOWN_NAME = "unknown"
RECOGNITION_WIDTH = 320
RECOGNITION_INTERVAL_SECONDS = 1.0
CAMERA_READ_SLEEP_SECONDS = 0.005
REQUIRE_LIVENESS_FOR_NOTIFICATION = False
LIVENESS_MIN_OBSERVATIONS = 8
LIVENESS_WINDOW_SECONDS = 10.0
LIVENESS_TURN_THRESHOLD = 0.16
LIVENESS_MIN_TOTAL_YAW_CHANGE = 0.32
LIVENESS_MAX_CENTER_MOVEMENT = 60.0
EMPTY_CHAT_IDS = {"", "None", "Катталган эмес"}
EMPTY_CHAT_IDS.update({"РљР°С‚С‚Р°Р»РіР°РЅ СЌРјРµСЃ"})
CAMERAS = [
    {"index": 0, "window": "Laptop Camera - keldi", "status": "keldi"},
    {"index": 1, "window": "Web Camera - ketti", "status": "ketti"},
]

telegram_request = HTTPXRequest(
    connect_timeout=20,
    read_timeout=30,
    write_timeout=30,
    pool_timeout=10,
)
bot = Bot(token=TOKEN, request=telegram_request)

# --- ИЗМЕНЕНИЕ ДЛЯ СВЕРХБЫСТРОЙ РАБОТЫ ---
# Отключаем поиск пятиточечных масок (landmark_2d_106) и определение пола/возраста (genderage), 
# оставляем только детекцию лиц (det) и извлечение векторов (rec).
app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"], providers=["CPUExecutionProvider"])
# Фиксируем размер картинки (det_size). Больше модель не будет тратить время на масштабирование кадров.
app.prepare(ctx_id=0, det_size=(320, 320))
# ----------------------------------------


class CameraStream:
    def __init__(self, index):
        self.index = index
        self.cap = open_camera(index)
        self.lock = threading.Lock()
        self.frame = None
        self.ret = False
        self.running = False
        self.thread = None

    def start(self):
        if not self.cap.isOpened():
            return False

        self.running = True
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()
        return True

    def _reader(self):
        while self.running:
            ret, frame = self.cap.read()
            with self.lock:
                self.ret = ret
                if ret:
                    self.frame = frame
            if not ret:
                print(f"Camera {self.index} frame not received")
                time.sleep(0.2)
            else:
                time.sleep(CAMERA_READ_SLEEP_SECONDS)

    def read(self):
        with self.lock:
            if not self.ret or self.frame is None:
                return False, None
            return True, self.frame.copy()

    def release(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        self.cap.release()


def is_valid_chat_id(chat_id):
    chat_id = str(chat_id).strip() if chat_id else ""
    return chat_id.lstrip("-").isdigit()

async def send_telegram_alert(chat_id, name, status, photo_path):
    now = datetime.now().strftime("%H:%M")
    text = f"{name} {status}\nTime: {now}"
    chat_id = str(chat_id).strip() if chat_id else ""
    if chat_id in EMPTY_CHAT_IDS or not is_valid_chat_id(chat_id):
        chat_id = DEFAULT_CHAT_ID

    try:
        if photo_path and os.path.exists(photo_path):
            with open(photo_path, "rb") as photo:
                await bot.send_photo(chat_id=chat_id, photo=photo, caption=text)
        else:
            await bot.send_message(chat_id=chat_id, text=text)
        print(f"Telegram sent to {chat_id}: {text}")
        return True
    except InvalidToken:
        print("Telegram error: bot token is invalid. Create a new token in BotFather.")
    except Forbidden:
        print(f"Telegram error for {chat_id}: user did not press /start or blocked the bot.")
    except BadRequest as e:
        print(f"Telegram bad request for {chat_id}: {e}. Check DEFAULT_CHAT_ID or press /start in the bot.")
    except TimedOut:
        print("Telegram error: request timed out. Check internet/VPN access to api.telegram.org.")
    except NetworkError as e:
        print(f"Telegram network error: {e}. Check internet/VPN/proxy/firewall.")
    except TelegramError as e:
        print(f"Telegram API error for {chat_id}: {e}")
    except Exception as e:
        print(f"Unexpected Telegram error for {chat_id}: {type(e).__name__}: {e}")
    return False


def resolve_chat_id(parent_chat_id, class_name):
    parent_chat_id = str(parent_chat_id).strip() if parent_chat_id else ""
    if parent_chat_id not in EMPTY_CHAT_IDS and is_valid_chat_id(parent_chat_id):
        return parent_chat_id

    teacher_chat_id = get_teacher_chat_id(class_name)
    if is_valid_chat_id(teacher_chat_id):
        return teacher_chat_id

    return DEFAULT_CHAT_ID


def prepare_known_faces():
    names, chat_ids, embeddings, classes = load_all_students()
    if not embeddings:
        return names, chat_ids, np.empty((0, 512), dtype=np.float32), classes

    embeddings = np.asarray(embeddings, dtype=np.float32)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings = embeddings / np.maximum(norms, 1e-6)
    return names, chat_ids, embeddings, classes


def recognize(embedding, known_embeddings, known_names, known_chat_ids, threshold=0.4):
    if len(known_embeddings) == 0:
        return UNKNOWN_NAME, None

    # Оптимизация: убрано лишнее приведение типов, так как embedding уже float32 от InsightFace
    norm = np.linalg.norm(embedding)
    embedding = embedding / (norm if norm > 1e-6 else 1e-6)
    
    scores = known_embeddings @ embedding
    best_idx = int(np.argmax(scores))

    if scores[best_idx] >= threshold:
        return known_names[best_idx], known_chat_ids[best_idx]
    return UNKNOWN_NAME, None


def detect_people(frame, known_embeddings, known_names, known_chat_ids, scale_x, scale_y):
    faces = app.get(frame)
    people = []

    for face in faces:
        name, chat_id = recognize(face.embedding, known_embeddings, known_names, known_chat_ids)
        x1, y1, x2, y2 = face.bbox.astype(int)
        box = (
            int(x1 * scale_x),
            int(y1 * scale_y),
            int(x2 * scale_x),
            int(y2 * scale_y),
        )
        kps = None
        if hasattr(face, "kps") and face.kps is not None:
            kps = face.kps.astype(np.float32).copy()
            kps[:, 0] *= scale_x
            kps[:, 1] *= scale_y
        people.append((name, chat_id, box, kps))

    return people   


def resize_for_recognition(frame):
    height, width = frame.shape[:2]
    if width <= RECOGNITION_WIDTH:
        return frame, 1.0, 1.0

    scale = RECOGNITION_WIDTH / width
    resized = cv2.resize(frame, (RECOGNITION_WIDTH, int(height * scale)))
    return resized, width / resized.shape[1], height / resized.shape[0]


def clamp_box(box, frame_shape):
    height, width = frame_shape[:2]
    x1, y1, x2, y2 = box
    return (
        max(0, min(width - 1, x1)),
        max(0, min(height - 1, y1)),
        max(0, min(width - 1, x2)),
        max(0, min(height - 1, y2)),
    )


def expand_box(box, frame_shape, scale=0.7):
    x1, y1, x2, y2 = box
    width = x2 - x1
    height = y2 - y1
    pad_x = int(width * scale)
    pad_y = int(height * scale)
    return clamp_box((x1 - pad_x, y1 - pad_y, x2 + pad_x, y2 + pad_y), frame_shape)


def face_crop_quality_ok(frame, box):
    x1, y1, x2, y2 = clamp_box(box, frame.shape)
    if x2 <= x1 or y2 <= y1:
        return False

    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return False

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return 35 <= brightness <= 235 and contrast >= 18 and sharpness >= 12


def likely_screen_spoof(frame, box):
    x1, y1, x2, y2 = box
    face_area = max(1, (x2 - x1) * (y2 - y1))
    regions = []
    ex1, ey1, ex2, ey2 = expand_box(box, frame.shape, scale=1.0)
    regions.append((frame[ey1:ey2, ex1:ex2], ex1, ey1))
    regions.append((frame, 0, 0))

    for region, offset_x, offset_y in regions:
        if region.size == 0:
            continue

        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(gray, 60, 160)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        face_center_x = ((x1 + x2) / 2) - offset_x
        face_center_y = ((y1 + y2) / 2) - offset_y

        for contour in contours:
            perimeter = cv2.arcLength(contour, True)
            if perimeter < 120:
                continue

            approx = cv2.approxPolyDP(contour, 0.04 * perimeter, True)
            if len(approx) != 4 or not cv2.isContourConvex(approx):
                continue

            rx, ry, rw, rh = cv2.boundingRect(approx)
            rectangle_area = rw * rh
            aspect = rw / max(1, rh)
            contains_face_center = rx <= face_center_x <= rx + rw and ry <= face_center_y <= ry + rh

            if contains_face_center and 0.35 <= aspect <= 2.9 and rectangle_area > face_area * 1.5:
                return True

    return False


def estimate_head_yaw(kps):
    if kps is None or len(kps) < 5:
        return None

    left_eye, right_eye, nose, left_mouth, right_mouth = kps[:5]
    eye_center = (left_eye + right_eye) / 2.0
    mouth_center = (left_mouth + right_mouth) / 2.0
    face_center_x = (eye_center[0] + mouth_center[0]) / 2.0
    eye_distance = float(np.linalg.norm(right_eye - left_eye))
    if eye_distance < 1.0:
        return None

    return float((nose[0] - face_center_x) / eye_distance)


def update_liveness_state(states, name, box, kps, now_ts):
    state = states.setdefault(name, [])
    x1, y1, x2, y2 = box
    center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
    yaw = estimate_head_yaw(kps)
    state.append((now_ts, center, yaw))
    states[name] = [item for item in state if now_ts - item[0] <= LIVENESS_WINDOW_SECONDS]
    return states[name]


def liveness_passed(observations):
    if len(observations) < LIVENESS_MIN_OBSERVATIONS:
        return False

    centers = np.asarray([item[1] for item in observations], dtype=np.float32)
    yaws = [item[2] for item in observations if item[2] is not None]
    if len(yaws) < LIVENESS_MIN_OBSERVATIONS:
        return False

    center_movement = float(np.max(np.linalg.norm(centers - centers[0], axis=1)))
    if center_movement > LIVENESS_MAX_CENTER_MOVEMENT:
        return False

    baseline = float(np.median(yaws[:3]))
    left_turns = sum(1 for yaw in yaws if yaw <= baseline - LIVENESS_TURN_THRESHOLD)
    right_turns = sum(1 for yaw in yaws if yaw >= baseline + LIVENESS_TURN_THRESHOLD)
    total_yaw_change = float(max(yaws) - min(yaws))

    return (
        left_turns >= 2
        and right_turns >= 2
        and total_yaw_change >= LIVENESS_MIN_TOTAL_YAW_CHANGE
    )


def anti_spoof_passed(frame, box, kps, camera, name, now_ts):
    if not face_crop_quality_ok(frame, box):
        print(f"{name} blocked by anti-spoof: low quality/flat face crop")
        return False

    if likely_screen_spoof(frame, box):
        print(f"{name} blocked by anti-spoof: possible phone/screen rectangle")
        camera["liveness_states"].pop(name, None)
        return False

    if not REQUIRE_LIVENESS_FOR_NOTIFICATION:
        return True

    observations = update_liveness_state(camera["liveness_states"], name, box, kps, now_ts)
    if not liveness_passed(observations):
        yaws = [item[2] for item in observations if item[2] is not None]
        yaw_change = max(yaws) - min(yaws) if yaws else 0.0
        print(
            f"{name} waiting for real-person check: "
            f"{len(observations)}/{LIVENESS_MIN_OBSERVATIONS}, yaw_change={yaw_change:.2f}. "
            "Turn head left and right."
        )
        return False

    return True


def create_tracker():
    if hasattr(cv2, "TrackerKCF_create"):
        return cv2.TrackerKCF_create()
    if hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerKCF_create"):
        return cv2.legacy.TrackerKCF_create()
    return None


def box_to_tracker_rect(box):
    x1, y1, x2, y2 = box
    return x1, y1, max(1, x2 - x1), max(1, y2 - y1)


def tracker_rect_to_box(rect):
    x, y, width, height = [int(v) for v in rect]
    return x, y, x + width, y + height


def open_camera(index):
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


async def notify_once_per_day(frame, name, chat_id, class_name, status, sent_notifications, pending_notifications=None):
    today = datetime.now().strftime("%Y-%m-%d")
    notification_key = (today, name, status)

    if notification_key in sent_notifications or (
        pending_notifications is not None and notification_key in pending_notifications
    ) or has_attendance_today(name, status):
        sent_notifications.add(notification_key)
        print(f"{name} {status} already sent today")
        return

    if pending_notifications is not None:
        pending_notifications.add(notification_key)

    alert_chat_id = resolve_chat_id(chat_id, class_name)
    now = datetime.now()
    photo_path = os.path.join(SCREENSHOTS_DIR, f"{name}_{status}_{now.strftime('%H%M%S')}.jpg")
    cv2.imwrite(photo_path, frame)

    try:
        if await send_telegram_alert(alert_chat_id, name, status, photo_path):
            log_attendance(name, class_name, status)
            sent_notifications.add(notification_key)
            print(f"{name} {status} notification sent")
        else:
            print(f"{name} {status} notification failed")
    finally:
        if pending_notifications is not None:
            pending_notifications.discard(notification_key)


def open_configured_cameras():
    cameras = []
    for config in CAMERAS:
        stream = CameraStream(config["index"])
        if stream.start():
            cameras.append(
                {
                    **config,
                    "stream": stream,
                    "last_recognition": 0.0,
                    "recognition_task": None,
                    "people": [],
                    "liveness_states": {},
                }
            )
            print(f"Camera {config['index']} started: {config['window']} -> {config['status']}")
        else:
            stream.release()
            print(f"Camera {config['index']} not opened: {config['window']}")
    return cameras


async def recognize_frame_async(frame, known_embeddings, known_names, known_chat_ids, recognition_lock):
    small_frame, scale_x, scale_y = resize_for_recognition(frame)
    async with recognition_lock:
        return await asyncio.to_thread(
            detect_people,
            small_frame,
            known_embeddings,
            known_names,
            known_chat_ids,
            scale_x,
            scale_y,
        )


async def recognize_camera_frame_async(frame, known_embeddings, known_names, known_chat_ids, recognition_lock, recognition_ts):
    people = await recognize_frame_async(frame, known_embeddings, known_names, known_chat_ids, recognition_lock)
    return frame, people, recognition_ts


async def main_loop():
    init_db()
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    known_names, known_chat_ids, known_embeddings, known_classes = prepare_known_faces()
    name_to_class = dict(zip(known_names, known_classes))

    cameras = open_configured_cameras()
    if not cameras:
        print("No cameras opened")
        return

    print(f"Loaded students: {len(known_names)}")
    sent_notifications = set()
    pending_notifications = set()
    notification_tasks = set()
    recognition_lock = asyncio.Lock()

    try:
        while True:
            now_ts = datetime.now().timestamp()
            active_cameras = 0

            for task in list(notification_tasks):
                if task.done():
                    notification_tasks.discard(task)
                    try:
                        task.result()
                    except Exception as e:
                        print(f"Notification task error: {type(e).__name__}: {e}")

            for camera in cameras:
                ret, frame = camera["stream"].read()
                if not ret:
                    continue

                active_cameras += 1
                recognition_task = camera.get("recognition_task")
                if recognition_task is not None and recognition_task.done():
                    try:
                        recognition_frame, people, recognition_ts = recognition_task.result()
                        camera["people"] = people

                        for name, chat_id, box, kps in people:
                            if name == UNKNOWN_NAME:
                                continue

                            if not anti_spoof_passed(recognition_frame, box, kps, camera, name, recognition_ts):
                                continue

                            class_name = name_to_class.get(name, "")
                            task = asyncio.create_task(
                                notify_once_per_day(
                                    recognition_frame,
                                    name,
                                    chat_id,
                                    class_name,
                                    camera["status"],
                                    sent_notifications,
                                    pending_notifications,
                                )
                            )
                            notification_tasks.add(task)
                    except Exception as e:
                        print(f"Recognition task error for camera {camera['index']}: {type(e).__name__}: {e}")
                    finally:
                        camera["recognition_task"] = None

                should_recognize = (
                    camera.get("recognition_task") is None
                    and now_ts - camera["last_recognition"] >= RECOGNITION_INTERVAL_SECONDS
                )
                if should_recognize:
                    recognition_frame = frame.copy()
                    recognition_ts = now_ts
                    camera["recognition_task"] = asyncio.create_task(
                        recognize_camera_frame_async(
                            recognition_frame,
                            known_embeddings,
                            known_names,
                            known_chat_ids,
                            recognition_lock,
                            recognition_ts,
                        )
                    )
                    camera["last_recognition"] = now_ts

                for name, _, box, _ in camera["people"]:
                    x1, y1, x2, y2 = box
                    is_unknown = name == UNKNOWN_NAME
                    color = (0, 0, 255) if is_unknown else (0, 255, 0)
                    label = "not in database" if is_unknown else f"{name} {camera['status']}"
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(frame, label, (x1, max(y1 - 8, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                cv2.putText(
                    frame,
                    "Known: green | Not in database: red",
                    (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 255),
                    2,
                )
                cv2.imshow(camera["window"], frame)

            if active_cameras == 0:
                await asyncio.sleep(0.1)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
                continue

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

            await asyncio.sleep(0)
    finally:
        for camera in cameras:
            recognition_task = camera.get("recognition_task")
            if recognition_task is not None and not recognition_task.done():
                recognition_task.cancel()
            camera["stream"].release()
        for task in notification_tasks:
            task.cancel()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    asyncio.run(main_loop())
