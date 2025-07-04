# Dockerfile

# Utilise une image Python officielle
FROM python:3.10-slim

# Crée un dossier dans le conteneur
WORKDIR /app

# Copie le code dans l'image
COPY . .

# Installe les dépendances
RUN pip install flask psycopg2-binary

# Définit la commande de lancement
CMD ["python", "api.py"]
