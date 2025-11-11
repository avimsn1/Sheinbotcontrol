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

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class SheinStockMonitor:
    def __init__(self, config):
        self.config = config
        self.monitoring = False
        self.monitor_thread = None
        self.setup_database()
        print("🤖 Shein Monitor initialized")
    
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
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
            }
            
            response = requests.get(
                self.config['api_url'],
                headers=headers,
                timeout=15
            )
            response.raise_for_status()
            
            # Parse the HTML response
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for script tags containing product data
            scripts = soup.find_all('script')
            for script in scripts:
                script_content = script.string
                if script_content and 'facets' in script_content and 'totalResults' in script_content:
                    try:
                        if 'window.goodsDetailData' in script_content:
                            json_str = script_content.split('window.goodsDetailData = ')[1].split(';')[0]
                            data = json.loads(json_str)
                            total_stock = data.get('facets', {}).get('totalResults', 0)
                            print(f"✅ Found stock: {total_stock} items")
                            return total_stock
                    except Exception as e:
                        continue
            
            # Alternative regex search
            response_text = response.text
            if 'facets' in response_text and 'totalResults' in response_text:
                pattern = r'"facets":\s*\{[^}]*"totalResults":\s*(\d+)'
                match = re.search(pattern, response_text)
                if match:
                    total_stock = int(match.group(1))
                    print(f"✅ Found stock via regex: {total_stock} items")
                    return total_stock
            
            print("❌ Could not find stock count")
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
    
    def check_stock(self):
        """Check stock and print if increase"""
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
            print(f"🚨 SIGNIFICANT INCREASE DETECTED: +{stock_change}")
            
            # Send Telegram alert
            asyncio.run(self.send_telegram_alert(current_stock, previous_stock, stock_change))
        else:
            self.save_current_stock(current_stock, stock_change)
            print("✅ No significant change")
    
    async def send_telegram_alert(self, current_stock, previous_stock, increase):
        """Send alert via Telegram"""
        try:
            from telegram import Bot
            
            bot = Bot(token=self.config['telegram_bot_token'])
            
            message = f"""
🚨 SVerse STOCK ALERT! 🚨

📈 **Stock Increased Significantly!**

🔄 Change: +{increase} items
📊 Current Total: {current_stock} items
📉 Previous Total: {previous_stock} items

🔗 Check Now: {self.config['api_url']}

⏰ Alert Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """.strip()
            
            await bot.send_message(
                chat_id=self.config['telegram_chat_id'],
                text=message
            )
            print("✅ Telegram alert sent!")
            
        except Exception as e:
            print(f"❌ Failed to send Telegram alert: {e}")
    
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
    
    def start_monitoring(self):
        """Start monitoring"""
        if self.monitoring:
            print("🔄 Monitoring is already running!")
            return
        
        self.monitoring = True
        self.start_monitoring_loop()
        
        # Send startup message
        asyncio.run(self.send_startup_message())
        
        print("✅ Monitoring started!")
    
    def stop_monitoring(self):
        """Stop monitoring"""
        if not self.monitoring:
            print("❌ Monitoring is not running!")
            return
        
        self.monitoring = False
        print("🛑 Monitoring stopped!")
    
    async def send_startup_message(self):
        """Send startup message"""
        try:
            from telegram import Bot
            
            bot = Bot(token=self.config['telegram_bot_token'])
            
            current_stock = self.get_shein_stock_count()
            
            message = f"""
✅ **SHEIN MONITOR STARTED!**

📊 Current Stock: {current_stock} items
⏰ Check Interval: {self.config['check_interval_minutes']} minutes
📈 Min Increase: {self.config['min_increase_threshold']} items

🤖 I will notify you when stock increases significantly!
            """.strip()
            
            await bot.send_message(
                chat_id=self.config['telegram_chat_id'],
                text=message
            )
            print("✅ Startup message sent!")
            
        except Exception as e:
            print(f"❌ Failed to send startup message: {e}")
    
    def check_status(self):
        """Check and print status"""
        current_stock = self.get_shein_stock_count()
        previous_stock = self.get_previous_stock()
        stock_change = current_stock - previous_stock
        
        status = f"""
📊 **SHEIN MONITOR STATUS**

🔄 Monitoring: {'✅ RUNNING' if self.monitoring else '❌ STOPPED'}
📈 Current Stock: {current_stock} items
📉 Previous Stock: {previous_stock} items
🔄 Stock Change: {stock_change} items

⏰ Last Check: {datetime.now().strftime('%H:%M:%S')}
        """.strip()
        
        print(status)
        return status

def main():
    """Main function"""
    print("🚀 Starting Shein Stock Monitor...")
    print("💡 This runs 24/7 and sends Telegram alerts")
    
    monitor = SheinStockMonitor(CONFIG)
    
    # Start monitoring immediately
    monitor.start_monitoring()
    
    print("✅ Monitor is running! Press Ctrl+C to stop.")
    
    try:
        # Keep the main thread alive
        while True:
            # Print status every 10 minutes
            time.sleep(600)
            monitor.check_status()
            
    except KeyboardInterrupt:
        print("\n🛑 Stopping monitor...")
        monitor.stop_monitoring()

if __name__ == "__main__":
    main()
