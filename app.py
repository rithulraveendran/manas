from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, make_response, get_flashed_messages
from datetime import datetime, timedelta
import random
import os
import smtplib
import requests
import json
import time
import uuid
from urllib.parse import urlencode, quote
from textblob import TextBlob
import firebase_admin
from firebase_admin import credentials, firestore, storage
from groq import Groq
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = "supersecretkey"
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config["PREFERRED_URL_SCHEME"] = "https"

GROQ_API_KEY = "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"
SENDER_EMAIL = "flightsofwhisper@gmail.com"
APP_PASSWORD = "shuy czpw xnsk rrre"

FIREBASE_KEY_PATHS = [
    os.path.join(os.path.dirname(__file__), "static", "firebase_key.json"),
    os.path.join(os.path.dirname(__file__), "firebase_key.json"),
]

if not firebase_admin._apps:
    firebase_key_path = next((p for p in FIREBASE_KEY_PATHS if os.path.exists(p)), None)
    if not firebase_key_path:
        raise FileNotFoundError(
            "Firebase key file not found. Expected at: " + " or ".join(FIREBASE_KEY_PATHS)
        )
    cred = credentials.Certificate(firebase_key_path)
    with open(firebase_key_path, "r", encoding="utf-8") as f:
        key_data = json.load(f)
    project_id = key_data.get("project_id", "").strip()
    storage_bucket = f"{project_id}.appspot.com" if project_id else ""
    firebase_admin.initialize_app(cred, {"storageBucket": storage_bucket} if storage_bucket else None)

db = firestore.client()
client = Groq(api_key=GROQ_API_KEY)

otp_storage = {}
GOOGLE_CLIENT_SECRETS_PATH = os.path.join(os.path.dirname(__file__), "static", "client_secrets.json")
GOOGLE_FIT_SCOPES = [
    "https://www.googleapis.com/auth/fitness.heart_rate.read",
    "https://www.googleapis.com/auth/fitness.sleep.read",
]
ALLOWED_DP_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_DP_FILE_SIZE_MB = 5
EMERGENCY_ALERT_EMAIL = "sos.manasemergency@gmail.com"


def _get_google_redirect_uri():
    # Prefer explicit env var so the value exactly matches Google Cloud OAuth config.
    configured = os.getenv("GOOGLE_REDIRECT_URI", "").strip()
    if configured:
        return configured
    # Behind ngrok/proxies Flask may infer http unless forwarded headers are trusted.
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.headers.get("X-Forwarded-Host", request.host)
    if host.endswith(".ngrok-free.dev"):
        scheme = "https"
    return f"{scheme}://{host}{url_for('google_callback')}"


def _load_google_client_config():
    try:
        with open(GOOGLE_CLIENT_SECRETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("web", {})
    except Exception as e:
        print("Google client config error:", e)
        return {}


def _refresh_google_access_token(refresh_token):
    config = _load_google_client_config()
    token_uri = config.get("token_uri")
    client_id = config.get("client_id")
    client_secret = config.get("client_secret")
    if not token_uri or not client_id or not client_secret:
        return None

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    try:
        token_resp = requests.post(token_uri, data=payload, timeout=15)
        token_resp.raise_for_status()
        token_data = token_resp.json()
        return {
            "access_token": token_data.get("access_token"),
            "refresh_token": refresh_token,
            "expires_at": int(time.time()) + int(token_data.get("expires_in", 3600)) - 60,
        }
    except Exception as e:
        print("Google refresh token error:", e)
        return None


def _get_google_access_token():
    token_data = session.get("google_fit_token")
    if not token_data:
        return None

    access_token = token_data.get("access_token")
    expires_at = token_data.get("expires_at", 0)
    refresh_token = token_data.get("refresh_token")
    if access_token and int(time.time()) < int(expires_at):
        return access_token

    if not refresh_token:
        return None

    refreshed = _refresh_google_access_token(refresh_token)
    if not refreshed or not refreshed.get("access_token"):
        session.pop("google_fit_token", None)
        return None

    session["google_fit_token"] = refreshed
    return refreshed["access_token"]


def _aggregate_google_fit(access_token, data_type_name, start_millis, end_millis, bucket_millis):
    url = "https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate"
    headers = {"Authorization": f"Bearer {access_token}"}
    payload = {
        "startTimeMillis": start_millis,
        "endTimeMillis": end_millis,
        "aggregateBy": [{"dataTypeName": data_type_name}],
        "bucketByTime": {"durationMillis": bucket_millis},
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=20)
        if res.status_code == 401:
            return {"error": "unauthorized"}
        if res.status_code == 403:
            return {"error": "forbidden", "details": res.text}
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"Google Fit aggregate error ({data_type_name}):", e)
        return {"error": "request_failed"}


def _extract_heart_rates(agg_payload):
    values = []
    for bucket in agg_payload.get("bucket", []):
        for dataset in bucket.get("dataset", []):
            for point in dataset.get("point", []):
                for value in point.get("value", []):
                    v = value.get("fpVal")
                    if v is None and "intVal" in value:
                        v = value.get("intVal")
                    if v is not None:
                        hr = round(float(v))
                        if 30 <= hr <= 220:
                            values.append(hr)
    return values


def _extract_sleep_hours(agg_payload):
    sleep_hours = []
    # Google Fit sleep segments: 2=sleep, 4=light, 5=deep, 6=REM.
    # (1 is awake and should not be counted as sleep.)
    sleep_segments = {2, 4, 5, 6}
    for bucket in agg_payload.get("bucket", []):
        total_ns = 0
        for dataset in bucket.get("dataset", []):
            for point in dataset.get("point", []):
                segment = None
                for value in point.get("value", []):
                    if "intVal" in value:
                        segment = int(value["intVal"])
                        break
                if segment in sleep_segments:
                    start_ns = int(point.get("startTimeNanos", "0"))
                    end_ns = int(point.get("endTimeNanos", "0"))
                    if end_ns > start_ns:
                        total_ns += end_ns - start_ns
        sleep_hours.append(round(total_ns / 3_600_000_000_000, 2))
    return sleep_hours


def _fetch_sleep_sessions_hours(access_token, day_starts):
    start_day = day_starts[0]
    end_day = day_starts[-1] + timedelta(days=1)
    url = "https://www.googleapis.com/fitness/v1/users/me/sessions"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "startTime": start_day.isoformat(timespec="seconds") + "Z",
        "endTime": end_day.isoformat(timespec="seconds") + "Z",
    }
    try:
        res = requests.get(url, headers=headers, params=params, timeout=20)
        if res.status_code in (401, 403):
            return None
        res.raise_for_status()
        sessions = res.json().get("session", [])

        day_ranges = []
        for day in day_starts:
            start_ms = int(day.timestamp() * 1000)
            end_ms = int((day + timedelta(days=1)).timestamp() * 1000)
            day_ranges.append((start_ms, end_ms))

        values = [0.0] * 7
        for sess in sessions:
            try:
                activity_type = int(sess.get("activityType", 0))
            except Exception:
                activity_type = 0
            # 72 is sleep in Google Fit activity types.
            if activity_type != 72:
                continue
            s_ms = int(sess.get("startTimeMillis", "0"))
            e_ms = int(sess.get("endTimeMillis", "0"))
            if e_ms <= s_ms:
                continue
            for idx, (d_start, d_end) in enumerate(day_ranges):
                overlap = max(0, min(e_ms, d_end) - max(s_ms, d_start))
                if overlap > 0:
                    values[idx] += overlap / 3_600_000
        return [round(v, 2) for v in values]
    except Exception as e:
        print("Google Fit sessions sleep fallback error:", e)
        return None


def _build_health_prompt_context():
    access_token = _get_google_access_token()
    if not access_token:
        return "Google Fit health context: not connected."

    try:
        now = datetime.utcnow()
        hr_start = now - timedelta(hours=24)
        hr_agg = _aggregate_google_fit(
            access_token,
            "com.google.heart_rate.bpm",
            int(hr_start.timestamp() * 1000),
            int(now.timestamp() * 1000),
            60 * 60 * 1000,
        )
        hr_values = _extract_heart_rates(hr_agg) if not hr_agg.get("error") else []

        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_day = today - timedelta(days=6)
        end_day = today + timedelta(days=1)
        sleep_agg = _aggregate_google_fit(
            access_token,
            "com.google.sleep.segment",
            int(start_day.timestamp() * 1000),
            int(end_day.timestamp() * 1000),
            24 * 60 * 60 * 1000,
        )
        sleep_values = _extract_sleep_hours(sleep_agg) if not sleep_agg.get("error") else []
        if len(sleep_values) < 7:
            sleep_values.extend([0] * (7 - len(sleep_values)))
        elif len(sleep_values) > 7:
            sleep_values = sleep_values[-7:]
        if sum(sleep_values) == 0:
            day_starts = [start_day + timedelta(days=i) for i in range(7)]
            fallback_values = _fetch_sleep_sessions_hours(access_token, day_starts)
            if fallback_values:
                sleep_values = fallback_values

        if hr_values:
            current_hr = hr_values[-1]
            avg_hr = round(sum(hr_values) / len(hr_values))
            min_hr = min(hr_values)
            max_hr = max(hr_values)
            hr_text = f"HR(24h): current={current_hr} bpm, avg={avg_hr}, min={min_hr}, max={max_hr}."
        else:
            hr_text = "HR(24h): no usable samples."

        if sleep_values:
            avg_sleep = round(sum(sleep_values) / len(sleep_values), 2)
            sleep_text = f"Sleep(7d hours): {sleep_values} | avg={avg_sleep}h."
        else:
            sleep_text = "Sleep(7d): no usable samples."

        return f"Google Fit health context: {hr_text} {sleep_text}"
    except Exception as e:
        print("Health prompt context error:", e)
        return "Google Fit health context: temporarily unavailable."


def _allowed_dp_file(filename):
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_DP_EXTENSIONS


def _validate_dp_file(file_obj):
    if not file_obj or file_obj.filename == "":
        return "Please select an image file."
    if not _allowed_dp_file(file_obj.filename):
        return "Invalid image type. Upload PNG, JPG, JPEG, or WEBP."
    try:
        file_obj.stream.seek(0, os.SEEK_END)
        size = file_obj.stream.tell()
        file_obj.stream.seek(0)
        if size > (MAX_DP_FILE_SIZE_MB * 1024 * 1024):
            return f"Image too large. Max allowed is {MAX_DP_FILE_SIZE_MB} MB."
    except Exception:
        return "Unable to validate image file."
    return None


def _get_default_dp_url():
    return url_for("static", filename="user.jpg")


def _resolve_profile_photo_url(email=None):
    fallback = _get_default_dp_url()
    email = email or session.get("email")
    if not email:
        return fallback

    cached = session.get("profile_photo_url")
    if cached:
        return cached

    try:
        doc = db.collection("users").document(email).get()
        if doc.exists:
            data = doc.to_dict() or {}
            profile_url = (data.get("profile_photo_url") or "").strip()
            if profile_url:
                session["profile_photo_url"] = profile_url
                return profile_url
    except Exception as e:
        print("Profile URL read error:", e)
    return fallback


def _upload_profile_photo_for_email(email, file_obj, replace_existing=True):
    bucket = storage.bucket()
    if not bucket or not bucket.name:
        raise RuntimeError("Firebase Storage bucket is not configured.")

    old_path = None
    old_doc = db.collection("users").document(email).get()
    if old_doc.exists:
        old_data = old_doc.to_dict() or {}
        old_path = (old_data.get("profile_photo_path") or "").strip() or None

    safe_email = email.replace("@", "_at_").replace(".", "_")
    filename = secure_filename(file_obj.filename) or "profile.jpg"
    blob_name = f"profile_photos/{safe_email}/{int(time.time())}_{filename}"
    blob = bucket.blob(blob_name)

    file_obj.stream.seek(0)
    blob.upload_from_file(file_obj.stream, content_type=file_obj.mimetype or "application/octet-stream")

    token = uuid.uuid4().hex
    blob.metadata = {"firebaseStorageDownloadTokens": token}
    blob.patch()
    encoded_name = quote(blob_name, safe="")
    profile_url = f"https://firebasestorage.googleapis.com/v0/b/{bucket.name}/o/{encoded_name}?alt=media&token={token}"

    db.collection("users").document(email).set(
        {"profile_photo_url": profile_url, "profile_photo_path": blob_name, "profile_photo_storage": "firebase"},
        merge=True,
    )

    if replace_existing and old_path and old_path != blob_name and old_path.startswith("profile_photos/"):
        try:
            old_blob = bucket.blob(old_path)
            if old_blob.exists():
                old_blob.delete()
        except Exception as del_err:
            print("Old profile photo delete error:", del_err)

    return profile_url


@app.context_processor
def inject_profile_photo():
    return {"profile_photo_url": _resolve_profile_photo_url()}


def send_otp_email(receiver_email):
    otp = str(random.randint(100000, 999999))
    otp_storage[receiver_email] = otp
    subject = "Manas AI - OTP Verification"
    message = f"""Subject: {subject}

Hello!

Your OTP is: {otp}

Meet Manas AI - your friendly mental wellness assistant.
"""
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, receiver_email, message)
        server.quit()
        return otp
    except Exception as e:
        print("Email error:", e)
        return None


def send_distress_email(to_email, user_name, user_email, triggering_text):
    subject = "Manas AI - URGENT: Suicidal/Self-harm Words Detected"
    message_body = (
        "This is an emergency message from Manas AI.\n\n"
        "The following user sent a message containing suicide or self-harm related content:\n"
        f"User Name: {user_name}\n"
        f"User Email: {user_email}\n"
        f"Triggered Message: {triggering_text}\n\n"
        "The user may be in emotional distress and needs immediate help.\n"
        "Please reach out to them or contact local support as soon as possible."
    )
    message = f"Subject: {subject}\n\n{message_body}"
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, to_email, message)
        server.quit()
        return True
    except Exception as e:
        print("Distress Email error:", e)
        return False


def save_user(email, password, name=None, age=None):
    data = {"email": email, "password": password}
    if name:
        data["name"] = name
    if age:
        data["age"] = age
    db.collection("users").document(email).set(data)


def verify_user(email, password):
    doc = db.collection("users").document(email).get()
    if doc.exists:
        data = doc.to_dict()
        return data.get("password") == password
    return False


def save_chat_message(email, chat_name, sender, message):
    chat_ref = db.collection("chats").document(email).collection(chat_name)
    chat_ref.add({"sender": sender, "message": message, "timestamp": datetime.now()})


def get_chat_history(email, chat_name):
    chat_ref = db.collection("chats").document(email).collection(chat_name).order_by("timestamp")
    docs = list(chat_ref.stream())
    return [
        {
            "sender": d.to_dict()["sender"],
            "message": d.to_dict()["message"],
            "timestamp": d.to_dict().get("timestamp"),
        }
        for d in docs
    ]


def get_user_chats(email):
    try:
        return [c.id for c in db.collection("chats").document(email).collections()]
    except Exception:
        return []


def delete_chat_firestore(email, chat_name):
    try:
        parent_ref = db.collection("chats").document(email).collection(chat_name)
        docs = list(parent_ref.stream())
        batch = db.batch()
        for doc in docs:
            batch.delete(doc.reference)
        batch.commit()
        return True
    except Exception as e:
        print(f"Error deleting chat '{chat_name}': {e}")
        return False


@app.route("/")
def home():
    if "email" in session:
        return redirect(url_for("chat"))
    return redirect(url_for("login"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm-password")
        name = request.form.get("name")
        age = request.form.get("age")
        profile_picture = request.files.get("profile_picture")
        if password != confirm_password:
            flash("Password and confirm password do not match.")
            return render_template("signup.html")

        file_error = _validate_dp_file(profile_picture) if profile_picture and profile_picture.filename else None
        if file_error:
            flash(file_error)
            return render_template("signup.html")

        existing_user = db.collection("users").document(email).get()
        if existing_user.exists:
            flash("Account already exists. Please log in.")
            return render_template("signup.html")

        save_user(email, password, name=name, age=age)
        if profile_picture and profile_picture.filename:
            try:
                _upload_profile_photo_for_email(email, profile_picture, replace_existing=True)
            except Exception as e:
                print("Signup profile photo upload error:", e)
                flash("Account created, but profile photo upload failed.")
        send_otp_email(email)
        session["pending_email"] = email
        session["user_name"] = name
        session["user_age"] = age
        flash("OTP sent to your email.")
        return redirect(url_for("verify_otp"))
    # Clear old flashes from unrelated pages so signup opens clean.
    get_flashed_messages()
    return render_template("signup.html")


@app.route("/verify_otp", methods=["GET", "POST"])
def verify_otp():
    email = session.get("pending_email")
    if not email:
        return redirect(url_for("signup"))
    if request.method == "POST":
        otp = request.form.get("otp")
        if otp and otp_storage.get(email) == otp:
            session["email"] = email
            session["name"] = session.get("user_name", "")
            session["age"] = session.get("user_age", "")
            session.pop("profile_photo_url", None)
            otp_storage.pop(email, None)
            session.pop("pending_email", None)
            session.pop("user_name", None)
            session.pop("user_age", None)
            return redirect(url_for("chat"))
        flash("Invalid OTP!")
    return render_template("verify_otp.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        if verify_user(email, password):
            session["email"] = email
            doc = db.collection("users").document(email).get()
            if doc.exists:
                user_data = doc.to_dict()
                session["name"] = user_data.get("name", "")
                session["age"] = user_data.get("age", "")
                profile_url = (user_data.get("profile_photo_url") or "").strip()
                if profile_url:
                    session["profile_photo_url"] = profile_url
                else:
                    session.pop("profile_photo_url", None)
            return redirect(url_for("chat"))
        flash("Invalid credentials!", "login")
    # Clear old flashes from unrelated pages so login opens clean.
    if request.method == "GET":
        get_flashed_messages()
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("email", None)
    session.pop("name", None)
    session.pop("age", None)
    session.pop("profile_photo_url", None)
    flash("Logged out.")
    return redirect(url_for("login"))


@app.route("/chat")
def chat():
    if "email" not in session:
        return redirect(url_for("login"))
    email = session["email"]
    user_chats = get_user_chats(email)
    user_name = session.get("name", "")
    user_age = session.get("age", "")
    return render_template("chat.html", user=email, user_name=user_name, user_age=user_age, user_chats=user_chats)


@app.route("/new_chat", methods=["POST"])
def new_chat():
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    email = session["email"]
    chat_name = f"Chat {datetime.now().strftime('%Y-%m-%d %H-%M-%S')}"
    save_chat_message(email, chat_name, "bot", "Hi there! I'm Manas, your AI mental health assistant. How can I help you today?")
    return jsonify({"chat_name": chat_name})


@app.route("/chat_message", methods=["POST"])
def chat_message():
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    email = session["email"]
    chat_name = request.json.get("chat_name")
    user_message = request.json.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "Empty message"}), 400
    if not chat_name:
        chat_name = f"Chat {datetime.now().strftime('%Y-%m-%d %H-%M-%S')}"
        save_chat_message(email, chat_name, "bot", "Hi there! I'm Manas, your AI mental health assistant. How can I help you today?")
    save_chat_message(email, chat_name, "user", user_message)

    user_msg_lower = user_message.lower()
    harmful_patterns = [
        "suicide", "sucide", "suicidal", "self harm", "self-harm",
        "kill myself", "end my life", "end it all", "want to die",
        "dont want to live", "don't want to live", "hurt myself",
        "cut myself", "overdose", "worthless", "hopeless"
    ]
    contains_keywords = any(keyword in user_msg_lower for keyword in harmful_patterns)
    sentiment_polarity = TextBlob(user_message).sentiment.polarity
    distress_detected = contains_keywords or (sentiment_polarity < -0.4)

    name = session.get("name", "")
    age = session.get("age", "")
    current_user_email = session.get("email", "")

    health_context = _build_health_prompt_context()
    system_prompt = f"""
You are Manas AI, an emotionally intelligent mental wellness companion.
You are built by first-year students of St. Joseph's College of Engineering, Chennai
(Rithul & Rubasree - AIML, Akshay & Arshath - ECE).

User profile:
- Name: {name}
- Age: {age}
- Locale context: India
- {health_context}

Core behavior:
1. Speak only in clear English.
2. Focus only on mental wellness, emotional regulation, stress, motivation, habits, and self-growth.
3. Be warm, practical, and human. Avoid generic filler.
4. Respond with concise, high-impact guidance: emotional validation + 2-4 actionable steps.
5. Personalize your response using available health context if relevant (sleep quality, HR trend, stress patterns).
6. Never present health data as diagnosis. Use tentative language and suggest healthy routines.
7. If distress/suicidal signals appear, prioritize safety, encourage immediate support, and provide official helpline guidance.
8. Do not discuss politics, unrelated topics, or medical treatment plans.

Response style:
- Start by acknowledging the user's feeling in one sentence.
- Then give structured next steps they can do now/today.
- Keep responses brief but meaningful.
"""

    history = get_chat_history(email, chat_name)
    last_messages = history[-6:] if len(history) >= 6 else history
    messages_for_model = [{"role": "system", "content": system_prompt}]
    for msg in last_messages:
        role = "user" if msg["sender"] == "user" else "assistant"
        messages_for_model.append({"role": role, "content": msg["message"]})

    try:
        response = client.chat.completions.create(model="llama-3.1-8b-instant", messages=messages_for_model)
        bot_message = response.choices[0].message.content.strip()
    except Exception:
        bot_message = "Error connecting to Manas AI."

    save_chat_message(email, chat_name, "bot", bot_message)

    alert_sent = False
    if distress_detected and EMERGENCY_ALERT_EMAIL:
        alert_sent = send_distress_email(EMERGENCY_ALERT_EMAIL, name, current_user_email, user_message)

    return jsonify({
        "message": bot_message,
        "chat_name": chat_name,
        "help_available": distress_detected,
        "sos_triggered": distress_detected and alert_sent,
    })


@app.route("/delete_chat", methods=["POST"])
def delete_chat():
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    email = session["email"]
    chat_name = request.json.get("chat_name")
    if not chat_name:
        return jsonify({"error": "Chat name required"}), 400
    success = delete_chat_firestore(email, chat_name)
    return jsonify({"success": success})


@app.route("/daily_inspiration")
def daily_inspiration():
    if "email" not in session:
        return redirect(url_for("login"))
    try:
        res = requests.get("https://zenquotes.io/api/random/10")
        quotes = res.json()
        quote_data = random.choice(quotes)
        quote = f"{quote_data['q']} - {quote_data['a']}"
    except Exception:
        quote = "Stay positive and keep going! - Unknown"

    system_prompt = """
    You are a motivational AI. Give ONE short, practical, uplifting self-improvement tip.
    Reply only with the tip text.
    """
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system_prompt}],
        )
        tip = response.choices[0].message.content.strip()
    except Exception as e:
        print("LLM error:", e)
        tip = "Take a few deep breaths and focus on the present moment."

    response = make_response(render_template("daily_inspiration.html", quote=quote, tip=tip))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/load_chat", methods=["POST"])
def load_chat():
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    email = session["email"]
    chat_name = request.json.get("chat_name")
    if not chat_name:
        return jsonify({"error": "Chat name required"}), 400
    history = get_chat_history(email, chat_name)
    return jsonify({"history": history})


@app.route("/songs")
def songs():
    if "email" not in session:
        return redirect(url_for("login"))
    return render_template("songs.html")


@app.route("/health")
def health():
    if "email" not in session:
        return redirect(url_for("login"))
    return render_template("health.html")


@app.route("/google_connect")
def google_connect():
    if "email" not in session:
        return redirect(url_for("login"))
    config = _load_google_client_config()
    if not config:
        flash("Google Fit config missing. Check static/client_secrets.json.")
        return redirect(url_for("health"))

    auth_uri = config.get("auth_uri")
    client_id = config.get("client_id")
    if not auth_uri or not client_id:
        flash("Google OAuth fields are missing in client_secrets.json.")
        return redirect(url_for("health"))

    state = str(random.randint(10**10, (10**11) - 1))
    session["google_oauth_state"] = state
    redirect_uri = _get_google_redirect_uri()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_FIT_SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return redirect(f"{auth_uri}?{urlencode(params)}")


@app.route("/google_callback")
def google_callback():
    if "email" not in session:
        return redirect(url_for("login"))

    incoming_state = request.args.get("state")
    code = request.args.get("code")
    saved_state = session.get("google_oauth_state")

    if not incoming_state or incoming_state != saved_state:
        flash("Google OAuth state mismatch. Try connecting again.")
        return redirect(url_for("health"))
    if not code:
        flash("Google OAuth failed or was cancelled.")
        return redirect(url_for("health"))

    config = _load_google_client_config()
    token_uri = config.get("token_uri")
    client_id = config.get("client_id")
    client_secret = config.get("client_secret")
    redirect_uri = _get_google_redirect_uri()
    if not token_uri or not client_id or not client_secret:
        flash("Invalid Google client configuration.")
        return redirect(url_for("health"))

    payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        token_resp = requests.post(token_uri, data=payload, timeout=20)
        token_resp.raise_for_status()
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            flash("Google token response is missing access token.")
            return redirect(url_for("health"))

        session["google_fit_token"] = {
            "access_token": access_token,
            "refresh_token": token_data.get("refresh_token"),
            "expires_at": int(time.time()) + int(token_data.get("expires_in", 3600)) - 60,
        }
        flash("Google Fit connected successfully.")
    except Exception as e:
        print("Google token exchange error:", e)
        flash("Failed to connect Google Fit. Check your redirect URI in Google Cloud.")

    return redirect(url_for("health"))


@app.route("/google_disconnect")
def google_disconnect():
    session.pop("google_fit_token", None)
    session.pop("google_oauth_state", None)
    flash("Google Fit disconnected.")
    return redirect(url_for("health"))


@app.route("/get_health_data")
def get_health_data():
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    access_token = _get_google_access_token()
    if not access_token:
        return jsonify({"error": "Google Fit not connected", "not_connected": True}), 400

    now = datetime.utcnow()
    # Use a wider lookback window so users without frequent HR samples still see data.
    start = now - timedelta(hours=24)
    agg = _aggregate_google_fit(
        access_token,
        "com.google.heart_rate.bpm",
        int(start.timestamp() * 1000),
        int(now.timestamp() * 1000),
        30 * 60 * 1000,
    )
    if agg.get("error") == "unauthorized":
        session.pop("google_fit_token", None)
        return jsonify({"error": "Google session expired. Reconnect Google Fit.", "not_connected": True}), 401
    if agg.get("error") == "forbidden":
        return jsonify({
            "error": "Google Fit permission missing. Reconnect and allow heart rate + sleep scopes.",
            "details": agg.get("details", "")
        }), 403
    if agg.get("error"):
        return jsonify({"error": "Unable to fetch heart-rate data from Google Fit."}), 500

    heart_rates = _extract_heart_rates(agg)
    if not heart_rates:
        return jsonify({"current_hr": "--", "heart_rates": [], "stress_status": "No Data"})

    current_hr = heart_rates[-1]
    if current_hr < 60:
        stress_status = "Low"
    elif current_hr <= 100:
        stress_status = "Normal"
    elif current_hr <= 120:
        stress_status = "Elevated"
    else:
        stress_status = "High"

    return jsonify({"current_hr": current_hr, "heart_rates": heart_rates[-20:], "stress_status": stress_status})


@app.route("/get_weekly_sleep")
def get_weekly_sleep():
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    access_token = _get_google_access_token()
    if not access_token:
        return jsonify({"error": "Google Fit not connected", "not_connected": True}), 400

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    start_day = today - timedelta(days=6)
    end_day = today + timedelta(days=1)

    agg = _aggregate_google_fit(
        access_token,
        "com.google.sleep.segment",
        int(start_day.timestamp() * 1000),
        int(end_day.timestamp() * 1000),
        24 * 60 * 60 * 1000,
    )
    if agg.get("error") == "unauthorized":
        session.pop("google_fit_token", None)
        return jsonify({"error": "Google session expired. Reconnect Google Fit.", "not_connected": True}), 401
    if agg.get("error") == "forbidden":
        return jsonify({
            "error": "Google Fit permission missing. Reconnect and allow heart rate + sleep scopes.",
            "details": agg.get("details", "")
        }), 403
    if agg.get("error"):
        return jsonify({"error": "Unable to fetch sleep data from Google Fit."}), 500

    values = _extract_sleep_hours(agg)
    day_starts = [start_day + timedelta(days=i) for i in range(7)]
    labels = [d.strftime("%a") for d in day_starts]
    if len(values) < 7:
        values.extend([0] * (7 - len(values)))
    elif len(values) > 7:
        values = values[-7:]

    # Fallback for accounts where sleep segments are missing but sessions exist.
    if sum(values) == 0:
        fallback_values = _fetch_sleep_sessions_hours(access_token, day_starts)
        if fallback_values:
            values = fallback_values

    return jsonify({"labels": labels, "values": values})


@app.route("/mood")
def mood():
    if "email" not in session:
        return redirect(url_for("login"))
    return render_template("mood.html")


@app.route("/mood_data")
def mood_data():
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    email = session["email"]
    all_chats = get_user_chats(email)
    today = datetime.now().date()
    week_scores = []
    week_labels = []

    for i in range(7):
        day = today - timedelta(days=6 - i)
        day_msgs = []
        for chat_name in all_chats:
            history = get_chat_history(email, chat_name)
            for msg in history:
                ts = msg.get("timestamp")
                if ts and msg["sender"] == "user":
                    if isinstance(ts, datetime):
                        ts_date = ts.date()
                    elif isinstance(ts, str):
                        try:
                            ts_date = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
                        except Exception:
                            ts_date = None
                    else:
                        ts_date = None
                    if ts_date == day:
                        day_msgs.append(msg["message"])

        if day_msgs:
            day_polarity = sum(TextBlob(m).sentiment.polarity for m in day_msgs) / len(day_msgs)
        else:
            day_polarity = 0

        week_scores.append(round(day_polarity, 2))
        week_labels.append(day.strftime("%a"))

    return jsonify({"mood_scores": week_scores, "mood_labels": week_labels})


@app.route("/game1")
def snake_game():
    if "email" not in session:
        return redirect(url_for("login"))
    return render_template("game1.html")


@app.route("/game2")
def runner_game():
    if "email" not in session:
        return redirect(url_for("login"))
    return render_template("game2.html")


@app.route("/game3")
def memory_game():
    if "email" not in session:
        return redirect(url_for("login"))
    return render_template("game3.html")


@app.route("/account", methods=["GET", "POST"])
def account():
    if "email" not in session:
        return redirect(url_for("login"))
    email = session["email"]
    doc = db.collection("users").document(email).get()
    if not doc.exists:
        flash("User not found!")
        return redirect(url_for("logout"))

    user_data = doc.to_dict()
    if request.method == "POST":
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")
        if not verify_user(email, current_password):
            flash("Current password is incorrect!")
        elif new_password != confirm_password:
            flash("New password and confirmation do not match!")
        elif not new_password:
            flash("New password cannot be empty!")
        else:
            user_data["password"] = new_password
            db.collection("users").document(email).set(user_data)
            flash("Password updated successfully!")

    return render_template("account.html", user=user_data, now=int(time.time()))


@app.route("/upload_dp", methods=["POST"])
def upload_dp():
    if "email" not in session:
        return redirect(url_for("login"))

    file = request.files.get("dp")
    file_error = _validate_dp_file(file)
    if file_error:
        flash(file_error)
        return redirect(url_for("account"))

    try:
        email = session["email"]
        profile_url = _upload_profile_photo_for_email(email, file, replace_existing=True)
        session["profile_photo_url"] = profile_url
        flash("Profile photo updated.")
    except Exception as e:
        print("Profile photo upload error:", e)
        flash("Failed to upload profile photo.")

    return redirect(url_for("account"))


@app.route("/games")
def gamecenter():
    if "email" not in session:
        return redirect(url_for("login"))
    return render_template("games.html")


@app.route("/delete_account", methods=["POST"])
def delete_account():
    if "email" not in session:
        return redirect(url_for("login"))
    email = session["email"]
    try:
        db.collection("users").document(email).delete()
        chat_collections = db.collection("chats").document(email).collections()
        for coll in chat_collections:
            for doc in coll.stream():
                doc.reference.delete()
        session.clear()
        flash("Your account has been deleted.")
        return redirect(url_for("signup"))
    except Exception as e:
        print(f"Error deleting account: {e}")
        flash("Failed to delete account. Please try again.")
        return redirect(url_for("account"))


@app.route('/send_emergency_email', methods=['POST'])
def send_emergency_email():
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    triggering_text = payload.get("triggering_text", "")

    ok = send_distress_email(
        to_email=EMERGENCY_ALERT_EMAIL,
        user_name=session.get("name", ""),
        user_email=session.get("email", ""),
        triggering_text=triggering_text,
    )
    if not ok:
        return jsonify({"error": "Failed to send emergency email"}), 500
    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(debug=True)
