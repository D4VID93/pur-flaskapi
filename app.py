from flask import Flask, jsonify, redirect
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

    data = [{"nom": r[0], "lien": r[1]} for r in rows]
    return jsonify(data)

if __name__ == '__main__':
    app.run(debug=True)
