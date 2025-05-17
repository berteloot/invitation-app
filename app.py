import os
from dotenv import load_dotenv
from openai import OpenAI
import json
import logging
from flask import Flask, request, jsonify, render_template, send_file, Response, session, redirect, url_for, flash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime
import config
import pandas as pd
from werkzeug.utils import secure_filename
import io
import csv
from lcs.models.post import Post
from lcs.analysis.analyzer import PostAnalyzer
from lcs.utils.data_handler import DataHandler
from lcs.utils.linkedin_client import LinkedInClient
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import requests
from functools import wraps

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-here')

login_manager = LoginManager()
login_manager.init_app(app)

# Configure rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'csv'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_db():
    db = sqlite3.connect('job_persona.db')
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    cursor = db.cursor()
    
    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT UNIQUE,
            is_admin INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    ''')
    
    # Create personas table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS personas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role_description TEXT,
            key_skills TEXT,
            industry_context TEXT,
            seniority_level TEXT,
            career_path TEXT,
            challenges TEXT,
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Create contacts table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            job_title TEXT,
            company TEXT,
            email TEXT,
            phone TEXT,
            linkedin TEXT,
            matched_persona_id INTEGER,
            confidence_score REAL,
            additional_info TEXT,
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (matched_persona_id) REFERENCES personas (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Create user_activities table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    db.commit()
    db.close()

class User:
    def __init__(self, id, username, password_hash, email, is_admin):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.email = email
        self.is_admin = is_admin

    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    user_data = cursor.fetchone()
    db.close()
    
    if user_data:
        return User(
            id=user_data['id'],
            username=user_data['username'],
            password_hash=user_data['password_hash'],
            email=user_data['email'],
            is_admin=user_data['is_admin']
        )
    return None

class JobPersonaAnalyzer:
    def __init__(self):
        api_key = config.OPENAI_API_KEY
        if not api_key or api_key == "your_openai_api_key_here":
            raise ValueError("OpenAI API key is not properly configured. Please check your config.py file.")
        
        self.client = OpenAI(api_key=api_key)
        self.custom_personas = []
        self.training_data = {}  # Dictionary to store title -> persona mappings

    def load_training_data(self, file_path):
        """Load training data from a CSV file."""
        try:
            df = pd.read_csv(file_path)
            if 'Title' not in df.columns or 'Persona' not in df.columns:
                raise ValueError("Training file must contain 'Title' and 'Persona' columns")
            
            # Add each title-persona pair to training data
            for _, row in df.iterrows():
                if pd.notna(row['Title']) and pd.notna(row['Persona']):
                    title = str(row['Title']).strip()
                    persona = str(row['Persona']).strip()
                    if title and persona:
                        self.training_data[title.lower()] = persona
                        if persona not in self.custom_personas:
                            self.custom_personas.append(persona)
            
            return {
                'training_pairs': len(self.training_data),
                'unique_personas': len(self.custom_personas),
                'personas': self.custom_personas
            }
        except Exception as e:
            logger.error(f"Error loading training data: {str(e)}")
            raise

    def analyze_job_title(self, job_title):
        """Match a job title to the most relevant persona."""
        try:
            if job_title is None or str(job_title).strip().lower() in ['unknown', '']:
                return "Unclear - Review"
            
            job_title_str = str(job_title).strip()
            
            # First check training data for exact match
            if job_title_str.lower() in self.training_data:
                return self.training_data[job_title_str.lower()]
            
            if not self.custom_personas:
                return "No personas defined"
            
            # Prepare training examples and personas
            training_examples = "\n".join([
                f"Title: {title}, Persona: {persona}"
                for title, persona in list(self.training_data.items())[:5]
            ])
            
            personas_text = "\n".join(f"{i+1}. {p}" for i, p in enumerate(self.custom_personas))
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": """You are an expert B2B persona classifier for enterprise software sales.
                    Your task is to definitively match job titles to persona categories.
                    
                    Follow these rules:
                    1. C-level, VP, Head of, General Manager = Executive Decision Maker
                    2. Architect, Technical Lead, Principal Engineer = Technical Authority
                    3. Director, Department Head, Business Lead = Business Unit Leader
                    4. Project Manager, Senior Consultant, Practice Lead = Implementation Expert
                    5. Consultant, Analyst, Specialist = Solution Consultant
                    
                    Be decisive - only use "Unclear - Review" if the title is empty or completely ambiguous.
                    If training examples are provided, use them to inform your matching."""},
                    {"role": "user", "content": f"""Available Personas:
{personas_text}

Training Examples (if any):
{training_examples if self.training_data else "No training examples available."}

Job Title: {job_title_str}

Rules for matching:
- Look for seniority keywords (Chief, VP, Head, Director, Lead, Senior)
- Consider role function (Technical, Business, Project, Sales)
- Match based on decision-making authority and influence
- If multiple matches possible, choose the higher authority level
- Use training examples as reference when similar titles appear

Return ONLY the exact name of the best matching persona from the list."""}
                ]
            )
            
            result = response.choices[0].message.content.strip()
            # Remove any numbering if present
            if '.' in result:
                result = result.split('.', 1)[1].strip()
            
            return result if result in self.custom_personas else "Unclear - Review"
            
        except Exception as e:
            logger.error(f"Error analyzing job title: {str(e)}")
            return "Unclear - Review"

    def analyze_job_title_with_notes(self, job_title):
        """Match a job title to the most relevant persona and provide justification."""
        try:
            if job_title is None:
                return {"persona": "Unclear - Review", "notes": "Empty job title"}
            
            job_title_str = str(job_title).strip()
            if not job_title_str or job_title_str.lower() == 'unknown':
                return {"persona": "Unclear - Review", "notes": "Empty or unknown job title"}
            
            if not self.custom_personas:
                return {"persona": "No personas defined", "notes": "Please generate personas first"}
            
            personas_text = "\n".join(self.custom_personas)
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": """You are an expert B2B marketing strategist and persona classifier.
                    Your task is to match job titles to the most relevant predefined persona category and provide a brief justification.
                    Be decisive in your matching based on these guidelines:
                    - Focus on the person's decision-making level and role in B2B processes
                    - Consider their influence in purchasing and implementation decisions
                    - Look for keywords indicating technical expertise, business authority, or end-user status
                    - Match based on role function rather than specific industry
                    Only mark as "Unclear - Review" if the title is completely ambiguous or empty."""},
                    {"role": "user", "content": f"""Available Personas:
{personas_text}

Job Title: {job_title_str}

Consider these aspects:
1. Level of authority (C-level, Director, Manager, etc.)
2. Function (Technical, Business, Sales, etc.)
3. Decision-making capacity
4. Role in B2B processes

Return the matching persona category name and a brief justification in JSON format:
{{"persona": "category_name", "notes": "brief justification"}}"""}
                ]
            )
            
            try:
                result = json.loads(response.choices[0].message.content.strip())
                if result["persona"] not in self.custom_personas:
                    result["persona"] = "Unclear - Review"
                    if "notes" not in result:
                        result["notes"] = "Could not match to available personas"
                return result
            except:
                return {"persona": "Unclear - Review", "notes": "Error parsing response"}
            
        except Exception as e:
            logger.error(f"Error analyzing job title with notes: {str(e)}")
            return {"persona": "Unclear - Review", "notes": str(e)}

# Initialize the analyzer
analyzer = JobPersonaAnalyzer()

@app.route('/')
def index():
    return render_template('index.html', authenticated='linkedin_token' in session)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        user_data = cursor.fetchone()
        db.close()
        
        if user_data and check_password_hash(user_data['password_hash'], password):
            user = User(
                id=user_data['id'],
                username=user_data['username'],
                password_hash=user_data['password_hash'],
                email=user_data['email'],
                is_admin=user_data['is_admin']
            )
            login_user(user)
            
            # Update last login
            db = get_db()
            cursor = db.cursor()
            cursor.execute('UPDATE users SET last_login = ? WHERE id = ?',
                         (datetime.utcnow(), user.id))
            db.commit()
            db.close()
            
            return jsonify({'status': 'success'})
        return jsonify({'status': 'error', 'message': 'Invalid credentials'}), 401
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return jsonify({'status': 'success'})

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')
        
        if not username or not password:
            return jsonify({'status': 'error', 'message': 'Username and password are required'}), 400
            
        db = get_db()
        cursor = db.cursor()
        
        # Check if username already exists
        cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
        if cursor.fetchone():
            db.close()
            return jsonify({'status': 'error', 'message': 'Username already exists'}), 400
            
        # Create new user
        password_hash = generate_password_hash(password)
        cursor.execute('''
            INSERT INTO users (username, password_hash, email, is_admin)
            VALUES (?, ?, ?, ?)
        ''', (username, password_hash, email, 0))
        
        db.commit()
        db.close()
        
        return jsonify({'status': 'success'})
    
    return render_template('register.html')

@app.route('/generate_personas', methods=['POST'])
def generate_personas():
    """Generate personas based on uploaded job titles."""
    try:
        data = request.json
        num_personas = int(data.get('num_personas', 5))
        job_titles = data.get('job_titles', [])
        
        if not job_titles:
            return jsonify({'error': 'No job titles provided'}), 400
        
        personas = analyzer.generate_personas(job_titles, num_personas)
        return jsonify({
            'status': 'success',
            'personas': personas
        })
    except Exception as e:
        logger.error(f"Error generating personas: {str(e)}")
        return jsonify({'error': str(e)}), 400

@app.route('/set_personas', methods=['POST'])
def set_personas():
    """Set custom personas manually."""
    try:
        data = request.json
        personas = data.get('personas', [])
        
        if not personas:
            return jsonify({'error': 'No personas provided'}), 400
        
        analyzer.custom_personas = [p.strip() for p in personas if p.strip()]
        return jsonify({
            'status': 'success',
            'personas': analyzer.custom_personas
        })
    except Exception as e:
        logger.error(f"Error setting personas: {str(e)}")
        return jsonify({'error': str(e)}), 400

def process_file(file_path, include_notes=False):
    """Process the uploaded CSV file."""
    try:
        df = pd.read_csv(file_path, sep=',', encoding='utf-8')
        
        required_columns = ['First Name', 'Last Name', 'Title', 'Company']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")
        
        results = []
        for _, row in df.iterrows():
            job_title = str(row['Title']) if pd.notna(row['Title']) else None
            
            if include_notes:
                analysis = analyzer.analyze_job_title_with_notes(job_title)
                persona = analysis['persona']
                notes = analysis['notes']
            else:
                persona = analyzer.analyze_job_title(job_title)
                notes = None
            
            result = {
                'first_name': str(row['First Name']) if pd.notna(row['First Name']) else '',
                'last_name': str(row['Last Name']) if pd.notna(row['Last Name']) else '',
                'title': job_title if job_title is not None else 'Unknown',
                'company': str(row['Company']) if pd.notna(row['Company']) else '',
                'persona': persona
            }
            
            if notes:
                result['notes'] = notes
            
            optional_fields = ['Email', 'Phone', 'LinkedIn', 'Location', 'Industry']
            for field in optional_fields:
                if field in df.columns and pd.notna(row[field]):
                    result[field.lower()] = str(row[field])
            
            results.append(result)
        
        return results
    except Exception as e:
        logger.error(f"Error processing file - {str(e)}")
        raise

@app.route('/api/profile')
@login_required
@limiter.limit("10 per minute")
def get_profile():
    try:
        # LinkedIn integration removed, so this route is not available
        return jsonify({'error': 'LinkedIn integration removed'}), 400
    except Exception as e:
        logger.error(f"Profile fetch error: {str(e)}")
        return jsonify({'error': 'Failed to fetch profile'}), 500

@app.route('/api/connections')
@login_required
@limiter.limit("5 per minute")
def get_connections():
    try:
        # LinkedIn integration removed, so this route is not available
        return jsonify({'error': 'LinkedIn integration removed'}), 400
    except Exception as e:
        logger.error(f"Connections fetch error: {str(e)}")
        return jsonify({'error': 'Failed to fetch connections'}), 500

@app.route('/upload', methods=['POST'])
@login_required
@limiter.limit("10 per hour")
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Only CSV files are allowed'}), 400
    
    try:
        # Validate CSV structure
        is_valid, error_message = validate_csv(file)
        if not is_valid:
            return jsonify({'error': error_message}), 400
        
        # Process the file
        results = process_linkedin_data(file)
        return jsonify({'results': results})
    except Exception as e:
        logger.error(f"File processing error: {str(e)}")
        return jsonify({'error': 'Error processing file'}), 500

@app.route('/export', methods=['POST'])
@login_required
@limiter.limit("5 per hour")
def export_data():
    try:
        data = request.json.get('data', [])
        if not data:
            return jsonify({'error': 'No data to export'}), 400
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers
        headers = ['Name', 'Title', 'Company', 'Location', 'Connection Date']
        writer.writerow(headers)
        
        # Write data
        for row in data:
            writer.writerow([
                row.get('name', ''),
                row.get('title', ''),
                row.get('company', ''),
                row.get('location', ''),
                row.get('connection_date', '')
            ])
        
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode()),
            mimetype='text/csv',
            as_attachment=True,
            download_name='linkedin_export.csv'
        )
    except Exception as e:
        logger.error(f"Export error: {str(e)}")
        return jsonify({'error': 'Error exporting data'}), 500

def process_linkedin_data(file):
    results = []
    try:
        reader = csv.DictReader(io.StringIO(file.read().decode('utf-8')))
        for row in reader:
            results.append({
                'name': f"{row.get('First Name', '')} {row.get('Last Name', '')}".strip(),
                'title': row.get('Title', ''),
                'company': row.get('Company', ''),
                'location': row.get('Location', ''),
                'connection_date': row.get('Connected On', '')
            })
    except Exception as e:
        logger.error(f"Data processing error: {str(e)}")
        raise
    return results

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_csv(file):
    try:
        # Read first few lines to validate structure
        content = file.read(1024).decode('utf-8')
        file.seek(0)  # Reset file pointer
        
        # Check for required columns
        required_columns = ['First Name', 'Last Name', 'Title', 'Company']
        reader = csv.DictReader(io.StringIO(content))
        if not all(col in reader.fieldnames for col in required_columns):
            return False, "CSV file must contain required columns: First Name, Last Name, Title, Company"
        
        return True, None
    except Exception as e:
        logger.error(f"CSV validation error: {str(e)}")
        return False, "Invalid CSV file format"

@app.route('/lcs/dashboard')
@login_required
def lcs_dashboard():
    """Render the LinkedIn Content Strategist dashboard."""
    return render_template('lcs_dashboard.html')

@app.route('/lcs/authenticate', methods=['POST'])
@login_required
def lcs_authenticate():
    """Handle LinkedIn authentication."""
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        
        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400
        
        # LinkedIn integration removed, so this route is not available
        return jsonify({'error': 'LinkedIn integration removed'}), 400
    
    except Exception as e:
        logger.error(f"LinkedIn authentication error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/lcs/analyze', methods=['POST'])
@login_required
def lcs_analyze():
    """Analyze a LinkedIn profile's posts."""
    try:
        data = request.json
        profile_url = data.get('profile_url')
        
        if not profile_url:
            return jsonify({'error': 'Profile URL is required'}), 400
        
        # LinkedIn integration removed, so this route is not available
        return jsonify({'error': 'LinkedIn integration removed'}), 400
    
    except Exception as e:
        logger.error(f"Error analyzing LinkedIn profile: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/lcs/upload', methods=['POST'])
@login_required
def lcs_upload():
    """Handle LinkedIn post data upload."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not file.filename.endswith('.csv'):
        return jsonify({'error': 'Only CSV files are supported'}), 400
    
    try:
        # Save the uploaded file
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # Process the file
        posts = DataHandler.import_from_csv(file_path)
        analyzer = PostAnalyzer(posts)
        
        # Generate insights
        insights = {
            'engagement_stats': analyzer.get_engagement_stats(),
            'sentiment_analysis': analyzer.analyze_sentiment(),
            'content_recommendations': analyzer.get_content_recommendations(),
            'top_posts': analyzer.get_top_performing_posts(5).to_dict('records')
        }
        
        return jsonify(insights)
    
    except Exception as e:
        logger.error(f"Error processing LinkedIn data: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/lcs/export', methods=['POST'])
@login_required
def lcs_export():
    """Export analysis results to CSV."""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Create a temporary file
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(['Metric', 'Value'])
        
        # Write engagement stats
        writer.writerow(['Engagement Statistics', ''])
        for key, value in data['engagement_stats'].items():
            writer.writerow([key, value])
        
        # Write sentiment analysis
        writer.writerow(['', ''])
        writer.writerow(['Sentiment Analysis', ''])
        for key, value in data['sentiment_analysis'].items():
            writer.writerow([key, value])
        
        # Write recommendations
        writer.writerow(['', ''])
        writer.writerow(['Content Recommendations', ''])
        for key, value in data['content_recommendations'].items():
            if isinstance(value, dict):
                for subkey, subvalue in value.items():
                    writer.writerow([f"{key} - {subkey}", subvalue])
            else:
                writer.writerow([key, value])
        
        # Prepare response
        output.seek(0)
        return Response(
            output,
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment;filename=linkedin_analysis.csv'}
        )
    
    except Exception as e:
        logger.error(f"Error exporting LinkedIn analysis: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/summarize', methods=['GET', 'POST'])
def summarize():
    if request.method == 'POST':
        try:
            # Check if OpenAI API key is configured
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                raise ValueError("OpenAI API key is not configured. Please check your environment variables.")

            text = request.form.get('text', '').strip()
            word_count = request.form.get('word_count', '').strip()
            custom_prompt = request.form.get('prompt', '').strip()
            
            # Validate inputs
            if not text:
                flash('Please enter text to summarize', 'error')
                return render_template('summarize.html')
            
            try:
                word_count = int(word_count)
                if word_count < 1:
                    raise ValueError
            except ValueError:
                flash('Please enter a valid word count (minimum 1)', 'error')
                return render_template('summarize.html')
            
            # Initialize OpenAI client
            client = OpenAI(api_key=api_key)
            
            # Default prompt if none provided
            if not custom_prompt:
                custom_prompt = f"""Summarize the following text in exactly {word_count} words. 
                Maintain the original tone and key message while being concise and clear. 
                Optimize for audio consumption with natural, listener-friendly language."""
            
            try:
                # Call OpenAI API for summarization
                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are a professional summarization assistant."},
                        {"role": "user", "content": f"{custom_prompt}\n\nText to summarize:\n{text}"}
                    ],
                    max_tokens=500,
                    temperature=0.7
                )
                
                summary = response.choices[0].message.content.strip()
                
                # Count actual words in summary
                actual_word_count = len(summary.split())
                
                return render_template('summarize.html', 
                                     summary=summary, 
                                     word_count=actual_word_count,
                                     original_text=text,
                                     original_word_count=word_count)
                
            except Exception as api_error:
                logger.error(f"OpenAI API Error: {str(api_error)}")
                flash(f'Error with OpenAI API: {str(api_error)}', 'error')
                return render_template('summarize.html')
            
        except Exception as e:
            logger.error(f"Error in summarization: {str(e)}")
            flash(f'Error generating summary: {str(e)}', 'error')
            return render_template('summarize.html')
    
    return render_template('summarize.html')

if __name__ == "__main__":
    # Run the app
    app.run(debug=True, port=5003, host='localhost') 