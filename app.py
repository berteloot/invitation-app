from flask import Flask, render_template, request, flash, redirect, url_for, jsonify, session
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import json
from functools import wraps
import time

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-dev-key')
app.config['ENV'] = os.getenv('FLASK_ENV', 'production')
app.config['ADMIN_PASSWORD'] = os.getenv('ADMIN_PASSWORD', 'admin123')  # Change this in production!

# File to store RSVPs
RSVP_FILE = 'rsvps.json'

# Rate limiting configuration
MAX_LOGIN_ATTEMPTS = 5
LOGIN_TIMEOUT = 300  # 5 minutes in seconds
login_attempts = {}

def load_rsvps():
    if os.path.exists(RSVP_FILE):
        with open(RSVP_FILE, 'r') as f:
            return json.load(f)
    return []

def save_rsvps(rsvps):
    with open(RSVP_FILE, 'w') as f:
        json.dump(rsvps, f, indent=2)

# Load existing RSVPs
rsvps = load_rsvps()

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
        food_contribution = request.form.getlist('food_contribution')
        food_contribution_str = ', '.join(food_contribution) if food_contribution else None
        
        if name and email:
            db = get_db()
            cursor = db.cursor()
            cursor.execute('''
                INSERT INTO rsvps (name, email, guests, dietary_restrictions, food_contribution)
                VALUES (?, ?, ?, ?, ?)
            ''', (name, email, guests, message, food_contribution_str))
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

    # Count food contributions
    bring_options = [
        "Meat or Plant-Based Mains",
        "Drinks",
        "Side Dish or Salad",
        "Dessert"
    ]
    bring_counts = {option: 0 for option in bring_options}
    for rsvp in rsvps:
        if rsvp['food_contribution']:
            for option in bring_options:
                if option in rsvp['food_contribution']:
                    bring_counts[option] += 1

    # Find the least selected (most needed) item(s)
    min_count = min(bring_counts.values())
    most_needed_items = [k for k, v in bring_counts.items() if v == min_count]

    db.close()
    
    return render_template(
        'index.html',
        rsvps=rsvps,
        bring_counts=bring_counts,
        most_needed_items=most_needed_items
    )

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
    total_guests = sum(int(rsvp['guests']) for rsvp in rsvps)
    return render_template('admin.html', rsvps=rsvps, total_guests=total_guests)

@app.route('/health')
def health_check():
    return {'status': 'healthy'}, 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    app.run(host='0.0.0.0', port=port) 