import sys
import os

# Ensure the current directory is in the python path
sys.path.append(os.getcwd())

from motopuppu import create_app, db
from sqlalchemy import text

app = create_app()
with app.app_context():
    with db.engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS use_lite_dashboard BOOLEAN DEFAULT FALSE NOT NULL;"))
            conn.commit()
            print("Successfully added 'use_lite_dashboard' column to 'users' table.")
        except Exception as e:
            print(f"Error adding column: {e}")
