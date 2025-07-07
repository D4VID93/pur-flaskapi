from flask import Flask, jsonify, redirect, render_template_string
from flask_cors import CORS
import psycopg2
import urllib.parse

app = Flask(__name__)
CORS(app)

def transformer_lien_sharepoint(lien):
    if "AllItems.aspx" in lien and "id=" in lien:
        try:
            id_part = lien.split("id=")[1].split("&")[0]
            chemin_decode = urllib.parse.unquote(id_part)
            return "https://purprojet.sharepoint.com" + chemin_decode
        except Exception:
            return lien  # retourne le lien d'origine si erreur
    else:
        return lien  # déjà un lien direct

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
        lien_direct = transformer_lien_sharepoint(lien)
        html += f'''
        <div class="item">
            <img src="{lien_direct}" alt="{nom}" />
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
