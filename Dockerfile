# Utilise une image Python officielle
FROM python:3.10-slim

# Crée un répertoire pour l'application
WORKDIR /app

# Copie les fichiers dans le conteneur
COPY . .

# Installe les dépendances
RUN pip install --no-cache-dir -r requirements.txt

# Expose le port utilisé par Flask
EXPOSE 5000

# Démarre l’application
CMD ["python", "api.py"]
