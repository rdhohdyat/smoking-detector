# pyrefly: ignore [missing-import]
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
# pyrefly: ignore [missing-import]
from fastapi.responses import HTMLResponse, JSONResponse
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
# pyrefly: ignore [missing-import]
from ultralytics import YOLO
# pyrefly: ignore [missing-import]
import cv2
# pyrefly: ignore [missing-import]
import numpy as np
import base64
import asyncio
import json
import urllib.request
import urllib.parse
from datetime import datetime
import time
import uuid
import threading

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
async def read_welcome():
    with open("welcome.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/index.html", response_class=HTMLResponse)
async def read_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

model = YOLO("best.pt")

BOT_TOKEN = "8852368840:AAH6KUjJDOfVD-eh_t7GjER8RtAu6GkHaf8"

ALERT_COOLDOWN = 10

link_store: dict[str, str | None] = {}

_polling_offset = 0

def _get_bot_username() -> str:
    """Ambil username bot dari Telegram API"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if data.get("ok"):
            return data["result"].get("username", "")
    except Exception as e:
        print(f"[Bot] Gagal ambil info bot: {e}")
    return ""

def _send_text_sync(chat_id: str, text: str):
    """Kirim pesan teks biasa ke Telegram"""
    try:
        params = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }).encode()
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        req = urllib.request.Request(url, data=params)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as e:
        print(f"[Bot] Gagal kirim pesan: {e}")

def _poll_telegram_loop():
    """Loop polling update Telegram (berjalan di background thread)"""
    global _polling_offset
    print("[Bot] Memulai polling Telegram...")
    while True:
        if not BOT_TOKEN or BOT_TOKEN == "GANTI_DENGAN_TOKEN_BOT_ANDA":
            time.sleep(5)
            continue
        try:
            url = (
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
                f"?offset={_polling_offset}&timeout=25&allowed_updates=[\"message\"]"
            )
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = json.loads(resp.read().decode())

            if not data.get("ok"):
                time.sleep(5)
                continue

            for update in data.get("result", []):
                _polling_offset = update["update_id"] + 1
                message = update.get("message", {})
                text = message.get("text", "")
                chat_id = str(message.get("chat", {}).get("id", ""))
                first_name = message.get("from", {}).get("first_name", "Pengguna")

                if not chat_id:
                    continue

                # Tangani perintah /start dengan kode link
                if text.startswith("/start"):
                    parts = text.strip().split(maxsplit=1)
                    code = parts[1].strip() if len(parts) > 1 else ""

                    if code and code in link_store:
                        # Hubungkan kode ini ke chat_id user
                        link_store[code] = chat_id
                        print(f"[Bot] Kode {code} berhasil dihubungkan ke chat_id {chat_id}")
                        _send_text_sync(
                            chat_id,
                            f"✅ *Halo, {first_name}!*\n\n"
                            f"Akun Telegram Anda berhasil dihubungkan ke sistem *Deteksi Merokok*.\n\n"
                            f"🔔 Anda akan menerima notifikasi otomatis beserta foto bukti setiap kali aktivitas merokok terdeteksi.\n\n"
                            f"_Silakan kembali ke halaman web untuk memulai deteksi._"
                        )
                    else:
                        # Tidak ada kode / kode tidak dikenal
                        _send_text_sync(
                            chat_id,
                            f"👋 *Halo, {first_name}!*\n\n"
                            f"Ini adalah bot notifikasi *Deteksi Merokok*.\n\n"
                            f"Untuk menghubungkan akun Anda, silakan buka halaman web deteksi dan klik tombol *Hubungkan Telegram*."
                        )
        except Exception as e:
            print(f"[Bot] Error polling: {e}")
            time.sleep(5)

_polling_thread = threading.Thread(target=_poll_telegram_loop, daemon=True)
_polling_thread.start()

@app.get("/api/generate-link")
async def generate_link():
    """Buat kode unik dan link Telegram untuk user baru"""
    if not BOT_TOKEN or BOT_TOKEN == "GANTI_DENGAN_TOKEN_BOT_ANDA":
        return JSONResponse(
            status_code=503,
            content={"error": "Bot token belum dikonfigurasi. Hubungi administrator."}
        )

    code = uuid.uuid4().hex[:8].upper()
    link_store[code] = None  # Belum terhubung

    bot_username = await asyncio.to_thread(_get_bot_username)
    if not bot_username:
        return JSONResponse(
            status_code=503,
            content={"error": "Gagal mengambil info bot. Periksa token bot Anda."}
        )

    deep_link = f"https://t.me/{bot_username}?start={code}"
    print(f"[API] Link dihasilkan: code={code}, link={deep_link}")
    return {"code": code, "link": deep_link, "bot_username": bot_username}


@app.get("/api/check-link/{code}")
async def check_link(code: str):
    """Cek apakah kode sudah dihubungkan ke chat_id Telegram"""
    if code not in link_store:
        return {"linked": False, "chat_id": None}
    chat_id = link_store[code]
    return {"linked": chat_id is not None, "chat_id": chat_id}

def send_telegram_photo_sync(chat_id: str, text: str, photo_bytes: bytes):
    """Kirim foto beserta caption ke Telegram menggunakan BOT_TOKEN server"""
    boundary = "----BotBoundary7MA4YWxkTrZu"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

    parts = []
    parts.append(f"--{boundary}")
    parts.append('Content-Disposition: form-data; name="chat_id"')
    parts.append('')
    parts.append(str(chat_id))

    parts.append(f"--{boundary}")
    parts.append('Content-Disposition: form-data; name="caption"')
    parts.append('')
    parts.append(text)

    parts.append(f"--{boundary}")
    parts.append('Content-Disposition: form-data; name="parse_mode"')
    parts.append('')
    parts.append("Markdown")

    parts.append(f"--{boundary}")
    parts.append('Content-Disposition: form-data; name="photo"; filename="detection.jpg"')
    parts.append('Content-Type: image/jpeg')
    parts.append('')

    header_body = "\r\n".join(parts).encode("utf-8") + b"\r\n"
    footer_body = f"\r\n--{boundary}--\r\n".encode("utf-8")
    payload = header_body + photo_bytes + footer_body

    req = urllib.request.Request(url, data=payload)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode("utf-8")
    except Exception as e:
        print(f"[Alert] Error kirim foto Telegram: {e}")
        return None

async def send_telegram_alert(chat_id: str, text: str, photo_bytes: bytes):
    """Kirim alert foto secara asinkronus"""
    if not chat_id:
        return
    await asyncio.to_thread(send_telegram_photo_sync, chat_id, text, photo_bytes)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("[WS] Koneksi diterima.")

    # Cooldown per-koneksi
    last_alert_time = 0

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)

            img_data = payload.get("image")
            detection_active = payload.get("active", False)
            # Kode link yang dikirim frontend untuk lookup chat_id
            link_code = payload.get("link_code", "")

            if not img_data:
                continue

            # Cari chat_id dari link_store berdasarkan kode
            chat_id = link_store.get(link_code) if link_code else None

            # Decode gambar
            try:
                header, encoded = img_data.split(",", 1)
                img_bytes = base64.b64decode(encoded)
                nparr = np.frombuffer(img_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            except Exception as e:
                print(f"[WS] Error decode gambar: {e}")
                continue

            if frame is None:
                continue

            # YOLO inference
            results = model(frame)

            detected_label = "no_detection"
            confidence = 0.0

            for r in results:
                for box in r.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])
                    label = model.names[cls_id]

                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(
                        frame, f"{label} {conf:.2f}", (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2
                    )

                    if label.lower() == "smoking":
                        detected_label = "smoking"
                        confidence = conf

                        if detection_active and confidence > 0.8 and chat_id:
                            current_time = time.time()
                            if current_time - last_alert_time > ALERT_COOLDOWN:
                                _, alert_buf = cv2.imencode('.jpg', frame)
                                photo_bytes = alert_buf.tobytes()
                                time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                conf_pct = round(confidence * 100)
                                message = (
                                    f"🚨 *DETEKSI MEROKOK* 🚨\n\n"
                                    f"⚠️ *Status*: Terdeteksi Orang Merokok\n"
                                    f"📈 *Confidence*: {conf_pct}%\n"
                                    f"📅 *Waktu*: {time_str}\n\n"
                                    f"Foto bukti terlampir di atas!"
                                )
                                asyncio.create_task(
                                    send_telegram_alert(chat_id, message, photo_bytes)
                                )
                                last_alert_time = current_time

            _, buffer = cv2.imencode('.jpg', frame)
            img_base64 = base64.b64encode(buffer).decode("utf-8")

            response_payload = {
                "type": "detection",
                "label": detected_label,
                "confidence": round(confidence * 100),
                "image": f"data:image/jpeg;base64,{img_base64}"
            }

            await websocket.send_text(json.dumps(response_payload))

    except WebSocketDisconnect:
        print("[WS] Client disconnected")
    except Exception as e:
        print(f"[WS] Error: {e}")
