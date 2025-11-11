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
        print("🤖 Shein Monitor initialized - Starting automatically...")
    
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
                            print(f"✅ Found stock: {total_stock} items")
                            return total_stock
                    except Exception as e:
                        continue
            
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

📈 **Stock Increased Significantly!**

🔄 Change: +{stock_change} items
📊 Current Total: {current_stock} items
📉 Previous Total: {previous_stock} items

🔗 Check Now: {self.config['api_url']}

⏰ Alert Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """.strip()
            
            asyncio.run(self.send_telegram_message(message))
            print("✅ Telegram alert sent!")
        else:
            self.save_current_stock(current_stock, stock_change)
    
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
    
    def start(self):
        """Start monitoring"""
        if self.monitoring:
            print("🔄 Monitoring is already running!")
            return
        
        self.monitoring = True
        self.start_monitoring_loop()
        
        # Send startup message
        asyncio.run(self.send_startup_message())
        
        print("✅ Monitoring STARTED - checking every 5 minutes")
    
    async def send_startup_message(self):
        """Send startup message to Telegram"""
        current_stock = self.get_shein_stock_count()
        
        message = f"""
✅ SHEIN MONITOR STARTED!

📊 Current Stock: {current_stock} items
⏰ Check Interval: {self.config['check_interval_minutes']} minutes
📈 Min Increase: {self.config['min_increase_threshold']} items

🤖 I will notify you when stock increases significantly!
        """.strip()
        
        await self.send_telegram_message(message)
        print("✅ Startup message sent to Telegram!")

def main():
    """Main function - starts automatically"""
    print("=" * 50)
    print("🚀 SHEIN STOCK MONITOR - CLOUD VERSION")
    print("=" * 50)
    print("💡 This version runs 24/7 automatically")
    print("📱 Sends Telegram alerts when stock increases")
    print("⏰ Checks every 5 minutes")
    print("=" * 50)
    
    monitor = SheinStockMonitor(CONFIG)
    
    # Start monitoring automatically
    monitor.start()
    
    print("\n✅ Monitor is now running 24/7!")
    print("📊 It will check stock every 5 minutes")
    print("🚨 You will receive Telegram alerts for significant increases")
    print("💤 Running in background...")
    
    try:
        # Keep the main thread alive forever
        while True:
            time.sleep(60)  # Sleep forever, monitoring runs in background thread
            
    except KeyboardInterrupt:
        print("\n🛑 Monitor stopped by user")
        monitor.monitoring = False

if __name__ == "__main__":
    main()
