from flask import Flask, jsonify, redirect, render_template_string
from flask_cors import CORS
import psycopg2

app = Flask(__name__)
CORS(app)  # <-- Ajout simple pour autoriser toutes les origines

@app.route('/')
def index():
    return redirect('/documents')
    
@app.route('/documents')
def get_documents():
    conn = psycopg2.connect(
        host='testcantodb.postgres.database.azure.com',
        database='postgres',
        user='admin_db',
        password='Da2025$2025@'
    )
    cur = conn.cursor()
    cur.execute("SELECT nom_fichier, lien_telechargement FROM documents;")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    # Génération du HTML
    html = """
    <html>
    <head>
        <title>Documents Images</title>
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; }
            .gallery { display: flex; flex-wrap: wrap; gap: 20px; }
            .item { width: 300px; text-align: center; }
            .item img { max-width: 100%; height: auto; border: 1px solid #ccc; border-radius: 4px; }
            .item p { margin-top: 8px; font-weight: bold; }
        </style>
    </head>
    <body>
        <h2>Images de la base de données</h2>
        <div class="gallery">
    """

    for nom, lien in rows:
        html += f'''
        <div class="item">
            <img src="{lien}" alt="{nom}" />
            <p>{nom}</p>
        </div>
        '''

    html += """
        </div>
    </body>
    </html>
    """

    return render_template_string(html)

if __name__ == '__main__':
    app.run(debug=True)
