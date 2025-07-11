from flask import Flask, jsonify, render_template_string
from flask_cors import CORS
import psycopg2

app = Flask(__name__)
CORS(app)

# ===== CONFIGURATION DB =====
DB_CONFIG = {
    'host': 'testcantodb.postgres.database.azure.com',
    'database': 'postgres',
    'user': 'admin_db',
    'password': 'Da2025$2025@',
    'port': '5432'
}

# ===== ROUTE PRINCIPALE : PAGE HTML =====
@app.route('/')
def index():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT nom_fichier, lien_telechargement FROM documents;")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    html = """
    <html>
    <head>
        <title>Galerie d'images</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                padding: 30px;
                background-color: #f8f9fa;
            }
            h2 {
                text-align: center;
                margin-bottom: 30px;
            }
            .gallery {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                gap: 20px;
            }
            .item {
                text-align: center;
                transition: transform 0.2s;
            }
            .item:hover {
                transform: scale(1.05);
            }
            .item img {
                width: 100%;
                height: auto;
                border-radius: 10px;
                box-shadow: 0 2px 6px rgba(0,0,0,0.2);
                cursor: pointer;
            }
        </style>
    </head>
    <body>
        <h2>Galerie des documents stockés</h2>
        <div class="gallery">
    """

    for nom, lien in rows:
        html += f'''
        <div class="item">
            <a href="{lien}" target="_blank">
                <img src="{lien}" alt="{nom}" title="{nom}" />
            </a>
        </div>
        '''

    html += """
        </div>
    </body>
    </html>
    """
    return render_template_string(html)

# ===== ROUTE JSON OPTIONNELLE =====
@app.route('/documents/json')
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

# ===== LANCEMENT LOCAL =====
if __name__ == '__main__':
    app.run(debug=True)
