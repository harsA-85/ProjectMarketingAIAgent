import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from .models import Base

# Use absolute path for persistent database
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'marketing_ai.db')
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
