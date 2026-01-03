from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, make_response
from datetime import datetime, timedelta
import random, os, smtplib, requests
from textblob import TextBlob
import firebase_admin
from firebase_admin import credentials, firestore
from groq import Groq

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = "supersecretkey"

GROQ_API_KEY = "ADD YOUR GROQ API KEY HERE"
SENDER_EMAIL = "ADD YOUR MAIL ID HERE"
APP_PASSWORD = "ADD YOUR APP PASSWORD HERE"
FIREBASE_KEY_PATH = os.path.join(os.path.dirname(__file__), "firebase_key.json")

if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_KEY_PATH)
    firebase_admin.initialize_app(cred)
db = firestore.client()
client = Groq(api_key=GROQ_API_KEY)

otp_storage = {}

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
        print("❌ Email error:", e)
        return None

def send_distress_email(to_email, user_name, user_email, triggering_text):
    subject = "Manas AI – URGENT: Suicidal/Self-harm Words Detected"
    message_body = (
        f"This is an emergency message from Manas AI.\n\n"
        f"The following user sent a message containing suicide or self-harm related content:\n"
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
    except Exception as e:
        print("❌ Distress Email error:", e)

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
    chat_ref.add({"sender": sender, "message": message, "timestamp": datetime.utcnow()})

def get_chat_history(email, chat_name):
    chat_ref = db.collection("chats").document(email).collection(chat_name).order_by("timestamp")
    docs = list(chat_ref.stream())
    return [{"sender": d.to_dict()["sender"], "message": d.to_dict()["message"], "timestamp": d.to_dict().get("timestamp")} for d in docs]

def get_user_chats(email):
    try:
        return [c.id for c in db.collection("chats").document(email).collections()]
    except:
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
        print(f"❌ Error deleting chat '{chat_name}': {e}")
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
        name = request.form.get("name")
        age = request.form.get("age")
        save_user(email, password, name=name, age=age)
        send_otp_email(email)
        session["pending_email"] = email
        session["user_name"] = name
        session["user_age"] = age
        flash("OTP sent to your email.")
        return redirect(url_for("verify_otp"))
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
            otp_storage.pop(email, None)
            session.pop("pending_email", None)
            session.pop("user_name", None)
            session.pop("user_age", None)
            return redirect(url_for("chat"))
        else:
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
            return redirect(url_for("chat"))
        else:
            flash("Invalid credentials!")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("email", None)
    session.pop("name", None)
    session.pop("age", None)
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
    return render_template(
        "chat.html",
        user=email,
        user_name=user_name,
        user_age=user_age,
        user_chats=user_chats
    )

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

    help_keywords = [
        "suicide", "self harm", "kill myself", "end my life", "cut myself",
        "hurt myself", "die", "depressed", "hopeless", "worthless"
    ]
    user_msg_lower = user_message.lower()
    contains_keywords = any(keyword in user_msg_lower for keyword in help_keywords)
    sentiment_polarity = TextBlob(user_message).sentiment.polarity
    distress_detected = contains_keywords or (sentiment_polarity < -0.5)

    name = session.get("name", "")
    age = session.get("age", "")
    current_user_email = session.get("email", "")

    system_prompt = f"""
You are Manas AI — a friendly mental health companion created by 
first-year students of St. Joseph’s College of Engineering, Chennai 
(Rithul & Rubasree – AIML, Akshay & Arshath – ECE).
You are chatting with an Indian student.
User name: {name}
User age: {age}
Speak only in English.
Talk only about mental health, motivation, emotions, stress, or self-growth.
Be kind, empathetic, and brief. Provide the official government helpline numbers whenever required.
Never discuss medical issues, politics, or any unrelated topic.
Your goal is to make the user feel understood and supported.
"""

    history = get_chat_history(email, chat_name)
    last_messages = history[-6:] if len(history) >= 6 else history
    messages_for_model = [{"role": "system", "content": system_prompt}]
    for msg in last_messages:
        role = "user" if msg["sender"] == "user" else "assistant"
        messages_for_model.append({"role": role, "content": msg["message"]})

    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages_for_model
        )
        bot_message = response.choices[0].message.content.strip()
    except:
        bot_message = "⚠️ Error connecting to Manas AI."

    save_chat_message(email, chat_name, "bot", bot_message)

    if distress_detected:
        send_distress_email(
            "manasemergencysos@gmail.com",
            name,
            current_user_email,
            user_message
        )

    return jsonify({
        "message": bot_message,
        "chat_name": chat_name,
        "help_available": distress_detected
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
        quote = f"{quote_data['q']} — {quote_data['a']}"
    except:
        quote = "Stay positive and keep going! — Unknown"
    system_prompt = """
    You are a motivational AI. Give ONE short, practical, uplifting self-improvement tip.
    Reply only with the tip text.
    """
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system_prompt}]
        )
        tip = response.choices[0].message.content.strip()
    except Exception as e:
        print("LLM error:", e)
        tip = "Take a few deep breaths and focus on the present moment."
    response = make_response(render_template(
        "daily_inspiration.html",
        quote=quote,
        tip=tip
    ))
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
    today = datetime.utcnow().date()
    week_scores = []
    week_labels = []
    for i in range(7):
        day = today - timedelta(days=6 - i)
        day_msgs = []
        for chat in all_chats:
            history = get_chat_history(email, chat)
            for msg in history:
                ts = msg.get("timestamp")
                if ts and msg["sender"] == "user":
                    ts_date = ts.date() if isinstance(ts, datetime) else ts
                    if ts_date == day:
                        day_msgs.append(msg["message"])
        if day_msgs:
            day_polarity = sum([TextBlob(m).sentiment.polarity for m in day_msgs]) / len(day_msgs)
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
    return render_template("account.html", user=user_data)

@app.route('/games')
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
def send_distress_email(to_email, user_name, user_email, triggering_text):
    subject = "Manas AI - URGENT: Suicidal/Self-harm Words Detected"
    message_body = (
        f"This is an emergency message from Manas AI.\n\n"
        f"The following user sent a message containing suicide or self-harm related content:\n"
        f"User Name: {user_name}\n"
        f"User Email: {user_email}\n"
        f"Triggered Message: {triggering_text}\n\n"
        "The user may be in emotional distress and needs immediate help.\n"
        "Please reach out to them or contact local support as soon as possible."
    )
    message = f"Subject: {subject}\nContent-Type: text/plain; charset=utf-8\n\n{message_body}"
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, to_email, message.encode('utf-8'))
        server.quit()
    except Exception as e:
        print("❌ Distress Email error:", e)

if __name__ == "__main__":
    app.run(debug=True)
