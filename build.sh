#!/usr/bin/env bash
# Script de build usado pelo Render (Render Web Service).
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate

# Bootstrap opcional de superusuário via variáveis de ambiente. Só roda algo
# se DJANGO_SUPERUSER_USERNAME/PASSWORD estiverem definidas, e é seguro rodar
# em todo deploy (não recria se o usuário já existir). Útil em planos do
# Render sem acesso a shell/jobs (ex: free tier).
python manage.py shell -c "
import os
from django.contrib.auth import get_user_model

User = get_user_model()
username = os.environ.get('DJANGO_SUPERUSER_USERNAME')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
email = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')

if username and password and not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username=username, email=email, password=password)
    print(f'Superusuario \"{username}\" criado.')
"
