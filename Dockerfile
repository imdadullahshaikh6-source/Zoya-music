FROM python:3.10-slim

# Install system dependencies (ffmpeg is crucial for music bots)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose port (Railway uses PORT env var, default 8080)
EXPOSE 8080

# Command to run the bot
CMD ["python", "main.py"]
