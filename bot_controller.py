import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import json
from datetime import datetime
import os
import threading
import re
import asyncio

# Configuration
CONFIG = {
    'telegram_bot_token': '8413664821:AAHjBwysQWk3GFdJV3Bvk3Jp1vhDLpoymI8',
    'telegram_chat_id': '1366899854',
    'api_url': 'https://www.sheinindia.in/c/sverse-5939-37961',
    'check_interval_minutes': 5,
    'min_stock_threshold': 10,
    'database_path': '/tmp/shein_monitor.db',
    'min_increase_threshold': 50
}

class SheinStockMonitor:
    def __init__(self, config):
        self.config = config
        self.monitoring = False
        self.monitor_thread = None
        self.setup_database()
        print("🤖 Shein Monitor initialized - Type 'help' for commands")
    
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
        """Get total stock count from Shein"""
        try:
            headers = {
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'accept-language': 'en-US,en;q=0.9',
                'cache-control': 'no-cache',
                'pragma': 'no-cache',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
            }
            
            response = requests.get(self.config['api_url'], headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            scripts = soup.find_all('script')
            
            for script in scripts:
                script_content = script.string
                if script_content and 'facets' in script_content and 'totalResults' in script_content:
                    try:
                        if 'window.goodsDetailData' in script_content:
                            json_str = script_content.split('window.goodsDetailData = ')[1].split(';')[0]
                            data = json.loads(json_str)
                            total_stock = data.get('facets', {}).get('totalResults', 0)
                            return total_stock
                    except Exception as e:
                        continue
            
            response_text = response.text
            if 'facets' in response_text and 'totalResults' in response_text:
                pattern = r'"facets":\s*\{[^}]*"totalResults":\s*(\d+)'
                match = re.search(pattern, response_text)
                if match:
                    return int(match.group(1))
            
            return 0
            
        except Exception as e:
            print(f"❌ Error getting stock: {e}")
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
    
    async def send_telegram_message(self, message):
        """Send message via Telegram"""
        try:
            from telegram import Bot
            bot = Bot(token=self.config['telegram_bot_token'])
            await bot.send_message(chat_id=self.config['telegram_chat_id'], text=message, parse_mode='HTML')
            return True
        except Exception as e:
            print(f"❌ Error sending Telegram: {e}")
            return False
    
    def check_stock(self):
        """Check stock and notify if increase"""
        if not self.monitoring:
            return
        
        current_stock = self.get_shein_stock_count()
        if current_stock == 0:
            return
        
        previous_stock = self.get_previous_stock()
        stock_change = current_stock - previous_stock
        
        print(f"🕒 {datetime.now().strftime('%H:%M:%S')} - Stock: {current_stock} | Change: {stock_change}")
        
        if (stock_change >= self.config['min_increase_threshold'] and 
            current_stock >= self.config['min_stock_threshold']):
            
            self.save_current_stock(current_stock, stock_change)
            print(f"🚨 SIGNIFICANT INCREASE: +{stock_change}")
            
            message = f"""
🚨 SVerse STOCK ALERT! 🚨
📈 Stock Increased: +{stock_change} items
📊 Current: {current_stock} items
⏰ {datetime.now().strftime('%H:%M:%S')}
            """.strip()
            
            asyncio.run(self.send_telegram_message(message))
        else:
            self.save_current_stock(current_stock, stock_change)
    
    def start_monitoring_loop(self):
        """Start monitoring in background thread"""
        def monitor():
            while self.monitoring:
                self.check_stock()
                time.sleep(self.config['check_interval_minutes'] * 60)
        
        self.monitor_thread = threading.Thread(target=monitor)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
    
    # COMMAND METHODS
    def start(self):
        """Start monitoring command"""
        if self.monitoring:
            print("🔄 Monitoring is already running!")
            return
        
        self.monitoring = True
        self.start_monitoring_loop()
        print("✅ Monitoring STARTED - checking every 5 minutes")
        asyncio.run(self.send_telegram_message("✅ Shein Monitor STARTED"))
    
    def stop(self):
        """Stop monitoring command"""
        if not self.monitoring:
            print("❌ Monitoring is not running!")
            return
        
        self.monitoring = False
        print("🛑 Monitoring STOPPED")
        asyncio.run(self.send_telegram_message("🛑 Shein Monitor STOPPED"))
    
    def status(self):
        """Check status command"""
        current_stock = self.get_shein_stock_count()
        previous_stock = self.get_previous_stock()
        stock_change = current_stock - previous_stock
        
        status_info = f"""
📊 SHEIN MONITOR STATUS
🔄 Monitoring: {'✅ RUNNING' if self.monitoring else '❌ STOPPED'}
📈 Current Stock: {current_stock} items
📉 Previous Stock: {previous_stock} items
🔄 Stock Change: {stock_change} items
⏰ Last Check: {datetime.now().strftime('%H:%M:%S')}
        """.strip()
        
        print(status_info)
        return status_info
    
    def check(self):
        """Force immediate check command"""
        print("🔍 Checking stock now...")
        current_stock = self.get_shein_stock_count()
        previous_stock = self.get_previous_stock()
        stock_change = current_stock - previous_stock
        
        print(f"📊 Current: {current_stock} | Previous: {previous_stock} | Change: {stock_change}")
        self.save_current_stock(current_stock, stock_change)
    
    def test(self):
        """Send test notification command"""
        print("📨 Sending test notification...")
        message = "🧪 TEST - Shein Monitor is working!"
        success = asyncio.run(self.send_telegram_message(message))
        if success:
            print("✅ Test notification sent!")
        else:
            print("❌ Failed to send test notification")
    
    def help(self):
        """Show help command"""
        help_text = """
🤖 SHEIN STOCK MONITOR - COMMANDS:

start   - Start continuous monitoring (checks every 5min)
stop    - Stop monitoring
status  - Check current stock and status
check   - Force immediate stock check
test    - Send test Telegram notification
help    - Show this help
exit    - Exit the program

💡 Example: Type 'start' to begin monitoring
        """.strip()
        
        print(help_text)

def main():
    """Main function with interactive commands"""
    print("🚀 Starting Shein Stock Monitor...")
    print("💡 Type 'help' to see available commands")
    
    monitor = SheinStockMonitor(CONFIG)
    
    # Command mapping
    commands = {
        'start': monitor.start,
        'stop': monitor.stop,
        'status': monitor.status,
        'check': monitor.check,
        'test': monitor.test,
        'help': monitor.help
    }
    
    while True:
        try:
            user_input = input("\n>>> ").strip().lower()
            
            if user_input == 'exit':
                print("👋 Goodbye!")
                if monitor.monitoring:
                    monitor.stop()
                break
            
            elif user_input in commands:
                commands[user_input]()
            
            else:
                print("❌ Unknown command. Type 'help' for available commands.")
                
        except KeyboardInterrupt:
            print("\n🛑 Stopping monitor...")
            if monitor.monitoring:
                monitor.stop()
            break
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
