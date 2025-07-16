from flask import Flask, jsonify, render_template, send_file, request
import psycopg2
import requests
from io import BytesIO


app = Flask(__name__)

# ===== CONFIGURATION DB =====
DB_CONFIG = {
    'host': 'testcantodb.postgres.database.azure.com',
    'database': 'postgres',
    'user': 'admin_db',
    'password': 'Da2025$2025@',
    'port': '5432'
}

# ===== ROUTE PRINCIPALE =====
@app.route('/')
def index():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT nom_fichier, lien_telechargement FROM documents;")
    images = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("page_canto.html", images=images)

# ===== ROUTE JSON =====
@app.route('/json')
def get_documents_json():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT nom_fichier, lien_telechargement FROM documents;")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    result = [
        {"nom": nom, "url": lien}
        for nom, lien in rows
    ]
    return jsonify(result)

@app.route("/download")
def download_file():
    url = request.args.get("url")
    filename = request.args.get("filename", "file")

    response = requests.get(url)
    file_stream = BytesIO(response.content)

    return send_file(file_stream, as_attachment=True, download_name=filename)

# ===== LANCEMENT LOCAL =====
if __name__ == '__main__':
    app.run(debug=True)
