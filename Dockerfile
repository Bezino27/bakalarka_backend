# Použijeme oficiálny Python image
FROM python:3.12

# Nastavíme pracovný adresár
WORKDIR /app

# Skopírujeme súbory
COPY requirements.txt .

# Nainštalujeme závislosti
RUN pip install --no-cache-dir -r requirements.txt

# Skopírujeme celý projekt
COPY . .

# Exponujeme port 8000
EXPOSE 8000

# Spustíme aplikáciu
CMD ["gunicorn", "dochadzka_backend.wsgi:application", "--config", "gunicorn.conf.py"]
