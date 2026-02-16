<div align="center"> <h1 style="font-size:4em;">Manas AI</h1> <p><b style="font-size:1.6em;">Your Intelligent Mental Wellness Companion</b></p> <img src="static/manas.jpeg" alt="Manas AI Logo" width="250" style="border-radius:15px; margin-bottom:20px;"/> <p style="font-size:1.3em;"> Talk, reflect, monitor wellbeing, and grow with an AI designed to support emotional health. </p> <br/> <p style="font-size:1.4em;"> <a href="#overview">Overview</a> • <a href="#features">Features</a> • <a href="#installation">Installation</a> • <a href="#usage">Usage</a> </p> </div>
<div style="background:#ffcccc; padding:15px; border-radius:10px; text-align:center; font-size:1.2em; margin-bottom:20px;"> ⚠️ <b>Important Setup:</b><br/> Place <code>firebase_key.json</code> inside the <code>static</code> folder.<br/> Also add <code>client_secrets.json</code> for Google Fit integration. </div>
<h2 id="overview" style="font-size:2.8em;">🌌 Overview</h2> <p style="font-size:1.3em;"> <strong>Manas AI</strong> is a Flask-powered AI mental wellness web application that combines empathetic conversation, mood insights, health tracking, and self-growth tools into one unified platform. </p> <p style="font-size:1.3em;"> Built by first-year students of St. Joseph’s College of Engineering, Chennai, Manas AI blends AI conversation, Firebase cloud storage, Google Fit health context, and emotional analysis to provide meaningful support and positive habits. </p>
<h2 id="features" style="font-size:2.8em;">🛠 Features</h2> <ul style="font-size:1.3em;"> <li>🤖 <strong>AI Mental Wellness Chatbot</strong> — emotionally aware conversations powered by Groq LLMs.</li> <li>🧠 <strong>Smart Emotional Detection</strong> — sentiment analysis + distress keyword detection.</li> <li>🚨 <strong>Emergency Distress Alerts</strong> — automatic SOS email trigger for high-risk messages.</li> <li>📊 <strong>Mood Tracking Dashboard</strong> — weekly sentiment visualization from chat history.</li> <li>❤️ <strong>Google Fit Integration</strong> — heart rate & sleep insights used for contextual responses.</li> <li>💡 <strong>Daily Inspiration</strong> — motivational quotes + AI-generated self-growth tips.</li> <li>🎮 <strong>Relaxation Mini-Games</strong> — Snake, Runner, and Memory games.</li> <li>📷 <strong>Profile Management</strong> — secure profile picture upload via Firebase Storage.</li> <li>🔐 <strong>Authentication System</strong> — Signup, OTP verification, login, and account controls.</li> <li>☁️ <strong>Cloud Storage</strong> — chats and user data stored securely in Firebase Firestore.</li> </ul>
<h2 id="installation" style="font-size:2.8em;">🚀 Installation</h2> <h3 style="font-size:2em;">Prerequisites</h3> <ul style="font-size:1.3em;"> <li>Python 3.11+</li> <li>Flask</li> <li>Firebase Project + Service Key</li> <li>Groq API Key</li> <li>Google OAuth Client (for Google Fit)</li> </ul> <h3 style="font-size:2em;">Quick Start</h3> <div style="background:#f5f5f5; padding:20px; border-radius:10px; font-size:1.3em; overflow-x:auto;">

<b>1️⃣ Clone the repository:</b>

<pre>git clone https://github.com/your-username/manas-ai.git cd manas-ai</pre>

<b>2️⃣ Install dependencies:</b>

<pre>pip install -r requirements.txt</pre>

<b>3️⃣ Add configuration files:</b>

<ul> <li><code>static/firebase_key.json</code></li> <li><code>static/client_secrets.json</code> (Google OAuth)</li> </ul>

<b>4️⃣ Configure credentials in <code>app.py</code>:</b>

<ul> <li>Groq API key</li> <li>Sender email + app password</li> <li>Emergency alert email (optional)</li> </ul>

<b>5️⃣ Run the app:</b>

<pre>python app.py</pre>

<b>6️⃣ Open in browser:</b>

<pre>http://127.0.0.1:5000</pre> </div>
<h2 id="usage" style="font-size:2.8em;">💬 Usage</h2> <ul style="font-size:1.3em;"> <li>Create an account and verify OTP via email.</li> <li>Chat with Manas AI in the <strong>Chat</strong> page.</li> <li>Connect Google Fit for personalized health-aware responses.</li> <li>View mood trends in <strong>Mood Analytics</strong>.</li> <li>Check <strong>Daily Inspiration</strong> for motivation.</li> <li>Play mini-games to relax and reset.</li> <li>Manage password, profile photo, and account settings.</li> </ul>