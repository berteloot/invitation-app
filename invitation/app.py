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

# Get the logger for this module
app_logger = logging.getLogger('app')

# Configure logging to use stdout/stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.StreamHandler(sys.stderr)
    ]
)

# Ensure the logger propagates to the root logger
app_logger.propagate = True

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

# Configure requests session with advanced retry strategy
session = requests.Session()

# Custom retry strategy with more granular control
retry_strategy = Retry(
    total=5,  # increased number of retries
    backoff_factor=0.5,  # shorter initial backoff
    backoff_max=10,  # maximum backoff time
    status_forcelist=[408, 429, 500, 502, 503, 504],  # expanded list of retry status codes
    allowed_methods=["POST"],  # only retry POST requests
    respect_retry_after_header=True  # respect server's retry-after header
)

# Configure connection pooling
adapter = HTTPAdapter(
    max_retries=retry_strategy,
    pool_connections=10,  # number of connections to keep in pool
    pool_maxsize=10,  # maximum number of connections in pool
    pool_block=False  # don't block when pool is full
)

# Mount the adapter for both HTTP and HTTPS
session.mount("https://", adapter)
session.mount("http://", adapter)

# Configure timeouts
DEFAULT_TIMEOUT = 10  # seconds
CONNECT_TIMEOUT = 5   # seconds
READ_TIMEOUT = 5      # seconds

def send_to_make_webhook(data):
    """
    Send data to Make.com webhook with enhanced reliability and error handling.
    """
    app_logger.info(f"Preparing to send webhook data: {json.dumps(data, indent=2)}")
    
    # Prepare headers
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'RSVP-App/1.0',
        'Accept': 'application/json'
    }
    
    try:
        start_time = time.time()
        
        # Make the request with explicit timeouts
        response = session.post(
            MAKE_WEBHOOK_URL,
            json=data,
            headers=headers,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            verify=True  # verify SSL certificates
        )
        
        duration = time.time() - start_time
        app_logger.info(f"Webhook request completed in {duration:.2f} seconds")
        app_logger.info(f"Webhook response status: {response.status_code}")
        app_logger.info(f"Webhook response headers: {dict(response.headers)}")
        
        # Try to parse response as JSON
        try:
            response_json = response.json()
            app_logger.info(f"Webhook response body: {json.dumps(response_json, indent=2)}")
        except json.JSONDecodeError:
            app_logger.info(f"Webhook response text: {response.text}")
        
        # Handle different response status codes
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

                # Prepare webhook data
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
                
                # Attempt webhook with retries
                max_attempts = 3
                for attempt in range(max_attempts):
                    if attempt > 0:
                        app_logger.info(f"Retrying webhook (attempt {attempt + 1}/{max_attempts})")
                        time.sleep(2 ** attempt)  # exponential backoff
                    
                    webhook_success = send_to_make_webhook(rsvp_data)
                    if webhook_success:
                        app_logger.info("Webhook notification sent successfully")
                        flash('Merci! Votre RSVP a été enregistré.', 'success')
                        break
                    elif attempt == max_attempts - 1:
                        app_logger.warning("All webhook attempts failed")
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