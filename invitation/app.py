from flask import Flask, render_template, request, flash, redirect, url_for, jsonify, session
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
from functools import wraps
import time
import sqlite3
import requests
import sys
import logging
from logging.handlers import RotatingFileHandler
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
from urllib3 import PoolManager
import socket

# Set up logging to ensure all logs go to stdout and are visible in Render
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logging.getLogger().setLevel(logging.INFO)
logging.getLogger('werkzeug').setLevel(logging.INFO)
app_logger = logging.getLogger('app')

# Attach app_logger and app.logger to root logger handlers for Render/Gunicorn visibility
root_logger = logging.getLogger()
for handler in root_logger.handlers:
    app_logger.addHandler(handler)
app_logger.propagate = True
app_logger.setLevel(logging.INFO)
for handler in root_logger.handlers:
    app.logger.addHandler(handler)
app.logger.propagate = True
app.logger.setLevel(logging.INFO)

app_logger.info("BOOT-MARK 2025-05-17-23-20")

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-dev-key')
app.config['ENV'] = os.getenv('FLASK_ENV', 'production')
app.config['ADMIN_PASSWORD'] = os.getenv('ADMIN_PASSWORD', 'admin123')  # Change this in production!

# Ensure Flask and app_logger use Gunicorn's logger in production
if __name__ != '__main__':
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
    app_logger.handlers = gunicorn_logger.handlers
    app_logger.setLevel(gunicorn_logger.level)

# Database setup
DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, 'invitation.db')

def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rsvps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            guests INTEGER DEFAULT 1,
            message TEXT,
            timestamp TEXT
        )
    ''')
    db.commit()
    db.close()

with app.app_context():
    init_db()

# Rate limiting configuration
MAX_LOGIN_ATTEMPTS = 5
LOGIN_TIMEOUT = 300  # 5 minutes in seconds
login_attempts = {}

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        if 'last_activity' in session:
            last_activity = session['last_activity']
            if time.time() - last_activity > 1800:
                session.clear()
                flash('Session expirée. Veuillez vous reconnecter.', 'error')
                return redirect(url_for('admin_login'))
        else:
            session.clear()
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def is_rate_limited(ip):
    if ip in login_attempts:
        attempts, timestamp = login_attempts[ip]
        if attempts >= MAX_LOGIN_ATTEMPTS:
            if time.time() - timestamp < LOGIN_TIMEOUT:
                return True
            else:
                login_attempts[ip] = (0, time.time())
    return False

def record_login_attempt(ip, success):
    if ip not in login_attempts:
        login_attempts[ip] = (0, time.time())
    attempts, _ = login_attempts[ip]
    if not success:
        login_attempts[ip] = (attempts + 1, time.time())
    else:
        login_attempts[ip] = (0, time.time())

MAKE_WEBHOOK_URL = os.getenv('MAKE_WEBHOOK_URL', "https://hook.us1.make.com/hz3fzz8mba7sn4se4rl4klo55qbjd1j8")

# Configure timeouts
DEFAULT_TIMEOUT = 10  # seconds
CONNECT_TIMEOUT = 5   # seconds
READ_TIMEOUT = 5      # seconds

def send_to_make_webhook(data):
    # Ensure all values are JSON-serializable (convert datetime to string)
    def make_serializable(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return obj
    serializable_data = {k: make_serializable(v) for k, v in data.items()}
    app_logger.info(f"Preparing to send webhook data: {json.dumps(serializable_data, indent=2)}")
    session = requests.Session()
    retry_strategy = Retry(
        total=5,
        backoff_factor=0.5,
        backoff_max=10,
        status_forcelist=[408, 429, 500, 502, 503, 504],
        allowed_methods=["POST"],
        respect_retry_after_header=True
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=10,
        pool_block=False
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    headers = {
        'Content-Type': 'application/json'
    }
    try:
        start_time = time.time()
        response = session.post(
            MAKE_WEBHOOK_URL,
            json=serializable_data,
            headers=headers,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            verify=False  # temporary test
        )
        duration = time.time() - start_time
        app_logger.info(f"Webhook request completed in {duration:.2f} seconds")
        app_logger.info(f"Webhook response status: {response.status_code}")
        app_logger.info(f"Webhook response headers: {dict(response.headers)}")
        app_logger.info(f"Response body: {response.text}")
        try:
            response_json = response.json()
            app_logger.info(f"Webhook response body (parsed): {json.dumps(response_json, indent=2)}")
        except Exception:
            pass
        if response.status_code == 200:
            app_logger.info("Webhook request successful")
            return True
        elif response.status_code == 429:
            app_logger.warning("Rate limit exceeded, will retry with backoff")
            return False
        elif 500 <= response.status_code < 600:
            app_logger.error(f"Server error: {response.status_code}")
            return False
        else:
            app_logger.error(f"Unexpected status code: {response.status_code}")
            return False
    except requests.exceptions.Timeout as e:
        app_logger.error(f"Request timed out: {str(e)}")
        return False
    except requests.exceptions.ConnectionError as e:
        app_logger.error(f"Connection error: {str(e)}")
        return False
    except requests.exceptions.RequestException as e:
        app_logger.error(f"Request failed: {str(e)}")
        return False
    except Exception as e:
        app_logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return False

@app.route('/', methods=['GET', 'POST'])
def home():
    app_logger.info("Home route accessed")
    if request.method == 'POST':
        app_logger.info(f"🟡 Raw form data: {dict(request.form)}")
        name = request.form.get('name')
        email = request.form.get('email')
        app.logger.info(f"raw form = {dict(request.form)}")
        app.logger.info(f"name={name!r}  email={email!r}")
        guests = request.form.get('guests', '1')
        message = request.form.get('message', '')
        food_contribution = request.form.getlist('food_contribution')
        food_contribution_str = ','.join(food_contribution)
        app_logger.info(f"Received RSVP: name={name}, email={email}, guests={guests}, message={message}, food_contribution={food_contribution_str}")
        if name and email:
            app_logger.info(f"✅ Webhook block entered for: name='{name}', email='{email}'")
            app_logger.info(f"Calling webhook for: {name}, {email}")
            try:
                db = get_db()
                cursor = db.cursor()
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute('''
                    INSERT INTO rsvps (name, email, guests, message, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                ''', (name, email, guests, message, timestamp))
                db.commit()
                db.close()
                app_logger.info(f"Successfully saved RSVP to database for {name}")
                rsvp_data = {
                    "name": name,
                    "email": email,
                    "guests": guests,
                    "message": message,
                    "food_contribution": food_contribution_str,
                    "timestamp": timestamp,
                    "source": "web",
                    "version": "1.0"
                }
                max_attempts = 3
                webhook_success = False
                for attempt in range(max_attempts):
                    if attempt > 0:
                        app_logger.info(f"Retrying webhook (attempt {attempt + 1}/{max_attempts})")
                        time.sleep(2 ** attempt)
                    try:
                        webhook_success = send_to_make_webhook(rsvp_data)
                        if webhook_success:
                            app_logger.info("Webhook notification sent successfully")
                            flash('Merci! Votre RSVP a été enregistré.', 'success')
                            break
                        else:
                            app_logger.warning(f"Webhook attempt {attempt + 1} failed")
                    except Exception as e:
                        app_logger.error(f"Exception during webhook attempt {attempt + 1}: {str(e)}", exc_info=True)
                if not webhook_success:
                    app_logger.error("All webhook attempts failed")
                    flash('Votre RSVP a été enregistré, mais il y a eu un problème avec la notification.', 'warning')
                return redirect(url_for('home'))
            except Exception as e:
                app_logger.error(f"Error processing RSVP: {str(e)}", exc_info=True)
                flash('Une erreur est survenue. Veuillez réessayer.', 'error')
        else:
            app_logger.warning(f"❌ Webhook block skipped: name='{name}', email='{email}'")
            app_logger.warning("Missing required fields in RSVP submission")
            flash('Veuillez remplir tous les champs obligatoires.', 'error')
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM rsvps ORDER BY timestamp DESC')
    rsvps = cursor.fetchall()
    db.close()
    return render_template('index.html', rsvps=rsvps)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        ip = request.remote_addr
        if is_rate_limited(ip):
            remaining_time = int(LOGIN_TIMEOUT - (time.time() - login_attempts[ip][1]))
            flash(f'Trop de tentatives. Veuillez réessayer dans {remaining_time} secondes.', 'error')
            return render_template('admin_login.html')
        password = request.form.get('password')
        if password == app.config['ADMIN_PASSWORD']:
            record_login_attempt(ip, True)
            session['admin_logged_in'] = True
            session['last_activity'] = time.time()
            return redirect(url_for('admin'))
        else:
            record_login_attempt(ip, False)
            flash('Mot de passe incorrect', 'error')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

@app.route('/admin')
@login_required
def admin():
    session['last_activity'] = time.time()
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM rsvps ORDER BY timestamp DESC')
    rsvps = cursor.fetchall()
    db.close()
    total_guests = sum(int(rsvp['guests']) for rsvp in rsvps)
    return render_template('admin.html', rsvps=rsvps, total_guests=total_guests)

@app.route('/health')
def health_check():
    return {'status': 'healthy'}, 200

@app.route('/test-print')
def test_print():
    print("PRINT TEST: This should appear in Render logs", flush=True)
    return "Print test done"

@app.route('/test-webhook', methods=['GET', 'POST'])
def test_webhook():
    app_logger.info("Test webhook endpoint called")
    test_data = {
        "test": True,
        "timestamp": datetime.now().isoformat(),
        "message": "This is a test webhook call"
    }
    app_logger.info(f"Sending test data: {json.dumps(test_data, indent=2)}")
    success = send_to_make_webhook(test_data)
    if success:
        app_logger.info("Test webhook sent successfully")
        return jsonify({"status": "success", "message": "Test webhook sent successfully"}), 200
    else:
        app_logger.error("Failed to send test webhook")
        return jsonify({"status": "error", "message": "Failed to send test webhook"}), 500

if __name__ == '__main__':
    app_logger.info("App is starting in __main__")
    app_logger.info("BOOT-MARK 2025-05-17-23-20")
    port = int(os.getenv('PORT', 10000))
    app.run(host='0.0.0.0', port=port) 