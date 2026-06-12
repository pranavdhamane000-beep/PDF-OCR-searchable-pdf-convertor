FROM ubuntu:22.04

# Prevent interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies including Tesseract with Marathi language pack
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    tesseract-ocr \
    tesseract-ocr-mar \
    tesseract-ocr-hin \
    tesseract-ocr-san \
    tesseract-ocr-tam \
    tesseract-ocr-tel \
    tesseract-ocr-kan \
    tesseract-ocr-mal \
    tesseract-ocr-guj \
    tesseract-ocr-pan \
    tesseract-ocr-ben \
    tesseract-ocr-ori \
    tesseract-ocr-urd \
    tesseract-ocr-eng \
    tesseract-ocr-spa \
    tesseract-ocr-fra \
    tesseract-ocr-deu \
    tesseract-ocr-ita \
    tesseract-ocr-por \
    tesseract-ocr-rus \
    ghostscript \
    poppler-utils \
    unpaper \
    pngquant \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .

# Create temporary directories
RUN mkdir -p /tmp/pdf_ocr_temp /tmp/pdf_ocr_downloads

# Expose port (Render will set PORT environment variable)
EXPOSE 8080

# Set environment variable for Tesseract data path
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

# Run the application
CMD ["python3", "app.py"]