from sqlalchemy import Column, Integer, String, Float, ForeignKey, create_engine, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from flask_login import UserMixin
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

Base = declarative_base()

class User(UserMixin, Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    email = Column(String(100), unique=True)
    is_admin = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)
    
    contacts = relationship("Contact", back_populates="user")
    personas = relationship("Persona", back_populates="user")

class Persona(Base):
    __tablename__ = 'personas'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    role_description = Column(String(500))
    key_skills = Column(String(500))  # Stored as comma-separated string
    industry_context = Column(String(200))
    seniority_level = Column(String(50))
    career_path = Column(String(500))
    challenges = Column(String(500))  # Stored as comma-separated string
    user_id = Column(Integer, ForeignKey('users.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="personas")
    contacts = relationship("Contact", back_populates="persona")

class Contact(Base):
    __tablename__ = 'contacts'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    job_title = Column(String(200))
    company = Column(String(200))
    email = Column(String(100))
    phone = Column(String(20))
    linkedin = Column(String(200))
    matched_persona_id = Column(Integer, ForeignKey('personas.id'))
    confidence_score = Column(Float)
    additional_info = Column(String(1000))  # JSON string for any extra fields
    user_id = Column(Integer, ForeignKey('users.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="contacts")
    persona = relationship("Persona", back_populates="contacts")

class UserActivity(Base):
    __tablename__ = 'user_activities'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    action = Column(String(50))  # e.g., 'upload', 'create_persona', 'delete_persona'
    details = Column(String(1000))  # JSON string with action details
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User")

class RSVP(Base):
    __tablename__ = 'rsvps'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), nullable=False)
    attending = Column(Integer, default=1)  # 1 for attending, 0 for not attending
    guests = Column(Integer, default=0)
    dietary_restrictions = Column(String(500))
    food_contribution = Column(String(100))  # Store the selected food contribution category
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

def init_db():
    """Initialize the database connection and create tables."""
    db_url = os.getenv('DATABASE_URL', 'sqlite:///job_persona.db')
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session() 