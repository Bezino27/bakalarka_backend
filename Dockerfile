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

# Spustíme ASGI aplikáciu, aby fungovali aj Django Channels WebSockety.
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "dochadzka_backend.asgi:application"]
