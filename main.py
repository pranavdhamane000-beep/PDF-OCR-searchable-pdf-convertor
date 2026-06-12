services:
  - type: web
    name: pdf-ocr-bot
    runtime: python
    repo: https://github.com/YOUR_USERNAME/YOUR_REPO_NAME
    plan: free
    buildCommand: |
      apt-get update && apt-get install -y \
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
      poppler-utils \
      && pip install -r requirements.txt
    startCommand: python app.py
    envVars:
      - key: TELEGRAM_BOT_TOKEN
        sync: false
