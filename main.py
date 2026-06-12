#!/usr/bin/env python3
"""
Telegram Bot - Scanned PDF to Searchable PDF Converter
Python 3.14.3 | Strong Marathi Language Support
Single file deployment for Render

Deploy on Render:
1. Create new Background Worker
2. Build Command: pip install -r requirements.txt && apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-mar tesseract-ocr-hin poppler-utils
3. Start Command: python main.py
4. Environment Variable: BOT_TOKEN=your_telegram_bot_token
"""

import os
import sys
import logging
import tempfile
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional
import asyncio
from datetime import datetime

# Telegram imports
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
from telegram.constants import ParseMode

# OCR imports
import pytesseract
from pdf2image import convert_from_path
from PIL import Image, ImageEnhance, ImageFilter
import ocrmypdf
from PyPDF2 import PdfReader, PdfWriter

# ============================================================================
# CONFIGURATION
# ============================================================================

# Bot Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN environment variable not set!")
    print("Set it with: export BOT_TOKEN='your_token_here'")
    sys.exit(1)

# File limits
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
MAX_PAGES = 100
PROCESSING_TIMEOUT = 600  # 10 minutes

# Language configurations with Marathi focus
SUPPORTED_LANGUAGES = {
    'mar': {
        'name': 'मराठी (Marathi)',
        'flag': '🇮🇳',
        'tesseract_code': 'mar',
        'description': 'Pure Marathi documents'
    },
    'mar+eng': {
        'name': 'मराठी + English',
        'flag': '🇮🇳',
        'tesseract_code': 'mar+eng',
        'description': 'Marathi documents with English text'
    },
    'mar+hin+eng': {
        'name': 'मराठी + हिंदी + English',
        'flag': '🇮🇳',
        'tesseract_code': 'mar+hin+eng',
        'description': 'Multilingual documents'
    },
    'eng': {
        'name': 'English',
        'flag': '🇬🇧',
        'tesseract_code': 'eng',
        'description': 'English only documents'
    }
}

# Marathi specific OCR configuration
MARATHI_OCR_CONFIG = {
    'psm': 6,  # Assume uniform block of text
    'oem': 3,  # Default OCR Engine mode
    'config_params': [
        '-c', 'tessedit_char_whitelist=',
        '-c', 'preserve_interword_spaces=1',
        '-c', 'textord_min_linesize=2.5',
        '-c', 'textord_heavy_nr=1',
        '-c', 'language_model_penalty_non_dict_word=0.1',
        '-c', 'language_model_penalty_non_freq_dict_word=0.05',
    ]
}

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================================
# DATA STORAGE (In-Memory)
# ============================================================================

class UserSession:
    """Store user session data"""
    def __init__(self):
        self.user_data: Dict[int, dict] = {}
    
    def get_language(self, user_id: int) -> str:
        """Get user's preferred language"""
        return self.user_data.get(user_id, {}).get('language', 'mar+eng')
    
    def set_language(self, user_id: int, language: str):
        """Set user's preferred language"""
        if user_id not in self.user_data:
            self.user_data[user_id] = {}
        self.user_data[user_id]['language'] = language
    
    def get_stats(self, user_id: int) -> dict:
        """Get user statistics"""
        return self.user_data.get(user_id, {}).get('stats', {
            'total_conversions': 0,
            'total_pages': 0,
            'last_conversion': None
        })
    
    def update_stats(self, user_id: int, pages: int):
        """Update user statistics"""
        if user_id not in self.user_data:
            self.user_data[user_id] = {}
        if 'stats' not in self.user_data[user_id]:
            self.user_data[user_id]['stats'] = {
                'total_conversions': 0,
                'total_pages': 0,
                'last_conversion': None
            }
        
        stats = self.user_data[user_id]['stats']
        stats['total_conversions'] += 1
        stats['total_pages'] += pages
        stats['last_conversion'] = datetime.now().isoformat()

# Initialize session storage
user_sessions = UserSession()

# ============================================================================
# OCR ENGINE
# ============================================================================

class MarathiOCR:
    """Advanced OCR engine with Marathi language optimization"""
    
    def __init__(self, language: str = 'mar+eng'):
        self.language = language
        self.tesseract_lang = SUPPORTED_LANGUAGES.get(language, {}).get('tesseract_code', 'mar+eng')
        self.temp_dir = Path(tempfile.mkdtemp(prefix='marathi_ocr_'))
        
    def cleanup(self):
        """Remove temporary files"""
        try:
            if self.temp_dir.exists():
                shutil.rmtree(self.temp_dir)
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
    
    def preprocess_image(self, image: Image.Image) -> Image.Image:
        """
        Preprocess image for better Marathi OCR
        - Convert to grayscale
        - Enhance contrast
        - Remove noise
        - Sharpen text
        """
        # Convert to grayscale if not already
        if image.mode != 'L':
            image = image.convert('L')
        
        # Enhance contrast
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(2.0)
        
        # Enhance sharpness
        enhancer = ImageEnhance.Sharpness(image)
        image = enhancer.enhance(2.0)
        
        # Apply median filter to remove noise
        image = image.filter(ImageFilter.MedianFilter(size=3))
        
        # Binarize image (threshold)
        image = image.point(lambda x: 0 if x < 140 else 255, '1')
        
        return image
    
    async def convert_pdf(self, input_path: str, output_path: str, 
                         progress_callback=None) -> Dict:
        """
        Convert scanned PDF to searchable PDF
        
        Returns:
            dict with conversion results
        """
        result = {
            'success': False,
            'pages': 0,
            'method': None,
            'error': None,
            'time_taken': 0
        }
        
        start_time = datetime.now()
        
        try:
            # Count pages first
            with open(input_path, 'rb') as f:
                reader = PdfReader(f)
                total_pages = len(reader.pages)
                result['pages'] = total_pages
            
            if total_pages > MAX_PAGES:
                result['error'] = f'PDF has {total_pages} pages. Maximum allowed: {MAX_PAGES}'
                return result
            
            logger.info(f"Starting OCR: {total_pages} pages, Language: {self.language}")
            
            # Method 1: Try ocrmypdf first (best quality)
            try:
                logger.info("Attempting conversion with ocrmypdf...")
                await self._ocr_with_ocrmypdf(input_path, output_path)
                result['method'] = 'ocrmypdf'
                result['success'] = True
                logger.info("ocrmypdf conversion successful")
            except Exception as e:
                logger.warning(f"ocrmypdf failed: {e}. Trying fallback method...")
                
                # Method 2: Fallback to pytesseract
                await self._ocr_with_pytesseract(input_path, output_path, progress_callback)
                result['method'] = 'pytesseract'
                result['success'] = True
                logger.info("pytesseract conversion successful")
            
        except subprocess.TimeoutExpired:
            result['error'] = 'Processing timeout exceeded'
            logger.error(f"Timeout: {input_path}")
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"Conversion failed: {e}")
        finally:
            result['time_taken'] = (datetime.now() - start_time).total_seconds()
        
        return result
    
    async def _ocr_with_ocrmypdf(self, input_path: str, output_path: str):
        """Convert using ocrmypdf (primary method)"""
        cmd = [
            'ocrmypdf',
            '--language', self.tesseract_lang,
            '--output-type', 'pdf',
            '--optimize', '1',
            '--deskew',
            '--clean',
            '--remove-background',
            '--skip-text',
            '--pdfa-image-compression', 'jpeg',
            '--jobs', '2',  # Use 2 CPU cores
            input_path,
            output_path
        ]
        
        # Run with timeout
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), 
                timeout=PROCESSING_TIMEOUT
            )
            
            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise Exception(f"ocrmypdf failed (code {process.returncode}): {error_msg}")
        except asyncio.TimeoutError:
            process.kill()
            raise subprocess.TimeoutExpired(cmd, PROCESSING_TIMEOUT)
    
    async def _ocr_with_pytesseract(self, input_path: str, output_path: str, 
                                   progress_callback=None):
        """Fallback method using pytesseract with Marathi optimization"""
        
        # Convert PDF to images
        logger.info("Converting PDF to images...")
        images = convert_from_path(
            input_path,
            dpi=300,
            thread_count=2,
            grayscale=True,
            size=(2480, 3508)  # A4 at 300 DPI
        )
        
        total_pages = len(images)
        pdf_writer = PdfWriter()
        
        for i, image in enumerate(images):
            # Update progress
            if progress_callback:
                progress = (i + 1) / total_pages * 100
                await progress_callback(progress)
            
            logger.info(f"Processing page {i+1}/{total_pages}")
            
            # Preprocess image for better Marathi recognition
            processed_image = self.preprocess_image(image)
            
            # OCR with Marathi configuration
            ocr_config = ' '.join([
                f'--psm {MARATHI_OCR_CONFIG["psm"]}',
                f'--oem {MARATHI_OCR_CONFIG["oem"]}',
                *MARATHI_OCR_CONFIG['config_params']
            ])
            
            # Generate searchable PDF
            pdf_data = pytesseract.image_to_pdf_or_hocr(
                processed_image,
                lang=self.tesseract_lang,
                config=ocr_config,
                extension='pdf'
            )
            
            # Add to output PDF
            temp_pdf = self.temp_dir / f"page_{i:04d}.pdf"
            temp_pdf.write_bytes(pdf_data)
            
            temp_reader = PdfReader(str(temp_pdf))
            for page in temp_reader.pages:
                pdf_writer.add_page(page)
        
        # Write final PDF
        logger.info("Writing final PDF...")
        with open(output_path, 'wb') as output_file:
            pdf_writer.write(output_file)
        
        logger.info(f"Created searchable PDF with {total_pages} pages")

# ============================================================================
# TELEGRAM BOT HANDLERS
# ============================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    
    welcome_text = f"""🌟 *नमस्कार {user.first_name}!*

📄 *Scan2Search PDF Bot* - आपला स्वागत आहे!

मी तुमच्या स्कॅन केलेल्या PDF फाईल्स *सर्चेबल PDF* मध्ये बदलतो!

━━━━━━━━━━━━━━━━━━━

✨ *वैशिष्ट्ये (Features):*
• 🇮🇳 मराठी भाषेचा उत्तम सपोर्ट
• 📝 टेक्स्ट सर्च करण्यायोग्य
• 🎯 हाय क्वालिटी OCR प्रोसेसिंग
• 📊 ओरिजिनल फॉरमॅटिंग सेव्ह होते
• 🚀 फास्ट प्रोसेसिंग

━━━━━━━━━━━━━━━━━━━

📌 *कसे वापरावे:*
1️⃣ /language - भाषा निवडा
2️⃣ PDF फाईल पाठवा (Max 20MB)
3️⃣ प्रोसेसिंगची वाट पहा
4️⃣ सर्चेबल PDF डाउनलोड करा!

━━━━━━━━━━━━━━━━━━━

🔧 *कमांड्स:*
/start - मुख्य मेनू
/language - भाषा निवडा
/help - मदत
/stats - तुमची सांख्यिकी

📤 आता एक PDF पाठवा!"""

    keyboard = [
        [InlineKeyboardButton("🌐 भाषा निवडा | Select Language", callback_data="menu_language")],
        [InlineKeyboardButton("❓ मदत | Help", callback_data="menu_help"),
         InlineKeyboardButton("📊 सांख्यिकी | Stats", callback_data="menu_stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = """📚 *मदत केंद्र | Help Center*

━━━━━━━━━━━━━━━━━━━

📝 *PDF कशी पाठवायची:*
• Direct PDF file upload करा
• Maximum size: 20MB
• Clear scan असावा (300 DPI)

🌐 *भाषा सपोर्ट:*
• 🇮🇳 मराठी (Marathi) - देवनागरी
• 🇮🇳 हिंदी (Hindi)
• 🇬🇧 English
• Combined languages

⏱ *प्रोसेसिंग टाइम:*
• 1-10 pages: ~30-60 seconds
• 10-50 pages: ~1-3 minutes
• 50-100 pages: ~3-8 minutes

✨ *बेस्ट रिझल्ट साठी:*
1. Clear, high-contrast scans वापरा
2. 300 DPI minimum
3. Proper lighting मध्ये scan करा
4. Handwritten text टाळा

⚠ *मर्यादा:*
• Max 100 pages per PDF
• Complex layouts accuracy कमी होऊ शकते
• Handwriting recognition limited आहे

🆘 *सपोर्ट:* @YourSupportUsername"""

    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /language command"""
    user_id = update.effective_user.id
    current_lang = user_sessions.get_language(user_id)
    
    keyboard = []
    for lang_code, lang_info in SUPPORTED_LANGUAGES.items():
        # Mark currently selected language
        prefix = "✅ " if lang_code == current_lang else ""
        button_text = f"{prefix}{lang_info['flag']} {lang_info['name']}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"lang_{lang_code}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    lang_text = f"""🌐 *भाषा निवडा | Select Language*

सध्या निवडलेली: *{SUPPORTED_LANGUAGES[current_lang]['name']}*

तुमच्या PDF साठी योग्य भाषा निवडा:
• मराठी - शुद्ध मराठी डॉक्युमेंट्स
• मराठी + English - मिश्र भाषा
• मराठी + हिंदी + English - बहुभाषिक

💡 *टीप:* मराठी+English सर्वोत्तम पर्याय!"""

    await update.message.reply_text(
        lang_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command"""
    user_id = update.effective_user.id
    user = update.effective_user
    stats = user_sessions.get_stats(user_id)
    current_lang = user_sessions.get_language(user_id)
    
    stats_text = f"""📊 *{user.first_name} ची सांख्यिकी | Your Statistics*

━━━━━━━━━━━━━━━━━━━

📄 *Total Conversions:* {stats['total_conversions']}
📑 *Total Pages Processed:* {stats['total_pages']}
🌐 *Current Language:* {SUPPORTED_LANGUAGES[current_lang]['name']}

━━━━━━━━━━━━━━━━━━━

⏰ *Last Conversion:* {stats['last_conversion'] if stats['last_conversion'] else 'No conversions yet'}"""

    keyboard = [
        [InlineKeyboardButton("🌐 Change Language", callback_data="menu_language")],
        [InlineKeyboardButton("📤 Convert New PDF", callback_data="menu_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = update.effective_user.id
    
    if data.startswith("lang_"):
        # Language selection
        lang_code = data.replace("lang_", "")
        user_sessions.set_language(user_id, lang_code)
        lang_info = SUPPORTED_LANGUAGES[lang_code]
        
        await query.edit_message_text(
            f"✅ भाषा बदलली: *{lang_info['name']}*\n\n"
            f"📤 आता तुमची PDF पाठवा!\n"
            f"Send your PDF now!",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "menu_language":
        await language_command(update, context)
    
    elif data == "menu_help":
        await help_command(update, context)
    
    elif data == "menu_stats":
        await stats_command(update, context)
    
    elif data == "menu_start":
        await start_command(update, context)

async def pdf_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle PDF file uploads"""
    user_id = update.effective_user.id
    user = update.effective_user
    message = update.message
    
    # Get file
    if message.document:
        file = message.document
        file_name = file.file_name or "document.pdf"
    else:
        await message.reply_text("❌ कृपया PDF फाईल पाठवा | Please send a PDF file")
        return
    
    # Validate file type
    if not file_name.lower().endswith('.pdf') and file.mime_type != 'application/pdf':
        await message.reply_text("❌ फक्त PDF फाईल्स स्वीकारल्या जातात | Only PDF files accepted")
        return
    
    # Validate file size
    if file.file_size > MAX_FILE_SIZE:
        size_mb = MAX_FILE_SIZE / (1024 * 1024)
        await message.reply_text(
            f"❌ फाईल खूप मोठी आहे! | File too large!\n"
            f"Maximum: {size_mb:.0f}MB"
        )
        return
    
    # Get language preference
    language = user_sessions.get_language(user_id)
    lang_info = SUPPORTED_LANGUAGES[language]
    
    # Send initial processing message
    status_message = await message.reply_text(
        f"⏳ *प्रोसेसिंग सुरू... | Processing...*\n\n"
        f"📄 *{file_name}*\n"
        f"🌐 Language: {lang_info['name']}\n"
        f"🔍 Analyzing PDF...",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Initialize OCR engine
    ocr_engine = None
    temp_input = None
    temp_output = None
    
    try:
        # Download file
        file_obj = await context.bot.get_file(file.file_id)
        temp_input = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        await file_obj.download_to_drive(temp_input.name)
        temp_input.close()
        
        # Update status
        await status_message.edit_text(
            f"⏳ *प्रोसेसिंग सुरू... | Processing...*\n\n"
            f"📄 *{file_name}*\n"
            f"🌐 Language: {lang_info['name']}\n"
            f"✅ PDF downloaded\n"
            f"🔄 Starting OCR with Marathi support...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Create OCR engine
        ocr_engine = MarathiOCR(language)
        
        # Define progress callback
        async def progress_callback(progress):
            """Update progress bar"""
            try:
                bar_length = 10
                filled = int(bar_length * progress / 100)
                bar = '█' * filled + '░' * (bar_length - filled)
                
                await status_message.edit_text(
                    f"⏳ *प्रोसेसिंग सुरू... | Processing...*\n\n"
                    f"📄 *{file_name}*\n"
                    f"🌐 Language: {lang_info['name']}\n"
                    f"🔄 OCR Progress: [{bar}] {progress:.0f}%\n"
                    f"📝 Marathi text recognition active...",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass  # Ignore update errors
        
        # Convert PDF
        temp_output = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        temp_output.close()
        
        result = await ocr_engine.convert_pdf(
            temp_input.name,
            temp_output.name,
            progress_callback
        )
        
        if result['success']:
            # Update stats
            user_sessions.update_stats(user_id, result['pages'])
            
            # Prepare success message
            time_taken = result['time_taken']
            method = result['method']
            
            success_caption = (
                f"✅ *तुमची सर्चेबल PDF तयार आहे!*\n"
                f"✅ *Your Searchable PDF is Ready!*\n\n"
                f"━━━━━━━━━━━━━━━━━━━\n\n"
                f"📄 *Original:* {file_name}\n"
                f"📑 *Pages:* {result['pages']}\n"
                f"🌐 *Language:* {lang_info['name']}\n"
                f"⚡ *Method:* {method.upper()}\n"
                f"⏱ *Time:* {time_taken:.1f} seconds\n\n"
                f"━━━━━━━━━━━━━━━━━━━\n\n"
                f"✨ *Features:*\n"
                f"• Text is searchable (Ctrl+F)\n"
                f"• मजकूर शोधता येईल\n"
                f"• Copy-paste supported\n"
                f"• Original formatting preserved\n\n"
                f"💡 *Tip:* Open in Adobe Reader for best results!"
            )
            
            # Delete status message
            await status_message.delete()
            
            # Send the converted PDF
            output_file_name = f"Searchable_{file_name}"
            with open(temp_output.name, 'rb') as pdf_file:
                await message.reply_document(
                    document=pdf_file,
                    filename=output_file_name,
                    caption=success_caption,
                    parse_mode=ParseMode.MARKDOWN
                )
            
            logger.info(f"Successfully converted: {file_name} ({result['pages']} pages)")
            
        else:
            # Conversion failed
            error_msg = result.get('error', 'Unknown error')
            await status_message.edit_text(
                f"❌ *Conversion Failed | रूपांतरण अयशस्वी*\n\n"
                f"Error: {error_msg}\n\n"
                f"📝 *Possible solutions:*\n"
                f"• Check if PDF is corrupted\n"
                f"• Try with better quality scan\n"
                f"• Ensure PDF has clear text\n\n"
                f"🔄 Try again with /start",
                parse_mode=ParseMode.MARKDOWN
            )
            logger.error(f"Conversion failed: {file_name} - {error_msg}")
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        await status_message.edit_text(
            "❌ *Unexpected Error | अनपेक्षित त्रुटी*\n\n"
            f"Error: {str(e)}\n\n"
            "Please try again or contact support.",
            parse_mode=ParseMode.MARKDOWN
        )
    
    finally:
        # Cleanup
        if ocr_engine:
            ocr_engine.cleanup()
        if temp_input and os.path.exists(temp_input.name):
            os.unlink(temp_input.name)
        if temp_output and os.path.exists(temp_output.name):
            os.unlink(temp_output.name)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")
    
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ *Error Occurred | त्रुटी आली*\n\n"
                "कृपया पुन्हा प्रयत्न करा | Please try again\n"
                "/start - Restart bot",
                parse_mode=ParseMode.MARKDOWN
            )
    except:
        pass

# ============================================================================
# MAIN APPLICATION
# ============================================================================

def create_bot_application() -> Application:
    """Create and configure the Telegram bot application"""
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("language", language_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    # Add callback query handler
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Add PDF file handler
    application.add_handler(MessageHandler(filters.Document.PDF, pdf_handler))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    return application

def check_dependencies():
    """Check if all required dependencies are installed"""
    errors = []
    
    # Check Tesseract
    try:
        version = pytesseract.get_tesseract_version()
        logger.info(f"Tesseract version: {version}")
    except:
        errors.append("Tesseract OCR not installed")
    
    # Check languages
    try:
        langs = pytesseract.get_languages()
        logger.info(f"Available languages: {langs}")
        if 'mar' not in langs:
            errors.append("Marathi language pack not installed (tesseract-ocr-mar)")
        if 'eng' not in langs:
            errors.append("English language pack not installed")
    except:
        errors.append("Cannot check Tesseract languages")
    
    # Check poppler
    try:
        result = subprocess.run(['pdftoppm', '-v'], capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("Poppler is installed")
        else:
            errors.append("Poppler not properly installed")
    except FileNotFoundError:
        errors.append("Poppler not installed (poppler-utils)")
    
    return errors

def main():
    """Main entry point"""
    print("=" * 60)
    print("📄 Scan2Search PDF Bot - Marathi Edition")
    print("=" * 60)
    print(f"Python Version: {sys.version}")
    print(f"Bot Token: {'✅ Set' if BOT_TOKEN else '❌ Missing'}")
    print("=" * 60)
    
    # Check dependencies
    print("\n🔍 Checking dependencies...")
    errors = check_dependencies()
    
    if errors:
        print("\n❌ Dependency Errors:")
        for error in errors:
            print(f"  • {error}")
        print("\n📝 Install missing dependencies:")
        print("  sudo apt-get install tesseract-ocr tesseract-ocr-mar tesseract-ocr-hin poppler-utils")
        print("  pip install -r requirements.txt")
        
        # On Render, continue anyway as dependencies should be installed
        if os.environ.get('RENDER'):
            print("\n⚠️ Running on Render, continuing anyway...")
        else:
            print("\n❌ Fix dependencies and restart")
            sys.exit(1)
    else:
        print("✅ All dependencies satisfied!")
    
    # Create application
    print("\n🚀 Starting bot...")
    application = create_bot_application()
    
    # Start bot
    print("✅ Bot is running!")
    print("\n📝 Available commands:")
    print("  /start - Start bot")
    print("  /language - Select OCR language")
    print("  /help - Help menu")
    print("  /stats - Your statistics")
    print("\n📤 Send a PDF to convert!")
    print("=" * 60)
    
    # Run the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

# ============================================================================
# DEPLOYMENT CONFIGURATION (for Render)
# ============================================================================

"""
RENDER DEPLOYMENT INSTRUCTIONS:
================================

1. Create these files in your repo:

   requirements.txt:
   ---------------
   python-telegram-bot==21.3
   pdf2image==1.17.0
   pytesseract==0.3.10
   Pillow==10.3.0
   PyPDF2==3.0.1
   ocrmypdf==16.2.0

   runtime.txt:
   -----------
   python-3.14.3

   Procfile:
   ---------
   worker: python main.py

2. On Render Dashboard:
   - New > Background Worker
   - Connect repository
   - Build Command:
     pip install -r requirements.txt && apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-mar tesseract-ocr-hin poppler-utils
   - Start Command: python main.py
   - Add Environment Variable: BOT_TOKEN=your_telegram_bot_token
   - Deploy!

3. Get Bot Token from @BotFather on Telegram
"""

if __name__ == '__main__':
    main()
