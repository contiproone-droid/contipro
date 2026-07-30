#!/usr/bin/env bash
# Script de build usado pelo Render (Render Web Service).
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate
