FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY wsgi.py .

RUN useradd --create-home beyassa && chown -R beyassa /app
USER beyassa

EXPOSE 8000
# --preload : l'application (et la création des tables) est initialisée une seule fois.
# Pas de journal d'accès Gunicorn : il écrirait le jeton du QR code (/acces/<jeton>).
# Le relais nginx journalise les requêtes, sauf /acces/.
CMD ["gunicorn", "--preload", "-w", "2", "-b", "0.0.0.0:8000", "wsgi:app"]
