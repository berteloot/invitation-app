import logging
import sys
import os
from flask import Flask
from dotenv import load_dotenv
from invitation.app import app

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logging.getLogger().setLevel(logging.INFO)
logging.getLogger('werkzeug').setLevel(logging.INFO)
app_logger = logging.getLogger('app')

# Attach app_logger to root logger handlers for Render/Gunicorn visibility
root_logger = logging.getLogger()
for handler in root_logger.handlers:
    app_logger.addHandler(handler)
app_logger.propagate = True
app_logger.setLevel(logging.INFO)

app_logger.info("BOOT-MARK 2025-05-17-23-20")

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-dev-key')
app.config['ENV'] = os.getenv('FLASK_ENV', 'production')
app.config['ADMIN_PASSWORD'] = os.getenv('ADMIN_PASSWORD', 'admin123')  # Change this in production!

# NOW attach handlers to app.logger
for handler in root_logger.handlers:
    app.logger.addHandler(handler)
app.logger.propagate = True
app.logger.setLevel(logging.INFO)

if app is None:
    raise RuntimeError("Flask app failed to import") 