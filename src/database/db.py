import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from .models import Base

# Use absolute path for persistent database (project root)
# __file__ is src/database/db.py, go up 3 levels to project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(PROJECT_ROOT, 'marketing_ai.db')
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    f'sqlite:///{DB_PATH}'
)

engine = create_engine(DATABASE_URL, connect_args={'check_same_thread': False} if 'sqlite' in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    """Get database session"""
    return SessionLocal()


def close_db(session: Session):
    """Close database session"""
    session.close()
