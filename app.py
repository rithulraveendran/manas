from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, make_response
from datetime import datetime, timedelta
import random, os, smtplib, requests, tempfile
from textblob import TextBlob
import firebase_admin
from firebase_admin import credentials, firestore
from groq import Groq

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ["FLASK_SECRET_KEY"]

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
SENDER_EMAIL = os.environ["SENDER_EMAIL"]
APP_PASSWORD = os.environ["APP_PASSWORD"]
FIREBASE_KEY_JSON = os.environ["FIREBASE_KEY_JSON"]

with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".json") as f:
    f.write(FIREBASE_KEY_JSON)
    firebase_key_path = f.name

if not firebase_admin._apps:
    cred = credentials.Certificate(firebase_key_path)
    firebase_admin.initialize_app(cred)

db = firestore.client()
client = Groq(api_key=GROQ_API_KEY)

otp_storage = {}

def send_otp_email(receiver_email):
    otp = str(random.randint(100000, 999999))
    otp_storage[receiver_email] = otp
    message = f"Subject: Manas AI - OTP Verification\n\nYour OTP is: {otp}"
    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(SENDER_EMAIL, APP_PASSWORD)
    server.sendmail(SENDER_EMAIL, receiver_email, message)
    server.quit()

def send_distress_email(to_email, user_name, user_email, triggering_text):
    message = (
        "Subject: Manas AI – URGENT\n\n"
        f"User Name: {user_name}\n"
        f"User Email: {user_email}\n"
        f"Message: {triggering_text}"
    )
    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(SENDER_EMAIL, APP_PASSWORD)
    server.sendmail(SENDER_EMAIL, to_email, message)
    server.quit()

def save_user(email, password, name=None, age=None):
    data = {"email": email, "password": password, "name": name, "age": age}
    db.collection("users").document(email).set(data)

def verify_user(email, password):
    doc = db.collection("users").document(email).get()
    return doc.exists and doc.to_dict()["password"] == password

def save_chat_message(email, chat_name, sender, message):
    db.collection("chats").document(email).collection(chat_name).add({
        "sender": sender,
        "message": message,
        "timestamp": datetime.utcnow()
    })

def get_chat_history(email, chat_name):
    docs = db.collection("chats").document(email).collection(chat_name).order_by("timestamp").stream()
    return [{"sender": d.to_dict()["sender"], "message": d.to_dict()["message"], "timestamp": d.to_dict()["timestamp"]} for d in docs]

def get_user_chats(email):
    return [c.id for c in db.collection("chats").document(email).collections()]

def delete_chat_firestore(email, chat_name):
    coll = db.collection("chats").document(email).collection(chat_name)
    for doc in coll.stream():
        doc.reference.delete()
    return True

@app.route("/")
def home():
    return redirect(url_for("chat")) if "email" in session else redirect(url_for("login"))

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        name = request.form["name"]
        age = request.form["age"]
        save_user(email, password, name, age)
        send_otp_email(email)
        session.update({"pending_email": email, "name": name, "age": age})
        return redirect(url_for("verify_otp"))
    return render_template("signup.html")

@app.route("/verify_otp", methods=["GET", "POST"])
def verify_otp():
    email = session.get("pending_email")
    if request.method == "POST" and request.form["otp"] == otp_storage.get(email):
        session["email"] = email
        session.pop("pending_email")
        return redirect(url_for("chat"))
    return render_template("verify_otp.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        if verify_user(email, request.form["password"]):
            session["email"] = email
            return redirect(url_for("chat"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/chat")
def chat():
    if "email" not in session:
        return redirect(url_for("login"))
    return render_template("chat.html", user=session["email"], user_chats=get_user_chats(session["email"]))

@app.route("/new_chat", methods=["POST"])
def new_chat():
    chat_name = f"Chat {datetime.now().strftime('%Y-%m-%d %H-%M-%S')}"
    save_chat_message(session["email"], chat_name, "bot", "Hi, I'm Manas. How can I help?")
    return jsonify({"chat_name": chat_name})

@app.route("/chat_message", methods=["POST"])
def chat_message():
    email = session["email"]
    chat_name = request.json.get("chat_name") or f"Chat {datetime.now().strftime('%Y-%m-%d %H-%M-%S')}"
    user_message = request.json["message"]
    save_chat_message(email, chat_name, "user", user_message)

    distress = TextBlob(user_message).sentiment.polarity < -0.5
    messages = [{"role": "system", "content": "You are Manas AI. Be empathetic."}]
    for m in get_chat_history(email, chat_name)[-6:]:
        messages.append({"role": "user" if m["sender"] == "user" else "assistant", "content": m["message"]})

    response = client.chat.completions.create(model="llama-3.1-8b-instant", messages=messages)
    bot_message = response.choices[0].message.content.strip()

    save_chat_message(email, chat_name, "bot", bot_message)
    if distress:
        send_distress_email("manasemergencysos@gmail.com", session.get("name"), email, user_message)

    return jsonify({"message": bot_message, "chat_name": chat_name})

@app.route("/delete_chat", methods=["POST"])
def delete_chat():
    delete_chat_firestore(session["email"], request.json["chat_name"])
    return jsonify({"success": True})

@app.route("/daily_inspiration")
def daily_inspiration():
    quote = requests.get("https://zenquotes.io/api/random").json()[0]
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": "Give one short motivational tip."}]
    )
    return render_template("daily_inspiration.html", quote=f"{quote['q']} — {quote['a']}", tip=response.choices[0].message.content)

@app.route("/games")
def games():
    return render_template("games.html")

@app.route("/delete_account", methods=["POST"])
def delete_account():
    email = session["email"]
    db.collection("users").document(email).delete()
    for coll in db.collection("chats").document(email).collections():
        for doc in coll.stream():
            doc.reference.delete()
    session.clear()
    return redirect(url_for("signup"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ["PORT"]))
