from flask import Flask, jsonify, render_template, send_file, request
import psycopg2
import requests
from io import BytesIO
from azure.storage.blob import BlobServiceClient
import os
import json
from datetime import datetime
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

UPLOAD_SECRET = os.getenv('UPLOAD_SECRET')


# ===== CONFIGURATION DB =====
DB_CONFIG = {
    'host': os.getenv("POSTGRES_HOST"),
    'database': os.getenv("POSTGRES_DB"),
    'user': os.getenv("POSTGRES_USER"),
    'password': os.getenv("POSTGRES_PASSWORD"),
    'port': os.getenv("POSTGRES_PORT", "5432")
}

# ===== CONFIGURATION BLOB AZURE =====

#CONTAINER_NAME = "testcanto"
AZURE_STORAGE_CONNECTION_STRING = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
CONTAINER_NAME = os.getenv("AZURE_STORAGE_CONTAINER")
blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)

# ===== ROUTE PRINCIPALE =====
@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    show_all = request.args.get('show_all', 'false') == 'true'
    per_page = 100 if not show_all else None

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) FROM documents;")
    total_files = cur.fetchone()[0]
    
    if show_all:
        cur.execute("SELECT nom_fichier, lien_telechargement, description, tags, is_exclusive, date_ajout, date_event FROM documents ORDER BY nom_fichier;")
    else:
        offset = (page - 1) * per_page
        cur.execute("SELECT nom_fichier, lien_telechargement, description, tags, is_exclusive, date_ajout, date_event FROM documents ORDER BY nom_fichier LIMIT %s OFFSET %s;", 
                   (per_page, offset))
    
    files = cur.fetchall()
    cur.close()
    conn.close()
    
    files_data = []
    for nom, lien, description, tags, is_exclusive, date_ajout, date_event in files:
        # Parser les tags
        if isinstance(tags, str):
            if tags.startswith('["') or tags.startswith("['"):
                try:
                    tag_list = json.loads(tags)
                except json.JSONDecodeError:
                    tag_list = [tag.strip().strip('"') for tag in tags.strip('{}').split(',') if tag.strip()]
            elif tags.startswith('{') and tags.endswith('}'):
                tag_list = [tag.strip().strip('"') for tag in tags[1:-1].split(',') if tag.strip()]
            else:
                tag_list = []
        else:
            tag_list = tags if tags else []
        
        # Assurez-vous que is_exclusive est un booléen
        is_exclusive = bool(is_exclusive) if is_exclusive is not None else False
        
        files_data.append({
            'nom': nom,
            'lien': lien,
            'description': description if description else "No description",
            'tags': tag_list,
            'is_exclusive': is_exclusive, 
            'date_ajout': date_ajout,
            'date_event': date_event.strftime("%d-%m-%Y") if date_event else None
        })
    
    total_pages = (total_files + per_page - 1) // per_page if per_page else 1
    
    return render_template("page_canto.html", 
                         files=files_data,
                         current_page=page,
                         total_pages=total_pages,
                         total_files=total_files,
                         show_all=show_all)

# ===== ROUTE JSON =====
@app.route('/json')
def get_documents_json():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT nom_fichier, lien_telechargement, description, tags, date_event FROM documents;")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    result = [
        {
            "nom": nom, 
            "url": lien, 
            "description": description, 
            "tags": tags,
            "date_event": date_event.strftime("%m-%d-%Y") if date_event else None
        }
        for nom, lien, description, tags, date_event in rows
    ]
    return jsonify(result)

@app.route("/download")
def download_file():
    url = request.args.get("url")
    filename = request.args.get("filename", "file")

    response = requests.get(url)
    file_stream = BytesIO(response.content)

    return send_file(file_stream, as_attachment=True, download_name=filename)

@app.route("/upload")
def upload_page():
    token = request.args.get("token")
    if token != UPLOAD_SECRET:
        return render_template("403.html"), 403
    return render_template("upload.html")

# ===== ROUTE UPLOAD (POST) =====
@app.route("/upload", methods=['POST'])
def upload_file():
    files = request.files.getlist("files")
    descriptions = request.form.getlist("descriptions")
    tags_list = request.form.getlist("tags")
    date_events = request.form.getlist("date_events")
    
    uploaded_urls = []
    current_date = datetime.now().date()
    forbidden_extensions = {".heic", ".thm"}

    for i, file in enumerate(files):
        filename = file.filename
        ext = os.path.splitext(filename)[1].lower()

        if ext in forbidden_extensions:
            return jsonify({"status": "error", "message": f"The extension '{ext}' should be avoided, please convert it to another suitable format."}), 400

        # Récupérer les métadonnées pour ce fichier
        description = descriptions[i] if i < len(descriptions) else ""
        try:
            tags = json.loads(tags_list[i]) if i < len(tags_list) else []
        except:
            tags = []
        
        # Traitement de la date d'événement
        date_event_str = date_events[i] if i < len(date_events) else None
        try:
            if date_event_str:
                day, month, year = map(int, date_event_str.split('-'))
                date_event = datetime(year, month, day).date()
            else:
                date_event = None
        except Exception as e:
            print(f"Error parsing date {date_event_str}: {str(e)}")
            date_event = None

        blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=filename)
        # Upload dans Azure
        blob_client.upload_blob(file.stream, overwrite=True)
        # Récupérer l'URL publique
        blob_url = blob_client.url
        # Enregistrer dans PostgreSQL avec les dates
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO documents (nom_fichier, lien_telechargement, description, tags, date_ajout, date_event) VALUES (%s, %s, %s, %s, %s, %s);",
            (filename, blob_url, description, tags, current_date, date_event))
        conn.commit()
        cur.close()
        conn.close()

        uploaded_urls.append(blob_url)

    return jsonify({"status": "success", "urls": uploaded_urls}), 200

# ===== ROUTE POUR LES DÉTAILS D'UN FICHIER =====
@app.route("/file_details")
def get_file_details():
    filename = request.args.get("filename")
    print("📥 FILENAME reçu :", repr(filename))

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT description, tags, date_ajout, is_exclusive, date_event FROM documents WHERE nom_fichier = %s;", (filename,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    
    if result:
        description, tags, date_ajout, is_exclusive, date_event = result

        # Parser les tags
        if isinstance(tags, str):
            if tags.startswith('["') or tags.startswith("['"):
                try:
                    tags = json.loads(tags)
                except json.JSONDecodeError:
                    tags = [tag.strip().strip('"') for tag in tags.strip('{}').split(',') if tag.strip()]
            elif tags.startswith('{') and tags.endswith('}'):
                tags = [tag.strip().strip('"') for tag in tags[1:-1].split(',') if tag.strip()]
            else:
                tags = []
        elif not tags:
            tags = []

        return jsonify({
            "description": description if description else "No description",
            "tags": tags,
            "date_ajout": date_ajout.strftime("%d-%m-%Y") if date_ajout else "",
            "is_exclusive": is_exclusive if is_exclusive is not None else False,
            "date_event": date_event.strftime("%d-%m-%Y") if date_event else ""
        })
    else:
        print("⛔ Aucun fichier trouvé pour :", repr(filename))
        return jsonify({"error": "File not found"}), 404
    
#===== ROUTE POUR LA SUPPRESSION =====
@app.route("/delete")
def delete_page():
    token = request.args.get("token")
    if token != UPLOAD_SECRET:
        return render_template("403.html"), 403
    return render_template("delete.html")

@app.route("/delete_file", methods=['POST'])
def delete_file():
    filename = request.form.get("filename")
    confirmation = request.form.get("confirmation") == "on"
    
    if not confirmation:
        return jsonify({"status": "error", "message": "Confirmation required"}), 400

    # Suppression du blob Azure
    blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=filename)
    try:
        blob_client.delete_blob()
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to delete from Azure: {str(e)}"}), 500

    # Suppression de la base de données
    conn = psycopg2.connect(**DB_CONFIG)
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
def search_file():
    filename = request.args.get("filename")
    tags = request.args.getlist("tag")
    exclusive = request.args.get("exclusive") == "true"

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

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY nom_fichier;"

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute(query, params)
    results = cur.fetchall()
    cur.close()
    conn.close()

    files = []
    for nom, url, description, tags, is_exclusive, date_ajout, date_event in results:
        # Formatage des tags
        if isinstance(tags, str):
            if tags.startswith('["') or tags.startswith("['"):
                try:
                    tag_list = json.loads(tags)
                except json.JSONDecodeError:
                    tag_list = [tag.strip().strip('"') for tag in tags.strip('{}').split(',') if tag.strip()]
            elif tags.startswith('{') and tags.endswith('}'):
                tag_list = [tag.strip().strip('"') for tag in tags[1:-1].split(',') if tag.strip()]
            else:
                tag_list = []
        else:
            tag_list = tags if tags else []

        files.append({
            "name": nom,
            "url": url,
            "description": description,
            "tags": tag_list,
            "is_exclusive": is_exclusive if is_exclusive is not None else False,
            "date_ajout": date_ajout.strftime("%d-%m-%Y") if date_ajout else None,
            "date_event": date_event.strftime("%d-%m-%Y") if date_event else None
        })

    return jsonify(files)

# ==== UPDATE EXCLUSIVE =====
@app.route("/update_exclusive", methods=['POST'])
def update_exclusive():
    token = request.args.get("token")
    if token != UPLOAD_SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
        
    filename = request.form.get("filename")
    is_exclusive = request.form.get("is_exclusive") == 'true'
    
    conn = psycopg2.connect(**DB_CONFIG)
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

# ===== LANCEMENT LOCAL =====
if __name__ == '__main__':
    app.run(debug=True)