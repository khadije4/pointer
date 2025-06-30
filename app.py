from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash,make_response
import sqlite3
import qrcode
import io
import base64
from datetime import datetime, timedelta
import secrets
import os
from werkzeug.utils import secure_filename
from openpyxl import Workbook
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle

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
            status TEXT DEFAULT 'en_attente' CHECK(status IN ('en_attente', 'refusee', 'validee')),
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
                ('PROF010','2234567899','rifaa','sadegh','professeur', NULL, NULL),                                                                                 
                
                ('C22932', '1234567890',  'Yacoub','El Hadi', 'eleve', 'DAII-L2', '+22232111101'),
('C23211', '1234567891',  'Fatou','Boureima', 'eleve', 'DAII-L2', '+22232111102'),
('C23282', '1234567892',  'Ismail','Sylla', 'eleve', 'DAII-L2', '+22232111103'),
('C23316', '1234567893',  'Alioune', 'Ba','eleve', 'DAII-L2', '+22232111104'),
('C23455', '1234567894',  'Aminata','Sow', 'eleve', 'DAII-L2', '+22232111105'),
('C23699', '1234567895',  'Cheikh','Fall', 'eleve', 'DAII-L2', '+22232111106'),
('C23785', '1234567896',  'Youssouf','Kane', 'eleve', 'DAII-L2', '+22232111107'),
('C23803', '1234567897',  'Abdoul','Wane', 'eleve', 'DAII-L2', '+22232111108'),
('C23945', '1234567898',  'Oum Lkeiri','Ahmed Cherif', 'eleve', 'DAII-L2', '+22230515163'),
('C24240', '1234567899',  'Neya','Mohamed Bebaha', 'eleve', 'DAII-L2', '+22233091086'),
('C24245', '1234567900',  'Rokia','Diagana', 'eleve', 'DAII-L2', '+22232111109'),
('C24333', '1234567901',  'Mohamedou','Abdoulaye', 'eleve', 'DAII-L2', '+22232111110'),
('C24522', '1234567902',  'Khadija','Salem Naji Abdellahi', 'eleve', 'DAII-L2', '+22227842321'),
('C24809', '1234567903',  'Ahmedou','Ould Elhacen', 'eleve', 'DAII-L2', '+22232111111'),
('C24828', '1234567904',  'Samba','Gaye', 'eleve', 'DAII-L2', '+22232111112'),
('C24903', '1234567905',  'Aboubacar','Yero', 'eleve', 'DAII-L2', '+22232111113'),
('C25094', '1234567907', 'Mariame','Mbaye',  'eleve', 'DAII-L2', '+22232111114'),
('C25101', '1234567908',  'Moulaye','Hamed', 'eleve', 'DAII-L2', '+22232111115'),
('C25366', '1234567909',  'Khoudia','Diop', 'eleve', 'DAII-L2', '+22232111116'),
('C22621', '1234567910', 'Moustapha', 'Khattri', 'eleve', 'MAIGE-L2', '+22232111117'),
('C22622', '1234567911',  'Ousmane','Sid’Ahmed', 'eleve', 'MAIGE-L2', '+22232111118'),
('C23073', '1234567912',  'Awa','Beye', 'eleve', 'MAIGE-L2', '+22232111119'),
('C23331', '1234567913',  'Lamine','MBareck', 'eleve', 'MAIGE-L2', '+22232111120'),
('C23625', '1234567914', 'Noura','Ahmed',  'eleve', 'MAIGE-L2', '+22232111121'),
('C23839', '1234567915',  'Zeinabou','Mane', 'eleve', 'MAIGE-L2', '+22232111122'),
('C23910', '1234567916',  'Fatimata','Moussa', 'eleve', 'MAIGE-L2', '+22232111123'),
('C24094', '1234567917',  'Issa','Abdel Kader', 'eleve', 'MAIGE-L2', '+22232111124'),
('C24228', '1234567918',  'Cheikhna', 'Moulaye','eleve', 'MAIGE-L2', '+22232111125'),
('C24451', '1234567919',  'Seynabou', 'Abdy','eleve', 'MAIGE-L2', '+22232111126'),
('C24544', '1234567920',  'Mouhamed Lehbib', 'Mamadou Bal','eleve', 'MAIGE-L2', '+22241787872'),
('C24664', '1234567921',  'Seynou','Ba', 'eleve', 'MAIGE-L2', '+22232111127'),
('C24884', '1234567922',  'Fatoumata','Bah', 'eleve', 'MAIGE-L2', '+22232111128'),
('C25105', '1234567923',  'Aly','Wedoud', 'eleve', 'MAIGE-L2', '+22232111129'),
('C25144', '1234567924',  'Hindou','Vall', 'eleve', 'MAIGE-L2', '+22232111130'),
('C25164', '1234567925', 'SidAhmed', 'Salimata', 'eleve', 'MAIGE-L2', '+22232111131'),
('C25273', '1234567926', 'HMeyd', 'Mohamed Mahmoud', 'eleve', 'MAIGE-L2', '+22232111132'),
('C25289', '1234567927', 'Cheikh', 'Veysoul', 'eleve', 'MAIGE-L2', '+22232111133'),
('C25321', '1234567928', 'Abdel Kader', 'Ndeye Coumba', 'eleve', 'MAIGE-L2', '+22232111134'),
('C25423', '1234567929', 'El Mokhtar', 'Amadou', 'eleve', 'MAIGE-L2', '+22232111135')
                       

        ''')
        stats = dict(conn.execute('''
    SELECT 
        (SELECT COUNT(*) FROM users WHERE role = 'eleve') as total_students,
        (SELECT COUNT(*) FROM users WHERE role = 'professeur') as total_teachers,
        COUNT(a.id) as total_records,
        SUM(CASE WHEN a.status = 'present' THEN 1 ELSE 0 END) as total_present,
        SUM(CASE WHEN a.status = 'absent' THEN 1 ELSE 0 END) as total_absent,
        SUM(CASE WHEN a.status = 'justified' THEN 1 ELSE 0 END) as total_justified
    FROM attendance a
''').fetchone())
        # Insert courses - Fixed syntax errors and standardized names
        cursor.execute('''
            INSERT INTO courses (nom_cours, professeur_id, classe) VALUES
                ('Marketing', (SELECT id FROM users WHERE matricule = 'PROF007'), 'DAII-L2'),
                ('Web Dynamique', (SELECT id FROM users WHERE matricule = 'PROF010'), 'DAII-L2'),
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
                ((SELECT id FROM users WHERE matricule = 'C24522'), (SELECT id FROM users WHERE matricule = 'PROF001'), 
                (SELECT id FROM courses WHERE nom_cours = 'Multimedia et Programmation Mobile' AND classe = 'DAII-L2'), 
                '2025-06-01', '09:00:00', 'present'),
                
                ((SELECT id FROM users WHERE matricule = 'C23211'), (SELECT id FROM users WHERE matricule = 'PROF001'), 
                (SELECT id FROM courses WHERE nom_cours = 'Multimedia et Programmation Mobile' AND classe = 'DAII-L2'), 
                '2025-06-01', '09:05:00', 'absent'),
                
                ((SELECT id FROM users WHERE matricule = 'C23282'), (SELECT id FROM users WHERE matricule = 'PROF005'), 
                (SELECT id FROM courses WHERE nom_cours = 'Web Dynamique' AND classe = 'DAII-L2'), 
                '2025-06-02', '10:00:00', 'absent'),
                ((SELECT id FROM users WHERE matricule = 'C24522'), (SELECT id FROM users WHERE matricule = 'PROF001'), 
                (SELECT id FROM courses WHERE nom_cours = 'Multimedia et Programmation Mobile' AND classe = 'DAII-L2'), 
                '2025-06-05', '09:00:00', 'absent'),
                
                ((SELECT id FROM users WHERE matricule = 'C24544'), (SELECT id FROM users WHERE matricule = 'PROF001'), 
                (SELECT id FROM courses WHERE nom_cours = 'Comptabilite Analytique' AND classe = 'MIAGE-L2'), 
                '2025-06-09', '09:05:00', 'absent'),
                
                ((SELECT id FROM users WHERE matricule = 'C2544'), (SELECT id FROM users WHERE matricule = 'PROF005'), 
                (SELECT id FROM courses WHERE nom_cours = 'Web Dynamique' AND classe = 'MAIGE-L2'), 
                '2025-06-02', '10:00:00', 'justified')
        ''')
        
        
        # Insert sample justifications - Fixed references
        cursor.execute('''
            INSERT INTO justifications (eleve_id, attendance_id, reason_type, document_path, status, description, approved_at, approved_by) VALUES
                ((SELECT id FROM users WHERE matricule = 'C23211'), 
                (SELECT id FROM attendance WHERE eleve_id = (SELECT id FROM users WHERE matricule = 'C23211') AND date_presence = '2025-06-01'), 
                'Maladie', 'justif_khadji_maladie.pdf', 'validee', 'test', datetime('now'), 
                (SELECT id FROM users WHERE matricule = 'SUPER001')),
                
                ((SELECT id FROM users WHERE matricule = 'C23282'), (SELECT id FROM attendance WHERE eleve_id = (SELECT id FROM users WHERE matricule = 'C23282') AND date_presence = '2025-06-02'), 
                'Problème familial','justif_mohamed_famille.pdf' , 'en_attente', '', NULL, NULL)
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
            ((SELECT id FROM courses WHERE nom_cours = 'Francais' AND classe = 'DAII-L2'), 5, '08:30', '10:30', '210', 'COURS', 'DAII-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Analyse des Donnees et DataMining' AND classe = 'DAII-L2'), 5, '10:30', '12:30', '202', 'COURS', 'DAII-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Multimedia et Programmation Mobile' AND classe = 'DAII-L2'), 4, '08:30', '10:30', '105', 'COURS', 'DAII-L2'), 
            ((SELECT id FROM courses WHERE nom_cours = 'Multimedia et Programmation Mobile' AND classe = 'DAII-L2'), 4, '10:30', '12:30', '105', 'TP', 'DAII-L2')                   
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
            ((SELECT id FROM courses WHERE nom_cours = 'Francais' AND classe = 'MAIGE-L2'), 5, '08:30', '10:30', '210', 'COURS', 'MAIGE-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Analyse des Donnees et DataMining' AND classe = 'MAIGE-L2'), 5, '10:30', '12:30', '202', 'COURS', 'MAIGE-L2'),
            ((SELECT id FROM courses WHERE nom_cours = 'Comptabilite Analytique' AND classe = 'MAIGE-L2'), 5, '12:30', '14:00', '105', 'COURS', 'MAIGE-L2')
        ''')
    
        conn.commit()
     
     

def get_db_connection():
    conn = sqlite3.connect('attendance.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.context_processor
def utility_processor():
    def find_course(day_schedule, start_time, end_time):
        if not day_schedule:
            return None
        for course in day_schedule:
            if course['time_slot'] == f"{start_time}-{end_time}":
                return course
        return None
    return dict(find_course=find_course)

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
        
        # Transform schedule data into a structured format for the template
        schedule_data = {
            'Monday': [], 'Tuesday': [], 'Wednesday': [], 
            'Thursday': [], 'Friday': [], 'Saturday': []
        }
        
        for item in schedule:
            day_map = {
                0: 'Monday', 1: 'Tuesday', 2: 'Wednesday',
                3: 'Thursday', 4: 'Friday', 5: 'Saturday'
            }
            day_name = day_map.get(item['day_of_week'], 'Unknown')
            
            # Organize by time slots
            time_slot = f"{item['start_time']}-{item['end_time']}"
            
            schedule_data[day_name].append({
                'course_name': item['course_name'],
                'room': item['room'],
                'type': item['type'],
                'time_slot': time_slot,
                'prof_name': f"{item['prof_nom']} {item['prof_prenom']}"
            })
        
        # Get attendance stats for the stats grid
        attendance_stats = conn.execute('''
            SELECT COUNT(*) as total_courses
            FROM attendance 
            WHERE eleve_id = ?
        ''', (session['user_id'],)).fetchone()
        
        # Get unique courses count
        courses = conn.execute('''
            SELECT DISTINCT c.id, c.nom_cours 
            FROM attendance a
            JOIN courses c ON a.course_id = c.id
            WHERE a.eleve_id = ?
        ''', (session['user_id'],)).fetchall()
        
        # Get unique rooms and labs
        unique_rooms = conn.execute('''
            SELECT DISTINCT room FROM schedule WHERE classe = ?
        ''', (student['classe'],)).fetchall()
        
        unique_labs = conn.execute('''
            SELECT DISTINCT room FROM schedule 
            WHERE classe = ? AND (room LIKE 'Lab%' OR room LIKE 'TP%')
        ''', (student['classe'],)).fetchall()
        
        return render_template('student_planning.html',
                            student=dict(student),
                            schedule=schedule_data,
                            attendance_stats=attendance_stats,
                            courses=courses,
                            unique_rooms=unique_rooms,
                            unique_labs=unique_labs)
        
    except Exception as e:
        print(f"Error in student_planning: {e}")
        flash('Error loading planning', 'error')
        return redirect(url_for('student_dashboard'))
    finally:
        conn.close()



@app.context_processor
def inject_stats():
    conn = get_db_connection()
    try:
        stats = conn.execute('''
            SELECT
                (SELECT COUNT(*) FROM users WHERE role = 'eleve') as total_students,
                (SELECT COUNT(*) FROM users WHERE role = 'professeur') as total_teachers,
                (SELECT COUNT(*) FROM attendance WHERE status = 'present') as total_present,
                (SELECT COUNT(*) FROM attendance WHERE status = 'absent') as total_absent,
                (SELECT COUNT(*) FROM attendance WHERE status = 'justified') as total_justified
        ''').fetchone()
        
        # Convert None values to 0
        stats_dict = dict(stats) if stats else {}
        for key in ['total_students', 'total_teachers', 'total_present', 'total_absent', 'total_justified']:
            stats_dict[key] = stats_dict.get(key, 0)
            
        return {'stats': stats_dict}
    except Exception as e:
        print(f"Error loading stats: {e}")
        return {'stats': {
            'total_students': 0,
            'total_teachers': 0,
            'total_present': 0,
            'total_absent': 0,
            'total_justified': 0
        }}
    finally:
        conn.close()


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

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            matricule = request.form.get('matricule', '').strip().upper()
            nni = request.form.get('nni', '').strip()
            
            if not matricule or not nni:
                flash('Matricule et NNI requis', 'error')
                return render_template('login.html', 
                                    matricule_value=matricule,
                                    nni_value=nni)
            
            # Check if matricule exists
            conn = get_db_connection()
            user = conn.execute('SELECT * FROM users WHERE matricule = ?', (matricule,)).fetchone()
            conn.close()
            
            if not user:
                flash('Matricule incorrect', 'error')
                return render_template('login.html',
                                    error_field='matricule',
                                    matricule_value=matricule,
                                    nni_value=nni)
            
            # Verify NNI
            if user['nni'] != nni:
                flash('NNI incorrect', 'error')
                return render_template('login.html',
                                    error_field='nni',
                                    matricule_value=matricule,
                                    nni_value=nni)
            
            # Successful login
            session.clear()
            session['user_id'] = user['id']
            session['user_role'] = user['role']
            session['user_name'] = f"{user['nom']} {user['prenom']}"
            session['matricule'] = user['matricule']
            
            if user['role'] == 'eleve':
                return redirect(url_for('student_dashboard'))
            elif user['role'] == 'professeur':
                return redirect(url_for('teacher_dashboard'))
            elif user['role'] == 'superviseur':
                return redirect(url_for('supervisor_dashboard'))
            else:
                flash('Rôle utilisateur non reconnu', 'error')
                return render_template('login.html')
                
        except Exception as e:
            app.logger.error(f"Login error: {e}")
            flash('Erreur système. Veuillez réessayer.', 'error')
            return render_template('login.html')
    
    # GET request - show login form
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
        
        # Get recent attendance records
        recent_attendance = conn.execute('''
            SELECT a.*, c.nom_cours, u.nom as prof_nom, u.prenom as prof_prenom
            FROM attendance a
            JOIN courses c ON a.course_id = c.id
            JOIN users u ON a.professeur_id = u.id
            WHERE a.eleve_id = ?
            ORDER BY a.date_presence DESC, a.heure_presence DESC
            LIMIT 10
        ''', (student_id,)).fetchall()
        
        # Convert Row objects to dictionaries and process dates/times
        attendance_list = []
        for record in recent_attendance:
            record_dict = dict(record)
            
            # Process date if it's a string
            if isinstance(record_dict['date_presence'], str):
                record_dict['date_presence'] = datetime.strptime(record_dict['date_presence'], '%Y-%m-%d').date()
            
            # Process time (handles both "HH:MM" and "HH:MM:SS")
            if isinstance(record_dict['heure_presence'], str):
                time_str = record_dict['heure_presence']
                try:
                    # Try parsing as "HH:MM:SS"
                    record_dict['heure_presence'] = datetime.strptime(time_str, '%H:%M:%S').time()
                except ValueError:
                    try:
                        # Fallback to "HH:MM"
                        record_dict['heure_presence'] = datetime.strptime(time_str, '%H:%M').time()
                    except ValueError:
                        # If still invalid, set to None
                        record_dict['heure_presence'] = None
            
            attendance_list.append(record_dict)
        
        # Get attendance stats (unchanged)
        attendance_stats = conn.execute('''
            SELECT 
                COUNT(*) as total_courses,
                SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) as present_count,
                SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) as absent_count
            FROM attendance 
            WHERE eleve_id = ?
        ''', (student_id,)).fetchone()
        
        return render_template('student_dashboard.html', 
                            recent_attendance=attendance_list,
                            stats=attendance_stats)
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
        
        # Get student information
        student_info = conn.execute(
            'SELECT * FROM users WHERE id = ?', 
            (student_id,)
        ).fetchone()
        
        # Get all attendance records for the student
        attendance_records = conn.execute('''
            SELECT a.*, c.nom_cours, u.nom as prof_nom, u.prenom as prof_prenom
            FROM attendance a
            JOIN courses c ON a.course_id = c.id
            JOIN users u ON a.professeur_id = u.id
            WHERE a.eleve_id = ?
            ORDER BY a.date_presence DESC, a.heure_presence DESC
        ''', (student_id,)).fetchall()
        
        # Convert Row objects to dictionaries and process dates/times
        processed_records = []
        for record in attendance_records:
            record_dict = dict(record)
            
            # Process date if it's a string
            if isinstance(record_dict['date_presence'], str):
                record_dict['date_presence'] = datetime.strptime(record_dict['date_presence'], '%Y-%m-%d').date()
            
            # Process time if it's a string (handles both HH:MM and HH:MM:SS)
            if isinstance(record_dict['heure_presence'], str):
                time_str = record_dict['heure_presence']
                try:
                    # Try parsing as HH:MM:SS first
                    record_dict['heure_presence'] = datetime.strptime(time_str, '%H:%M:%S').time()
                except ValueError:
                    try:
                        # Fall back to HH:MM if first attempt fails
                        record_dict['heure_presence'] = datetime.strptime(time_str, '%H:%M').time()
                    except ValueError:
                        # If still can't parse, set to None
                        record_dict['heure_presence'] = None
            
            processed_records.append(record_dict)
        
        # Get attendance stats
        stats = conn.execute('''
            SELECT 
                COUNT(*) as total_courses,
                SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) as present_count,
                SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) as absent_count,
                SUM(CASE WHEN status = 'justified' THEN 1 ELSE 0 END) as justified_count
            FROM attendance 
            WHERE eleve_id = ?
        ''', (student_id,)).fetchone()
        
        # Get pending justifications count
        pending_count = conn.execute('''
            SELECT COUNT(*) as count FROM justifications 
            WHERE eleve_id = ? AND status = 'en_attente'
        ''', (student_id,)).fetchone()['count']
        
        # Calculate attendance rate
        attendance_rate = 0
        if stats['total_courses'] > 0:
            attendance_rate = round((stats['present_count'] / stats['total_courses']) * 100, 1)
        
        
        courses = conn.execute('''
            SELECT DISTINCT c.id, c.nom_cours 
            FROM attendance a
            JOIN courses c ON a.course_id = c.id
            WHERE a.eleve_id = ?
            ORDER BY c.nom_cours
        ''', (student_id,)).fetchall()
        
        
        attendance_trend = 0
        
        return render_template('student_attendance.html',
                            student_info=dict(student_info) if student_info else None,
                            attendance_records=processed_records,
                            stats=dict(stats),
                            attendance_rate=attendance_rate,
                            attendance_trend=attendance_trend,
                            justified_count=stats['justified_count'],
                            pending_count=pending_count,
                            courses=courses)
    except Exception as e:
        print(f"Error in mes_presences: {e}")
        flash('Erreur lors du chargement des présences', 'error')
        return redirect(url_for('student_dashboard'))
    finally:
        conn.close()



@app.route('/export/attendance/excel')
def export_attendance_excel():
    if 'user_id' not in session or session.get('user_role') != 'eleve':
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    try:
        # Get attendance data
        attendance = conn.execute('''
            SELECT a.date_presence, a.heure_presence, a.status, 
                   c.nom_cours, u.nom as prof_nom, u.prenom as prof_prenom
            FROM attendance a
            JOIN courses c ON a.course_id = c.id
            JOIN users u ON a.professeur_id = u.id
            WHERE a.eleve_id = ?
            ORDER BY a.date_presence DESC, a.heure_presence DESC
        ''', (session['user_id'],)).fetchall()
        
        # Create Excel workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Mes Présences"
        
        # Add headers
        headers = ["Date", "Heure", "Statut", "Matière", "Professeur"]
        ws.append(headers)
        
        # Add data
        for record in attendance:
            ws.append([
                record['date_presence'],
                record['heure_presence'],
                'Présent' if record['status'] == 'present' else 'Absent' if record['status'] == 'absent' else 'Justifié',
                record['nom_cours'],
                f"{record['prof_prenom']} {record['prof_nom']}"
            ])
        
        # Create response
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = f'attachment; filename=mes_presences_{datetime.now().strftime("%Y%m%d")}.xlsx'
        
        return response
    finally:
        conn.close()

@app.route('/export/attendance/pdf')
def export_attendance_pdf():
    if 'user_id' not in session or session.get('user_role') != 'eleve':
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    try:
        # Get attendance data
        attendance = conn.execute('''
            SELECT a.date_presence, a.heure_presence, a.status, 
                   c.nom_cours, u.nom as prof_nom, u.prenom as prof_prenom
            FROM attendance a
            JOIN courses c ON a.course_id = c.id
            JOIN users u ON a.professeur_id = u.id
            WHERE a.eleve_id = ?
            ORDER BY a.date_presence DESC, a.heure_presence DESC
        ''', (session['user_id'],)).fetchall()
        
        # Create PDF
        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        
        # Add title
        p.setFont("Helvetica-Bold", 16)
        p.drawString(50, 750, "Historique de Présence")
        
        # Student info
        p.setFont("Helvetica", 12)
        student = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        p.drawString(50, 720, f"Étudiant: {student['prenom']} {student['nom']}")
        p.drawString(50, 700, f"Classe: {student['classe']}")
        p.drawString(50, 680, f"Généré le: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        
        # Prepare data for table
        data = [["Date", "Heure", "Statut", "Matière", "Professeur"]]
        for record in attendance:
            data.append([
                record['date_presence'],
                record['heure_presence'],
                'Présent' if record['status'] == 'present' else 'Absent' if record['status'] == 'absent' else 'Justifié',
                record['nom_cours'],
                f"{record['prof_prenom']} {record['prof_nom']}"
            ])
        
        # Create table
        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        
        # Draw table
        table.wrapOn(p, 400, 600)
        table.drawOn(p, 50, 550)
        
        p.showPage()
        p.save()
        
        buffer.seek(0)
        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=mes_presences_{datetime.now().strftime("%Y%m%d")}.pdf'
        
        return response
    finally:
        conn.close()

@app.route('/attendance_detail/<int:attendance_id>')
def attendance_detail(attendance_id):
    if 'user_id' not in session or session.get('user_role') != 'eleve':
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    try:
        # Get attendance record
        record = conn.execute('''
            SELECT a.*, c.nom_cours, u.nom as prof_nom, u.prenom as prof_prenom,
                   j.reason_type, j.description as justification_desc, j.status as justification_status
            FROM attendance a
            JOIN courses c ON a.course_id = c.id
            JOIN users u ON a.professeur_id = u.id
            LEFT JOIN justifications j ON a.id = j.attendance_id
            WHERE a.id = ? AND a.eleve_id = ?
        ''', (attendance_id, session['user_id'])).fetchone()
        
        if not record:
            flash('Enregistrement de présence non trouvé', 'error')
            return redirect(url_for('mes_presences'))
        
        # Convert to dict and process dates
        record_dict = dict(record)
        if isinstance(record_dict['date_presence'], str):
            record_dict['date_presence'] = datetime.strptime(record_dict['date_presence'], '%Y-%m-%d').date()
        
        # Process time (handles both HH:MM and HH:MM:SS formats)
        if isinstance(record_dict['heure_presence'], str):
            time_str = record_dict['heure_presence']
            try:
                # Try parsing as HH:MM:SS first
                record_dict['heure_presence'] = datetime.strptime(time_str, '%H:%M:%S').time()
            except ValueError:
                try:
                    # Fall back to HH:MM if first attempt fails
                    record_dict['heure_presence'] = datetime.strptime(time_str, '%H:%M').time()
                except ValueError:
                    # If still can't parse, set to None
                    record_dict['heure_presence'] = None
        
        return render_template('attendance_detail.html', record=record_dict)
    except Exception as e:
        print(f"Error in attendance_detail: {e}")
        flash('Erreur lors du chargement des détails de présence', 'error')
        return redirect(url_for('mes_presences'))
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
        
        return render_template('Justifier_Absence.html', absences=absences)
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
        
        student = conn.execute('''
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
                             student=student,
                             attendance_stats=attendance_stats)
    except Exception as e:
        print(f"Error in student_profile: {e}")
        flash('Erreur lors du chargement du profil', 'error')
        return redirect(url_for('student_dashboard'))
    finally:
        conn.close()
@app.route('/update_student_profile', methods=['POST'])
def update_student_profile():
    if 'user_id' not in session or session.get('user_role') != 'eleve':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    try:
        data = request.get_json() if request.is_json else request.form
        email = data.get('email')
        telephone = data.get('telephone')
        
        # Basic validation
        if not email:
            return jsonify({'success': False, 'message': 'Email is required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if email already exists for another user
        existing = cursor.execute('''
            SELECT id FROM users 
            WHERE email = ? AND id != ?
        ''', (email, session['user_id'])).fetchone()
        
        if existing:
            return jsonify({'success': False, 'message': 'Email already in use by another account'}), 400
        
        # Update student profile
        cursor.execute('''
            UPDATE users 
            SET email = ?, telephone = ?
            WHERE id = ? AND role = 'eleve'
        ''', (email, telephone, session['user_id']))
        
        if cursor.rowcount == 0:
            return jsonify({'success': False, 'message': 'No changes made or student not found'}), 400
        
        conn.commit()
        return jsonify({
            'success': True, 
            'message': 'Profile updated successfully',
            'data': {'email': email, 'telephone': telephone}
        })
        
    except Exception as e:
        conn.rollback()
        print(f"Error updating student profile: {e}")
        return jsonify({'success': False, 'message': 'Internal server error'}), 500
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/api/student_info')
def api_student_info():
    if 'user_id' not in session or session.get('user_role') != 'eleve':
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db_connection()
    try:
        student = conn.execute(
            'SELECT id, matricule, nni, nom, prenom, classe, email, telephone FROM users WHERE id = ?',
            (session['user_id'],)
        ).fetchone()
        
        if not student:
            return jsonify({'error': 'Student not found'}), 404
        
        return jsonify(dict(student))
    except Exception as e:
        return jsonify({'error': str(e)}), 500
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
        return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db_connection()
    try:
        justifications = conn.execute('''
            SELECT j.*, 
                   a.date_presence, a.heure_presence, c.nom_cours,
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
    except Exception as e:
        return jsonify({'error': str(e)}), 500
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

@app.route('/supervisor_dashboard')
def supervisor_dashboard():
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    try:
        # Get all students - convert to dict
        students = [dict(row) for row in conn.execute('''
            SELECT id, matricule, nni, nom, prenom, classe, email, telephone 
            FROM users WHERE role = 'eleve' ORDER BY nom, prenom
        ''').fetchall()]
        
        # Get all professors - convert to dict
        professors = [dict(row) for row in conn.execute('''
            SELECT id, matricule, nni, nom, prenom, email, telephone 
            FROM users WHERE role = 'professeur' ORDER BY nom, prenom
        ''').fetchall()]
        
        # Get all courses - convert to dict and include professor names
        courses = []
        for row in conn.execute('''
            SELECT c.id, c.nom_cours, c.code_cours, c.professeur_id, c.classe, c.credits, c.description,
                   u.nom as prof_nom, u.prenom as prof_prenom
            FROM courses c
            LEFT JOIN users u ON c.professeur_id = u.id
            ORDER BY c.nom_cours
        ''').fetchall():
            course = dict(row)
            courses.append(course)
        
        # Get statistics - convert to dict
        stats = dict(conn.execute('''
             SELECT
                (SELECT COUNT(*) FROM users WHERE role = 'eleve') as total_students,
                (SELECT COUNT(*) FROM users WHERE role = 'professeur') as total_teachers,
                (SELECT COUNT(*) FROM attendance WHERE status = 'present') as total_present,
                (SELECT COUNT(*) FROM attendance WHERE status = 'absent') as total_absent,
                (SELECT COUNT(*) FROM attendance WHERE status = 'justified') as total_justified
        ''').fetchone())

        # Get students with highest absence rates - convert to dict
        absent_students = [dict(row) for row in conn.execute('''
            SELECT u.id, u.matricule, u.nom, u.prenom, u.classe,
                   COUNT(a.id) as total_absences,
                   ROUND(100.0 * SUM(CASE WHEN a.status = 'absent' THEN 1 ELSE 0 END) / COUNT(a.id), 1) as absence_rate
            FROM attendance a
            JOIN users u ON a.eleve_id = u.id
            WHERE u.role = 'eleve'
            GROUP BY u.id
            ORDER BY absence_rate DESC
            LIMIT 5
        ''').fetchall()]

        # Get professors with their students' absence rates - convert to dict
        professor_stats = [dict(row) for row in conn.execute('''
            SELECT p.id, p.nom, p.prenom, 
                   COUNT(DISTINCT a.eleve_id) as student_count,
                   ROUND(100.0 * SUM(CASE WHEN a.status = 'absent' THEN 1 ELSE 0 END) / COUNT(a.id), 1) as absence_rate
            FROM attendance a
            JOIN users p ON a.professeur_id = p.id
            WHERE p.role = 'professeur'
            GROUP BY p.id
            ORDER BY absence_rate DESC
            LIMIT 5
        ''').fetchall()]

        # Get pending justifications - convert to dict
        pending_justifications = [dict(row) for row in conn.execute('''
            SELECT j.id, j.reason_type, j.description, j.created_at,
                   u.nom as eleve_nom, u.prenom as eleve_prenom, u.matricule as eleve_matricule,
                   c.nom_cours, a.date_presence, j.status, j.document_path
            FROM justifications j
            JOIN attendance a ON j.attendance_id = a.id
            JOIN users u ON j.eleve_id = u.id
            JOIN courses c ON a.course_id = c.id
            WHERE j.status = 'en_attente'
            ORDER BY j.created_at DESC
        ''').fetchall()]

        # Get all classes for the class filter
        classes = [row['classe'] for row in conn.execute('''
            SELECT DISTINCT classe FROM users WHERE role = 'eleve' AND classe IS NOT NULL
        ''').fetchall()]

        # Calculate class stats - convert to dict
        class_stats = {}
        for class_name in classes:
            stats = dict(conn.execute('''
                SELECT 
                    ROUND(100.0 * SUM(CASE WHEN a.status = 'absent' THEN 1 ELSE 0 END) / COUNT(a.id), 1) as absence,
                    ROUND(100.0 * SUM(CASE WHEN a.status = 'present' THEN 1 ELSE 0 END) / COUNT(a.id), 1) as presence
                FROM attendance a
                JOIN users u ON a.eleve_id = u.id
                WHERE u.classe = ?
            ''', (class_name,)).fetchone())
            class_stats[class_name] = stats

        return render_template('supervisor_dashboard.html',
                            students=students,
                            professors=professors,
                            courses=courses,
                            stats=stats,
                            absent_students=absent_students,
                            professor_stats=professor_stats,
                            pending_justifications=pending_justifications,
                            classes=classes,
                            class_stats=class_stats)
    except Exception as e:
        print(f"Error in supervisor_dashboard: {e}")
        flash('Erreur lors du chargement du tableau de bord', 'error')
        return redirect(url_for('index'))
    finally:
        conn.close()

@app.route('/api/justifications/<int:justification_id>/update_status', methods=['PUT'])
def update_justification_status(justification_id):
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data or 'status' not in data or 'comment' not in data:
        return jsonify({'success': False, 'error': 'Missing status or comment'}), 400

    # Only allow changing from 'en_attente' to 'validee' or 'refusee'
    if data['status'] not in ['validee', 'refusee']:
        return jsonify({'success': False, 'error': 'Invalid status'}), 400

    conn = get_db_connection()
    try:
        # Check if justification exists and is pending
        justification = conn.execute('''
            SELECT * FROM justifications 
            WHERE id = ? AND status = 'en_attente'
        ''', (justification_id,)).fetchone()

        if not justification:
            return jsonify({'success': False, 'error': 'Justification not found or already processed'}), 404

        # Update justification status
        conn.execute('''
            UPDATE justifications 
            SET status = ?, 
                approved_at = datetime('now'),
                approved_by = ?,
                description = ?
            WHERE id = ?
        ''', (data['status'], session['user_id'], data['comment'], justification_id))

        # If approved, update attendance record to 'justified'
        if data['status'] == 'validee':
            conn.execute('''
                UPDATE attendance 
                SET status = 'justified' 
                WHERE id = ?
            ''', (justification['attendance_id'],))

        conn.commit()
        return jsonify({'success': True, 'message': 'Status updated successfully'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/justifications/pending', methods=['GET'])
def get_pending_justifications():
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    conn = get_db_connection()
    try:
        pending_justifications = conn.execute('''
            SELECT j.*, 
                   u.nom as eleve_nom, u.prenom as eleve_prenom,
                   c.nom_cours, a.date_presence
            FROM justifications j
            JOIN users u ON j.eleve_id = u.id
            JOIN attendance a ON j.attendance_id = a.id
            JOIN courses c ON a.course_id = c.id
            WHERE j.status = 'en_attente'
            ORDER BY j.created_at DESC
        ''').fetchall()

        return jsonify({
            'success': True,
            'justifications': [dict(row) for row in pending_justifications]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

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
    
    conn = get_db_connection()
    
    if request.method == 'GET':
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

@app.route('/api/professor/<int:professor_id>', methods=['GET', 'PUT', 'DELETE'])
def api_professor(professor_id):
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db_connection()
    
    try:
        if request.method == 'GET':
            professor = conn.execute('''
                SELECT id, matricule, nni, nom, prenom, email, telephone 
                FROM users WHERE id = ? AND role = 'professeur'
            ''', (professor_id,)).fetchone()
            
            if not professor:
                return jsonify({'error': 'Professor not found'}), 404
            return jsonify(dict(professor))
        
        elif request.method == 'PUT':
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400
            
            # Validate required fields
            required_fields = ['matricule', 'nni', 'nom', 'prenom']
            for field in required_fields:
                if not data.get(field):
                    return jsonify({'error': f'Missing required field: {field}'}), 400
            
            # Check if professor exists
            existing = conn.execute(
                'SELECT id FROM users WHERE id = ? AND role = "professeur"', 
                (professor_id,)
            ).fetchone()
            
            if not existing:
                return jsonify({'error': 'Professor not found'}), 404
            
            # Check for duplicate matricule/nni (excluding current professor)
            duplicate = conn.execute('''
                SELECT id FROM users 
                WHERE (matricule = ? OR nni = ?) AND id != ? AND role = 'professeur'
            ''', (data['matricule'], data['nni'], professor_id)).fetchone()
            
            if duplicate:
                return jsonify({'error': 'Matricule or NNI already exists'}), 400
            
            # Update professor
            conn.execute('''
                UPDATE users 
                SET matricule = ?, nni = ?, nom = ?, prenom = ?, email = ?, telephone = ?
                WHERE id = ? AND role = 'professeur'
            ''', (
                data['matricule'], data['nni'], data['nom'], data['prenom'],
                data.get('email', ''), data.get('telephone', ''),
                professor_id
            ))
            
            if conn.total_changes == 0:
                return jsonify({'error': 'No changes made'}), 400
            
            conn.commit()
            return jsonify({'success': True, 'message': 'Professor updated successfully'})
        
        elif request.method == 'DELETE':
            # Check if professor exists
            professor = conn.execute(
                'SELECT id FROM users WHERE id = ? AND role = "professeur"', 
                (professor_id,)
            ).fetchone()
            
            if not professor:
                return jsonify({'error': 'Professor not found'}), 404
            
            # Check for related records
            courses_count = conn.execute(
                'SELECT COUNT(*) as count FROM courses WHERE professeur_id = ?', 
                (professor_id,)
            ).fetchone()['count']
            
            if courses_count > 0:
                return jsonify({
                    'error': f'Cannot delete professor with {courses_count} associated courses. Please update or delete these courses first.',
                    'courses_count': courses_count
                }), 400
            
            # Delete professor
            conn.execute('DELETE FROM users WHERE id = ? AND role = "professeur"', (professor_id,))
            
            if conn.total_changes == 0:
                return jsonify({'error': 'Professor not found or already deleted'}), 404
            
            conn.commit()
            return jsonify({'success': True, 'message': 'Professor deleted successfully'})
    
    except sqlite3.IntegrityError as e:
        conn.rollback()
        return jsonify({'error': f'Database constraint error: {str(e)}'}), 400
    except Exception as e:
        conn.rollback()
        print(f"Error in api_professor: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500
    finally:
        conn.close()
@app.route('/api/courses', methods=['GET', 'POST'])
def api_courses():
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db_connection()
    
    if request.method == 'GET':
        courses = conn.execute('''
            SELECT c.*, u.nom as prof_nom, u.prenom as prof_prenom
            FROM courses c
            LEFT JOIN users u ON c.professeur_id = u.id
            ORDER BY c.nom_cours
        ''').fetchall()
        conn.close()
        return jsonify([dict(course) for course in courses])
    
    elif request.method == 'POST':
        data = request.get_json()
        required_fields = ['nom_cours', 'classe']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400
        
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO courses (nom_cours, code_cours, professeur_id, classe, credits, description)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                data['nom_cours'],
                data.get('code_cours', ''),
                data.get('professeur_id'),
                data['classe'],
                data.get('credits'),
                data.get('description', '')
            ))
            course_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'id': course_id}), 201
        except sqlite3.IntegrityError as e:
            return jsonify({'error': 'Course already exists for this professor and class'}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        

@app.route('/api/course/<int:course_id>', methods=['GET', 'PUT', 'DELETE'])
def api_course(course_id):
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db_connection()
    
    try:
        if request.method == 'GET':
            course = conn.execute('''
                SELECT c.*, u.nom as prof_nom, u.prenom as prof_prenom
                FROM courses c
                LEFT JOIN users u ON c.professeur_id = u.id
                WHERE c.id = ?
            ''', (course_id,)).fetchone()
            
            if not course:
                return jsonify({'error': 'Course not found'}), 404
            return jsonify(dict(course))
        
        elif request.method == 'PUT':
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400
            
            # Validate required fields
            required_fields = ['nom_cours', 'classe']
            for field in required_fields:
                if not data.get(field):
                    return jsonify({'error': f'Missing required field: {field}'}), 400
            
            # Check if course exists
            existing = conn.execute(
                'SELECT id FROM courses WHERE id = ?', 
                (course_id,)
            ).fetchone()
            
            if not existing:
                return jsonify({'error': 'Course not found'}), 404
            
            # Update course
            conn.execute('''
                UPDATE courses 
                SET nom_cours = ?, code_cours = ?, professeur_id = ?, 
                    classe = ?, credits = ?, description = ?
                WHERE id = ?
            ''', (
                data['nom_cours'],
                data.get('code_cours', ''),
                data.get('professeur_id'),
                data['classe'],
                data.get('credits'),
                data.get('description', ''),
                course_id
            ))
            
            if conn.total_changes == 0:
                return jsonify({'error': 'No changes made'}), 400
            
            conn.commit()
            return jsonify({'success': True, 'message': 'Course updated successfully'})
        
        elif request.method == 'DELETE':
            # Check if course exists
            course = conn.execute(
                'SELECT id FROM courses WHERE id = ?', 
                (course_id,)
            ).fetchone()
            
            if not course:
                return jsonify({'error': 'Course not found'}), 404
            
            # Check for related records
            attendance_count = conn.execute(
                'SELECT COUNT(*) as count FROM attendance WHERE course_id = ?', 
                (course_id,)
            ).fetchone()['count']
            
            if attendance_count > 0:
                return jsonify({
                    'error': f'Cannot delete course with {attendance_count} attendance records. Please delete these records first.',
                    'attendance_count': attendance_count
                }), 400
            
            # Delete course
            conn.execute('DELETE FROM courses WHERE id = ?', (course_id,))
            
            if conn.total_changes == 0:
                return jsonify({'error': 'Course not found or already deleted'}), 404
            
            conn.commit()
            return jsonify({'success': True, 'message': 'Course deleted successfully'})
    
    except sqlite3.IntegrityError as e:
        conn.rollback()
        return jsonify({'error': f'Database constraint error: {str(e)}'}), 400
    except Exception as e:
        conn.rollback()
        print(f"Error in api_course: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500
    finally:
        conn.close()


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





@app.route('/api/students/<int:student_id>', methods=['GET', 'PUT', 'DELETE'])
def api_student_fixed(student_id):
    if 'user_id' not in session or session.get('user_role') != 'superviseur':
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db_connection()
    
    try:
        if request.method == 'GET':
            student = conn.execute('''
                SELECT id, matricule, nni, nom, prenom, classe, email, telephone 
                FROM users WHERE id = ? AND role = 'eleve'
            ''', (student_id,)).fetchone()
            
            if not student:
                return jsonify({'error': 'Student not found'}), 404
            return jsonify(dict(student))
        
        elif request.method == 'PUT':
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400
            
            # Validate required fields
            required_fields = ['matricule', 'nni', 'nom', 'prenom', 'classe']
            for field in required_fields:
                if not data.get(field):
                    return jsonify({'error': f'Missing required field: {field}'}), 400
            
            # Check if student exists
            existing = conn.execute(
                'SELECT id FROM users WHERE id = ? AND role = "eleve"', 
                (student_id,)
            ).fetchone()
            
            if not existing:
                return jsonify({'error': 'Student not found'}), 404
            
            # Check for duplicate matricule/nni (excluding current student)
            duplicate = conn.execute('''
                SELECT id FROM users 
                WHERE (matricule = ? OR nni = ?) AND id != ? AND role = 'eleve'
            ''', (data['matricule'], data['nni'], student_id)).fetchone()
            
            if duplicate:
                return jsonify({'error': 'Matricule or NNI already exists'}), 400
            
            # Update student
            conn.execute('''
                UPDATE users 
                SET matricule = ?, nni = ?, nom = ?, prenom = ?, classe = ?, email = ?, telephone = ?
                WHERE id = ? AND role = 'eleve'
            ''', (
                data['matricule'], data['nni'], data['nom'], data['prenom'],
                data['classe'], data.get('email', ''), data.get('telephone', ''),
                student_id
            ))
            
            if conn.total_changes == 0:
                return jsonify({'error': 'No changes made'}), 400
            
            conn.commit()
            return jsonify({'success': True, 'message': 'Student updated successfully'})
        
        elif request.method == 'DELETE':
            # Check if student exists
            student = conn.execute(
                'SELECT id FROM users WHERE id = ? AND role = "eleve"', 
                (student_id,)
            ).fetchone()
            
            if not student:
                return jsonify({'error': 'Student not found'}), 404
            
            # Check for related records
            attendance_count = conn.execute(
                'SELECT COUNT(*) as count FROM attendance WHERE eleve_id = ?', 
                (student_id,)
            ).fetchone()['count']
            
            justification_count = conn.execute(
                'SELECT COUNT(*) as count FROM justifications WHERE eleve_id = ?', 
                (student_id,)
            ).fetchone()['count']
            
            if attendance_count > 0 or justification_count > 0:
                return jsonify({
                    'error': f'Cannot delete student with {attendance_count} attendance records and {justification_count} justifications. Please remove related records first.',
                    'attendance_count': attendance_count,
                    'justification_count': justification_count
                }), 400
            
            # Delete student
            conn.execute('DELETE FROM users WHERE id = ? AND role = "eleve"', (student_id,))
            
            if conn.total_changes == 0:
                return jsonify({'error': 'Student not found or already deleted'}), 404
            
            conn.commit()
            return jsonify({'success': True, 'message': 'Student deleted successfully'})
    
    except sqlite3.IntegrityError as e:
        conn.rollback()
        return jsonify({'error': f'Database constraint error: {str(e)}'}), 400
    except Exception as e:
        conn.rollback()
        print(f"Error in api_student_fixed: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500
    finally:
        conn.close()
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