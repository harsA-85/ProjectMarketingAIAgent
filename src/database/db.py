import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from .models import Base

# Use absolute path for persistent database (project root)
# Force to C:\Users\harsa\OneDrive\Desktop\axelunfiltered\ProjectMarketingAIAgent\marketing_ai.db
PROJECT_ROOT = r'C:\Users\harsa\OneDrive\Desktop\axelunfiltered\ProjectMarketingAIAgent'
DB_PATH = os.path.join(PROJECT_ROOT, 'marketing_ai.db')
# Convert backslashes to forward slashes for SQLite URL
DB_PATH_NORMALIZED = DB_PATH.replace('\\', '/')
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    f'sqlite:///{DB_PATH_NORMALIZED}'
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
