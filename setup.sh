#!/bin/bash
cd raffle_project
pip install -r requirements.txt
python manage.py migrate
python manage.py create_superuser_default
echo "Setup complete! Run: python manage.py runserver"
echo "Dashboard: http://127.0.0.1:8000/dashboard/"
echo "Login: admin / admin123"
