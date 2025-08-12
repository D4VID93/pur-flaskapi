from flask import Flask, jsonify, render_template, send_file, request, redirect, url_for, session, flash
import psycopg2
import requests
from io import BytesIO
from azure.storage.blob import BlobServiceClient
import os
import json
from datetime import datetime
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from msal import ConfidentialClientApplication
import uuid
from functools import wraps

load_dotenv()

app = Flask(__name__)
app.config.update(
    SESSION_COOKIE_SECURE=True,  # À passer en True en production avec HTTPS
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax'
)
app.secret_key = os.getenv('SECRET_KEY')

# Configuration de la base de données
DB_CONFIG = {
    'host': os.getenv("POSTGRES_HOST"),
    'database': os.getenv("POSTGRES_DB"),
    'user': os.getenv("POSTGRES_USER"),
    'password': os.getenv("POSTGRES_PASSWORD"),
    'port': os.getenv("POSTGRES_PORT", "5432")
}

# Configuration Azure Blob Storage
AZURE_STORAGE_CONNECTION_STRING = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
CONTAINER_NAME = os.getenv("AZURE_STORAGE_CONTAINER")
blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)

# Clé secrète pour les uploads
UPLOAD_SECRET = os.getenv('UPLOAD_SECRET')

# Configuration Azure AD
AZURE_AD_CLIENT_ID = os.getenv('AZURE_AD_CLIENT_ID')
AZURE_AD_CLIENT_SECRET = os.getenv('AZURE_AD_CLIENT_SECRET')
AZURE_AD_TENANT_ID = os.getenv('AZURE_AD_TENANT_ID')
REDIRECT_URI = os.getenv('REDIRECT_URI')
ALLOWED_DOMAIN = os.getenv('ALLOWED_DOMAIN')

# Debug des variables d'environnement
print(f"AZURE_AD_CLIENT_ID: {AZURE_AD_CLIENT_ID}")
print(f"AZURE_AD_TENANT_ID: {AZURE_AD_TENANT_ID}")
print(f"REDIRECT_URI: {REDIRECT_URI}")
print(f"ALLOWED_DOMAIN: {ALLOWED_DOMAIN}")

# Initialiser le client MSAL
msal_app = ConfidentialClientApplication(
    AZURE_AD_CLIENT_ID,
    authority=f"https://login.microsoftonline.com/{AZURE_AD_TENANT_ID}",
    client_credential=AZURE_AD_CLIENT_SECRET
)

# ===========================================
# DÉCORATEURS D'AUTHENTIFICATION
# ===========================================

def require_auth():
    """Décorateur pour vérifier l'authentification"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def require_api_auth():
    """Décorateur pour les routes API"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                return jsonify({"error": "Unauthorized"}), 401
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def require_upload_token():
    """Décorateur pour vérifier le token d'upload"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                return redirect(url_for('login'))
            token = request.args.get("token")
            if token != UPLOAD_SECRET:
                return render_template("403.html"), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ===========================================
# FONCTIONS UTILITAIRES
# ===========================================

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

def build_folder_hierarchy(folders):
    """Construit une hiérarchie de dossiers à partir d'une liste plate"""
    folder_map = {f[0]: {"id": f[0], "name": f[1], "parent_id": f[2], "children": []} for f in folders}
    hierarchy = []
    
    for folder in folder_map.values():
        if folder["parent_id"] is None:
            hierarchy.append(folder)
        else:
            parent = folder_map.get(folder["parent_id"])
            if parent:
                parent["children"].append(folder)
    
    return hierarchy

def parse_tags(tags):
    """Parse les tags depuis différents formats (JSON, string, etc.)"""
    if not tags:
        return []
    
    if isinstance(tags, str):
        if tags.startswith(('["', "['")):
            try:
                return json.loads(tags)
            except json.JSONDecodeError:
                pass
        elif tags.startswith('{') and tags.endswith('}'):
            return [tag.strip().strip('"') for tag in tags[1:-1].split(',') if tag.strip()]
    
    return tags if isinstance(tags, list) else []

def get_files_for_folder(folder_id=None, page=1, per_page=None):
    """Récupère les fichiers pour un dossier donné (avec pagination)"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    query = """
        SELECT id, nom_fichier, lien_telechargement, description, tags, 
               is_exclusive, date_ajout, date_event, folder_id 
        FROM documents
    """
    params = []
    
    if folder_id:
        query = """
            WITH RECURSIVE folder_tree AS (
                SELECT id FROM folders WHERE id = %s
                UNION ALL
                SELECT f.id FROM folders f
                JOIN folder_tree ft ON f.parent_id = ft.id
            )
            SELECT id, nom_fichier, lien_telechargement, description, tags, 
                   is_exclusive, date_ajout, date_event, folder_id 
            FROM documents 
            WHERE folder_id IN (SELECT id FROM folder_tree)
        """
        params.append(folder_id)
    
    query += " ORDER BY nom_fichier"
    
    if per_page:
        offset = (page - 1) * per_page
        query += " LIMIT %s OFFSET %s"
        params.extend([per_page, offset])
    
    cur.execute(query, params)
    files = cur.fetchall()
    cur.close()
    conn.close()
    
    return files

def count_files_for_folder(folder_id=None):
    """Compte le nombre de fichiers dans un dossier et ses sous-dossiers"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    if folder_id:
        cur.execute("""
            WITH RECURSIVE folder_tree AS (
                SELECT id FROM folders WHERE id = %s
                UNION ALL
                SELECT f.id FROM folders f
                JOIN folder_tree ft ON f.parent_id = ft.id
            )
            SELECT COUNT(*) FROM documents 
            WHERE folder_id IN (SELECT id FROM folder_tree);
        """, (folder_id,))
    else:
        cur.execute("SELECT COUNT(*) FROM documents;")
    
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    
    return count

# ===========================================
# ROUTES D'AUTHENTIFICATION
# ===========================================

@app.route('/login')
def login():
    if 'user' in session:
        return redirect(url_for('index'))

    session.clear()  # Nettoyer la session
    state = str(uuid.uuid4())
    session['auth_state'] = state
    session.modified = True  # Force la sauvegarde de la session

    auth_url = msal_app.get_authorization_request_url(
        scopes=["User.Read"],
        redirect_uri=REDIRECT_URI,
        state=state  # Utilisez le même state que celui stocké
    )
    print(f"Redirecting to auth URL: {auth_url}")  # Debug
    return redirect(auth_url)

@app.route('/getAToken')
def authorized():
    print("\n=== DEBUG: Authorization callback ===")
    print(f"Request args: {request.args}")
    print(f"Session state: {session.get('auth_state')}")
    print(f"User in session: {session.get('user')}")

    if request.args.get('state') != session.get('auth_state'):
        print("State mismatch or expired session")
        session.pop('auth_state', None)
        flash("Session expired. Please try again.", "danger")
        return redirect(url_for('login'))

    code = request.args.get('code')
    if not code:
        flash("Authorization code missing", "danger")
        return redirect(url_for('login'))

    try:
        # récupération du token 
        result = msal_app.acquire_token_by_authorization_code(
            code,
            scopes=["User.Read"],
            redirect_uri=REDIRECT_URI
        )

        print(f"Token acquisition result: {result}")

        if "error" in result:
            error_msg = result.get('error_description', result.get('error', 'Unknown error'))
            print(f"Token error: {error_msg}")
            flash(f"Token acquisition failed: {error_msg}", "danger")
            return redirect(url_for('login'))

        # vérification renforcée du token
        if not result.get('id_token_claims'):
            print("No ID token claims in result")
            flash("Authentication failed: No user information", "danger")
            return redirect(url_for('login'))

        claims = result['id_token_claims']
        user_email = claims.get('preferred_username') or claims.get('email')
        
        if not user_email:
            print("No email in claims")
            flash("Authentication failed: No email found", "danger")
            return redirect(url_for('login'))

        # validation du domaine
        if not user_email.lower().endswith(f"@{ALLOWED_DOMAIN.lower()}"):
            print(f"Invalid domain for email: {user_email}")
            flash(f"Only @{ALLOWED_DOMAIN} accounts allowed", "danger")
            return redirect(url_for('login'))

        # Création de la session
        session['user'] = {
            'name': claims.get('name', ''),
            'email': user_email,
            'id': claims.get('oid'),
            'access_token': result.get('access_token')
        }

        print(f"User authenticated: {session['user']}")
        flash("Login successful", "success")
        return redirect(url_for('index'))

    except Exception as e:
        print(f"Exception during auth: {str(e)}")
        flash("Authentication error. Please try again.", "danger")
        return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    # rediriger vers la déconnexion Microsoft
    logout_url = f"https://login.microsoftonline.com/{AZURE_AD_TENANT_ID}/oauth2/v2.0/logout?post_logout_redirect_uri={request.url_root}login"
    return redirect(logout_url)

# ===========================================
# ROUTES PRINCIPALES
# ===========================================

@app.route('/')
@require_auth()
def index():
    # Param de pagination et filtrage
    page = request.args.get('page', 1, type=int)
    show_all = request.args.get('show_all', 'false') == 'true'
    folder_id = request.args.get('folder_id', None)
    per_page = 100 if not show_all else None
    
    # recup les fichiers
    files = get_files_for_folder(folder_id, page, per_page)
    total_files = count_files_for_folder(folder_id)
    
    # recup la structure des dossiers
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, parent_id FROM folders ORDER BY name;")
    folders = cur.fetchall()
    cur.close()
    conn.close()
    
    # formate les données pour le template
    files_data = []
    for doc in files:
        files_data.append({
            'id': doc[0],
            'nom': doc[1],
            'lien': doc[2],
            'description': doc[3] if doc[3] else "No description",
            'tags': parse_tags(doc[4]),
            'is_exclusive': bool(doc[5]) if doc[5] is not None else False,
            'date_ajout': doc[6],
            'date_event': doc[7].strftime("%d-%m-%Y") if doc[7] else None,
            'folder_id': doc[8]
        })
    
    # calcul le nombre total de pages
    total_pages = (total_files + per_page - 1) // per_page if per_page else 1
    
    return render_template("page_canto.html", 
                         files=files_data,
                         current_page=page,
                         total_pages=total_pages,
                         total_files=total_files,
                         show_all=show_all,
                         folder_hierarchy=build_folder_hierarchy(folders),
                         current_folder_id=folder_id,
                         username=session['user']['name'])

# ===========================================
# ROUTES POUR LES DOSSIERS
# ===========================================

@app.route("/get_folders")
@require_api_auth()
def get_folders():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Récupérer la structure des dossiers
    cur.execute("SELECT id, name, parent_id FROM folders ORDER BY name;")
    folders = cur.fetchall()
    
    cur.close()
    conn.close()
    
    # Construire la réponse
    folder_list = [{"id": f[0], "name": f[1], "parent_id": f[2]} for f in folders]
    
    return jsonify({"folders": folder_list})

@app.route("/create_folder", methods=['POST'])
@require_api_auth()
def create_folder():
    name = request.form.get("name")
    parent_id = request.form.get("parent_id")
    
    if not name:
        return jsonify({"status": "error", "message": "Folder name is required"}), 400
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO folders (name, parent_id) VALUES (%s, %s) RETURNING id;",
            (name, parent_id if parent_id else None))
        folder_id = cur.fetchone()[0]
        conn.commit()
        return jsonify({
            "status": "success",
            "folder": {"id": folder_id, "name": name, "parent_id": parent_id}
        }), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route("/delete_folder", methods=['POST'])
@require_api_auth()
def delete_folder():
    folder_id = request.form.get("folder_id")
    
    if not folder_id:
        return jsonify({"status": "error", "message": "Folder ID is required"}), 400
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Supprimer le dossier (les fichiers auront folder_id = NULL grâce à ON DELETE SET NULL)
        cur.execute("DELETE FROM folders WHERE id = %s;", (folder_id,))
        conn.commit()
        return jsonify({"status": "success"}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route("/update_file_folder", methods=['POST'])
@require_api_auth()
def update_file_folder():
    filename = request.form.get("filename")
    folder_id = request.form.get("folder_id")  # Peut être null
    
    if not filename:
        return jsonify({"status": "error", "message": "Filename is required"}), 400
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE documents SET folder_id = %s WHERE nom_fichier = %s;",
            (folder_id if folder_id else None, filename))
        conn.commit()
        return jsonify({"status": "success"}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()

# ===========================================
# ROUTES D'ADMINISTRATION
# ===========================================

@app.route("/upload")
@require_upload_token()
def upload_page():
    # Récupérer les dossiers pour le formulaire d'upload
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, parent_id FROM folders ORDER BY name;")
    folders = cur.fetchall()
    cur.close()
    conn.close()
    
    return render_template("upload.html", folders=build_folder_hierarchy(folders))

@app.route("/upload", methods=['POST'])
@require_api_auth()
def upload_file():
    files = request.files.getlist("files")
    descriptions = request.form.getlist("descriptions")
    tags_list = request.form.getlist("tags")
    date_events = request.form.getlist("date_events")
    folder_ids = request.form.getlist("folder_ids")
    
    uploaded_urls = []
    current_date = datetime.now().date()
    forbidden_extensions = {".heic", ".thm"}

    for i, file in enumerate(files):
        filename = file.filename
        ext = os.path.splitext(filename)[1].lower()

        if ext in forbidden_extensions:
            return jsonify({"status": "error", "message": f"The extension '{ext}' should be avoided, please convert it to another suitable format."}), 400

        description = descriptions[i] if i < len(descriptions) else ""
        tags = json.loads(tags_list[i]) if i < len(tags_list) and tags_list[i] else []
        date_event_str = date_events[i] if i < len(date_events) else None
        folder_id = folder_ids[i] if i < len(folder_ids) else None

        try:
            if date_event_str:
                day, month, year = map(int, date_event_str.split('-'))
                date_event = datetime(year, month, day).date()
            else:
                date_event = None
        except Exception as e:
            print(f"Error parsing date {date_event_str}: {str(e)}")
            date_event = None

        # Upload vers Azure Blob Storage
        blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=filename)
        blob_client.upload_blob(file.stream, overwrite=True)
        blob_url = blob_client.url
        
        # Enregistrement en base de données
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO documents (nom_fichier, lien_telechargement, description, tags, date_ajout, date_event, folder_id) VALUES (%s, %s, %s, %s, %s, %s, %s);",
            (filename, blob_url, description, json.dumps(tags), current_date, date_event, folder_id))
        conn.commit()
        cur.close()
        conn.close()

        uploaded_urls.append(blob_url)

    return jsonify({"status": "success", "urls": uploaded_urls}), 200

@app.route("/file_details")
@require_api_auth()
def get_file_details():
    filename = request.args.get("filename")

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT description, tags, date_ajout, is_exclusive, date_event, folder_id 
        FROM documents 
        WHERE nom_fichier = %s;
    """, (filename,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    
    if result:
        description, tags, date_ajout, is_exclusive, date_event, folder_id = result
        return jsonify({
            "description": description if description else "No description",
            "tags": parse_tags(tags),
            "date_ajout": date_ajout.strftime("%d-%m-%Y") if date_ajout else "",
            "is_exclusive": is_exclusive if is_exclusive is not None else False,
            "date_event": date_event.strftime("%d-%m-%Y") if date_event else "",
            "folder_id": folder_id
        })
    else:
        return jsonify({"error": "File not found"}), 404
    
@app.route("/delete")
@require_upload_token()
def delete_page():
    return render_template("delete.html")

@app.route("/delete_file", methods=['POST'])
@require_api_auth()
def delete_file():
    filename = request.form.get("filename")
    confirmation = request.form.get("confirmation") == "on"
    
    if not confirmation:
        return jsonify({"status": "error", "message": "Confirmation required"}), 400

    # Supprimer du stockage Azure
    blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=filename)
    try:
        blob_client.delete_blob()
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to delete from Azure: {str(e)}"}), 500

    # Supprimer de la base de données
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM documents WHERE nom_fichier = %s;", (filename,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": f"Failed to delete from database: {str(e)}"}), 500
    finally:
        cur.close()
        conn.close()

    return jsonify({"status": "success", "message": f"File {filename} deleted successfully"}), 200

@app.route("/search_file")
@require_api_auth()
def search_file():
    filename = request.args.get("filename")
    tags = request.args.getlist("tag")
    exclusive = request.args.get("exclusive") == "true"
    folder_id = request.args.get("folder_id")

    query = """
        SELECT nom_fichier, lien_telechargement, description, tags, is_exclusive, date_ajout, date_event 
        FROM documents
    """
    conditions = []
    params = []

    if filename:
        conditions.append("nom_fichier ILIKE %s")
        params.append(f"%{filename}%")

    if tags:
        tag_conditions = []
        for tag in tags:
            tag_conditions.append("%s = ANY(tags::text[])")
            params.append(tag)
        conditions.append("(" + " OR ".join(tag_conditions) + ")")

    if exclusive:
        conditions.append("is_exclusive = TRUE")
        
    if folder_id:
        conditions.append("folder_id = %s")
        params.append(folder_id)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY nom_fichier;"

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    results = cur.fetchall()
    cur.close()
    conn.close()

    files = []
    for nom, url, description, tags, is_exclusive, date_ajout, date_event in results:
        files.append({
            "name": nom,
            "url": url,
            "description": description,
            "tags": parse_tags(tags),
            "is_exclusive": is_exclusive if is_exclusive is not None else False,
            "date_ajout": date_ajout.strftime("%d-%m-%Y") if date_ajout else None,
            "date_event": date_event.strftime("%d-%m-%Y") if date_event else None
        })

    return jsonify(files)

@app.route("/update_exclusive", methods=['POST'])
@require_upload_token()
def update_exclusive():
    filename = request.form.get("filename")
    is_exclusive = request.form.get("is_exclusive") == 'true'
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE documents SET is_exclusive = %s WHERE nom_fichier = %s RETURNING is_exclusive;", 
                   (is_exclusive, filename))
        updated_value = cur.fetchone()[0]
        conn.commit()
        return jsonify({
            "status": "success", 
            "is_exclusive": bool(updated_value)
        }), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()

# ===========================================
# ROUTE DE DÉBOGAGE (À SUPPRIMER EN PRODUCTION)
# ===========================================

@app.route("/debug_session")
def debug_session():
    if app.debug:  # Seulement en mode debug
        return jsonify({
            "session": dict(session),
            "user_authenticated": 'user' in session,
            "user_info": session.get('user', 'Not logged in')
        })
    return jsonify({"error": "Debug mode disabled"}), 403

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)