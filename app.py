from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
import sqlite3
import hashlib
import qrcode
import io
import base64
from datetime import datetime, timedelta
import secrets
import os
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
# Generate a proper secret key
app.secret_key = secrets.token_hex(32)
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Configure file upload
UPLOAD_FOLDER = 'uploads/justifications'
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max file size

# Create upload directory if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Database initialization
def init_db():
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    
    # Enable foreign keys
    cursor.execute('PRAGMA foreign_keys = ON')
    
    # Users table (students, teachers, supervisors)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            matricule TEXT UNIQUE NOT NULL,
            nni TEXT NOT NULL,
            nom TEXT NOT NULL,
            prenom TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('eleve', 'professeur', 'superviseur')),
            classe TEXT,
            email TEXT,
            telephone TEXT,
            password_hash TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Courses table - Fixed foreign key reference
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom_cours TEXT NOT NULL,
            code_cours TEXT,
            professeur_id INTEGER,
            classe TEXT NOT NULL,
            credits INTEGER,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (professeur_id) REFERENCES users(id)
        )
    ''')
    
    # QR codes table - Fixed foreign key references
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS qr_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            professeur_id INTEGER,
            course_id INTEGER,
            qr_token TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            FOREIGN KEY (professeur_id) REFERENCES users(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )
    ''')
    
    # Attendance table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            eleve_id INTEGER,
            professeur_id INTEGER,
            course_id INTEGER,
            date_presence DATE,
            heure_presence TIME,
            status TEXT DEFAULT 'present' CHECK(status IN ('present', 'absent', 'justified')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(eleve_id, course_id, date_presence),
            FOREIGN KEY (eleve_id) REFERENCES users(id),
            FOREIGN KEY (professeur_id) REFERENCES users(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )
    ''')
    
    # Justifications table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS justifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            eleve_id INTEGER NOT NULL,
            attendance_id INTEGER NOT NULL,
            reason_type TEXT NOT NULL,
            custom_reason TEXT,
            description TEXT,
            document_path TEXT,
            status TEXT DEFAULT 'en_attente',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_at TIMESTAMP,
            approved_by INTEGER,
            FOREIGN KEY (eleve_id) REFERENCES users (id),
            FOREIGN KEY (attendance_id) REFERENCES attendance (id),
            FOREIGN KEY (approved_by) REFERENCES users (id),
            UNIQUE(attendance_id)
        )
    ''')
    
    # Schedule table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER,
            day_of_week INTEGER NOT NULL,  -- 0=Monday, 1=Tuesday, etc.
            start_time TEXT NOT NULL,      
            end_time TEXT NOT NULL,
            room TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('COURS', 'TD', 'TP')),
            classe TEXT NOT NULL,
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )
    ''')
    
    # Check if default data already exists before inserting
    existing_users = cursor.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    
    if existing_users == 0:
        # Insert default data only if no users exist
        cursor.execute('''
            INSERT INTO users (matricule, nni, nom, prenom, role, classe, telephone) VALUES
                ('SUPER001', '1234567890', 'Admin', 'Principal', 'superviseur', NULL, NULL),          
                ('PROF001','2234567890','ahmed','sejad','professeur', NULL, NULL),
                ('PROF002','2234567891','ba', 'aboubakry','professeur', NULL, NULL),
                ('PROF003', '2234567892','moustapha','med salek','professeur', NULL, NULL),
                ('PROF004', '2234567893','dahah','ahmed mahmoud','professeur', NULL, NULL),
                ('PROF005','2234567894','Ahmed','mohameden','professeur', NULL, NULL), 
                ('PROF006','2234567895','eby','','professeur', NULL, NULL),
                ('PROF007','2234567896','mohamed lemine','moukhtar loully','professeur', NULL, NULL),
                ('PROF008','2234567897','el veth', 'sidi','professeur', NULL, NULL),
                ('PROF009','2234567898','mohamed vall','mohamed','professeur', NULL, NULL),                                                                          
                ('C22932', '1234567890', 'El Mouna', 'Mohamed El Moctar SidAmar', 'eleve', 'DAII-L2', '+22244216964'),
                ('C23211', '1234567891', 'Khadji', 'Abderrahmane Diallo', 'eleve', 'DAII-L2', '+22231213982'),
                ('C23282', '1234567892', 'Mohamed', 'Sidi Mohamed Mohamed Salem', 'eleve', 'DAII-L2', '+22234509008'),
                ('C23316', '1234567893', 'Mamadou', 'Abou Ba', 'eleve', 'DAII-L2', '+22249107874'),
                ('C23455', '1234567894', 'Marièma', 'Mohamed Lemine Louly', 'eleve', 'DAII-L2', '+22241914772'),
                ('C23699', '1234567895', 'Cheikh Melaynine', 'Aboubacarin Abdellah', 'eleve', 'DAII-L2', '+22228660638'),
                ('C23785', '1234567896', 'Oussama', 'Mohamed Leghdhef Beyah', 'eleve', 'DAII-L2', '+22237182151'),
                ('C23803', '1234567897', 'Sidi', 'Mohamed Lemine Ahmed El Hanoun', 'eleve', 'DAII-L2', '+22222552125'),
                ('C23945', '1234567898', 'Oum Lkeiri', 'Ahmed Cherif Ahmed Cherif', 'eleve', 'DAII-L2', '+22230515163'),
                ('C24240', '1234567899', 'Neya', 'Mohamed Bebaha', 'eleve', 'DAII-L2', '+22233091086'),
                ('C24245', '1234567900', 'Mariem', 'Elbou Ivikou', 'eleve', 'DAII-L2', '+22244567638'),
                ('C24333', '1234567901', 'Abdellahi', 'Oumar El Hacen', 'eleve', 'DAII-L2', '+22241020008'),
                ('C24522', '1234567902', 'Khadija', 'Salem Naji Abdellahi', 'eleve', 'DAII-L2', '+22227842321'),
                ('C24809', '1234567903', 'Mohamed Salem', 'Mohamed Abdel Wedoud', 'eleve', 'DAII-L2', '+22238634664'),
                ('C24828', '1234567904', 'Mohamed', 'Gleiguem Kheyri', 'eleve', 'DAII-L2', '+22237460309'),
                ('C24903', '1234567905', 'Mohamed', 'Slame El Maaloum', 'eleve', 'DAII-L2', '+22242520486'),
                ('C25056', '1234567906', 'Mohamed El Khachaa', 'Mohamed Lemine Mohamed El Hadj', 'eleve', 'DAII-L2', '+22247606286'),
                ('C25094', '1234567907', 'Cheikha', 'Chbihenna Mohamed Sidina', 'eleve', 'DAII-L2', '+22249636805'),
                ('C25101', '1234567908', 'Terbe', 'Sid El Moctar Abde Selam', 'eleve', 'DAII-L2', '+22234227835'),
                ('C25366', '1234567909', 'Khadijetou', 'Ahmedou Limam', 'eleve', 'DAII-L2', '+22243048032'),
                ('C22621', '1234567910', 'Sidi Mohamed', 'Yahya Khattri', 'eleve', 'MAIGE-L2', '+22242844294'),
                ('C22622', '1234567911', 'Mohamed Vadell', 'Cheikhna Sid''Mhamed', 'eleve', 'MAIGE-L2', '+22227105282'),
                ('C23073', '1234567912', 'Sidi', 'Mohamed Vadel Beye', 'eleve', 'MAIGE-L2', '+22248651045'),
                ('C23331', '1234567913', 'Teyeb', 'Sidi MBareck', 'eleve', 'MAIGE-L2', '+22248292738'),
                ('C23625', '1234567914', 'Mouna', 'Nagi Ahmed', 'eleve', 'MAIGE-L2', '+22232050152'),
                ('C23839', '1234567915', 'NZaha', 'Said Mane', 'eleve', 'MAIGE-L2', '+22226064951'),
                ('C23910', '1234567916', 'Yassmine', 'Abderrahmane Moussa', 'eleve', 'MAIGE-L2', '+22242257614'),
                ('C24094', '1234567917', 'Neina', 'Mohamed Vall Abdel Kader', 'eleve', 'MAIGE-L2', '+22237019460'),
                ('C24228', '1234567918', 'Moulaye El Hacen', 'Selam Moulaye', 'eleve', 'MAIGE-L2', '+22248491712'),
                ('C24451', '1234567919', 'Selekha', 'Oumar Abdy', 'eleve', 'MAIGE-L2', '+22233666745'),
                ('C24544', '1234567920', 'Mouhamed Lehbib', 'Mamadou Bal', 'eleve', 'MAIGE-L2', '+22241787872'),
                ('C24664', '1234567921', 'Sidi', 'Abou Ba', 'eleve', 'MAIGE-L2', '+22248168763'),
                ('C24884', '1234567922', 'Penda', 'Boyi Hamadi Moctar Bah', 'eleve', 'MAIGE-L2', '+22244001139'),
                ('C25105', '1234567923', 'Chivae', 'Ahmed Bezeid Abd El Wedoud', 'eleve', 'MAIGE-L2', '+22249398731'),
                ('C25144', '1234567924', 'Mariem', 'Brahim Mohamdi Vall', 'eleve', 'MAIGE-L2', '+22248208792'),
                ('C25164', '1234567925', 'Hafsa', 'Beddih SidAhmed', 'eleve', 'MAIGE-L2', '+22247346288'),
                ('C25273', '1234567926', 'Mohamed', 'Mahfoudh HMeyd', 'eleve', 'MAIGE-L2', '+22249490080'),
                ('C25289', '1234567927', 'Veisal', 'Sidi Mohamed Mohamed Cheikh', 'eleve', 'MAIGE-L2', '+22237016100'),
                ('C25321', '1234567928', 'Nakou', 'Ahmed Mohamed Abdel Kader', 'eleve', 'MAIGE-L2', '+22237904758'),
                ('C25423', '1234567929', 'Moulay', 'Abderrahmane Baba Chrif El Mokhtar', 'eleve', 'MAIGE-L2', '+22226320097')
        ''')
        
        # Insert courses - Fixed syntax errors and standardized names
        cursor.execute('''
            INSERT INTO courses (nom_cours, professeur_id, classe) VALUES
                ('Marketing', (SELECT id FROM users WHERE matricule = 'PROF007'), 'DAII-L2'),
                ('Web Dynamique', (SELECT id FROM users WHERE matricule = 'PROF005'), 'DAII-L2'),
                ('Reseau Informatique', (SELECT id FROM users WHERE matricule = 'PROF008'), 'DAII-L2'),
                ('Anglais', (SELECT id FROM users WHERE matricule = 'PROF006'), 'DAII-L2'),
                ('Projet Web', (SELECT id FROM users WHERE matricule = 'PROF005'), 'DAII-L2'),
                ('Outils Web', (SELECT id FROM users WHERE matricule = 'PROF009'), 'DAII-L2'),
                ('Multimedia et Programmation Mobile', (SELECT id FROM users WHERE matricule = 'PROF001'), 'DAII-L2'),
                ('Francais', (SELECT id FROM users WHERE matricule = 'PROF002'), 'DAII-L2'),
                ('Analyse des Donnees et DataMining', (SELECT id FROM users WHERE matricule = 'PROF003'), 'DAII-L2'),
                ('Marketing', (SELECT id FROM users WHERE matricule = 'PROF007'), 'MAIGE-L2'),
                ('Web Dynamique', (SELECT id FROM users WHERE matricule = 'PROF005'), 'MAIGE-L2'),
                ('Reseau Informatique', (SELECT id FROM users WHERE matricule = 'PROF008'), 'MAIGE-L2'),
                ('Anglais', (SELECT id FROM users WHERE matricule = 'PROF006'), 'MAIGE-L2'),
                ('Projet Web', (SELECT id FROM users WHERE matricule = 'PROF005'), 'MAIGE-L2'),
                ('Outils Web', (SELECT id FROM users WHERE matricule = 'PROF009'), 'MAIGE-L2'),
                ('Francais', (SELECT id FROM users WHERE matricule = 'PROF002'), 'MAIGE-L2'),
                ('Analyse des Donnees et DataMining', (SELECT id FROM users WHERE matricule = 'PROF003'), 'MAIGE-L2'),      
                ('Comptabilite Analytique', (SELECT id FROM users WHERE matricule = 'PROF004'), 'MAIGE-L2')
        ''')
        
        # Insert sample attendance records - Fixed syntax
        cursor.execute('''
            INSERT INTO attendance (eleve_id, professeur_id, course_id, date_presence, heure_presence, status) VALUES
                ((SELECT id FROM users WHERE matricule = 'C24544'), (SELECT id FROM users WHERE matricule = 'PROF001'), 
                (SELECT id FROM courses WHERE nom_cours = 'Multimedia et Programmation Mobile' AND classe = 'DAII-L2'), 
                '2025-06-01', '09:00:00', 'present'),
                
                ((SELECT id FROM users WHERE matricule = 'C23211'), (SELECT id FROM users WHERE matricule = 'PROF001'), 
                (SELECT id FROM courses WHERE nom_cours = 'Multimedia et Programmation Mobile' AND classe = 'DAII-L2'), 
                '2025-06-01', '09:05:00', 'absent'),
                
                ((SELECT id FROM users WHERE matricule = 'C23282'), (SELECT id FROM users WHERE matricule = 'PROF005'), 
                (SELECT id FROM courses WHERE nom_cours = 'Web Dynamique' AND classe = 'DAII-L2'), 
                '2025-06-02', '10:00:00', 'justified')
        ''')
        
        # Insert sample justifications - Fixed references
        cursor.execute('''
            INSERT INTO justifications (eleve_id, attendance_id, reason_type, document_path, status, description, approved_at, approved_by) VALUES
                ((SELECT id FROM users WHERE matricule = 'C23211'), 
                (SELECT id FROM attendance WHERE eleve_id = (SELECT id FROM users WHERE matricule = 'C23211') AND date_presence = '2025-06-01'), 
                'Maladie', 'documents/justif_khadji_maladie.pdf', 'validee', '', datetime('now'), 
                (SELECT id FROM users WHERE matricule = 'SUPER001')),
                
                ((SELECT id FROM users WHERE matricule = 'C23282'), 
                (SELECT id FROM attendance WHERE eleve_id = (SELECT id FROM users WHERE matricule = 'C23282') AND date_presence = '2025-06-02'), 
                'Problème familial', 'documents/justif_mohamed_famille.pdf', 'en_attente', '', NULL, NULL)
        ''')
        
        # Insert sample schedule data for DAII-L2
        cursor.execute('''
        INSERT INTO schedule (course_id, day_of_week, start_time, end_time, room, type, classe) VALUES
            ((SELECT id FROM courses WHERE nom_cours = 'Marketing' AND classe = 'DAII-L2'), 0, '08:30', '10:30', '206', 'COURS', 'DAII-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Reseau Informatique' AND classe = 'DAII-L2'), 0, '10:30', '12:30', '105', 'COURS', 'DAII-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Analyse des Donnees et DataMining' AND classe = 'DAII-L2'), 0, '14:00', '16:00', '206', 'COURS', 'DAII-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Analyse des Donnees et DataMining' AND classe = 'DAII-L2'), 0, '16:00', '18:00', '206', 'TD', 'DAII-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Anglais' AND classe = 'DAII-L2'), 1, '10:30', '12:30', '105', 'COURS', 'DAII-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Analyse des Donnees et DataMining' AND classe = 'DAII-L2'), 1, '14:00', '16:00', '002/204', 'TP', 'DAII-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Outils Web' AND classe = 'DAII-L2'), 1, '16:00', '18:00', '206', 'TP', 'DAII-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Projet Web' AND classe = 'DAII-L2'), 2, '08:30', '10:30', '105', 'COURS', 'DAII-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Outils Web' AND classe = 'DAII-L2'), 2, '10:30', '12:30', '105', 'COURS', 'DAII-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Reseau Informatique' AND classe = 'DAII-L2'), 2, '14:00', '16:00', '206', 'TD', 'DAII-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Web Dynamique' AND classe = 'DAII-L2'), 3, '08:30', '10:30', '105', 'COURS', 'DAII-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Web Dynamique' AND classe = 'DAII-L2'), 3, '10:30', '12:30', '002', 'TP', 'DAII-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Multimedia et Programmation Mobile' AND classe = 'DAII-L2'), 4, '08:30', '10:30', '002', 'COURS', 'DAII-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Multimedia et Programmation Mobile' AND classe = 'DAII-L2'), 4, '10:30', '12:30', '002', 'TD', 'DAII-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Francais' AND classe = 'DAII-L2'), 5, '08:30', '10:30', '210', 'COURS', 'DAII-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Analyse des Donnees et DataMining' AND classe = 'DAII-L2'), 5, '10:30', '12:30', '202', 'COURS', 'DAII-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Comptabilite Analytique' AND classe = 'DAII-L2'), 5, '12:30', '14:00', '105', 'COURS', 'DAII-L2')
        ''')

        # Insert sample schedule data for MAIGE-L2
        cursor.execute('''
        INSERT INTO schedule (course_id, day_of_week, start_time, end_time, room, type, classe) VALUES
            ((SELECT id FROM courses WHERE nom_cours = 'Marketing' AND classe = 'MAIGE-L2'), 0, '08:30', '10:30', '206', 'COURS', 'MAIGE-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Reseau Informatique' AND classe = 'MAIGE-L2'), 0, '10:30', '12:30', '105', 'COURS', 'MAIGE-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Comptabilite Analytique' AND classe = 'MAIGE-L2'), 0, '14:00', '16:00', '206', 'COURS', 'MAIGE-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Comptabilite Analytique' AND classe = 'MAIGE-L2'), 0, '16:00', '18:00', '206', 'TD', 'MAIGE-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Anglais' AND classe = 'MAIGE-L2'), 1, '10:30', '12:30', '105', 'COURS', 'MAIGE-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Analyse des Donnees et DataMining' AND classe = 'MAIGE-L2'), 1, '14:00', '16:00', '002/204', 'TP', 'MAIGE-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Outils Web' AND classe = 'MAIGE-L2'), 1, '16:00', '18:00', '206', 'TP', 'MAIGE-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Projet Web' AND classe = 'MAIGE-L2'), 2, '08:30', '10:30', '105', 'COURS', 'MAIGE-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Outils Web' AND classe = 'MAIGE-L2'), 2, '10:30', '12:30', '105', 'COURS', 'MAIGE-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Reseau Informatique' AND classe = 'MAIGE-L2'), 2, '14:00', '16:00', '206', 'TD', 'MAIGE-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Web Dynamique' AND classe = 'MAIGE-L2'), 3, '08:30', '10:30', '105', 'COURS', 'MAIGE-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Web Dynamique' AND classe = 'MAIGE-L2'), 3, '10:30', '12:30', '002', 'TP', 'MAIGE-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Francais' AND classe = 'MAIGE-L2'), 4, '08:30', '10:30', '210', 'COURS', 'MAIGE-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Analyse des Donnees et DataMining' AND classe = 'MAIGE-L2'), 4, '10:30', '12:30', '202', 'COURS', 'MAIGE-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Comptabilite Analytique' AND classe = 'MAIGE-L2'), 5, '12:30', '14:00', '105', 'COURS', 'MAIGE-L2')
        ''')
    
        conn.commit()
     
     

def get_db_connection():
    conn = sqlite3.connect('attendance.db')
    conn.row_factory = sqlite3.Row
    return conn

# ... [Keep all your existing route definitions, but make these changes:]

# 1. Fix the duplicate route - remove one of the /api/course_attendance/<int:course_id> definitions
# 2. In the student planning route, fix the course_name reference:
@app.route('/student/planning')
def student_planning():
    if 'user_id' not in session or session.get('user_role') != 'eleve':
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    try:
        # Get student information
        student = conn.execute(
            'SELECT * FROM users WHERE id = ?', 
            (session['user_id'],)
        ).fetchone()
        
        if not student:
            flash('Student not found', 'error')
            return redirect(url_for('student_dashboard'))
        
        # Get schedule data
        schedule = conn.execute('''
            SELECT s.*, c.nom_cours as course_name, u.nom as prof_nom, u.prenom as prof_prenom
            FROM schedule s
            JOIN courses c ON s.course_id = c.id
            JOIN users u ON c.professeur_id = u.id
            WHERE s.classe = ?
            ORDER BY s.day_of_week, s.start_time
        ''', (student['classe'],)).fetchall()
        
        # Transform schedule data
        schedule_data = {
            'Monday': [],
            'Tuesday': [],
            'Wednesday': [],
            'Thursday': [],
            'Friday': [],
            'Saturday': []
        }
        
        for item in schedule:
            day_map = {
                0: 'Monday',
                1: 'Tuesday', 
                2: 'Wednesday',
                3: 'Thursday',
                4: 'Friday',
                5: 'Saturday'
            }
            day_name = day_map.get(item['day_of_week'], 'Unknown')
            schedule_data[day_name].append({
                'course_name': item['course_name'],
                'room': item['room'],
                'type': item['type'],
                'start_time': item['start_time'],
                'end_time': item['end_time'],
                'prof_name': f"{item['prof_prenom']} {item['prof_nom']}"
            })
        
        return render_template('student_planning.html',
                            student=dict(student),
                            schedule=schedule_data)
        
    except Exception as e:
        print(f"Error in student_planning: {e}")
        flash('Error loading planning', 'error')
        return redirect(url_for('student_dashboard'))
    finally:
        conn.close()

# 3. Fix the manual attendance route to use safe parameterized queries:
@app.route('/api/manual_attendance', methods=['POST'])
def save_manual_attendance():
    if 'user_id' not in session or session.get('user_role') != 'professeur':
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    if not data or 'attendance' not in data or 'date_presence' not in data:
        return jsonify({'error': 'Invalid data'}), 400
    
    conn = get_db_connection()
    try:
        # First delete any existing attendance for these students on this date
        student_ids = [str(record['eleve_id']) for record in data['attendance']]
        placeholders = ','.join(['?'] * len(student_ids))
        
        conn.execute(f'''
            DELETE FROM attendance 
            WHERE course_id = ? AND date_presence = ? 
            AND eleve_id IN ({placeholders})
        ''', [data['attendance'][0]['course_id'], data['date_presence']] + student_ids)
        
        # Then insert new attendance records
        for record in data['attendance']:
            conn.execute('''
                INSERT INTO attendance 
                (eleve_id, professeur_id, course_id, date_presence, heure_presence, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                record['eleve_id'],
                session['user_id'],
                record['course_id'],
                data['date_presence'],
                record['heure_presence'],
                record['status']
            ))
        
        conn.commit()
        return jsonify({'success': True, 'count': len(data['attendance'])})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()
# ... [Previous code remains the same until the routes section] ...

@app.route('/')
def index():
    # Only redirect if we have COMPLETE valid session data
    if all(key in session for key in ['user_id', 'user_role']):
        try:
            role = session['user_role']
            if role == 'eleve':
                return redirect(url_for('student_dashboard'))
            elif role == 'professeur':
                return redirect(url_for('teacher_dashboard'))
            elif role == 'superviseur':
                return redirect(url_for('supervisor_dashboard'))
        except Exception as e:
            print(f"Redirect error: {e}")
            session.clear()
    
    return render_template('login.html')

def authenticate_user(matricule, nni):
    conn = get_db_connection()
    try:
        user = conn.execute(
            'SELECT * FROM users WHERE matricule = ? AND nni = ?',
            (matricule, nni)
        ).fetchone()
        return dict(user) if user else None
    except Exception as e:
        print(f"Database error in authenticate_user: {e}")
        return None
    finally:
        conn.close()

def generate_qr_code(data):
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    img_io = io.BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    
    img_base64 = base64.b64encode(img_io.read()).decode()
    return f"data:image/png;base64,{img_base64}"

def create_qr_token(professeur_id, course_id):
    import random
    import string
    
    token = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    
    conn = get_db_connection()
    try:
        while conn.execute('SELECT id FROM qr_codes WHERE qr_token = ?', (token,)).fetchone():
            token = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        expires_at = datetime.now() + timedelta(hours=2)
        
        # Deactivate old QR codes for this course
        conn.execute(
            'UPDATE qr_codes SET is_active = 0 WHERE professeur_id = ? AND course_id = ?',
            (professeur_id, course_id)
        )
        
        # Create new QR code
        conn.execute(
            'INSERT INTO qr_codes (professeur_id, course_id, qr_token, expires_at) VALUES (?, ?, ?, ?)',
            (professeur_id, course_id, token, expires_at)
        )
        conn.commit()
        return token
    except Exception as e:
        print(f"Database error in create_qr_token: {e}")
        return None
    finally:
        conn.close()

@app.route('/login', methods=['POST'])
def login():
    try:
        matricule = request.form.get('matricule', '').strip()
        nni = request.form.get('nni', '').strip()
        
        if not matricule or not nni:
            return render_template('login.html', error='Matricule et NNI requis')
        
        user = authenticate_user(matricule, nni)
        if user:
            session.clear()
            
            session['user_id'] = user['id']
            session['user_role'] = user['role']
            session['user_name'] = f"{user['prenom']} {user['nom']}"
            session['matricule'] = user['matricule']
            session['user_type'] = user['role']
            
            session.permanent = True
            
            print(f"Login successful for user: {user['matricule']}, role: {user['role']}")
            
            if user['role'] == 'eleve':
                return redirect(url_for('student_dashboard'))
            elif user['role'] == 'professeur':
                return redirect(url_for('teacher_dashboard'))
            elif user['role'] == 'superviseur':
                return redirect(url_for('supervisor_dashboard'))
            else:
                return render_template('login.html', error='Rôle utilisateur non reconnu')
        else:
            return render_template('login.html', error='Matricule ou NNI invalide')
            
    except Exception as e:
        app.logger.error(f"Login error: {e}")
        flash('Erreur système. Veuillez réessayer.', 'error')
        return render_template('login.html')    

@app.route('/logout')
def logout():
    session.clear()
    response = redirect(url_for('index'))
    response.delete_cookie('session')
    return response

@app.route('/student')
def student_dashboard():
    if 'user_id' not in session or session.get('user_role') != 'eleve':
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    try:
        student_id = session['user_id']
        
        # FIX: Make sure date values are properly converted to datetime objects
        recent_attendance = conn.execute('''
            SELECT a.*, c.nom_cours, u.nom as prof_nom, u.prenom as prof_prenom
            FROM attendance a
            JOIN courses c ON a.course_id = c.id
            JOIN users u ON a.professeur_id = u.id
            WHERE a.eleve_id = ?
            ORDER BY a.date_presence DESC, a.heure_presence DESC
            LIMIT 10
        ''', (student_id,)).fetchall()
        
        # Convert string dates to datetime objects if needed
        for record in recent_attendance:
            if isinstance(record['date_presence'], str):
                record['date_presence'] = datetime.strptime(record['date_presence'], '%Y-%m-%d')
            if isinstance(record['heure_presence'], str):
                record['heure_presence'] = datetime.strptime(record['heure_presence'], '%H:%M:%S').time()
        
        return render_template('student_dashboard.html', 
                             recent_attendance=recent_attendance)
    except Exception as e:
        print(f"Error in student_dashboard: {e}")
        session.clear()  # Clear session to break redirect loop
        return redirect(url_for('index'))
    finally:
        conn.close()

@app.route('/scan_qr', methods=['POST'])
def scan_qr():
    if 'user_id' not in session or session.get('user_role') != 'eleve':
        return jsonify({'error': 'Session expirée - Veuillez vous reconnecter'}), 401
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Données JSON requises'}), 400
            
        qr_token = data.get('qr_token', '').strip().upper()
        student_id = session['user_id']
        
        if not qr_token:
            return jsonify({'error': 'Token QR requis'}), 400
        
        conn = get_db_connection()
        
        qr_data = conn.execute('''
            SELECT q.*, c.nom_cours 
            FROM qr_codes q
            JOIN courses c ON q.course_id = c.id
            WHERE q.qr_token = ? AND q.is_active = 1 AND q.expires_at > datetime('now')
        ''', (qr_token,)).fetchone()
        
        if not qr_data:
            return jsonify({'error': 'Code QR invalide ou expiré'}), 400
        
        today = datetime.now().date()
        existing = conn.execute('''
            SELECT id FROM attendance 
            WHERE eleve_id = ? AND course_id = ? AND date_presence = ?
        ''', (student_id, qr_data['course_id'], today)).fetchone()
        
        if existing:
            return jsonify({'error': 'Présence déjà enregistrée pour ce cours aujourd\'hui'}), 400
        
        now = datetime.now()
        conn.execute('''
            INSERT INTO attendance (eleve_id, professeur_id, course_id, date_presence, heure_presence, status)
            VALUES (?, ?, ?, ?, ?, 'present')
        ''', (student_id, qr_data['professeur_id'], qr_data['course_id'], 
              now.date(), now.time()))
        
        conn.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Présence enregistrée pour {qr_data["nom_cours"]}',
            'course_name': qr_data['nom_cours'],
            'time': now.strftime('%H:%M')
        })
        
    except Exception as e:
        print(f"Error in scan_qr: {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/mes_presences')
def mes_presences():
    if 'user_id' not in session or session.get('user_role') != 'eleve':
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    try:
        student_id = session['user_id']
        
        attendance = conn.execute('''
            SELECT a.*, c.nom_cours, u.nom as prof_nom, u.prenom as prof_prenom
            FROM attendance a
            JOIN courses c ON a.course_id = c.id
            JOIN users u ON a.professeur_id = u.id
            WHERE a.eleve_id = ?
            ORDER BY a.date_presence DESC, a.heure_presence DESC
        ''', (student_id,)).fetchall()
        
        return render_template('student_attendance.html', attendance=attendance)
    finally:
        conn.close()

@app.route('/justifier_absence')
def justifier_absence():
    if 'user_id' not in session or session.get('user_role') != 'eleve':
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    try:
        absences = conn.execute('''
            SELECT a.id, a.date_presence, c.nom_cours
            FROM attendance a
            JOIN courses c ON a.course_id = c.id
            LEFT JOIN justifications j ON a.id = j.attendance_id
            WHERE a.eleve_id = ? 
            AND a.status = 'absent'
            AND j.id IS NULL
            AND datetime(a.date_presence || ' ' || a.heure_presence) >= datetime('now', '-48 hours')
            ORDER BY a.date_presence DESC
        ''', (session['user_id'],)).fetchall()
        
        return render_template('justify_absence.html', absences=absences)
    finally:
        conn.close()

@app.route('/submit_justification', methods=['POST'])
def submit_justification():
    if 'user_id' not in session or session.get('user_role') != 'eleve':
        return jsonify({'success': False, 'message': 'Non autorisé'}), 401
    
    try:
        attendance_id = request.form.get('attendance_id')
        reason_type = request.form.get('reason_type')
        custom_reason = request.form.get('custom_reason', '')
        description = request.form.get('description')
        
        if not attendance_id or not reason_type or not description:
            return jsonify({'success': False, 'message': 'Tous les champs obligatoires doivent être remplis'})
        
        document_path = None
        if 'document' in request.files:
            file = request.files['document']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                filename = timestamp + filename
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                document_path = filename
        
        conn = get_db_connection()
        
        attendance = conn.execute('''
            SELECT * FROM attendance 
            WHERE id = ? AND eleve_id = ? AND status = 'absent'
        ''', (attendance_id, session['user_id'])).fetchone()
        
        if not attendance:
            return jsonify({'success': False, 'message': 'Enregistrement d\'absence non trouvé'})
        
        existing = conn.execute('''
            SELECT id FROM justifications WHERE attendance_id = ?
        ''', (attendance_id,)).fetchone()
        
        if existing:
            return jsonify({'success': False, 'message': 'Cette absence a déjà été justifiée'})
        
        conn.execute('''
            INSERT INTO justifications (
                eleve_id, attendance_id, reason_type, custom_reason, 
                description, document_path, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'en_attente', ?)
        ''', (
            session['user_id'], attendance_id, reason_type, custom_reason,
            description, document_path, datetime.now()
        ))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Justificatif soumis avec succès'})
        
    except Exception as e:
        print(f"Error in submit_justification: {e}")
        return jsonify({'success': False, 'message': 'Erreur interne du serveur'})

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/student/profile')
def student_profile():
    if 'user_id' not in session or session.get('user_role') != 'eleve':
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    try:
        student_id = session['user_id']
        
        student_info = conn.execute('''
            SELECT * FROM users WHERE id = ? AND role = 'eleve'
        ''', (student_id,)).fetchone()
        
        attendance_stats = conn.execute('''
            SELECT 
                COUNT(*) as total_courses,
                SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) as present_count,
                SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) as absent_count
            FROM attendance 
            WHERE eleve_id = ?
        ''', (student_id,)).fetchone()
        
        return render_template('student_profile.html', 
                             student_info=student_info,
                             attendance_stats=attendance_stats)
    except Exception as e:
        print(f"Error in student_profile: {e}")
        flash('Erreur lors du chargement du profil', 'error')
        return redirect(url_for('student_dashboard'))
    finally:
        conn.close()

@app.route('/api/student_info')
def get_student_info():
    if 'user_id' not in session or session.get('user_role') != 'eleve':
        return jsonify({'error': 'Non autorisé'}), 401
    
    conn = get_db_connection()
    try:
        student = conn.execute(
            'SELECT * FROM users WHERE id = ? AND role = "eleve"',
            (session['user_id'],)
        ).fetchone()
        
        return jsonify(dict(student)) if student else jsonify({'error': 'Étudiant non trouvé'}), 404
    finally:
        conn.close()

@app.route('/api/student_absent_courses')
def get_student_absent_courses():
    if 'user_id' not in session or session.get('user_role') != 'eleve':
        return jsonify({'error': 'Non autorisé'}), 401
    
    conn = get_db_connection()
    try:
        absent_courses = conn.execute('''
            SELECT a.id as attendance_id, a.date_presence, a.heure_presence, 
                   c.nom_cours, c.id as course_id
            FROM attendance a
            JOIN courses c ON a.course_id = c.id
            LEFT JOIN justifications j ON a.id = j.attendance_id
            WHERE a.eleve_id = ? 
            AND a.status = 'absent'
            AND j.id IS NULL
            AND datetime(a.date_presence || ' ' || a.heure_presence) >= datetime('now', '-48 hours')
            ORDER BY a.date_presence DESC, a.heure_presence DESC
        ''', (session['user_id'],)).fetchall()
        
        return jsonify([dict(row) for row in absent_courses])
    finally:
        conn.close()

@app.route('/api/student_justifications')
def get_student_justifications():
    if 'user_id' not in session or session.get('user_role') != 'eleve':
        return jsonify({'error': 'Non autorisé'}), 401
    
    conn = get_db_connection()
    try:
        justifications = conn.execute('''
            SELECT j.*, a.date_presence, a.heure_presence, c.nom_cours,
                   CASE 
                       WHEN j.status = 'en_attente' THEN 'En attente'
                       WHEN j.status = 'validee' THEN 'Validée'
                       WHEN j.status = 'refusee' THEN 'Refusée'
                       ELSE j.status
                   END as status_display
            FROM justifications j
            JOIN attendance a ON j.attendance_id = a.id
            JOIN courses c ON a.course_id = c.id
            WHERE j.eleve_id = ?
            ORDER BY j.created_at DESC
        ''', (session['user_id'],)).fetchall()
        
        return jsonify([dict(row) for row in justifications])
    finally:
        conn.close()

# Teacher routes
@app.route('/teacher_dashboard')
def teacher_dashboard():
    if 'user_id' not in session or session.get('user_role') != 'professeur':
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    try:
        courses = conn.execute('''
            SELECT * FROM courses 
            WHERE professeur_id = ?
            ORDER BY nom_cours
        ''', (session['user_id'],)).fetchall()
        
        return render_template('teacher_dashboard.html', 
                            teacher_courses=courses,
                            session=session)
    finally:
        conn.close()
@app.route('/teacher/profile')
def professor_profile():
    if 'user_id' not in session or session.get('user_role') != 'professeur':
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    try:
        # Get professor information
        professor = conn.execute(
            'SELECT * FROM users WHERE id = ?', 
            (session['user_id'],)
        ).fetchone()
        
        if not professor:
            flash('Professeur non trouvé', 'error')
            return redirect(url_for('teacher_dashboard'))
        
        # Get courses taught by this professor
        courses_taught = conn.execute('''
            SELECT c.id, c.nom_cours, c.classe 
            FROM courses c
            WHERE c.professeur_id = ?
            ORDER BY c.nom_cours
        ''', (session['user_id'],)).fetchall()
        
        return render_template('professor_profile.html',
                            professor=dict(professor),
                            courses_taught=courses_taught)
        
    except Exception as e:
        print(f"Error in professor_profile: {e}")
        flash('Erreur lors du chargement du profil', 'error')
        return redirect(url_for('teacher_dashboard'))
    finally:
        conn.close()

@app.route('/update_professor_profile', methods=['POST'])
def update_professor_profile():
    if 'user_id' not in session or session.get('user_role') != 'professeur':
        return redirect(url_for('index'))
    
    email = request.form.get('email')
    telephone = request.form.get('telephone')
    
    # Basic validation
    if not email:
        flash('L\'email est obligatoire', 'error')
        return redirect(url_for('professor_profile'))
    
    conn = get_db_connection()
    try:
        conn.execute('''
            UPDATE users 
            SET email = ?, telephone = ?
            WHERE id = ?
        ''', (email, telephone, session['user_id']))
        
        conn.commit()
        flash('Profil mis à jour avec succès', 'success')
    except sqlite3.IntegrityError:
        flash('Cet email est déjà utilisé par un autre utilisateur', 'error')
    except Exception as e:
        conn.rollback()
        flash(f'Erreur lors de la mise à jour: {str(e)}', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('professor_profile'))
@app.route('/generate_qr/<int:course_id>')
def generate_qr_route(course_id):
    if 'user_id' not in session or session.get('user_role') != 'professeur':
        return jsonify({'error': 'Non autorisé'}), 401
    
    teacher_id = session['user_id']
    token = create_qr_token(teacher_id, course_id)
    
    if token:
        qr_image = generate_qr_code(token)
        return jsonify({'qr_code': qr_image, 'token': token})
    else:
        return jsonify({'error': 'Erreur lors de la génération du QR code'}), 500

@app.route('/teacher/courses')
def get_teacher_courses():
    if 'user_id' not in session or session.get('user_role') != 'professeur':
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db_connection()
    try:
        courses = conn.execute('''
            SELECT * FROM courses 
            WHERE professeur_id = ?
            ORDER BY nom_cours
        ''', (session['user_id'],)).fetchall()
        return jsonify([dict(course) for course in courses])
    finally:
        conn.close()

@app.route('/api/course_students/<int:course_id>')
def get_course_students(course_id):
    if 'user_id' not in session or session.get('user_role') != 'professeur':
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db_connection()
    try:
        course = conn.execute('SELECT classe FROM courses WHERE id = ?', (course_id,)).fetchone()
        if not course:
            return jsonify({'error': 'Course not found'}), 404
            
        students = conn.execute('''
            SELECT id, matricule, nom, prenom 
            FROM users 
            WHERE role = 'eleve' AND classe = ?
            ORDER BY nom, prenom
        ''', (course['classe'],)).fetchall()
        
        return jsonify([dict(student) for student in students])
    finally:
        conn.close()

@app.route('/api/today_attendance/<int:course_id>')
def get_today_attendance(course_id):
    if 'user_id' not in session or session.get('user_role') != 'professeur':
        return jsonify({'error': 'Unauthorized'}), 401
    
    today = datetime.now().date().isoformat()
    
    conn = get_db_connection()
    try:
        attendance = conn.execute('''
            SELECT a.*, u.nom as eleve_nom, u.prenom as eleve_prenom
            FROM attendance a
            JOIN users u ON a.eleve_id = u.id
            WHERE a.course_id = ? AND a.date_presence = ?
            ORDER BY a.heure_presence DESC
        ''', (course_id, today)).fetchall()
        
        return jsonify([dict(record) for record in attendance])
    finally:
        conn.close()

@app.route('/api/course_attendance/<int:course_id>')
def get_course_attendance(course_id):
    if 'user_id' not in session or session.get('user_role') != 'professeur':
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db_connection()
    try:
        attendance = conn.execute('''
            SELECT a.*, u.nom as eleve_nom, u.prenom as eleve_prenom
            FROM attendance a
            JOIN users u ON a.eleve_id = u.id
            WHERE a.course_id = ?
            ORDER BY a.date_presence DESC, a.heure_presence DESC
        ''', (course_id,)).fetchall()
        
        return jsonify([dict(record) for record in attendance])
    finally:
        conn.close()

# Supervisor routes
@app.route('/supervisor_dashboard')
def supervisor_dashboard():
    # Get statistics data
    conn = get_db_connection()
    students = conn.execute('''
            SELECT id, matricule, nni, nom, prenom, classe, email, telephone 
            FROM users WHERE role = 'eleve' ORDER BY nom, prenom
        ''').fetchall()
        
        # Convert to list of dicts for easier template handling
    students_list = [dict(student) for student in students]
    stats = conn.execute('''
        SELECT 
            COUNT(DISTINCT eleve_id) as total_students,
            COUNT(DISTINCT professeur_id) as total_teachers,
            COUNT(*) as total_records,
            SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) as total_present,
            SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) as total_absent,
            SUM(CASE WHEN status = 'justified' THEN 1 ELSE 0 END) as total_justified
        FROM attendance
    ''').fetchone()

    # Get students with highest absence rates
    absent_students = conn.execute('''
        SELECT u.id, u.matricule, u.nom, u.prenom, u.classe,
               COUNT(a.id) as total_absences,
               ROUND(100.0 * SUM(CASE WHEN a.status = 'absent' THEN 1 ELSE 0 END) / COUNT(a.id), 1) as absence_rate
        FROM attendance a
        JOIN users u ON a.eleve_id = u.id
        WHERE u.role = 'eleve'
        GROUP BY u.id
        ORDER BY absence_rate DESC
        LIMIT 5
    ''').fetchall()

    # Get professors with their students' absence rates
    professor_stats = conn.execute('''
        SELECT p.id, p.nom, p.prenom, 
               COUNT(DISTINCT a.eleve_id) as student_count,
               ROUND(100.0 * SUM(CASE WHEN a.status = 'absent' THEN 1 ELSE 0 END) / COUNT(a.id), 1) as absence_rate
        FROM attendance a
        JOIN users p ON a.professeur_id = p.id
        WHERE p.role = 'professeur'
        GROUP BY p.id
        ORDER BY absence_rate DESC
        LIMIT 5
    ''').fetchall()

    # Get pending justifications
    pending_justifications = conn.execute('''
        SELECT j.id, j.reason_type, j.description, j.created_at,
               u.nom as eleve_nom, u.prenom as eleve_prenom, u.matricule as eleve_matricule,
               c.nom_cours, a.date_presence
        FROM justifications j
        JOIN attendance a ON j.attendance_id = a.id
        JOIN users u ON j.eleve_id = u.id
        JOIN courses c ON a.course_id = c.id
        WHERE j.status = 'en_attente'
        ORDER BY j.created_at DESC
        LIMIT 10
    ''').fetchall()

    # Get all classes for the class filter
    classes = [row['classe'] for row in conn.execute('''
        SELECT DISTINCT classe FROM users WHERE role = 'eleve' AND classe IS NOT NULL
    ''').fetchall()]

    # Calculate class stats
    class_stats = {}
    for class_name in classes:
        stats = conn.execute('''
            SELECT 
                ROUND(100.0 * SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) / COUNT(*), 1) as absence,
                ROUND(100.0 * SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) / COUNT(*), 1) as presence
            FROM attendance a
            JOIN users u ON a.eleve_id = u.id
            WHERE u.classe = ?
        ''', (class_name,)).fetchone()
        class_stats[class_name] = dict(stats)

    conn.close()

    return render_template('supervisor_dashboard.html',
                         students=students_list,
                         stats=dict(stats),
                         absent_students=absent_students,
                         professor_stats=professor_stats,
                         pending_justifications=pending_justifications,
                         classes=classes,
                         class_stats=class_stats,
                         absence_rates=class_stats)  
@app.route('/add_professor', methods=['POST'])
def add_professor():
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return redirect(url_for('index'))
    
    matricule = request.form.get('matricule')
    nni = request.form.get('nni')
    nom = request.form.get('nom')
    prenom = request.form.get('prenom')
    email = request.form.get('email', '')
    telephone = request.form.get('telephone', '')
    
    if not matricule or not nni or not nom or not prenom:
        flash('Matricule, NNI, nom et prénom sont obligatoires', 'error')
        return redirect(url_for('supervisor_dashboard'))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO users (matricule, nni, nom, prenom, role, email, telephone)
            VALUES (?, ?, ?, ?, 'professeur', ?, ?)
        """, (matricule, nni, nom, prenom, email, telephone))
        
        conn.commit()
        conn.close()
        
        flash(f'Professeur {prenom} {nom} ajouté avec succès', 'success')
    except sqlite3.IntegrityError:
        flash('Ce matricule existe déjà', 'error')
    except Exception as e:
        flash(f'Erreur lors de l\'ajout: {str(e)}', 'error')
    
    return redirect(url_for('supervisor_dashboard'))

@app.route('/add_course', methods=['POST'])
def add_course():
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return redirect(url_for('index'))
    
    nom_cours = request.form.get('nom_cours')
    code_cours = request.form.get('code_cours', '')
    classe = request.form.get('classe')
    professeur_id = request.form.get('professeur_id')
    credits = request.form.get('credits', '')
    description = request.form.get('description', '')
    
    if not nom_cours or not classe:
        flash('Le nom du cours et la classe sont obligatoires', 'error')
        return redirect(url_for('supervisor_dashboard'))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        professeur_id = int(professeur_id) if professeur_id else None
        credits = int(credits) if credits else None
        
        cursor.execute("""
            INSERT INTO courses (nom_cours, code_cours, professeur_id, classe, credits, description)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (nom_cours, code_cours, professeur_id, classe, credits, description))
        
        conn.commit()
        conn.close()
        
        flash(f'Cours "{nom_cours}" ajouté avec succès', 'success')
    except sqlite3.IntegrityError:
        flash('Ce cours existe déjà pour ce professeur et cette classe', 'error')
    except Exception as e:
        flash(f'Erreur lors de l\'ajout: {str(e)}', 'error')
    
    return redirect(url_for('supervisor_dashboard'))

# Justification management
@app.route('/approve_justification/<int:justification_id>', methods=['POST'])
def approve_justification(justification_id):
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'success': False, 'message': 'Non autorisé'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE justifications 
            SET status = 'validee', approved_at = ?, approved_by = ?
            WHERE id = ?
        """, (datetime.now(), session['user_id'], justification_id))
        
        cursor.execute("""
            SELECT attendance_id FROM justifications WHERE id = ?
        """, (justification_id,))
        result = cursor.fetchone()
        
        if result:
            cursor.execute("""
                UPDATE attendance 
                SET status = 'justified' 
                WHERE id = ?
            """, (result['attendance_id'],))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Justification approuvée'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/reject_justification/<int:justification_id>', methods=['POST'])
def reject_justification(justification_id):
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'success': False, 'message': 'Non autorisé'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE justifications 
            SET status = 'refusee', approved_at = ?, approved_by = ?
            WHERE id = ?
        """, (datetime.now(), session['user_id'], justification_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Justification rejetée'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

# API Routes
@app.route('/api/students', methods=['GET', 'POST'])
def api_students():
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'error': 'Unauthorized'}), 401
    
    if request.method == 'GET':
        # Get all students
        conn = get_db_connection()
        students = conn.execute('''
            SELECT id, matricule, nni, nom, prenom, classe, email, telephone 
            FROM users WHERE role = 'eleve' ORDER BY nom, prenom
        ''').fetchall()
        conn.close()
        return jsonify([dict(student) for student in students])
    
    elif request.method == 'POST':
        # Add new student
        data = request.get_json()
        required_fields = ['matricule', 'nni', 'nom', 'prenom', 'classe']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO users (matricule, nni, nom, prenom, role, classe, email, telephone)
                VALUES (?, ?, ?, ?, 'eleve', ?, ?, ?)
            ''', (
                data['matricule'], data['nni'], data['nom'], data['prenom'],
                data['classe'], data.get('email', ''), data.get('telephone', '')
            ))
            student_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'id': student_id}), 201
        except sqlite3.IntegrityError as e:
            return jsonify({'error': 'Matricule or NNI already exists'}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@app.route('/api/professors', methods=['GET', 'POST'])
def api_professors():
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'error': 'Unauthorized'}), 401
    
    if request.method == 'GET':
        conn = get_db_connection()
        professors = conn.execute('''
            SELECT id, matricule, nni, nom, prenom, email, telephone 
            FROM users WHERE role = 'professeur' ORDER BY nom, prenom
        ''').fetchall()
        conn.close()
        return jsonify([dict(professor) for professor in professors])
    
    elif request.method == 'POST':
        data = request.get_json()
        required_fields = ['matricule', 'nni', 'nom', 'prenom']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO users (matricule, nni, nom, prenom, role, email, telephone)
                VALUES (?, ?, ?, ?, 'professeur', ?, ?)
            ''', (
                data['matricule'], data['nni'], data['nom'], data['prenom'],
                data.get('email', ''), data.get('telephone', '')
            ))
            professor_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'id': professor_id}), 201
        except sqlite3.IntegrityError as e:
            return jsonify({'error': 'Matricule or NNI already exists'}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/delete_student/<int:student_id>', methods=['POST'])
def delete_student(student_id):
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'success': False, 'message': 'Non autorisé'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        attendance_count = cursor.execute(
            'SELECT COUNT(*) FROM attendance WHERE eleve_id = ?', 
            (student_id,)
        ).fetchone()[0]
        
        if attendance_count > 0:
            return jsonify({
                'success': False, 
                'message': 'Impossible de supprimer: l\'étudiant a des enregistrements de présence'
            })
        
        cursor.execute('DELETE FROM users WHERE id = ? AND role = "eleve"', (student_id,))
        
        if cursor.rowcount == 0:
            return jsonify({'success': False, 'message': 'Étudiant non trouvé'})
            
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Étudiant supprimé avec succès'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/delete_professor/<int:professor_id>', methods=['POST'])
def delete_professor(professor_id):
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'success': False, 'message': 'Non autorisé'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        course_count = cursor.execute(
            'SELECT COUNT(*) FROM courses WHERE professeur_id = ?', 
            (professor_id,)
        ).fetchone()[0]
        
        attendance_count = cursor.execute(
            'SELECT COUNT(*) FROM attendance WHERE professeur_id = ?', 
            (professor_id,)
        ).fetchone()[0]
        
        if course_count > 0 or attendance_count > 0:
            return jsonify({
                'success': False, 
                'message': 'Impossible de supprimer: le professeur a des cours ou des enregistrements'
            })
        
        cursor.execute('DELETE FROM users WHERE id = ? AND role = "professeur"', (professor_id,))
        
        if cursor.rowcount == 0:
            return jsonify({'success': False, 'message': 'Professeur non trouvé'})
            
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Professeur supprimé avec succès'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/delete_course/<int:course_id>', methods=['POST'])
def delete_course(course_id):
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'success': False, 'message': 'Non autorisé'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        attendance_count = cursor.execute(
            'SELECT COUNT(*) FROM attendance WHERE course_id = ?', 
            (course_id,)
        ).fetchone()[0]
        
        if attendance_count > 0:
            return jsonify({
                'success': False, 
                'message': 'Impossible de supprimer: le cours a des enregistrements de présence'
            })
        
        cursor.execute('DELETE FROM qr_codes WHERE course_id = ?', (course_id,))
        cursor.execute('DELETE FROM courses WHERE id = ?', (course_id,))
        
        if cursor.rowcount == 0:
            return jsonify({'success': False, 'message': 'Cours non trouvé'})
            
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Cours supprimé avec succès'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/edit_student/<int:student_id>', methods=['POST'])
def edit_student(student_id):
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return redirect(url_for('index'))
    
    matricule = request.form.get('matricule')
    nni = request.form.get('nni')
    nom = request.form.get('nom')
    prenom = request.form.get('prenom')
    email = request.form.get('email', '')
    telephone = request.form.get('telephone', '')
    classe = request.form.get('classe')
    
    if not matricule or not nni or not nom or not prenom:
        flash('Matricule, NNI, nom et prénom sont obligatoires', 'error')
        return redirect(url_for('supervisor_dashboard'))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE users 
            SET matricule = ?, nni = ?, nom = ?, prenom = ?, classe = ?, email = ?, telephone = ?
            WHERE id = ? AND role = 'eleve'
        """, (matricule, nni, nom, prenom, classe, email, telephone, student_id))
        
        if cursor.rowcount == 0:
            flash('Étudiant non trouvé', 'error')
        else:
            flash(f'Étudiant {prenom} {nom} modifié avec succès', 'success')
        
        conn.commit()
        conn.close()
        
    except sqlite3.IntegrityError:
        flash('Ce matricule existe déjà', 'error')
    except Exception as e:
        flash(f'Erreur lors de la modification: {str(e)}', 'error')
    
    return redirect(url_for('supervisor_dashboard'))

@app.route('/edit_professor/<int:professor_id>', methods=['POST'])
def edit_professor(professor_id):
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return redirect(url_for('index'))
    
    matricule = request.form.get('matricule')
    nni = request.form.get('nni')
    nom = request.form.get('nom')
    prenom = request.form.get('prenom')
    email = request.form.get('email', '')
    telephone = request.form.get('telephone', '')
    
    if not matricule or not nni or not nom or not prenom:
        flash('Matricule, NNI, nom et prénom sont obligatoires', 'error')
        return redirect(url_for('supervisor_dashboard'))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE users 
            SET matricule = ?, nni = ?, nom = ?, prenom = ?, email = ?, telephone = ?
            WHERE id = ? AND role = 'professeur'
        """, (matricule, nni, nom, prenom, email, telephone, professor_id))
        
        if cursor.rowcount == 0:
            flash('Professeur non trouvé', 'error')
        else:
            flash(f'Professeur {prenom} {nom} modifié avec succès', 'success')
        
        conn.commit()
        conn.close()
        
    except sqlite3.IntegrityError:
        flash('Ce matricule existe déjà', 'error')
    except Exception as e:
        flash(f'Erreur lors de la modification: {str(e)}', 'error')
    
    return redirect(url_for('supervisor_dashboard'))

@app.route('/edit_course/<int:course_id>', methods=['POST'])
def edit_course(course_id):
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return redirect(url_for('index'))
    
    nom_cours = request.form.get('nom_cours')
    code_cours = request.form.get('code_cours', '')
    classe = request.form.get('classe')
    professeur_id = request.form.get('professeur_id')
    credits = request.form.get('credits', '')
    description = request.form.get('description', '')
    
    if not nom_cours or not classe:
        flash('Le nom du cours et la classe sont obligatoires', 'error')
        return redirect(url_for('supervisor_dashboard'))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        professeur_id = int(professeur_id) if professeur_id else None
        credits = int(credits) if credits else None
        
        cursor.execute("""
            UPDATE courses 
            SET nom_cours = ?, code_cours = ?, professeur_id = ?, classe = ?, credits = ?, description = ?
            WHERE id = ?
        """, (nom_cours, code_cours, professeur_id, classe, credits, description, course_id))
        
        if cursor.rowcount == 0:
            flash('Cours non trouvé', 'error')
        else:
            flash(f'Cours "{nom_cours}" modifié avec succès', 'success')
        
        conn.commit()
        conn.close()
        
    except sqlite3.IntegrityError:
        flash('Ce cours existe déjà pour ce professeur et cette classe', 'error')
    except Exception as e:
        flash(f'Erreur lors de la modification: {str(e)}', 'error')
    
    return redirect(url_for('supervisor_dashboard'))

@app.route('/api/student/<int:student_id>')
def get_student(student_id):
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'error': 'Non autorisé'}), 401
    
    conn = get_db_connection()
    student = conn.execute(
        'SELECT * FROM users WHERE id = ? AND role = "eleve"', 
        (student_id,)
    ).fetchone()
    conn.close()
    
    if student:
        return jsonify(dict(student))
    else:
        return jsonify({'error': 'Étudiant non trouvé'}), 404

@app.route('/api/justifications/<int:justification_id>', methods=['PUT'])
def update_justification(justification_id):
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    if 'status' not in data or data['status'] not in ['validee', 'refusee']:
        return jsonify({'error': 'Invalid status'}), 400
    
    try:
        conn = get_db_connection()
        
        # Update justification status
        conn.execute('''
            UPDATE justifications 
            SET status = ?, approved_at = datetime('now'), approved_by = ?
            WHERE id = ?
        ''', (data['status'], session['user_id'], justification_id))
        
        # Update attendance record if approved
        if data['status'] == 'validee':
            conn.execute('''
                UPDATE attendance 
                SET status = 'justified' 
                WHERE id = (SELECT attendance_id FROM justifications WHERE id = ?)
            ''', (justification_id,))
        
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    
# Student CRUD API
@app.route('/api/students/<int:student_id>', methods=['GET', 'PUT', 'DELETE'])
def api_student(student_id):
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db_connection()
    
    if request.method == 'GET':
        student = conn.execute('''
            SELECT id, matricule, nni, nom, prenom, classe, email, telephone 
            FROM users WHERE id = ? AND role = 'eleve'
        ''', (student_id,)).fetchone()
        conn.close()
        return jsonify(dict(student)) if student else jsonify({'error': 'Student not found'}), 404
    
    elif request.method == 'PUT':
        data = request.get_json()
        try:
            conn.execute('''
                UPDATE users 
                SET matricule = ?, nni = ?, nom = ?, prenom = ?, classe = ?, email = ?, telephone = ?
                WHERE id = ? AND role = 'eleve'
            ''', (
                data['matricule'], data['nni'], data['nom'], data['prenom'],
                data['classe'], data.get('email', ''), data.get('telephone', ''),
                student_id
            ))
            conn.commit()
            conn.close()
            return jsonify({'success': True})
        except sqlite3.IntegrityError:
            return jsonify({'error': 'Matricule or NNI already exists'}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    elif request.method == 'DELETE':
        try:
            # Check if student has attendance records
            attendance_count = conn.execute('''
                SELECT COUNT(*) FROM attendance WHERE eleve_id = ?
            ''', (student_id,)).fetchone()[0]
            
            if attendance_count > 0:
                return jsonify({
                    'error': 'Cannot delete student with attendance records',
                    'attendance_count': attendance_count
                }), 400
            
            conn.execute('DELETE FROM users WHERE id = ? AND role = "eleve"', (student_id,))
            conn.commit()
            conn.close()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

# Generate CSRF token
@app.before_request
def csrf_protect():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(16)    
@app.route('/api/professor/<int:professor_id>')
def get_professor(professor_id):
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'error': 'Non autorisé'}), 401
    
    conn = get_db_connection()
    professor = conn.execute(
        'SELECT * FROM users WHERE id = ? AND role = "professeur"', 
        (professor_id,)
    ).fetchone()
    conn.close()
    
    if professor:
        return jsonify(dict(professor))
    else:
        return jsonify({'error': 'Professeur non trouvé'}), 404

@app.route('/api/course/<int:course_id>')
def get_course(course_id):
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'error': 'Non autorisé'}), 401
    
    conn = get_db_connection()
    course = conn.execute(
        'SELECT * FROM courses WHERE id = ?', 
        (course_id,)
    ).fetchone()
    conn.close()
    
    if course:
        return jsonify(dict(course))
    else:
        return jsonify({'error': 'Cours non trouvé'}), 404

@app.route('/delete_attendance/<int:attendance_id>', methods=['POST'])
def delete_attendance(attendance_id):
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'success': False, 'message': 'Non autorisé'})
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM justifications WHERE attendance_id = ?', (attendance_id,))
        cursor.execute('DELETE FROM attendance WHERE id = ?', (attendance_id,))
        
        if cursor.rowcount == 0:
            return jsonify({'success': False, 'message': 'Enregistrement non trouvé'})
            
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Enregistrement supprimé avec succès'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'})

@app.route('/get_student_attendance/<int:student_id>')
def get_student_attendance(student_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Non autorisé'}), 401
    
    conn = get_db_connection()
    attendance = conn.execute('''
        SELECT a.*, c.nom_cours, u.nom as prof_nom, u.prenom as prof_prenom
        FROM attendance a
        JOIN courses c ON a.course_id = c.id
        JOIN users u ON a.professeur_id = u.id
        WHERE a.eleve_id = ?
        ORDER BY a.date_presence DESC, a.heure_presence DESC
    ''', (student_id,)).fetchall()
    conn.close()
    
    return jsonify([dict(row) for row in attendance])

@app.route('/debug/session')
def debug_session_route():
    if app.debug:
        return jsonify({
            'session': dict(session),
            'user_id': session.get('user_id'),
            'user_role': session.get('user_role'),
            'user_name': session.get('user_name')
        })
    return jsonify({'error': 'Debug mode not enabled'}), 403

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='127.0.0.1', port=5000)