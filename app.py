from flask import Flask, render_template, request, flash, redirect, url_for, jsonify
from dotenv import load_dotenv
import os
from datetime import datetime
import json

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-dev-key')
app.config['ENV'] = os.getenv('FLASK_ENV', 'production')

# File to store RSVPs
RSVP_FILE = 'rsvps.json'

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

@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        guests = request.form.get('guests', '1')
        message = request.form.get('message', '')
        
        if name and email:
            rsvp = {
                'name': name,
                'email': email,
                'guests': guests,
                'message': message,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            rsvps.append(rsvp)
            save_rsvps(rsvps)  # Save to file
            flash('Merci! Votre RSVP a été enregistré.', 'success')
            return redirect(url_for('home'))
        else:
            flash('Veuillez remplir tous les champs obligatoires.', 'error')
    
    return render_template('index.html', rsvps=rsvps)

@app.route('/admin')
def admin():
    total_guests = sum(int(rsvp['guests']) for rsvp in rsvps)
    return render_template('admin.html', rsvps=rsvps, total_guests=total_guests)

@app.route('/health')
def health_check():
    return {'status': 'healthy'}, 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    app.run(host='0.0.0.0', port=port) 