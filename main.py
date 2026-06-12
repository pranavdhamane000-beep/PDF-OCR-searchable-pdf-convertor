import os
import logging
import asyncio
import threading
from pathlib import Path
from datetime import datetime
import uuid
import ocrmypdf
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction
from flask import Flask, request, jsonify
import asyncio

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Create necessary directories
TEMP_DIR = Path("/tmp/pdf_ocr_temp")  # Use /tmp on Render
DOWNLOADS_DIR = Path("/tmp/pdf_ocr_downloads")
TEMP_DIR.mkdir(exist_ok=True)
DOWNLOADS_DIR.mkdir(exist_ok=True)

# Bot token from environment variable
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("No TELEGRAM_BOT_TOKEN found in environment variables")

# Supported languages including Marathi (मराठी)
SUPPORTED_LANGUAGES = {
    'eng': 'English',
    'spa': 'Spanish', 
    'fra': 'French',
    'deu': 'German',
    'ita': 'Italian',
    'por': 'Portuguese',
    'rus': 'Russian',
    'chi_sim': 'Chinese (Simplified)',
    'jpn': 'Japanese',
    'ara': 'Arabic',
    'hin': 'Hindi',
    'mar': 'Marathi (मराठी)',  # Marathi language support
    'san': 'Sanskrit',
    'tel': 'Telugu',
    'tam': 'Tamil',
    'kan': 'Kannada',
    'mal': 'Malayalam',
    'guj': 'Gujarati',
    'pan': 'Punjabi',
    'ben': 'Bengali',
    'ori': 'Odia',
    'urd': 'Urdu'
}

# Flask app for Render health checks
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    return jsonify({"status": "Bot is running", "languages": list(SUPPORTED_LANGUAGES.keys())}), 200

@flask_app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

# Telegram Bot Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message when the /start command is issued."""
    welcome_message = (
        "🔍 *Welcome to PDF OCR Bot!*\n\n"
        "I can convert your scanned PDFs into *searchable PDF files*.\n\n"
        "📌 *Supported Languages:*\n"
        f"• Marathi (मराठी) ✓ Fully supported\n"
        f"• Hindi, Sanskrit, Tamil, Telugu, Kannada, Malayalam, Gujarati, Punjabi, Bengali, Odia\n"
        f"• English, Spanish, French, German, Italian, Portuguese, Russian, Chinese, Japanese, Arabic\n\n"
        "📌 *How to use:*\n"
        "1. Send me any scanned PDF document\n"
        "2. I'll perform OCR on every page\n"
        "3. I'll send back a searchable PDF\n\n"
        "⚙️ *Available commands:*\n"
        "/start - Show this message\n"
        "/help - Get detailed help\n"
        "/lang - Set OCR language (default: English)\n"
        "/lang_marathi - Set OCR language to Marathi\n"
        "/status - Check bot status\n\n"
        "🚀 *Try it now!* Just send me a PDF file."
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send detailed help message."""
    help_text = (
        "📚 *Detailed Help*\n\n"
        "*What this bot does:*\n"
        "• Converts scanned/image-based PDFs to searchable PDFs\n"
        "• Uses Tesseract OCR with Marathi language support\n"
        "• Preserves original image quality while adding text layer\n\n"
        "*How to use:*\n"
        "1️⃣ Send a PDF file (any size up to 50MB)\n"
        "2️⃣ Wait for processing (depends on file size & pages)\n"
        "3️⃣ Download your searchable PDF\n\n"
        "*Tips for best results:*\n"
        "• Use high-quality scans (200-300 DPI)\n"
        "• Ensure text is straight (not crooked)\n"
        "• Set the correct language with /lang\n"
        "• For multi-language documents, use both codes\n\n"
        "*Examples:*\n"
        "/lang eng - Set to English\n"
        "/lang mar - Set to Marathi\n"
        "/lang eng+mar - Set to English + Marathi\n\n"
        "*Indian Languages Supported:*\n"
        "🇮🇳 Marathi (मराठी), Hindi (हिन्दी), Sanskrit (संस्कृत)\n"
        "🇮🇳 Tamil (தமிழ்), Telugu (తెలుగు), Kannada (ಕನ್ನಡ)\n"
        "🇮🇳 Malayalam (മലയാളം), Gujarati (ગુજરાતી), Punjabi (ਪੰਜਾਬੀ)\n"
        "🇮🇳 Bengali (বাংলা), Odia (ଓଡ଼ିଆ), Urdu (اردو)"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set OCR language."""
    if not context.args:
        available = "\n".join([f"• `{code}`: {name}" for code, name in SUPPORTED_LANGUAGES.items()])
        await update.message.reply_text(
            f"🌐 *Available languages:*\n{available}\n\n"
            f"*Usage:* `/lang eng` (for English) or `/lang mar` (for Marathi)\n\n"
            f"*Current language:* `{context.user_data.get('ocr_language', 'eng')}`\n\n"
            f"*Quick set:* `/lang_marathi` to set Marathi language",
            parse_mode='Markdown'
        )
        return
    
    language_code = context.args[0].lower()
    
    # Validate language(s)
    if '+' in language_code:
        codes = language_code.split('+')
        valid = all(code in SUPPORTED_LANGUAGES for code in codes)
        if valid:
            context.user_data['ocr_language'] = language_code
            await update.message.reply_text(f"✅ Language set to: {', '.join(SUPPORTED_LANGUAGES[code] for code in codes)}")
        else:
            await update.message.reply_text(f"❌ Invalid language code. Use /lang to see available options.")
    elif language_code in SUPPORTED_LANGUAGES:
        context.user_data['ocr_language'] = language_code
        await update.message.reply_text(f"✅ Language set to: {SUPPORTED_LANGUAGES[language_code]}")
    else:
        await update.message.reply_text(f"❌ Unsupported language. Use /lang to see available options.")

async def set_language_marathi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick command to set Marathi language."""
    context.user_data['ocr_language'] = 'mar'
    await update.message.reply_text(
        "✅ *Language set to Marathi (मराठी)*\n\n"
        "Now send me a PDF with Marathi text, and I'll make it searchable!",
        parse_mode='Markdown'
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check bot status."""
    status_text = (
        "🤖 *Bot Status*\n\n"
        f"• Status: 🟢 Online\n"
        f"• Default language: {context.user_data.get('ocr_language', 'eng')}\n"
        f"• Supported languages: {len(SUPPORTED_LANGUAGES)}\n"
        f"• Marathi support: ✅ Enabled\n"
        f"• Max file size: 50 MB\n"
        f"• OCR Engine: Tesseract 5+\n"
        f"• Backend: ocrmypdf\n\n"
        "Ready to process your PDFs in multiple languages!"
    )
    await update.message.reply_text(status_text, parse_mode='Markdown')

async def process_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process the received PDF file."""
    
    # Check if message contains a document
    if not update.message.document:
        await update.message.reply_text("📄 Please send a PDF file.")
        return
    
    document = update.message.document
    
    # Check if it's a PDF
    if not document.file_name.lower().endswith('.pdf'):
        await update.message.reply_text("❌ Please send a PDF file. Other formats are not supported.")
        return
    
    # Check file size (Telegram limit is 50MB)
    if document.file_size > 50 * 1024 * 1024:
        await update.message.reply_text("❌ File too large! Maximum size is 50MB.")
        return
    
    # Inform user that processing has started
    status_message = await update.message.reply_text(
        "📥 *PDF received!*\n\n"
        "⚙️ Processing your document...\n"
        "• Extracting pages\n"
        "• Running OCR (optical character recognition)\n"
        "• Creating searchable PDF\n\n"
        "_This may take a few moments depending on file size..._",
        parse_mode='Markdown'
    )
    
    # Send typing action
    await update.message.chat.send_action(action=ChatAction.TYPING)
    
    # Generate unique filenames
    unique_id = str(uuid.uuid4())[:8]
    input_path = DOWNLOADS_DIR / f"input_{unique_id}_{document.file_name}"
    output_path = TEMP_DIR / f"output_{unique_id}_{document.file_name}"
    
    try:
        # Download the file
        file = await document.get_file()
        await file.download_to_drive(input_path)
        
        # Get OCR language
        ocr_lang = context.user_data.get('ocr_language', 'eng')
        
        # Perform OCR
        await update.message.chat.send_action(action=ChatAction.TYPING)
        
        # OCR options for better quality
        # Note: For Render deployment, Tesseract needs to be installed with Marathi language pack
        ocr_options = {
            'language': ocr_lang,
            'output_type': 'pdf',
            'force_ocr': True,      # Force OCR even if text exists
            'deskew': True,          # Straighten crooked pages
            'clean': True,           # Clean scan artifacts
            'optimize': 1,           # Mild optimization
            'verbose': False,
            'jobs': 2                # Use 2 CPU cores (Render free tier limitation)
        }
        
        # Run ocrmypdf
        ocrmypdf.ocr(input_path, output_path, **ocr_options)
        
        # Check if output file was created
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise Exception("OCR processing failed")
        
        # Send the processed file back
        await update.message.chat.send_action(action=ChatAction.UPLOAD_DOCUMENT)
        
        with open(output_path, 'rb') as processed_file:
            await update.message.reply_document(
                document=processed_file,
                filename=f"searchable_{document.file_name}",
                caption=f"✅ *Success!*\n\n"
                       f"• Original file: {document.file_name}\n"
                       f"• Pages processed: All pages\n"
                       f"• OCR language: {ocr_lang}\n"
                       f"• File is now *searchable* and text-selectable\n\n"
                       f"✨ Try searching for text in this PDF!",
                parse_mode='Markdown'
            )
        
        # Delete status message
        await status_message.delete()
        
    except ocrmypdf.exceptions.PriorOcrFoundError:
        await update.message.reply_text(
            "⚠️ *Note:* This PDF already contains text.\n\n"
            "The file appears to already be searchable. If you still want to re-OCR it, please try a different file.",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error processing PDF: {str(e)}")
        await update.message.reply_text(
            f"❌ *Error processing your PDF*\n\n"
            f"Error: {str(e)[:200]}\n\n"
            f"Possible issues:\n"
            f"• File might be corrupted\n"
            f"• PDF might be password protected\n"
            f"• Image quality might be too low\n"
            f"• Marathi language pack may not be installed\n\n"
            f"Please try with a different PDF or contact support.",
            parse_mode='Markdown'
        )
    
    finally:
        # Clean up temporary files
        try:
            if input_path.exists():
                input_path.unlink()
            if output_path.exists():
                output_path.unlink()
        except Exception as cleanup_error:
            logger.error(f"Cleanup error: {cleanup_error}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors."""
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ *An unexpected error occurred*\n\n"
            "Please try again later or contact the bot administrator.",
            parse_mode='Markdown'
        )

def run_bot():
    """Run the Telegram bot in a separate thread."""
    # Create event loop for the bot thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("lang", set_language))
    application.add_handler(CommandHandler("lang_marathi", set_language_marathi))
    application.add_handler(CommandHandler("status", status_command))
    
    # Add message handler for PDF documents
    application.add_handler(MessageHandler(
        filters.Document.PDF, 
        process_pdf
    ))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot with polling
    print("🤖 Telegram bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

def main():
    """Main function to run both Flask and Telegram bot."""
    # Start Telegram bot in a background thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Get port from environment variable (Render sets this)
    port = int(os.environ.get("PORT", 5000))
    
    # Run Flask web server (required for Render)
    print(f"🌐 Flask web server starting on port {port}...")
    flask_app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    main()