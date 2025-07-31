# Utilise une image Python officielle légère
FROM python:3.10-slim

# Crée un dossier de travail dans le conteneur
WORKDIR /app

# Copie les fichiers locaux dans le conteneur
COPY . .

# Donne les droits d'exécution à startup.sh
RUN chmod +x startup.sh

# Installe les dépendances listées dans requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Définit la commande de lancement avec Gunicorn via startup.sh
CMD ["./startup.sh"]
