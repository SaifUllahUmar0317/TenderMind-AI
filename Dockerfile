FROM python:3.11-slim

# Prevent Python from writing .pyc and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    HOST=0.0.0.0

# Install system dependencies for Tesseract OCR, PyMuPDF, OpenCV, and image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces runs as user with UID 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# Install Python dependencies first for layer caching
COPY --chown=user requirements.txt $HOME/app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy all application code
COPY --chown=user . $HOME/app/

# Expose Hugging Face default port
EXPOSE 7860

# Start TenderMind AI Flask server
CMD ["python", "app.py"]
