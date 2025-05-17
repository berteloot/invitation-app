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

# Configure logging
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'app.log')

# Create a formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Create a file handler
file_handler = RotatingFileHandler(log_file, maxBytes=1024 * 1024, backupCount=5)
file_handler.setFormatter(formatter)

# Create a stream handler for console output
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

# Get the root logger and configure it
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(stream_handler)

# Create a logger for this module
app_logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-dev-key')
app.config['ENV'] = os.getenv('FLASK_ENV', 'production')
app.config['ADMIN_PASSWORD'] = os.getenv('ADMIN_PASSWORD', 'admin123')  # Change this in production!

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

MAKE_WEBHOOK_URL = "https://hook.us1.make.com/hz3fzz8mba7sn4se4rl4klo55qbjd1j8"

# Configure requests session with retry strategy
session = requests.Session()
retry_strategy = Retry(
    total=3,  # number of retries
    backoff_factor=1,  # wait 1, 2, 4 seconds between retries
    status_forcelist=[500, 502, 503, 504]  # HTTP status codes to retry on
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)
session.mount("http://", adapter)

def send_to_make_webhook(data):
    app_logger.info(f"Preparing to send webhook data: {data}")
    try:
        start_time = time.time()
        response = session.post(MAKE_WEBHOOK_URL, json=data, timeout=10)
        duration = time.time() - start_time
        
        app_logger.info(f"Webhook request completed in {duration:.2f} seconds")
        app_logger.info(f"Webhook response status: {response.status_code}")
        app_logger.info(f"Webhook response headers: {dict(response.headers)}")
        app_logger.info(f"Webhook response text: {response.text}")
        
        if response.status_code >= 400:
            app_logger.error(f"Webhook request failed with status {response.status_code}")
            return False
            
        return True
    except requests.exceptions.Timeout:
        app_logger.error("Webhook request timed out after 10 seconds")
        return False
    except requests.exceptions.ConnectionError as e:
        app_logger.error(f"Webhook connection error: {str(e)}")
        return False
    except requests.exceptions.RequestException as e:
        app_logger.error(f"Webhook request failed: {str(e)}")
        return False
    except Exception as e:
        app_logger.error(f"Unexpected error in webhook request: {str(e)}")
        return False

@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        guests = request.form.get('guests', '1')
        message = request.form.get('message', '')
        food_contribution = request.form.getlist('food_contribution')
        food_contribution_str = ','.join(food_contribution)
        
        app_logger.info(f"Received RSVP: name={name}, email={email}, guests={guests}, message={message}, food_contribution={food_contribution_str}")
        
        if name and email:
            try:
                # Save to database
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

                # Send to webhook
                rsvp_data = {
                    "name": name,
                    "email": email,
                    "guests": guests,
                    "message": message,
                    "food_contribution": food_contribution_str,
                    "timestamp": timestamp
                }
                
                webhook_success = send_to_make_webhook(rsvp_data)
                if webhook_success:
                    app_logger.info("Webhook notification sent successfully")
                    flash('Merci! Votre RSVP a été enregistré.', 'success')
                else:
                    app_logger.warning("RSVP saved but webhook notification failed")
                    flash('Votre RSVP a été enregistré, mais il y a eu un problème avec la notification.', 'warning')
                
                return redirect(url_for('home'))
                
            except Exception as e:
                app_logger.error(f"Error processing RSVP: {str(e)}", exc_info=True)
                flash('Une erreur est survenue. Veuillez réessayer.', 'error')
        else:
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

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    app.run(host='0.0.0.0', port=port) 