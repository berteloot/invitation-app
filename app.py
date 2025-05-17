from flask import Flask, render_template, request, flash, redirect, url_for, jsonify, session
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import json
from functools import wraps
import time
import sqlite3

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-dev-key')
app.config['ENV'] = os.getenv('FLASK_ENV', 'production')
app.config['ADMIN_PASSWORD'] = os.getenv('ADMIN_PASSWORD', 'admin123')  # Change this in production!

def get_db():
    # Ensure the database directory exists
    db_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
    os.makedirs(db_dir, exist_ok=True)
    
    db_path = os.path.join(db_dir, 'job_persona.db')
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    cursor = db.cursor()
    
    # Create rsvps table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rsvps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            attending INTEGER DEFAULT 1,
            guests INTEGER DEFAULT 0,
            dietary_restrictions TEXT,
            food_contribution TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    db.commit()
    db.close()

# Initialize the database when the app starts
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
        
        # Check session timeout (30 minutes)
        if 'last_activity' in session:
            last_activity = session['last_activity']
            if time.time() - last_activity > 1800:  # 30 minutes
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
                # Reset attempts after timeout
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

@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        guests = request.form.get('guests', '1')
        message = request.form.get('message', '')
        
        if name and email:
            db = get_db()
            cursor = db.cursor()
            cursor.execute('''
                INSERT INTO rsvps (name, email, guests, dietary_restrictions)
                VALUES (?, ?, ?, ?)
            ''', (name, email, guests, message))
            db.commit()
            db.close()
            
            flash('Merci! Votre RSVP a été enregistré.', 'success')
            return redirect(url_for('home'))
        else:
            flash('Veuillez remplir tous les champs obligatoires.', 'error')
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM rsvps')
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
    # Update last activity time
    session['last_activity'] = time.time()
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM rsvps')
    rsvps = cursor.fetchall()
    db.close()
    
    total_guests = sum(int(rsvp['guests']) for rsvp in rsvps)
    return render_template('admin.html', rsvps=rsvps, total_guests=total_guests)

@app.route('/check_rsvp', methods=['GET', 'POST'])
def check_rsvp():
    if request.method == 'POST':
        email = request.form.get('email')
        if not email:
            flash('Please enter your email address.', 'danger')
            return render_template('check_rsvp.html')
        
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT * FROM rsvps WHERE email = ?', (email,))
        rsvp = cursor.fetchone()
        db.close()
        
        if rsvp:
            return render_template('check_rsvp.html', rsvp=rsvp)
        else:
            flash('No RSVP found for this email address.', 'warning')
            return render_template('check_rsvp.html')
    
    return render_template('check_rsvp.html')

@app.route('/rsvp', methods=['GET', 'POST'])
def submit_rsvp():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        attending = int(request.form.get('attending', 1))
        guests = int(request.form.get('guests', 0))
        dietary_restrictions = request.form.get('dietary_restrictions', '')
        food_contribution = request.form.get('food_contribution') if attending else None

        if not name or not email:
            flash('Please provide your name and email address.', 'danger')
            return render_template('rsvp_form.html')

        db = get_db()
        cursor = db.cursor()
        
        # Check if RSVP already exists for this email
        cursor.execute('SELECT id FROM rsvps WHERE email = ?', (email,))
        existing_rsvp = cursor.fetchone()
        
        if existing_rsvp:
            # Update existing RSVP
            cursor.execute('''
                UPDATE rsvps 
                SET name = ?, attending = ?, guests = ?, dietary_restrictions = ?, 
                    food_contribution = ?, updated_at = CURRENT_TIMESTAMP
                WHERE email = ?
            ''', (name, attending, guests, dietary_restrictions, food_contribution, email))
            flash('Your RSVP has been updated!', 'success')
        else:
            # Create new RSVP
            cursor.execute('''
                INSERT INTO rsvps (name, email, attending, guests, dietary_restrictions, food_contribution)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (name, email, attending, guests, dietary_restrictions, food_contribution))
            flash('Thank you for your RSVP!', 'success')
        
        db.commit()
        db.close()
        
        return redirect(url_for('check_rsvp'))
    
    return render_template('rsvp_form.html')

@app.route('/health')
def health_check():
    return {'status': 'healthy'}, 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
