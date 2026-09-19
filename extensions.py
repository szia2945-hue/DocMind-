# ===========================================
# extensions.py
# Ye file Flask extensions (db, login_manager) ko
# initialize karti hai, lekin app se bind nahi karti.
# Isse circular import ka masla nahi hota jab
# models.py, auth.py, aur app.py ek dusre ko import karte hain.
# ===========================================

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

# Database instance - abhi kisi app se attached nahi hai
db = SQLAlchemy()

# Login manager - authentication session handle karega
login_manager = LoginManager()
login_manager.login_view = "auth.login"          # agar login required page pe user na aaye login pe
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "error"
