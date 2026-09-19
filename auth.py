# ===========================================
# auth.py
# Authentication blueprint - Signup, Login, Logout.
# Werkzeug se password hashing hoti hai (models.py me set_password/check_password).
# ===========================================

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user

from extensions import db
from models import User

# Blueprint create karte hain - "auth" prefix se routes register honge
auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    # Agar user pehle se login hai to dashboard pe bhej do
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        # --- Basic validation ---
        if not username or not email or not password:
            flash("Please fill in all fields.", "error")
            return render_template("signup.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return render_template("signup.html")

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("signup.html")

        # --- Check duplicate username/email ---
        if User.query.filter_by(username=username).first():
            flash("Username already taken.", "error")
            return render_template("signup.html")

        if User.query.filter_by(email=email).first():
            flash("Email already registered.", "error")
            return render_template("signup.html")

        # --- Naya user banao ---
        new_user = User(username=username, email=email)
        new_user.set_password(password)   # hash karke store hoga

        # Sabse pehla user jo signup karta hai, wo automatically admin ban jata hai
        # (admin panel access ke liye). Baad wale sab normal users hote hain.
        if User.query.count() == 0:
            new_user.is_admin = True

        db.session.add(new_user)
        db.session.commit()

        flash("Account created successfully! Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("signup.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username_or_email = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # Username ya email se dono se login allow karte hain
        user = User.query.filter(
            (User.username == username_or_email) | (User.email == username_or_email.lower())
        ).first()

        if user and user.check_password(password):
            login_user(user)
            flash(f"Welcome back, {user.username}!", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("main.dashboard"))

        flash("Invalid username/email or password.", "error")
        return render_template("login.html")

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))
