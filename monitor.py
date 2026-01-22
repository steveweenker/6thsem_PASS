import asyncio
import os
import time
import aiohttp
import pytz
from datetime import datetime
from typing import Optional
from playwright.async_api import async_playwright

# ========== CONFIGURATION ==========
# Get credentials from Railway environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

# Validate credentials
if not BOT_TOKEN or not CHAT_ID:
    print("❌ ERROR: Telegram credentials not set!")
    print("Please set these environment variables in Railway:")
    print("  - BOT_TOKEN: Your Telegram bot token")
    print("  - CHAT_ID: Your Telegram chat ID")
    print("\nGet these from @BotFather and @userinfobot")
    exit(1)

# Personal details (hardcoded - safe)
YOUR_REG_NO = "22156148040"
TARGET_SUBJECT_CODE = "156606P"
TARGET_SUBJECT_NAME = "NPTEL Course-II Lab"
CURRENT_WRONG_VALUE = "NA"
EXPECTED_MARK = "68"

# Monitoring settings
CHECK_INTERVAL = 30  # Check every 30 seconds
DOWN_NOTIFY_INTERVAL = 3600  # Notify if down for 1 hour
DOWN_GRACE = 300  # 5 minutes grace before declaring down

# ========== MONITOR CLASS ==========
class ResultCorrectionMonitor:
    def __init__(self):
        # State tracking
        self.site_down_since = None
        self.site_down_notified = False
        self.correction_found = False
        self.verified_count = 0
        self.consecutive_failures = 0
        
        # Timezone for India
        self.ist = pytz.timezone('Asia/Kolkata')
        
        # Browser configuration for Railway
        self.browser_args = [
            '--disable-dev-shm-usage',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-gpu'
        ]
        
        # Startup information
        self.print_banner()
    
    def print_banner(self):
        """Display startup banner"""
        print("=" * 60)
        print("🚀 6TH SEMESTER RESULT CORRECTION MONITOR")
        print("=" * 60)
        print(f"📝 Registration: {YOUR_REG_NO}")
        print(f"🎯 Subject: {TARGET_SUBJECT_CODE} ({TARGET_SUBJECT_NAME})")
        print(f"❌ Current: {CURRENT_WRONG_VALUE}")
        print(f"✅ Expected: {EXPECTED_MARK} marks")
        print(f"⏰ Check Interval: {CHECK_INTERVAL} seconds")
        print(f"🔔 Notifications: Telegram ✅")
        print(f"🏢 Platform: Railway")
        print(f"🕐 Start Time: {self.get_indian_time()}")
        print("=" * 60)
    
    def get_indian_time(self) -> str:
        """Get current Indian Standard Time"""
        utc_now = datetime.now(pytz.utc)
        ist_now = utc_now.astimezone(self.ist)
        return ist_now.strftime("%d-%m-%Y %I:%M:%S %p IST")
    
    def build_result_url(self) -> str:
        """Build BEU result URL for 6th semester"""
        # URL-encoded parameters
        params = f"name=B.Tech.%206th%20Semester%20Examination%2C%202025" \
                f"&semester=VI" \
                f"&session=2025" \
                f"&regNo={YOUR_REG_NO}" \
                f"&exam_held=November%2F2025"
        return f"https://beu-bih.ac.in/result-three?{params}"
    
    async def send_telegram(self, message: str) -> bool:
        """Send message to Telegram"""
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            data = {
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            }
            
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=data) as response:
                    if response.status == 200:
                        return True
                    else:
                        print(f"Telegram error: HTTP {response.status}")
                        return False
        except Exception as e:
            print(f"Telegram send failed: {str(e)[:50]}")
            return False
    
    async def check_website(self) -> bool:
        """Quick check if website is accessible"""
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.build_result_url()) as response:
                    return response.status == 200
        except:
            return False
    
    async def fetch_result(self) -> dict:
        """Fetch and parse result page"""
        result = {
            "success": False,
            "mark": None,
            "status": None,
            "error": None
        }
        
        async with async_playwright() as p:
            try:
                # Launch browser with Railway-optimized settings
                browser = await p.chromium.launch(
                    headless=True,
                    args=self.browser_args,
                    timeout=30000
                )
                
                page = await browser.new_page()
                
                # Navigate to result page
                await page.goto(self.build_result_url(), timeout=40000)
                
                # Verify page loaded
                try:
                    await page.wait_for_selector(f"text={YOUR_REG_NO}", timeout=15000)
                except:
                    result["error"] = "Registration number not found"
                    await browser.close()
                    return result
                
                # Get page content
                content = await page.content()
                
                # Check result status
                if "RESULT : PASS" in content.upper():
                    result["status"] = "PASS"
                elif "RESULT : FAIL" in content.upper():
                    result["status"] = "FAIL"
                
                # Find target subject
                rows = await page.query_selector_all("tr")
                for row in rows:
                    text = await row.text_content()
                    if TARGET_SUBJECT_CODE in text:
                        # Found the subject row
                        cells = await row.query_selector_all("td")
                        if len(cells) >= 4:
                            mark = (await cells[3].text_content()).strip()
                            result["mark"] = mark
                            result["success"] = True
                        break
                
                await browser.close()
                
            except Exception as e:
                result["error"] = f"Browser error: {str(e)[:100]}"
        
        return result
    
    async def capture_proof(self) -> Optional[bytes]:
        """Capture screenshot of result page"""
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(
                    headless=True,
                    args=self.browser_args
                )
                page = await browser.new_page()
                
                await page.goto(self.build_result_url(), timeout=40000)
                await page.wait_for_selector("table", timeout=10000)
                
                screenshot = await page.screenshot(full_page=True)
                await browser.close()
                return screenshot
                
            except:
                return None
    
    async def send_screenshot(self, image_data: bytes, caption: str) -> bool:
        """Send screenshot to Telegram"""
        try:
            form = aiohttp.FormData()
            form.add_field('chat_id', CHAT_ID)
            form.add_field('photo', image_data, filename='result_proof.png')
            form.add_field('caption', caption)
            form.add_field('parse_mode', 'HTML')
            
            timeout = aiohttp.ClientTimeout(total=40)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
                async with session.post(url, data=form) as response:
                    return response.status == 200
        except:
            return False
    
    async def monitor_website_status(self, is_up: bool):
        """Handle website up/down status"""
        current_time = time.time()
        
        if not is_up:
            # Website is down
            if not self.site_down_since:
                self.site_down_since = current_time
                self.consecutive_failures += 1
                
                # Notify after grace period
                if self.consecutive_failures >= (DOWN_GRACE / CHECK_INTERVAL):
                    if not self.site_down_notified:
                        await self.send_telegram(
                            f"🔴 <b>Website is DOWN</b>\n"
                            f"⏰ {self.get_indian_time()}\n\n"
                            f"<i>Will notify when back online.</i>"
                        )
                        self.site_down_notified = True
            
            # Hourly reminder if still down
            elif self.site_down_notified and (current_time - self.site_down_since) >= DOWN_NOTIFY_INTERVAL:
                minutes = int((current_time - self.site_down_since) / 60)
                await self.send_telegram(
                    f"🔴 <b>Still DOWN</b> ({minutes} minutes)\n"
                    f"🕐 {self.get_indian_time()}"
                )
                
        else:
            # Website is up
            if self.site_down_since:
                # Just came back online
                minutes = int((current_time - self.site_down_since) / 60)
                await self.send_telegram(
                    f"✅ <b>Website BACK ONLINE!</b>\n"
                    f"⏰ Was down for {minutes} minutes\n"
                    f"🕐 {self.get_indian_time()}"
                )
                self.site_down_since = None
                self.site_down_notified = False
                self.consecutive_failures = 0
    
    async def run(self):
        """Main monitoring loop"""
        # Send startup notification
        await self.send_telegram(
            f"🚀 <b>6th Semester Monitor Started</b>\n\n"
            f"📝 <b>Registration:</b> {YOUR_REG_NO}\n"
            f"🎯 <b>Subject:</b> {TARGET_SUBJECT_CODE}\n"
            f"✅ <b>Expected:</b> {EXPECTED_MARK} marks\n"
            f"⏰ <b>Started:</b> {self.get_indian_time()}\n"
            f"🔄 <b>Checking:</b> Every {CHECK_INTERVAL} seconds\n\n"
            f"<i>Monitoring 24/7 for result correction...</i>"
        )
        
        print("[*] Starting 24/7 monitoring loop...")
        
        while True:
            try:
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(f"[{timestamp}] Checking result...")
                
                # Check website status
                is_accessible = await self.check_website()
                await self.monitor_website_status(is_accessible)
                
                if not is_accessible:
                    print("[!] Website not accessible")
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue
                
                # Fetch result
                result = await self.fetch_result()
                
                if not result["success"]:
                    print(f"[!] Fetch failed: {result.get('error')}")
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue
                
                current_mark = result["mark"]
                result_status = result["status"]
                
                print(f"[*] Mark: {current_mark} | Status: {result_status}")
                
                # Check for correction
                if current_mark == EXPECTED_MARK or (current_mark.isdigit() and current_mark != CURRENT_WRONG_VALUE):
                    # Correction detected!
                    if not self.correction_found:
                        self.correction_found = True
                        
                        await self.send_telegram(
                            f"🚨 <b>CORRECTION DETECTED!</b>\n\n"
                            f"✅ {TARGET_SUBJECT_CODE}: {current_mark} marks\n"
                            f"📊 Result: {result_status}\n"
                            f"🕐 {self.get_indian_time()}"
                        )
                        
                        # Send screenshot proof
                        screenshot = await self.capture_proof()
                        if screenshot:
                            await self.send_screenshot(
                                screenshot,
                                f"📸 Proof: {TARGET_SUBJECT_CODE} = {current_mark}"
                            )
                    
                    self.verified_count += 1
                    
                    # Confirm after 3 checks
                    if self.verified_count == 3:
                        await self.send_telegram(
                            f"✅ <b>CONFIRMED!</b>\n\n"
                            f"🎉 Your result is now correct!\n"
                            f"📚 {TARGET_SUBJECT_NAME}: {current_mark}\n"
                            f"🏆 Status: {result_status}\n"
                            f"⏰ {self.get_indian_time()}\n\n"
                            f"<b>Ready for applications!</b>"
                        )
                
                elif current_mark == CURRENT_WRONG_VALUE and self.correction_found:
                    # Reverted to NA
                    await self.send_telegram(
                        f"⚠️ <b>Back to NA</b>\n"
                        f"{TARGET_SUBJECT_CODE} shows NA again\n"
                        f"🕐 {self.get_indian_time()}"
                    )
                    self.correction_found = False
                    self.verified_count = 0
                
            except Exception as e:
                print(f"[!] Error: {str(e)[:80]}")
            
            # Wait for next check
            await asyncio.sleep(CHECK_INTERVAL)

# ========== MAIN ==========
async def main():
    monitor = ResultCorrectionMonitor()
    await monitor.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Stopped by user")
    except Exception as e:
        print(f"[!] Fatal: {e}")
