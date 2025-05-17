import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from openai import OpenAI
from datetime import datetime, timedelta
import secrets
import pandas as pd
from io import StringIO
import re
from difflib import SequenceMatcher
from collections import defaultdict
import logging
from math import ceil
from sqlalchemy import text

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(16))

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///persona.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Email configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')

# Initialize extensions
db = SQLAlchemy(app)
mail = Mail(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Initialize OpenAI client only if API key is available
openai_api_key = os.getenv('OPENAI_API_KEY')
client = OpenAI(api_key=openai_api_key) if openai_api_key else None

# In-memory cache for job title analysis
job_title_cache = {}

# Batch analyze job titles with OpenAI
BATCH_SIZE = 20

# Department Group model
class DepartmentGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    contacts = db.relationship('Contact', backref='department_group', lazy=True)

# Update Contact model to include department group
class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False)
    job_title = db.Column(db.String(200))
    persona = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    department_group_id = db.Column(db.Integer, db.ForeignKey('department_group.id'))

# Update User model to include department groups
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    reset_token = db.Column(db.String(100), unique=True)
    reset_token_expiry = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    contacts = db.relationship('Contact', backref='user', lazy=True)
    department_groups = db.relationship('DepartmentGroup', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_reset_token(self):
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expiry = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()
        return self.reset_token

# Helper functions for job title processing
def normalize_job_title(title):
    if not title:
        return ""
    # Convert to lowercase and remove punctuation
    title = re.sub(r'[^\w\s]', '', title.lower())
    # Remove common words
    common_words = ['the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by']
    words = [word for word in title.split() if word not in common_words]
    return ' '.join(words)

def similar(a, b, threshold=0.8):
    return SequenceMatcher(None, a, b).ratio() > threshold

def analyze_job_title(title, client):
    """Use OpenAI to analyze a job title and determine its department."""
    try:
        prompt = f"""Analyze this job title and determine which department it belongs to: "{title}"
        
        Consider:
        1. The role's primary function
        2. Common industry standards
        3. Typical reporting structure
        4. Key responsibilities
        
        Return the response in this format:
        Department: [department name]
        Confidence: [high/medium/low]
        Reasoning: [brief explanation]
        Alternative Departments: [comma-separated list if applicable]
        """
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an expert in organizational structure and job role analysis."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error analyzing job title: {str(e)}")
        return None

def get_department_group(title, client):
    """Get department group for a job title using OpenAI analysis."""
    if not title:
        return 'other'
    
    # First try to normalize and match with predefined groups
    normalized_title = normalize_job_title(title)
    
    # Define department mappings
    department_mappings = {
        'finance': ['finance', 'accounting', 'controller', 'cfo', 'treasurer', 'audit'],
        'it': ['it', 'technology', 'software', 'systems', 'infrastructure', 'cio', 'cto'],
        'marketing': ['marketing', 'brand', 'communications', 'growth', 'digital', 'cmo'],
        'hr': ['hr', 'human resources', 'people', 'talent', 'recruitment', 'chro'],
        'operations': ['operations', 'procurement', 'supply chain', 'logistics', 'operations'],
        'sales': ['sales', 'business development', 'account executive', 'cso'],
        'product': ['product', 'development', 'engineering', 'r&d', 'cto'],
        'executive': ['ceo', 'president', 'founder', 'owner', 'managing director'],
        'legal': ['legal', 'compliance', 'regulatory', 'general counsel'],
        'strategy': ['strategy', 'business development', 'corporate development']
    }
    
    # Check each department's keywords
    for dept, keywords in department_mappings.items():
        if any(keyword in normalized_title for keyword in keywords):
            return dept
    
    # If no clear match, use OpenAI to analyze
    if client:
        analysis = analyze_job_title(title, client)
        if analysis:
            # Parse the analysis response
            lines = analysis.split('\n')
            department = None
            confidence = None
            
            for line in lines:
                if line.startswith('Department:'):
                    department = line.replace('Department:', '').strip().lower()
                elif line.startswith('Confidence:'):
                    confidence = line.replace('Confidence:', '').strip().lower()
            
            if department and confidence:
                # Only use the AI suggestion if confidence is high
                if confidence == 'high':
                    return department
                elif confidence == 'medium':
                    # For medium confidence, check if it matches any existing department
                    for dept in department_mappings.keys():
                        if similar(department, dept):
                            return dept
    
    return 'other'

def suggest_personas(department_groups, client):
    """Generate personas using OpenAI analysis."""
    personas = []
    min_contacts = 5
    
    # Sort departments by contact count
    sorted_departments = sorted(department_groups.items(), key=lambda x: len(x[1]), reverse=True)
    
    # Generate personas for departments with enough contacts
    for dept, contacts in sorted_departments:
        if len(contacts) >= min_contacts:
            try:
                # Get sample job titles for context
                sample_titles = [contact.job_title for contact in contacts[:3]]
                
                prompt = f"""Create a detailed B2B buyer persona for the following department:
                Department: {dept}
                Sample Job Titles: {', '.join(sample_titles)}
                Number of Contacts: {len(contacts)}
                
                Return the response in this format:
                Title: [persona title]
                Description: [brief description]
                Key Characteristics: [bullet points]
                """
                
                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are an expert in B2B marketing and buyer persona development."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7
                )
                
                persona_data = response.choices[0].message.content.strip()
                
                # Parse the persona data
                lines = persona_data.split('\n')
                title = None
                description = None
                
                for line in lines:
                    if line.startswith('Title:'):
                        title = line.replace('Title:', '').strip()
                    elif line.startswith('Description:'):
                        description = line.replace('Description:', '').strip()
                
                if title and description:
                    persona = {
                        'department': dept,
                        'count': len(contacts),
                        'title': title,
                        'description': description
                    }
                    personas.append(persona)
                    
                    if len(personas) >= 5:  # Limit to 5 personas
                        break
                        
            except Exception as e:
                print(f"Error generating persona for {dept}: {str(e)}")
                # Fallback to basic persona if AI generation fails
                persona = {
                    'department': dept,
                    'count': len(contacts),
                    'title': f"The {dept.title()} Leader",
                    'description': f"Senior decision maker in {dept} with {len(contacts)} contacts"
                }
                personas.append(persona)
    
    return personas

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def send_reset_email(user):
    if not app.config['MAIL_USERNAME'] or not app.config['MAIL_PASSWORD']:
        flash('Email configuration is not set up. Please contact the administrator.', 'error')
        return False
    
    token = user.generate_reset_token()
    reset_url = url_for('reset_password', token=token, _external=True)
    msg = Message('Password Reset Request',
                  recipients=[user.email])
    msg.body = f'''To reset your password, visit the following link:
{reset_url}

If you did not make this request then simply ignore this email.
'''
    try:
        mail.send(msg)
        return True
    except Exception as e:
        flash('Failed to send email. Please try again later.', 'error')
        return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = request.form.get('remember', False)
        
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        
        flash('Invalid email or password', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return redirect(url_for('register'))
        
        user = User(email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        
        if user:
            if send_reset_email(user):
                flash('Password reset instructions have been sent to your email.', 'info')
            return redirect(url_for('login'))
        
        flash('Email not found.', 'error')
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    user = User.query.filter_by(reset_token=token).first()
    if not user or user.reset_token_expiry < datetime.utcnow():
        flash('Invalid or expired reset token.', 'error')
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('reset_password.html', token=token)
        
        user.set_password(password)
        user.reset_token = None
        user.reset_token_expiry = None
        db.session.commit()
        
        flash('Your password has been reset. Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('reset_password.html', token=token)

def batch_analyze_job_titles(titles, client):
    """Batch analyze job titles using OpenAI and return a mapping."""
    if not client or not titles:
        return {}
    
    prompt = """For each of the following job titles, determine the most likely department. Return a JSON object mapping each job title to a department, confidence (high/medium/low), and a brief reasoning. Example:
{"Job Title": {"department": "Department Name", "confidence": "high", "reasoning": "..."}}

Job Titles:
"""
    for t in titles:
        prompt += f"- {t}\n"
    prompt += "\nJSON:"
    
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an expert in organizational structure and job role analysis. Respond only with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=1500
        )
        import json
        # Find the first { and last } to extract JSON
        content = response.choices[0].message.content
        start = content.find('{')
        end = content.rfind('}') + 1
        mapping = json.loads(content[start:end])
        return mapping
    except Exception as e:
        print(f"Batch OpenAI error: {e}")
        return {}

def get_department_group_batched(title, cache):
    """Get department from cache or fallback to 'other'."""
    result = cache.get(title)
    if result and result.get('confidence') == 'high':
        return result['department'].lower()
    return 'other'

@app.route('/upload-contacts', methods=['POST'])
@login_required
def upload_contacts():
    logger.debug("Starting file upload process")
    
    if 'file' not in request.files:
        logger.error("No file part in request")
        flash('No file uploaded', 'error')
        return redirect(url_for('index'))
    
    file = request.files['file']
    logger.debug(f"Received file: {file.filename}")
    
    if file.filename == '':
        logger.error("No file selected")
        flash('No file selected', 'error')
        return redirect(url_for('index'))
    
    if not file.filename.endswith('.csv'):
        logger.error(f"Invalid file type: {file.filename}")
        flash('Please upload a CSV file', 'error')
        return redirect(url_for('index'))
    
    try:
        # Read the CSV file
        logger.debug("Attempting to read CSV file")
        df = pd.read_csv(file)
        logger.debug(f"Successfully read CSV file with {len(df)} rows")
        
        # Check required columns
        required_columns = ['email', 'job_title', 'persona']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logger.error(f"Missing required columns: {missing_columns}")
            flash(f'Missing required columns: {", ".join(missing_columns)}', 'error')
            return redirect(url_for('index'))
        
        # Unique job titles
        unique_titles = list(set(df['job_title'].dropna()))
        titles_to_query = [t for t in unique_titles if t not in job_title_cache]
        logger.debug(f"Unique job titles: {len(unique_titles)}, to query: {len(titles_to_query)}")
        
        # Batch query OpenAI for uncached titles
        for i in range(ceil(len(titles_to_query) / BATCH_SIZE)):
            batch = titles_to_query[i*BATCH_SIZE:(i+1)*BATCH_SIZE]
            mapping = batch_analyze_job_titles(batch, client)
            for t in batch:
                if t in mapping:
                    job_title_cache[t] = mapping[t]
        
        # Group contacts by department using cache
        department_groups = defaultdict(list)
        ungrouped_titles = []
        for _, row in df.iterrows():
            dept = get_department_group_batched(row['job_title'], job_title_cache)
            if dept == 'other':
                ungrouped_titles.append(row['job_title'])
            department_groups[dept].append(row)
        logger.debug(f"Grouped contacts into {len(department_groups)} departments")
        
        # Create department groups and contacts
        for dept, contacts in department_groups.items():
            try:
                dept_group = DepartmentGroup.query.filter_by(
                    name=dept,
                    user_id=current_user.id
                ).first()
                if not dept_group:
                    logger.debug(f"Creating new department group: {dept}")
                    dept_group = DepartmentGroup(
                        name=dept,
                        user_id=current_user.id
                    )
                    db.session.add(dept_group)
                    db.session.flush()
                for contact_data in contacts:
                    contact = Contact(
                        email=contact_data['email'],
                        job_title=contact_data['job_title'],
                        persona=contact_data['persona'],
                        user_id=current_user.id,
                        department_group_id=dept_group.id
                    )
                    db.session.add(contact)
            except Exception as e:
                logger.error(f"Error processing department {dept}: {str(e)}")
                continue
        logger.debug("Committing changes to database")
        db.session.commit()
        logger.debug("Generating personas")
        personas = suggest_personas(department_groups, client)
        message = f'Successfully uploaded {len(df)} contacts and grouped them into {len(department_groups)} departments.'
        if ungrouped_titles:
            message += f' {len(ungrouped_titles)} job titles could not be grouped automatically.'
        logger.info(message)
        flash(message, 'success')
        session['upload_stats'] = {
            'total_contacts': len(df),
            'total_departments': len(department_groups),
            'ungrouped_count': len(ungrouped_titles)
        }
        return redirect(url_for('dashboard'))
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}", exc_info=True)
        db.session.rollback()
        flash(f'Error processing file: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    # Get all department groups for the current user
    department_groups = DepartmentGroup.query.filter_by(user_id=current_user.id).all()
    
    # Calculate statistics
    total_contacts = sum(len(group.contacts) for group in department_groups)
    total_departments = len(department_groups)
    
    # Get top 5 departments by contact count
    top_departments = sorted(
        department_groups,
        key=lambda x: len(x.contacts),
        reverse=True
    )[:5]
    
    # Generate personas
    department_contacts = {
        group.name: group.contacts
        for group in department_groups
    }
    personas = suggest_personas(department_contacts, client)
    
    # Get upload stats from session if available
    upload_stats = session.get('upload_stats', {})
    if upload_stats:
        session.pop('upload_stats', None)  # Clear the stats after using them
    
    return render_template('dashboard.html',
                         total_contacts=total_contacts,
                         total_departments=total_departments,
                         top_departments=top_departments,
                         personas=personas,
                         upload_stats=upload_stats)

@app.route('/contacts')
@login_required
def view_contacts():
    contacts = Contact.query.filter_by(user_id=current_user.id).all()
    return render_template('contacts.html', contacts=contacts)

@app.route('/generate', methods=['POST'])
@login_required
def generate_persona():
    if not client:
        return jsonify({'error': 'OpenAI API key is not configured'}), 500
        
    try:
        data = request.json
        role = data.get('role', '')
        industry = data.get('industry', '')
        company_size = data.get('company_size', '')
        
        if not role:
            return jsonify({'error': 'Role is required'}), 400

        # Create the prompt for persona generation
        prompt = f"""Create a detailed B2B buyer persona for the following role:
        Role: {role}
        Industry: {industry}
        Company Size: {company_size}

        Please include:
        1. Demographics
        2. Goals and Challenges
        3. Pain Points
        4. Decision-Making Process
        5. Preferred Communication Channels
        6. Key Responsibilities
        7. Technical Proficiency
        8. Buying Criteria
        9. Common Objections
        10. Success Metrics

        Format the response in clear sections with bullet points where appropriate."""

        # Call OpenAI API
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an expert in B2B marketing and buyer persona development."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1000
        )

        persona = response.choices[0].message.content.strip()
        return jsonify({'persona': persona})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

def init_db():
    with app.app_context():
        # Create all tables
        db.create_all()
        
        # Add department_group_id column if it doesn't exist
        try:
            with db.engine.connect() as conn:
                conn.execute(text("""
                    ALTER TABLE contact 
                    ADD COLUMN department_group_id INTEGER 
                    REFERENCES department_group(id)
                """))
                conn.commit()
        except Exception as e:
            # Column might already exist, which is fine
            pass

# Initialize the database
init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5004) 