import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import logging
import json
from datetime import datetime
import os
import threading
import re

# Try to import telegram with fallback
try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
    TELEGRAM_AVAILABLE = True
except ImportError as e:
    print(f"Telegram import warning: {e}")
    TELEGRAM_AVAILABLE = False

# Configuration
def get_config():
    return {
        'telegram_bot_token': os.getenv('TELEGRAM_BOT_TOKEN', '8413664821:AAHjBwysQWk3GFdJV3Bvk3Jp1vhDLpoymI8'),
        'telegram_chat_id': os.getenv('TELEGRAM_CHAT_ID', '1366899854'),
        'api_url': 'https://www.sheinindia.in/c/sverse-5939-37961',
        'check_interval_minutes': 5,
        'min_stock_threshold': 10,
        'database_path': '/tmp/shein_monitor.db',
        'min_increase_threshold': 50
    }

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class SheinStockMonitorBot:
    def __init__(self, config):
        self.config = config
        self.application = None
        self.monitoring = False
        self.monitor_thread = None
        self.setup_database()
        print("🤖 Bot initialized - waiting for commands")
    
    def setup_database(self):
        """Initialize SQLite database"""
        self.conn = sqlite3.connect(self.config['database_path'], check_same_thread=False)
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_stock INTEGER,
                stock_change INTEGER DEFAULT 0,
                notified BOOLEAN DEFAULT FALSE
            )
        ''')
        self.conn.commit()
        print("✅ Database setup completed")
    
    def get_shein_stock_count(self):
        """
        Get total stock count from Shein
        """
        try:
            headers = {
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'accept-language': 'en-US,en;q=0.9',
                'cache-control': 'no-cache',
                'pragma': 'no-cache',
                'priority': 'u=0, i',
                'sec-ch-ua': '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'document',
                'sec-fetch-mode': 'navigate',
                'sec-fetch-site': 'same-origin',
                'sec-fetch-user': '?1',
                'upgrade-insecure-requests': '1',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
            }
            
            print("🔍 Checking Shein stock...")
            response = requests.get(
                self.config['api_url'],
                headers=headers,
                timeout=15
            )
            response.raise_for_status()
            
            # Parse the HTML response to find the JSON data
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for script tags containing product data
            scripts = soup.find_all('script')
            for script in scripts:
                script_content = script.string
                if script_content and 'facets' in script_content and 'totalResults' in script_content:
                    try:
                        # Extract JSON data from script tag
                        if 'window.goodsDetailData' in script_content:
                            json_str = script_content.split('window.goodsDetailData = ')[1].split(';')[0]
                            data = json.loads(json_str)
                            total_stock = data.get('facets', {}).get('totalResults', 0)
                            print(f"✅ Found stock: {total_stock} items")
                            return total_stock
                    except (json.JSONDecodeError, IndexError, KeyError) as e:
                        continue
            
            # Alternative: Search for the pattern in the entire response
            response_text = response.text
            if 'facets' in response_text and 'totalResults' in response_text:
                pattern = r'"facets":\s*\{[^}]*"totalResults":\s*(\d+)'
                match = re.search(pattern, response_text)
                if match:
                    total_stock = int(match.group(1))
                    print(f"✅ Found stock via regex: {total_stock} items")
                    return total_stock
            
            print("❌ Could not find stock count in response")
            return 0
            
        except requests.RequestException as e:
            print(f"❌ Network error: {e}")
            return 0
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return 0
    
    def get_previous_stock(self):
        """Get last recorded stock"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT total_stock FROM stock_history ORDER BY timestamp DESC LIMIT 1')
        result = cursor.fetchone()
        return result[0] if result else 0
    
    def save_current_stock(self, current_stock, change=0):
        """Save stock to database"""
        cursor = self.conn.cursor()
        cursor.execute('INSERT INTO stock_history (total_stock, stock_change) VALUES (?, ?)', 
                      (current_stock, change))
        self.conn.commit()
    
    async def send_telegram_message(self, message, parse_mode='HTML'):
        """Send message via Telegram"""
        try:
            await self.application.bot.send_message(
                chat_id=self.config['telegram_chat_id'],
                text=message,
                parse_mode=parse_mode
            )
            return True
        except Exception as e:
            print(f"❌ Error sending message: {e}")
            return False
    
    def check_stock(self):
        """Check stock and notify if increase"""
        if not self.monitoring:
            return
        
        print(f"🕒 Checking stock at {datetime.now().strftime('%H:%M:%S')}")
        current_stock = self.get_shein_stock_count()
        if current_stock == 0:
            return
        
        previous_stock = self.get_previous_stock()
        stock_change = current_stock - previous_stock
        
        print(f"📊 Stock: {current_stock} | Previous: {previous_stock} | Change: {stock_change}")
        
        # Check if significant increase
        if (stock_change >= self.config['min_increase_threshold'] and 
            current_stock >= self.config['min_stock_threshold']):
            
            self.save_current_stock(current_stock, stock_change)
            print(f"🚨 SIGNIFICANT INCREASE: +{stock_change}")
            
            # Send alert
            message = f"""
🚨 SVerse STOCK ALERT! 🚨

📈 **Stock Increased Significantly!**

🔄 Change: +{stock_change} items
📊 Current Total: {current_stock} items
📉 Previous Total: {previous_stock} items

🔗 Check Now: {self.config['api_url']}

⏰ Alert Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

⚡ Quick! New SVerse items might be available!
            """.strip()
            
            # Use asyncio to send message safely
            try:
                import asyncio
                asyncio.run_coroutine_threadsafe(
                    self.send_telegram_message(message),
                    self.application.loop
                )
                print("✅ Alert sent to Telegram!")
            except Exception as e:
                print(f"❌ Error sending alert: {e}")
        else:
            self.save_current_stock(current_stock, stock_change)
            print("✅ No significant change - continuing monitoring")
    
    def start_monitoring_loop(self):
        """Start monitoring in background thread"""
        def monitor():
            print("🔄 Monitoring loop started!")
            while self.monitoring:
                self.check_stock()
                time.sleep(self.config['check_interval_minutes'] * 60)
            print("🛑 Monitoring loop stopped")
        
        self.monitor_thread = threading.Thread(target=monitor)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
    
    async def start_monitoring(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start monitoring command"""
        if self.monitoring:
            await update.message.reply_text("🔄 Monitoring is already running!")
            return
        
        self.monitoring = True
        self.start_monitoring_loop()
        
        # Get current stock for status
        current_stock = self.get_shein_stock_count()
        
        message = f"""
✅ **SHEIN MONITOR STARTED!**

📊 Current Stock: {current_stock} items
⏰ Check Interval: {self.config['check_interval_minutes']} minutes
📈 Min Increase: {self.config['min_increase_threshold']} items

🔗 Monitoring: SVerse Collection

🤖 I will notify you when stock increases significantly!

Use /stop to stop monitoring.
        """.strip()
        
        await update.message.reply_text(message)
        print("✅ Monitoring started via /start command")
    
    async def stop_monitoring(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Stop monitoring command"""
        if not self.monitoring:
            await update.message.reply_text("❌ Monitoring is not running!")
            return
        
        self.monitoring = False
        await update.message.reply_text("🛑 Monitoring stopped!")
        print("🛑 Monitoring stopped via /stop command")
    
    async def check_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check status command"""
        current_stock = self.get_shein_stock_count()
        previous_stock = self.get_previous_stock()
        stock_change = current_stock - previous_stock
        
        message = f"""
📊 **SHEIN MONITOR STATUS**

🔄 Monitoring: {'✅ RUNNING' if self.monitoring else '❌ STOPPED'}
📈 Current Stock: {current_stock} items
📉 Previous Stock: {previous_stock} items
🔄 Stock Change: {stock_change} items

⏰ Last Check: {datetime.now().strftime('%H:%M:%S')}

{'Use /start to begin monitoring' if not self.monitoring else 'Use /stop to stop monitoring'}
        """.strip()
        
        await update.message.reply_text(message)
        print(f"📊 Status checked - Monitoring: {self.monitoring}")
    
    async def force_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Force immediate check"""
        await update.message.reply_text("🔍 Checking stock now...")
        
        current_stock = self.get_shein_stock_count()
        previous_stock = self.get_previous_stock()
        change = current_stock - previous_stock
        
        message = f"""
🔍 **IMMEDIATE STOCK CHECK**

📊 Current Stock: {current_stock} items
📉 Previous Stock: {previous_stock} items
🔄 Stock Change: {change} items

⏰ Checked: {datetime.now().strftime('%H:%M:%S')}
        """.strip()
        
        await update.message.reply_text(message)
        
        # Save this check
        self.save_current_stock(current_stock, change)
        print("🔍 Manual stock check completed")
    
    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help"""
        help_text = """
🤖 **SHEIN STOCK MONITOR BOT**

**Commands:**
/start - Start monitoring Shein stock
/stop - Stop monitoring  
/status - Check current status
/check - Force immediate stock check
/help - Show this help

**Quick Start:**
Send /start to begin monitoring!
        """.strip()
        
        await update.message.reply_text(help_text)
    
    async def start_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Welcome message"""
        welcome = """
🎉 **Welcome to Shein Stock Monitor!**

I monitor SVerse collection on Shein and alert you when stock increases significantly.

**Commands:**
/start - Begin monitoring
/stop - Stop monitoring
/status - Check current status
/check - Force stock check
/help - Show all commands

Send /start to begin!
        """.strip()
        
        await update.message.reply_text(welcome)
    
    def setup_handlers(self):
        """Setup bot command handlers"""
        self.application.add_handler(CommandHandler("start", self.start_monitoring))
        self.application.add_handler(CommandHandler("stop", self.stop_monitoring))
        self.application.add_handler(CommandHandler("status", self.check_status))
        self.application.add_handler(CommandHandler("check", self.force_check))
        self.application.add_handler(CommandHandler("help", self.show_help))
        
        # Handle other messages
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.show_help))
    
    async def run_bot(self):
        """Run the bot"""
        if not TELEGRAM_AVAILABLE:
            print("❌ Telegram library not available. Please check dependencies.")
            return
        
        self.application = Application.builder().token(self.config['telegram_bot_token']).build()
        self.setup_handlers()
        
        # Send startup notification
        await self.send_telegram_message("🤖 Shein Stock Monitor is now ONLINE and ready!")
        
        print("🤖 Bot started successfully - ready for commands!")
        print("📱 Open Telegram and send /start to begin monitoring")
        
        # Start polling - this will keep the bot running
        await self.application.run_polling()

async def main():
    """Main async function"""
    print("🚀 Starting Shein Stock Monitor Cloud Bot...")
    print("💡 This bot runs 24/7 in the cloud!")
    print("📱 Control it entirely via Telegram commands")
    
    config = get_config()
    monitor_bot = SheinStockMonitorBot(config)
    
    try:
        # Run the bot (this will keep running)
        await monitor_bot.run_bot()
    except Exception as e:
        print(f"❌ Bot error: {e}")

if __name__ == "__main__":
    import asyncio
    # Proper asyncio execution
    asyncio.run(main())
