import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import cv2
import numpy as np
from insightface.app import FaceAnalysis

from database import load_all_students, log_attendance
from settings import (
    CAMERA_FPS,
    CAMERA_READ_SLEEP_SECONDS,
    JPEG_QUALITY,
    RECOGNITION_INTERVAL_SECONDS,
    RECOGNITION_WIDTH,
    SCREENSHOTS_DIR,
    UNKNOWN_NAME,
)


camera_lock = threading.Lock()
face_lock = threading.Lock()
face_inference_lock = threading.Lock()
cameras = {}
face_app = None
recognition_executor = ThreadPoolExecutor(max_workers=2)
TRACK_MAX_AGE_SECONDS = 2.0
TRACK_MAX_MISSES = 6
KNOWN_FACE_COLOR = (0, 220, 0)
UNKNOWN_FACE_COLOR = (0, 0, 255)
display_face_detector = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)
known_cache = {
    "loaded_at": 0.0,
    "names": [],
    "parent_codes": [],
    "embeddings": np.empty((0, 512), dtype=np.float32),
    "classes": [],
}


class CameraStream:
    def __init__(self, index):
        self.index = index
        self.cap = self._open_camera(index)
        self.lock = threading.Lock()
        self.frame = None
        self.ok = False
        self.running = False
        self.thread = None
        self.failed_reads = 0

    def _open_camera(self, index):
        camera = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        camera.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return camera

    def start(self):
        if not self.cap.isOpened():
            return False
        self.running = True
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()
        return True

    def _reader(self):
        while self.running:
            try:
                ok, frame = self.cap.read()
            except Exception:
                ok, frame = False, None

            with self.lock:
                self.ok = ok
                if ok:
                    self.frame = frame
                    self.failed_reads = 0
                else:
                    self.failed_reads += 1

            if not ok and self.failed_reads >= 10:
                self._reopen()

            time.sleep(CAMERA_READ_SLEEP_SECONDS if ok else 0.1)

    def _reopen(self):
        try:
            self.cap.release()
        except Exception:
            pass
        time.sleep(0.2)
        self.cap = self._open_camera(self.index)
        with self.lock:
            self.failed_reads = 0

    def read(self):
        with self.lock:
            if not self.ok or self.frame is None:
                return False, None
            return True, self.frame.copy()

    def release(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        self.cap.release()


def get_face_app():
    global face_app
    if face_app is not None:
        return face_app

    with face_lock:
        if face_app is None:
            face_app = FaceAnalysis(
                name="buffalo_l",
                allowed_modules=["detection", "recognition"],
                providers=["CPUExecutionProvider"],
            )
            face_app.prepare(ctx_id=0, det_size=(640, 640))
    return face_app


def normalize_embedding(embedding):
    embedding = np.asarray(embedding, dtype=np.float32)
    norm = np.linalg.norm(embedding)
    return embedding / max(norm, 1e-6)


def load_known_faces(force=False):
    now = time.time()
    if not force and now - known_cache["loaded_at"] < 5:
        return known_cache

    names, parent_codes, embeddings, classes = load_all_students()
    if embeddings:
        matrix = np.asarray(embeddings, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix = matrix / np.maximum(norms, 1e-6)
    else:
        matrix = np.empty((0, 512), dtype=np.float32)

    known_cache.update({
        "loaded_at": now,
        "names": names,
        "parent_codes": parent_codes,
        "embeddings": matrix,
        "classes": classes,
    })
    return known_cache


def recognize_face(embedding, known, threshold=0.45, margin=0.03):
    if len(known["embeddings"]) == 0:
        return UNKNOWN_NAME, "", ""

    scores = known["embeddings"] @ normalize_embedding(embedding)
    best_idx = int(np.argmax(scores))
    best_score = float(scores[best_idx])
    second_score = float(np.partition(scores, -2)[-2]) if len(scores) > 1 else -1.0
    if best_score >= threshold and (len(scores) == 1 or best_score - second_score >= margin):
        return known["names"][best_idx], known["parent_codes"][best_idx], known["classes"][best_idx]
    return UNKNOWN_NAME, "", ""


def resize_for_recognition(frame):
    height, width = frame.shape[:2]
    if width <= RECOGNITION_WIDTH:
        return frame, 1.0, 1.0
    scale = RECOGNITION_WIDTH / width
    resized = cv2.resize(frame, (RECOGNITION_WIDTH, int(height * scale)))
    return resized, width / resized.shape[1], height / resized.shape[0]


def enhance_low_light_frame(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if float(np.mean(gray)) >= 95:
        return frame

    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced_l = clahe.apply(l_channel)
    enhanced = cv2.merge((enhanced_l, a_channel, b_channel))
    enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
    return cv2.convertScaleAbs(enhanced, alpha=1.15, beta=12)


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


def get_camera_stream(index):
    with camera_lock:
        stream = cameras.get(index)
        if stream is not None and stream.running:
            return stream
        if stream is not None:
            stream.release()
            cameras.pop(index, None)

        stream = CameraStream(index)
        if stream.start():
            cameras[index] = stream
        else:
            stream.release()
        return stream


def create_fast_tracker():
    if hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerMOSSE_create"):
        return cv2.legacy.TrackerMOSSE_create()
    if hasattr(cv2, "TrackerMOSSE_create"):
        return cv2.TrackerMOSSE_create()
    if hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerKCF_create"):
        return cv2.legacy.TrackerKCF_create()
    if hasattr(cv2, "TrackerKCF_create"):
        return cv2.TrackerKCF_create()
    return None


def box_to_rect(box):
    x1, y1, x2, y2 = box
    return x1, y1, max(1, x2 - x1), max(1, y2 - y1)


def rect_to_box(rect):
    x, y, width, height = [int(v) for v in rect]
    return x, y, x + width, y + height


def build_tracks(frame, people):
    detected_at = time.time()
    tracks = []
    for name, class_name, box in people:
        track_box = expand_box(box, frame.shape, scale=0.25)
        tracker = create_fast_tracker()
        if tracker is not None:
            try:
                tracker.init(frame, box_to_rect(track_box))
            except Exception:
                tracker = None

        tracks.append({
            "name": name,
            "class_name": class_name,
            "box": track_box,
            "detected_at": detected_at,
            "tracker": tracker,
            "misses": 0,
        })
    return tracks


def update_tracks(frame, tracks, now):
    updated = []
    for track in tracks:
        if now - track.get("detected_at", 0.0) > TRACK_MAX_AGE_SECONDS:
            continue

        tracker = track.get("tracker")
        if tracker is not None:
            ok, rect = tracker.update(frame)
            if ok:
                track["box"] = clamp_box(rect_to_box(rect), frame.shape)
                track["misses"] = 0
            else:
                track["misses"] = track.get("misses", 0) + 1

        if track.get("misses", 0) <= TRACK_MAX_MISSES:
            updated.append(track)

    return updated


def detect_display_faces(frame):
    if display_face_detector.empty():
        return []

    height, width = frame.shape[:2]
    target_width = 360
    scale = min(1.0, target_width / max(1, width))
    small = cv2.resize(frame, (int(width * scale), int(height * scale))) if scale < 1.0 else frame
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    faces = display_face_detector.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(45, 45),
    )

    boxes = []
    inv_scale = 1.0 / scale
    for x, y, face_width, face_height in faces:
        box = (
            int(x * inv_scale),
            int(y * inv_scale),
            int((x + face_width) * inv_scale),
            int((y + face_height) * inv_scale),
        )
        boxes.append(expand_box(box, frame.shape, scale=0.15))
    return boxes


def draw_face_box(frame, box, color, label=""):
    x1, y1, x2, y2 = box
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

    label = (label or "").strip()
    if not label:
        return

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.6
    thickness = 2
    text_size, baseline = cv2.getTextSize(label, font, font_scale, thickness)
    text_width, text_height = text_size
    label_y1 = max(0, y1 - text_height - baseline - 8)
    label_y2 = max(text_height + baseline + 8, y1)
    label_x2 = min(frame.shape[1] - 1, x1 + text_width + 10)

    cv2.rectangle(frame, (x1, label_y1), (label_x2, label_y2), color, -1)
    cv2.putText(
        frame,
        label,
        (x1 + 5, label_y2 - baseline - 4),
        font,
        font_scale,
        (255, 255, 255),
        thickness,
        cv2.LINE_AA,
    )


def recognize_frame(frame, status):
    known = load_known_faces()
    small_frame, scale_x, scale_y = resize_for_recognition(frame)
    with face_inference_lock:
        faces = get_face_app().get(small_frame)
        if not faces:
            faces = get_face_app().get(enhance_low_light_frame(small_frame))
    people = []

    for face in faces:
        name, parent_code, class_name = recognize_face(face.embedding, known)
        x1, y1, x2, y2 = face.bbox.astype(int)
        box = (int(x1 * scale_x), int(y1 * scale_y), int(x2 * scale_x), int(y2 * scale_y))
        people.append((name, class_name, box))

        if name != UNKNOWN_NAME and log_attendance(name, class_name, status):
            photo_path = os.path.join(SCREENSHOTS_DIR, f"{name}_{status}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
            cv2.imwrite(photo_path, frame)

    return people


def camera_frames(status, camera_index):
    last_recognition = 0.0
    tracks = []
    recognition_task = None

    while True:
        stream = get_camera_stream(camera_index)
        ok, frame = stream.read()
        if not ok:
            error_frame = np.zeros((360, 640, 3), dtype=np.uint8)
            ok, buffer = cv2.imencode(".jpg", error_frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
            if ok:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
            time.sleep(0.5)
            continue

        now = time.time()
        if recognition_task is not None and recognition_task.done():
            try:
                people = recognition_task.result()
                tracks = build_tracks(frame, people)
            except Exception as exc:
                print(f"Recognition error: {type(exc).__name__}: {exc}")
            recognition_task = None

        if recognition_task is None and now - last_recognition >= RECOGNITION_INTERVAL_SECONDS:
            last_recognition = now
            recognition_task = recognition_executor.submit(recognize_frame, frame.copy(), status)

        tracks = update_tracks(frame, tracks, now)
        active_tracks = [track for track in tracks if track.get("misses", 0) == 0]
        if active_tracks:
            display_boxes = [
                (
                    track["box"],
                    UNKNOWN_FACE_COLOR if track.get("name") == UNKNOWN_NAME else KNOWN_FACE_COLOR,
                    "" if track.get("name") == UNKNOWN_NAME else track.get("name", ""),
                )
                for track in active_tracks
            ]
        else:
            display_boxes = [(box, UNKNOWN_FACE_COLOR, "") for box in detect_display_faces(frame)]

        for box, color, label in display_boxes:
            draw_face_box(frame, box, color, label)
        ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        if ok:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
        time.sleep(max(0.001, 1 / max(1, CAMERA_FPS)))
