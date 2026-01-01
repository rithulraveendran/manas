Manas AI 🤖🧠
A friendly mental health companion chatbot built with Python, Flask, and AI
🌟 Overview

Manas AI is a web-based chatbot designed to support mental wellness, provide daily inspiration, and track moods. Users can chat, play small games, listen to motivational content, and get alerts if distressing keywords are detected.

It uses AI language models to generate empathetic responses and integrates with Firebase for authentication and chat history storage.

🛠️ Features

User Authentication – Signup, login, OTP verification, and account management.

Chatbot – AI-powered mental health companion with empathetic responses.

Distress Detection – Detects keywords or negative sentiments and can send emergency alerts.

Daily Inspiration – Motivational quotes and self-improvement tips.

Mood Tracking – Weekly mood analysis based on chat sentiment.

Mini Games – Snake, Runner, and Memory games for fun breaks.

Songs & Mood Pages – Personalization options for users.

💻 Tech Stack

Backend: Python, Flask

AI Integration: Groq API, TextBlob (for sentiment analysis)

Database: Firebase Firestore

Frontend: HTML, CSS, JavaScript, Jinja2 templates

Email Service: SMTP (Gmail) for OTP and distress alerts

⚡ Installation

Clone the repository:

git clone https://github.com/your-username/manas-ai.git
cd manas-ai


Create a virtual environment and activate it:

python -m venv venv
source venv/bin/activate      # Linux / macOS
venv\Scripts\activate         # Windows


Install dependencies:

pip install -r requirements.txt


Add your Firebase key in static/firebase_key.json and update API keys in app.py.

Run the app:

python app.py


Open in your browser at:

http://127.0.0.1:5000

🔑 Usage

Signup/Login: Create an account using email and OTP verification.

Chat: Talk to Manas AI for mental wellness guidance.

Games & Mood Tracking: Access mini-games and track your weekly mood.

Daily Inspiration: Get motivational quotes and tips daily.

Account Management: Update or delete your account securely.

⚠️ Notes

This project is for educational and personal wellness purposes.

Manas AI is not a substitute for professional medical advice.

Emergency emails are sent only if distress keywords or negative sentiments are detected.

📂 Project Structure
Manas/
│   app.py
│
├───static
│       bot.png
│       firebase_key.json
│       user.jpg
│
└───templates
        account.html
        chat.html
        daily_inspiration.html
        game1.html
        game2.html
        game3.html
        games.html
        login.html
        mood.html
        signup.html
        songs.html
        verify_otp.html

🛠️ Future Improvements

Add real-time chat with websockets.

Integrate voice input/output.

Enhance AI responses with more nuanced sentiment analysis.

Mobile-friendly responsive design.

📜 License

This project is under a Custom License – anyone must get explicit permission from the owner before using, modifying, or distributing the code.

🌐 Connect

📧 Email: flightsofwhisper@gmail.com

⭐ “Your mental wellness matters. Talk, reflect, and grow with Manas AI.”
