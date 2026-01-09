import imaplib
import email
import re
import sqlite3
import datetime
import os
import subprocess
import base64
import requests
import json
import time
from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION ---
EMAIL_USER = "joseken440@gmail.com"
EMAIL_PASS = "emke gleg qrwz cvrs"
IMAP_SERVER = "imap.gmail.com"
TARGET_LABEL = "cfl"
DB_FILE = "termux_bot.db"
ALARM_FILE = "alarm.mp3"
GEMINI_API_KEY = "AIzaSyDnf7reRzJrQnyNTlBfJUifKexlyVDdRWw"  # Get from: https://makersuite.google.com/app/apikey
# ---------------------

current_alarm_process = None

# Initialize database
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  ref_code TEXT, 
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    # Add CAPTCHA solving stats table
    c.execute('''CREATE TABLE IF NOT EXISTS captcha_stats 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  success BOOLEAN,
                  captcha_type TEXT,
                  solve_time FLOAT,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

# CAPTCHA Solver Class
class CaptchaSolver:
    def __init__(self, api_key):
        self.api_key = api_key
        self.gemini_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-vision:generateContent"
        self.solve_count = 0
        self.success_count = 0
        
    def solve_image_captcha(self, image_base64, instruction=""):
        """Solve image-based CAPTCHA using Gemini Vision"""
        start_time = time.time()
        try:
            # Clean base64 if it has data URL prefix
            if 'base64,' in image_base64:
                image_base64 = image_base64.split('base64,')[1]
            
            prompt = f"""Solve this CAPTCHA image. Instruction from website: "{instruction}"
            
            IMPORTANT: Respond ONLY with JSON in this exact format:
            {{
                "type": "selection|text|click|coordinates",
                "solution": "brief description of what to do",
                "positions": ["top-left", "middle-right"] or null,
                "text": "text to enter" or null,
                "confidence": "high|medium|low",
                "grid_size": "3x3" or "4x4" or "unknown"
            }}
            
            If it's a selection CAPTCHA (like "select all images with cars"):
            - Provide grid positions in a 3x3 or 4x4 grid
            - Positions format: ["top-left", "middle-center", "bottom-right"]
            - Estimate grid size based on image
            
            If it's text/number CAPTCHA:
            - Provide the exact text/number in "text" field
            
            Return only JSON, no explanations."""
            
            payload = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": image_base64
                            }
                        }
                    ]
                }]
            }
            
            headers = {"Content-Type": "application/json"}
            response = requests.post(
                f"{self.gemini_url}?key={self.api_key}",
                json=payload,
                headers=headers,
                timeout=45
            )
            
            solve_time = time.time() - start_time
            self.solve_count += 1
            
            if response.status_code == 200:
                result = response.json()
                response_text = result["candidates"][0]["content"]["parts"][0]["text"]
                
                # Extract JSON from response
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    solution = json.loads(json_match.group())
                    solution["solve_time"] = round(solve_time, 2)
                    self.success_count += 1
                    
                    # Log to database
                    self.log_captcha_solve(True, "image", solve_time)
                    
                    return solution
                else:
                    # Fallback: return raw text
                    self.log_captcha_solve(False, "image", solve_time)
                    return {
                        "type": "text",
                        "solution": response_text.strip(),
                        "text": response_text.strip(),
                        "confidence": "low",
                        "solve_time": round(solve_time, 2)
                    }
            else:
                print(f"Gemini API Error {response.status_code}: {response.text[:200]}")
                self.log_captcha_solve(False, "image", solve_time)
                return None
                
        except Exception as e:
            print(f"Error solving CAPTCHA: {e}")
            self.log_captcha_solve(False, "image", time.time() - start_time)
            return None
    
    def solve_text_captcha(self, captcha_text, context=""):
        """Solve text-based CAPTCHA"""
        start_time = time.time()
        try:
            prompt = f"""Solve this text CAPTCHA: "{captcha_text}"
            
            Context: {context}
            
            Return ONLY the solution text/numbers, no explanations, no quotes, no additional text.
            
            If it's distorted text, read it carefully.
            If it's a math problem, solve it and provide the number.
            If it's a question, answer it concisely.
            
            Solution:"""
            
            # Use text-only model
            text_url = self.gemini_url.replace("-vision", "")
            payload = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }]
            }
            
            response = requests.post(
                f"{text_url}?key={self.api_key}",
                json=payload,
                timeout=30
            )
            
            solve_time = time.time() - start_time
            self.solve_count += 1
            
            if response.status_code == 200:
                result = response.json()
                solution_text = result["candidates"][0]["content"]["parts"][0]["text"].strip()
                self.success_count += 1
                self.log_captcha_solve(True, "text", solve_time)
                
                return {
                    "type": "text",
                    "solution": solution_text,
                    "text": solution_text,
                    "confidence": "high",
                    "solve_time": round(solve_time, 2)
                }
            else:
                self.log_captcha_solve(False, "text", solve_time)
                return None
                
        except Exception as e:
            print(f"Error solving text CAPTCHA: {e}")
            self.log_captcha_solve(False, "text", time.time() - start_time)
            return None
    
    def log_captcha_solve(self, success, captcha_type, solve_time):
        """Log CAPTCHA solve attempt to database"""
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute(
                "INSERT INTO captcha_stats (success, captcha_type, solve_time) VALUES (?, ?, ?)",
                (success, captcha_type, solve_time)
            )
            conn.commit()
            conn.close()
        except:
            pass
    
    def get_stats(self):
        """Get solver statistics"""
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM captcha_stats WHERE success = 1")
            total_success = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM captcha_stats")
            total_attempts = c.fetchone()[0]
            c.execute("SELECT AVG(solve_time) FROM captcha_stats WHERE success = 1")
            avg_time = c.fetchone()[0] or 0
            conn.close()
            
            return {
                "total_attempts": total_attempts,
                "total_success": total_success,
                "success_rate": round((total_success / total_attempts * 100) if total_attempts > 0 else 0, 1),
                "avg_solve_time": round(avg_time, 2)
            }
        except:
            return {"total_attempts": 0, "total_success": 0, "success_rate": 0, "avg_solve_time": 0}

# Initialize solver
captcha_solver = CaptchaSolver(GEMINI_API_KEY)

# Email functions (keep your existing)
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

        match = re.search(r'\b\d{5,6}\b', subject)
        
        if match:
            code = match.group(0)
            mail.store(latest_email_id, '+FLAGS', '\\Seen')
            return code
        mail.store(latest_email_id, '+FLAGS', '\\Seen')
    except Exception as e:
        print(f"Email error: {e}")
    return None

# HTML Template (updated with CAPTCHA info)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>CFL Inviter Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="30">
    <style>
        :root { --bg: #0f172a; --card: #1e293b; --text: #e2e8f0; --green: #10b981; --fire: #f59e0b; --blue: #3b82f6; --purple: #8b5cf6; }
        body { font-family: 'Courier New', monospace; background: var(--bg); color: var(--text); padding: 15px; margin: 0; padding-bottom: 50px; }
        
        .header { text-align: center; margin-bottom: 20px; border-bottom: 1px solid #334155; padding-bottom: 10px; }
        .header h1 { margin: 0; font-size: 20px; color: var(--green); }
        .header p { margin: 5px 0 0; font-size: 11px; color: #64748b; }

        .card { background: var(--card); padding: 15px; border-radius: 12px; margin-bottom: 15px; border: 1px solid #334155; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; border-bottom: 1px solid #334155; padding-bottom: 5px; }
        .card-title { font-size: 16px; font-weight: bold; color: #fff; }
        
        .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
        .stat-box { background: #0f172a; padding: 10px; border-radius: 8px; text-align: center; border: 1px solid #334155; }
        .stat-val { font-size: 20px; font-weight: bold; color: #fff; }
        .stat-lbl { font-size: 10px; color: #94a3b8; text-transform: uppercase; }
        .fire-text { color: var(--fire); }
        .purple-text { color: var(--purple); }
        
        /* CAPTCHA Stats */
        .captcha-stats { background: linear-gradient(135deg, #1e1b4b, #312e81); padding: 12px; border-radius: 10px; margin-bottom: 15px; }
        .captcha-title { color: #c4b5fd; font-size: 14px; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
        .captcha-title::before { content: "🤖"; }
        
        .api-status { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: bold; }
        .api-active { background: #10b981; color: white; }
        .api-inactive { background: #ef4444; color: white; }
        
        .btn { display: inline-block; padding: 8px 15px; background: var(--blue); color: white; text-decoration: none; border-radius: 6px; font-size: 12px; border: none; cursor: pointer; }
        .btn:hover { opacity: 0.9; }
        .btn-purple { background: var(--purple); }
        
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th { text-align: left; color: #64748b; padding: 8px; font-size: 11px; }
        td { padding: 8px; border-top: 1px solid #334155; }
        tr:hover { background: #334155; cursor: pointer; }
        
        .tag { background: #064e3b; color: #34d399; padding: 2px 6px; border-radius: 4px; font-size: 10px; }
        .flame-add { color: var(--fire); font-weight: bold; font-size: 11px; }
        
        .footer { position: fixed; bottom: 0; left: 0; width: 100%; background: #0f172a; text-align: center; padding: 10px; border-top: 1px solid #334155; font-size: 12px; color: #64748b; }
        .test-btn { width: 100%; padding: 10px; background: #ef4444; color: white; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; margin-top: 10px; }
        
        /* API Endpoints */
        .endpoint { font-family: monospace; font-size: 11px; background: #0f172a; padding: 8px; border-radius: 6px; margin: 5px 0; border-left: 3px solid #3b82f6; }
    </style>
</head>
<body>

    <div class="header">
        <h1>CFL Inviter Dashboard</h1>
        <p>phcorner.org | Chisato-Chan | AI CAPTCHA Solver</p>
    </div>

    <!-- CAPTCHA Stats Panel -->
    <div class="captcha-stats">
        <div class="captcha-title">
            <span>AI CAPTCHA Solver Status</span>
            <span class="api-status {{ 'api-active' if gemini_ready else 'api-inactive' }}">
                {{ 'ACTIVE' if gemini_ready else 'INACTIVE' }}
            </span>
        </div>
        
        <div class="grid">
            <div class="stat-box">
                <div class="stat-val purple-text">{{ captcha_stats.total_attempts }}</div>
                <div class="stat-lbl">Total Attempts</div>
            </div>
            <div class="stat-box">
                <div class="stat-val purple-text">{{ captcha_stats.success_rate }}%</div>
                <div class="stat-lbl">Success Rate</div>
            </div>
            <div class="stat-box">
                <div class="stat-val purple-text">{{ captcha_stats.avg_solve_time }}s</div>
                <div class="stat-lbl">Avg Time</div>
            </div>
        </div>
        
        <div style="margin-top: 10px; font-size: 11px; color: #94a3b8;">
            <div class="endpoint">POST /api/captcha/solve - Solve CAPTCHA images</div>
            <div class="endpoint">GET /api/captcha/stats - Get solving statistics</div>
            <div class="endpoint">GET /api/captcha/test - Test API connection</div>
        </div>
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
        Credits: phcorner.org | Chisato-Chan | Powered by Google Gemini AI
    </div>

</body>
</html>
"""

# ========================
# ROUTES
# ========================

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
    
    # Check Gemini API status
    gemini_ready = GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_GEMINI_API_KEY_HERE"
    captcha_stats_data = captcha_solver.get_stats()
    
    return render_template_string(
        HTML_TEMPLATE, 
        view='summary', 
        total=total, 
        rate=rate, 
        grouped_data=grouped,
        gemini_ready=gemini_ready,
        captcha_stats=captcha_stats_data
    )

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
    
    gemini_ready = GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_GEMINI_API_KEY_HERE"
    captcha_stats_data = captcha_solver.get_stats()
    
    return render_template_string(
        HTML_TEMPLATE, 
        view='details', 
        total=total, 
        rate=rate, 
        selected_code=code_id, 
        details_data=data,
        details_count=len(data),
        gemini_ready=gemini_ready,
        captcha_stats=captcha_stats_data
    )

# Existing routes
@app.route('/log-success', methods=['POST'])
def log_success():
    ref_code = request.form.get('code', 'Unknown')
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO history (ref_code) VALUES (?)", (ref_code,))
    conn.commit()
    conn.close()
    return "OK"

@app.route('/trigger-alarm', methods=['POST'])
def alarm():
    return "ALARM_REQUEST_RECEIVED"

@app.route('/get-code', methods=['GET'])
def fetch_code():
    code = get_latest_code()
    return jsonify({"code": code, "status": "found"}) if code else jsonify({"status": "waiting"})

# ========================
# NEW CAPTCHA API ROUTES
# ========================

@app.route('/api/captcha/solve', methods=['POST'])
def solve_captcha():
    """Main CAPTCHA solving endpoint for Tampermonkey"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                "success": False,
                "error": "No JSON data provided",
                "timestamp": datetime.datetime.now().isoformat()
            }), 400
        
        # Validate required fields
        if 'image' not in data and 'text' not in data:
            return jsonify({
                "success": False,
                "error": "Missing 'image' or 'text' field",
                "timestamp": datetime.datetime.now().isoformat()
            }), 400
        
        # Check API key
        if not GEMINI_API_KEY or GEMINI_API_KEY == "YOUR_GEMINI_API_KEY_HERE":
            return jsonify({
                "success": False,
                "error": "Gemini API key not configured",
                "timestamp": datetime.datetime.now().isoformat()
            }), 503
        
        # Determine CAPTCHA type
        if 'image' in data:
            # Image CAPTCHA
            image_base64 = data['image']
            instruction = data.get('instruction', 'Select matching images')
            
            if not image_base64:
                return jsonify({
                    "success": False,
                    "error": "Empty image data",
                    "timestamp": datetime.datetime.now().isoformat()
                }), 400
            
            # Solve image CAPTCHA
            solution = captcha_solver.solve_image_captcha(image_base64, instruction)
            
            if solution:
                return jsonify({
                    "success": True,
                    "type": "image",
                    "solution": solution,
                    "instruction": instruction,
                    "timestamp": datetime.datetime.now().isoformat(),
                    "server_version": "1.0"
                })
            else:
                return jsonify({
                    "success": False,
                    "error": "Failed to solve image CAPTCHA",
                    "timestamp": datetime.datetime.now().isoformat()
                }), 500
                
        elif 'text' in data:
            # Text CAPTCHA
            captcha_text = data['text']
            context = data.get('context', '')
            
            if not captcha_text:
                return jsonify({
                    "success": False,
                    "error": "Empty text data",
                    "timestamp": datetime.datetime.now().isoformat()
                }), 400
            
            # Solve text CAPTCHA
            solution = captcha_solver.solve_text_captcha(captcha_text, context)
            
            if solution:
                return jsonify({
                    "success": True,
                    "type": "text",
                    "solution": solution,
                    "timestamp": datetime.datetime.now().isoformat(),
                    "server_version": "1.0"
                })
            else:
                return jsonify({
                    "success": False,
                    "error": "Failed to solve text CAPTCHA",
                    "timestamp": datetime.datetime.now().isoformat()
                }), 500
                
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "timestamp": datetime.datetime.now().isoformat()
        }), 500

@app.route('/api/captcha/stats', methods=['GET'])
def get_captcha_stats():
    """Get CAPTCHA solving statistics"""
    stats = captcha_solver.get_stats()
    gemini_ready = GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_GEMINI_API_KEY_HERE"
    
    return jsonify({
        "success": True,
        "solver_status": "active" if gemini_ready else "inactive",
        "gemini_configured": gemini_ready,
        "statistics": stats,
        "endpoints": {
            "solve": "POST /api/captcha/solve",
            "stats": "GET /api/captcha/stats",
            "test": "GET /api/captcha/test",
            "health": "GET /api/captcha/health"
        },
        "timestamp": datetime.datetime.now().isoformat()
    })

@app.route('/api/captcha/test', methods=['GET'])
def test_captcha_api():
    """Test endpoint to verify API is working"""
    gemini_ready = GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_GEMINI_API_KEY_HERE"
    
    return jsonify({
        "success": True,
        "message": "CAPTCHA solver API is running",
        "status": "operational",
        "gemini_api_configured": gemini_ready,
        "server_time": datetime.datetime.now().isoformat(),
        "version": "1.0.0"
    })

@app.route('/api/captcha/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "CFL CAPTCHA Solver",
        "timestamp": datetime.datetime.now().isoformat(),
        "uptime": "running"
    })

@app.route('/api/captcha/quick-test', methods=['POST'])
def quick_test():
    """Quick test with sample CAPTCHA"""
    try:
        # Sample base64 of a simple image
        sample_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        
        solution = captcha_solver.solve_image_captcha(
            sample_base64,
            "Select all squares containing text"
        )
        
        return jsonify({
            "success": True,
            "test": "quick_test",
            "solution": solution or {"message": "Test completed"},
            "timestamp": datetime.datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "timestamp": datetime.datetime.now().isoformat()
        })

# ========================
# MAIN
# ========================

if __name__ == '__main__':
    init_db()
    print("=" * 60)
    print("🚀 CFL Inviter Dashboard with AI CAPTCHA Solver")
    print("=" * 60)
    print(f"📧 Email: {EMAIL_USER}")
    
    gemini_ready = GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_GEMINI_API_KEY_HERE"
    if gemini_ready:
        print("🤖 Gemini API: ✅ CONFIGURED")
    else:
        print("🤖 Gemini API: ❌ NOT CONFIGURED")
        print("   Get API key from: https://makersuite.google.com/app/apikey")
        print("   Then update GEMINI_API_KEY in the code")
    
    print(f"🌐 Dashboard: http://localhost:5000")
    print(f"🔧 CAPTCHA API: http://localhost:5000/api/captcha/solve")
    print(f"📊 Stats API: http://localhost:5000/api/captcha/stats")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=True)
