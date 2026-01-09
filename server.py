import imaplib
import email
import re
import sqlite3
import datetime
import os
import subprocess
from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION ---
EMAIL_USER = "shaprhades2004@gmail.com"
EMAIL_PASS = "yyro ijcv cuxe akhj"
IMAP_SERVER = "imap.gmail.com" #do not change this unless you have your own imap server
TARGET_LABEL = "cfl" #do not change this unless you want an specific label
DB_FILE = "termux_bot.db" #do not change this
ALARM_FILE = "alarm.mp3" #do not change this unless you want an specific alarm
# ---------------------

current_alarm_process = None

def play_smart_alarm():
    global current_alarm_process
    
    if current_alarm_process is not None:
        if current_alarm_process.poll() is None:
            print("⏳ Alarm is already playing... Ignoring request.")
            return

    print("🚨 STARTING ALARM (Once)...")
    try:
        current_alarm_process = subprocess.Popen(["mpv", ALARM_FILE])
    except FileNotFoundError:
        print("❌ Error: 'mpv' is not installed. Run: pkg install mpv")
    except Exception as e:
        print(f"❌ Error playing sound: {e}")


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  ref_code TEXT, 
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def get_latest_code():
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_USER, EMAIL_PASS)
        status, messages = mail.select(TARGET_LABEL)
        if status != 'OK': return None

        status, messages = mail.search(None, '(UNSEEN)')
        email_ids = messages[0].split()
        if not email_ids: return None

        latest_email_id = email_ids[-1]
        status, msg_data = mail.fetch(latest_email_id, '(RFC822)')
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)
        
        from email.header import decode_header
        subject, encoding = decode_header(msg["Subject"])[0]
        if isinstance(subject, bytes): subject = subject.decode(encoding if encoding else "utf-8")

        print(f"📧 New Email: {subject}")
        match = re.search(r'\b\d{5,6}\b', subject)
        
        if match:
            code = match.group(0)
            print(f"✅ CODE: {code}")
            mail.store(latest_email_id, '+FLAGS', '\\Seen')
            return code
        mail.store(latest_email_id, '+FLAGS', '\\Seen')
    except: pass
    return None


HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>CFL Inviter Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="10">
    <style>
        :root { --bg: #0f172a; --card: #1e293b; --text: #e2e8f0; --green: #10b981; --fire: #f59e0b; --blue: #3b82f6; }
        body { font-family: 'Courier New', monospace; background: var(--bg); color: var(--text); padding: 15px; margin: 0; padding-bottom: 50px; }
        
        /* HEADER */
        .header { text-align: center; margin-bottom: 20px; border-bottom: 1px solid #334155; padding-bottom: 10px; }
        .header h1 { margin: 0; font-size: 20px; color: var(--green); }
        .header p { margin: 5px 0 0; font-size: 11px; color: #64748b; }

        /* CARDS */
        .card { background: var(--card); padding: 15px; border-radius: 12px; margin-bottom: 15px; border: 1px solid #334155; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; border-bottom: 1px solid #334155; padding-bottom: 5px; }
        .card-title { font-size: 16px; font-weight: bold; color: #fff; }
        
        /* GRID */
        .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
        .stat-box { background: #0f172a; padding: 10px; border-radius: 8px; text-align: center; border: 1px solid #334155; }
        .stat-val { font-size: 20px; font-weight: bold; color: #fff; }
        .stat-lbl { font-size: 10px; color: #94a3b8; text-transform: uppercase; }
        .fire-text { color: var(--fire); }

        /* TABLES */
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th { text-align: left; color: #64748b; padding: 8px; font-size: 11px; }
        td { padding: 8px; border-top: 1px solid #334155; }
        tr:hover { background: #334155; cursor: pointer; }
        
        /* UTILS */
        .btn { display: inline-block; padding: 5px 10px; background: var(--blue); color: white; text-decoration: none; border-radius: 4px; font-size: 12px; }
        .back-btn { background: #475569; margin-bottom: 15px; }
        .tag { background: #064e3b; color: #34d399; padding: 2px 6px; border-radius: 4px; font-size: 10px; }
        .flame-add { color: var(--fire); font-weight: bold; font-size: 11px; }

        /* FOOTER */
        .footer { position: fixed; bottom: 0; left: 0; width: 100%; background: #0f172a; text-align: center; padding: 10px; border-top: 1px solid #334155; font-size: 12px; color: #64748b; }
        .test-btn { width: 100%; padding: 10px; background: #ef4444; color: white; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; margin-top: 10px; }
    </style>
</head>
<body>

    <div class="header">
        <h1>CFL Inviter Dashboard</h1>
        <p>phcorner.org | Chisato-Chan</p>
    </div>

    <div class="card">
        <div class="grid">
            <div class="stat-box">
                <div class="stat-val">{{ total }}</div>
                <div class="stat-lbl">Invites</div>
            </div>
            <div class="stat-box">
                <div class="stat-val fire-text">{{ total * 10 }}</div>
                <div class="stat-lbl">Flames</div>
            </div>
            <div class="stat-box">
                <div class="stat-val">{{ rate }}</div>
                <div class="stat-lbl">Avg / Hour</div>
            </div>
        </div>
    </div>
    
    <div class="card" style="padding: 10px;">
        <button class="test-btn" onclick="fetch('/trigger-alarm', {method: 'POST'})">🔊 TEST ALARM (CLICK ME)</button>
    </div>

    {% if view == 'summary' %}
    <div class="card">
        <div class="card-header">
            <span class="card-title">📂 Referral Codes</span>
        </div>
        <table>
            <thead><tr><th>CODE</th><th>INVITES</th><th>FLAMES</th><th></th></tr></thead>
            <tbody>
                {% for row in grouped_data %}
                <tr onclick="window.location.href='/details/{{ row[0] }}'">
                    <td><span class="tag">{{ row[0] }}</span></td>
                    <td>{{ row[1] }}</td>
                    <td class="fire-text">🔥 {{ row[1] * 10 }}</td>
                    <td>➡</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    {% else %}
    <a href="/" class="btn back-btn">⬅ Back to Dashboard</a>
    
    <div class="card">
        <div class="card-header">
            <span class="card-title">📜 History: {{ selected_code }}</span>
            <span class="tag">Count: {{ details_count }}</span>
        </div>
        <table>
            <thead><tr><th>DATE / TIME</th><th>REWARD</th></tr></thead>
            <tbody>
                {% for row in details_data %}
                <tr>
                    <td>{{ row[0] }}</td>
                    <td><span class="flame-add">+10 Flames 🔥</span></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% endif %}

    <div class="footer">
        Credits: phcorner.org | Chisato-Chan
    </div>

</body>
</html>
"""



@app.route('/')
def index():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    
    c.execute("SELECT COUNT(*) FROM history")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM history WHERE timestamp >= datetime('now', '-1 hour')")
    rate = c.fetchone()[0]
    
    
    c.execute('''
        SELECT ref_code, COUNT(*), MAX(timestamp) 
        FROM history 
        GROUP BY ref_code 
        ORDER BY MAX(timestamp) DESC
    ''')
    grouped = c.fetchall()
    conn.close()
    
    return render_template_string(HTML_TEMPLATE, view='summary', total=total, rate=rate, grouped_data=grouped)

@app.route('/details/<code_id>')
def details(code_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    
    c.execute("SELECT COUNT(*) FROM history")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM history WHERE timestamp >= datetime('now', '-1 hour')")
    rate = c.fetchone()[0]

   
    query = f"""
        SELECT strftime('%Y-%m-%d  %I:%M %p', timestamp, 'localtime') 
        FROM history 
        WHERE ref_code = ? 
        ORDER BY timestamp DESC
    """
    c.execute(query, (code_id,))
    data = c.fetchall()
    conn.close()
    
    return render_template_string(HTML_TEMPLATE, 
                                  view='details', 
                                  total=total, 
                                  rate=rate, 
                                  selected_code=code_id, 
                                  details_data=data,
                                  details_count=len(data))

@app.route('/log-success', methods=['POST'])
def log_success():
    ref_code = request.form.get('code', 'Unknown')
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO history (ref_code) VALUES (?)", (ref_code,))
    conn.commit()
    conn.close()
    print(f"✅ SUCCESS: {ref_code} (+10 Flames) | phcorner.org | Chisato-Chan")
    return "OK"

@app.route('/trigger-alarm', methods=['POST'])
def alarm():
    play_smart_alarm()
    return "ALARM_REQUEST_RECEIVED"

@app.route('/get-code', methods=['GET'])
def fetch_code():
    code = get_latest_code()
    return jsonify({"code": code, "status": "found"}) if code else jsonify({"status": "waiting"})

if __name__ == '__main__':
    init_db()
    print("--- 📱 CFL INVITER DASHBOARD (ADVANCED) ---")
    print("Credits: phcorner.org | Chisato-Chan")
    app.run(host='0.0.0.0', port=5000)
