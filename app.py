from flask import Flask, render_template, redirect, url_for, request, flash, send_file, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from database import db, User, Document, FamilyMember
from datetime import datetime, timedelta
from google import genai
from dotenv import load_dotenv
load_dotenv()
import os, secrets, fitz

app = Flask(__name__)
app.config['SECRET_KEY'] = 'docnest-secret-2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///docnest.db'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}


client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        if User.query.filter_by(email=email).first():
            flash('Email already exists!', 'error')
            return redirect(url_for('register'))
        user = User(name=name, email=email,
                    password=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        flash('Account created! Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid email or password!', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    docs = Document.query.filter_by(user_id=current_user.id).all()
    family = FamilyMember.query.filter_by(user_id=current_user.id).all()
    expiring = []
    for doc in docs:
        if doc.expiry_date:
            days_left = (doc.expiry_date - datetime.utcnow().date()).days
            if days_left <= 30:
                expiring.append({'doc': doc, 'days': days_left})
    categories = {}
    for doc in docs:
        categories[doc.category] = categories.get(doc.category, 0) + 1
    return render_template('dashboard.html', docs=docs, family=family,
                           expiring=expiring, categories=categories)

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    family = FamilyMember.query.filter_by(user_id=current_user.id).all()
    if request.method == 'POST':
        file = request.files['file']
        name = request.form['name']
        category = request.form['category']
        expiry = request.form.get('expiry_date')
        family_id = request.form.get('family_member_id') or None
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            unique_name = f"{secrets.token_hex(8)}_{filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_name))
            expiry_date = datetime.strptime(expiry, '%Y-%m-%d').date() if expiry else None
            doc = Document(name=name, filename=unique_name, category=category,
                           expiry_date=expiry_date, user_id=current_user.id,
                           family_member_id=family_id)
            db.session.add(doc)
            db.session.commit()
            flash('Document uploaded successfully!', 'success')
            return redirect(url_for('dashboard'))
    return render_template('upload.html', family=family)

@app.route('/documents')
@login_required
def documents():
    category = request.args.get('category', 'all')
    search = request.args.get('search', '')
    query = Document.query.filter_by(user_id=current_user.id)
    if category != 'all':
        query = query.filter_by(category=category)
    if search:
        query = query.filter(Document.name.ilike(f'%{search}%'))
    docs = query.order_by(Document.uploaded_at.desc()).all()
    return render_template('documents.html', docs=docs,
                           category=category, search=search)

@app.route('/view/<int:doc_id>')
@login_required
def view_doc(doc_id):
    doc = Document.query.get_or_404(doc_id)
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], doc.filename))

@app.route('/summarize/<int:doc_id>')
@login_required
def summarize(doc_id):
    try:
        doc = Document.query.get_or_404(doc_id)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], doc.filename)
        text = ""
        if doc.filename.endswith('.pdf'):
            pdf = fitz.open(filepath)
            for page in pdf:
                text += page.get_text()
        else:
            text = f"Document name: {doc.name}, Category: {doc.category}"

        prompt = f"Summarize this document in simple English in 3-4 lines: {text[:2000]}"
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        doc.ai_summary = response.text
        db.session.commit()
        return jsonify({'summary': response.text})
    except Exception as e:
        print("SUMMARIZE ERROR:", str(e))
        error_msg = str(e)
        if "RESOURCE_EXHAUSTED" in error_msg or "429" in error_msg:
            return jsonify({'summary': '⚠️ AI quota limit reached for today. Please try again later.'}), 429
        return jsonify({'summary': f'Error: {error_msg}'}), 500

@app.route('/share/<int:doc_id>')
@login_required
def share(doc_id):
    doc = Document.query.get_or_404(doc_id)
    token = secrets.token_urlsafe(16)
    doc.share_token = token
    doc.share_expiry = datetime.utcnow() + timedelta(hours=24)
    db.session.commit()
    link = url_for('shared_view', token=token, _external=True)
    return jsonify({'link': link})

@app.route('/shared/<token>')
def shared_view(token):
    doc = Document.query.filter_by(share_token=token).first_or_404()
    if doc.share_expiry < datetime.utcnow():
        return "This link has expired.", 410
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], doc.filename))

@app.route('/family', methods=['GET', 'POST'])
@login_required
def family():
    if request.method == 'POST':
        name = request.form['name']
        relation = request.form['relation']
        member = FamilyMember(name=name, relation=relation,
                              user_id=current_user.id)
        db.session.add(member)
        db.session.commit()
        flash('Family member added!', 'success')
    members = FamilyMember.query.filter_by(user_id=current_user.id).all()
    return render_template('family.html', members=members)

@app.route('/delete/<int:doc_id>')
@login_required
def delete_doc(doc_id):
    doc = Document.query.get_or_404(doc_id)
    try:
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], doc.filename))
    except:
        pass
    db.session.delete(doc)
    db.session.commit()
    flash('Document deleted!', 'success')
    return redirect(url_for('documents'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)