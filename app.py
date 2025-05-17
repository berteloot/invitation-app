from flask import Flask, render_template, request, flash, redirect, url_for
from dotenv import load_dotenv
import os
from datetime import datetime

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-dev-key')
app.config['ENV'] = os.getenv('FLASK_ENV', 'production')

# Store RSVPs in memory (in production, you'd use a database)
rsvps = []

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
            flash('Merci! Votre RSVP a été enregistré.', 'success')
            return redirect(url_for('home'))
        else:
            flash('Veuillez remplir tous les champs obligatoires.', 'error')
    
    return render_template('index.html', rsvps=rsvps)

@app.route('/health')
def health_check():
    return {'status': 'healthy'}, 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    app.run(host='0.0.0.0', port=port) 