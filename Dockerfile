FROM python:3.11-slim

# Instala dependencias del sistema, incluyendo ffmpeg
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

# Instala dependencias de Python
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia el código del bot
COPY . .

CMD ["python", "bot.py"]
