import asyncio
import os
import time
import aiohttp
import pytz
from datetime import datetime
from typing import Optional
from playwright.async_api import async_playwright

# --- CONFIGURATION ---
# MUST be set in Railway environment variables - NO HARDCODING
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Validate credentials on startup
if not BOT_TOKEN or not CHAT_ID:
    print("❌ ERROR: Telegram credentials not set!")
    print("Please set these environment variables in Railway:")
    print("  BOT_TOKEN=your_telegram_bot_token")
    print("  CHAT_ID=your_telegram_chat_id")
    print("\nTo get these:")
    print("1. Create bot with @BotFather")
    print("2. Get chat ID from @userinfobot")
    exit(1)

# --- HARDCODED PERSONAL DETAILS (Non-sensitive) ---
YOUR_REG_NO = "22156148040"
TARGET_SUBJECT_CODE = "156606P"
TARGET_SUBJECT_NAME = "NPTEL Course-II Lab"
CURRENT_WRONG_VALUE = "NA"
EXPECTED_MARK = "68"

# --- SETTINGS ---
CHECK_INTERVAL = 30
DOWN_CHECK_INTERVAL = 3600
DOWN_GRACE = 300

class RailwayMonitor:
    def __init__(self):
        # State tracking
        self.down_since = None
        self.down_notified = False
        self.correction_found = False
        self.verified_count = 0
        self.failures = 0
        
        # Timezone
        self.ist = pytz.timezone('Asia/Kolkata')
        
        # Browser optimization
        self.browser_args = [
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--no-sandbox',
            '--disable-setuid-sandbox'
        ]
        
        # Startup banner
        print("=" * 60)
        print("🚀 6th Semester Result Correction Monitor")
        print("=" * 60)
        print(f"📝 Registration: {YOUR_REG_NO}")
        print(f"🎯 Subject: {TARGET_SUBJECT_CODE}")
        print(f"❌ Current: {CURRENT_WRONG_VALUE} → ✅ Expected: {EXPECTED_MARK}")
        print(f"⏰ Check Interval: {CHECK_INTERVAL} seconds")
        print(f"🔔 Telegram: ✅ Connected")
        print(f"🏢 Platform: Railway")
        print(f"🕐 Started: {self.get_time()}")
        print("=" * 60)
    
    def get_time(self):
        return datetime.now(self.ist).strftime("%d-%m-%Y %I:%M:%S %p IST")
    
    def build_url(self):
        """Build result URL for 6th semester"""
        params = {
            'name': 'B.Tech. 6th Semester Examination, 2025',
            'semester': 'VI',
            'session': '2025',
            'regNo': YOUR_REG_NO,
            'exam_held': 'November/2025'
        }
        # Manual URL encoding
        encoded_params = '&'.join([f"{k}={v.replace(' ', '%20').replace(',', '%2C')}" for k, v in params.items()])
        return f"https://beu-bih.ac.in/result-three?{encoded_params}"
    
    async def send_telegram(self, text: str) -> bool:
        """Send message to Telegram with retry logic"""
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
        
        for attempt in range(3):
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(15)) as session:
                    async with session.post(url, json=data) as response:
                        if response.status == 200:
                            return True
                        else:
                            print(f"⚠️ Telegram API error: {response.status}")
            except Exception as e:
                print(f"⚠️ Telegram attempt {attempt + 1} failed: {str(e)[:50]}")
                if attempt < 2:
                    await asyncio.sleep(1)
        
        print("❌ Failed to send Telegram message after 3 attempts")
        return False
    
    async def check_site_access(self) -> bool:
        """Quick HTTP check for website accessibility"""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(8)) as session:
                async with session.get(self.build_url()) as response:
                    return response.status == 200
        except:
            return False
    
    async def check_result(self) -> dict:
        """Check result page for marks"""
        result = {
            "success": False,
            "mark": None,
            "status": None,
            "error": None
        }
        
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(
                    headless=True,
                    args=self.browser_args
                )
                page = await browser.new_page()
                
                # Navigate to result page
                await page.goto(self.build_url(), timeout=40000)
                
                # Verify page loaded correctly
                try:
                    await page.wait_for_selector(f"text={YOUR_REG_NO}", timeout=15000)
                except:
                    result["error"] = "Registration number not found"
                    await browser.close()
                    return result
                
                # Get page content
                content = await page.content()
                
                # Check overall result status
                if "RESULT : PASS" in content:
                    result["status"] = "PASS"
                elif "RESULT : FAIL" in content:
                    result["status"] = "FAIL"
                
                # Find the specific subject
                rows = await page.query_selector_all("tr")
                for row in rows:
                    text = await row.text_content()
                    if TARGET_SUBJECT_CODE in text:
                        cells = await row.query_selector_all("td")
                        if len(cells) >= 4:
                            mark = (await cells[3].text_content()).strip()
                            result["mark"] = mark
                            result["success"] = True
                        break
                
                await browser.close()
                
            except Exception as e:
                result["error"] = str(e)[:100]
        
        return result
    
    async def capture_screenshot(self) -> Optional[bytes]:
        """Take full-page screenshot as proof"""
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(
                    headless=True,
                    args=self.browser_args
                )
                page = await browser.new_page()
                
                await page.goto(self.build_url(), timeout=40000)
                await page.wait_for_selector("table", timeout=15000)
                
                screenshot = await page.screenshot(full_page=True)
                await browser.close()
                return screenshot
                
            except:
                return None
    
    async def send_screenshot(self, image_bytes: bytes, caption: str) -> bool:
        """Send screenshot to Telegram"""
        try:
            form_data = aiohttp.FormData()
            form_data.add_field('chat_id', CHAT_ID)
            form_data.add_field('photo', image_bytes, filename='result_proof.png')
            form_data.add_field('caption', caption)
            form_data.add_field('parse_mode', 'HTML')
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(40)) as session:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
                async with session.post(url, data=form_data) as response:
                    return response.status == 200
        except:
            return False
    
    async def handle_site_status(self, is_accessible: bool):
        """Manage website up/down notifications"""
        now = time.time()
        
        if not is_accessible:
            # Site is down
            if not self.down_since:
                self.down_since = now
                self.failures += 1
                
                # Only notify after grace period
                if self.failures >= (DOWN_GRACE / CHECK_INTERVAL):
                    if not self.down_notified:
                        await self.send_telegram(
                            f"🔴 <b>Website is DOWN</b>\n"
                            f"⏰ Since: {self.get_time()}\n\n"
                            f"<i>Monitoring continues...</i>"
                        )
                        self.down_notified = True
                        
            elif self.down_notified and (now - self.down_since) >= DOWN_CHECK_INTERVAL:
                # Hourly reminder if still down
                minutes = int((now - self.down_since) / 60)
                await self.send_telegram(
                    f"🔴 <b>Still DOWN</b>\n"
                    f"⏰ {minutes} minutes and counting...\n"
                    f"🕐 {self.get_time()}"
                )
                
        else:
            # Site is up
            if self.down_since:
                # Site just came back online
                minutes = int((time.time() - self.down_since) / 60)
                await self.send_telegram(
                    f"✅ <b>Website is BACK ONLINE!</b>\n"
                    f"⏰ Was down for: {minutes} minutes\n"
                    f"🕐 {self.get_time()}\n\n"
                    f"<i>Resuming result monitoring...</i>"
                )
                self.down_since = None
                self.down_notified = False
                self.failures = 0
    
    async def run_monitor(self):
        """Main monitoring loop"""
        # Send startup notification
        await self.send_telegram(
            f"🚀 <b>6th Semester Monitor Started</b>\n\n"
            f"📝 <b>Registration:</b> {YOUR_REG_NO}\n"
            f"🎯 <b>Monitoring:</b> {TARGET_SUBJECT_CODE}\n"
            f"✅ <b>Expected Marks:</b> {EXPECTED_MARK}\n"
            f"⏰ <b>Started:</b> {self.get_time()}\n"
            f"🔄 <b>Check Interval:</b> Every {CHECK_INTERVAL} seconds\n\n"
            f"<i>Will notify instantly when correction is detected...</i>"
        )
        
        print("[*] Starting 24/7 monitoring loop...")
        
        while True:
            try:
                current_time = datetime.now().strftime("%H:%M:%S")
                print(f"[{current_time}] Checking result...")
                
                # Check website accessibility
                is_up = await self.check_site_access()
                await self.handle_site_status(is_up)
                
                if not is_up:
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue
                
                # Check result
                result = await self.check_result()
                
                if not result["success"]:
                    print(f"[!] Check failed: {result.get('error', 'Unknown error')}")
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue
                
                mark = result["mark"]
                status = result["status"]
                
                print(f"[*] Current mark: {mark} | Result status: {status}")
                
                # Check if correction has been made
                if mark == EXPECTED_MARK or (mark.isdigit() and mark != CURRENT_WRONG_VALUE):
                    # Correction detected!
                    if not self.correction_found:
                        self.correction_found = True
                        
                        # Send immediate alert
                        await self.send_telegram(
                            f"🚨 <b>CORRECTION DETECTED!</b>\n\n"
                            f"✅ <b>Subject:</b> {TARGET_SUBJECT_CODE}\n"
                            f"📊 <b>New Mark:</b> {mark}\n"
                            f"📝 <b>Result Status:</b> {status}\n"
                            f"🕐 <b>Time:</b> {self.get_time()}\n\n"
                            f"<i>Verifying...</i>"
                        )
                        
                        # Capture and send screenshot as proof
                        screenshot = await self.capture_screenshot()
                        if screenshot:
                            await self.send_screenshot(
                                screenshot,
                                f"📸 <b>Visual Proof</b>\n{TARGET_SUBJECT_CODE} = {mark} marks"
                            )
                    
                    # Count verifications
                    self.verified_count += 1
                    
                    # Confirm after 3 successful checks
                    if self.verified_count == 3:
                        await self.send_telegram(
                            f"✅ <b>CORRECTION CONFIRMED!</b>\n\n"
                            f"🎉 <b>Your result has been officially corrected!</b>\n"
                            f"📚 <b>Subject:</b> {TARGET_SUBJECT_NAME}\n"
                            f"📈 <b>Marks:</b> {mark} (was {CURRENT_WRONG_VALUE})\n"
                            f"🏆 <b>Final Status:</b> {status}\n"
                            f"⏰ <b>Confirmed at:</b> {self.get_time()}\n\n"
                            f"<b>You can now use your 6th semester result card for applications!</b>"
                        )
                
                elif mark == CURRENT_WRONG_VALUE and self.correction_found:
                    # Result reverted back to incorrect state
                    await self.send_telegram(
                        f"⚠️ <b>WARNING: Correction Reverted!</b>\n\n"
                        f"{TARGET_SUBJECT_CODE} shows '{CURRENT_WRONG_VALUE}' again\n"
                        f"🕐 {self.get_time()}"
                    )
                    self.correction_found = False
                    self.verified_count = 0
                    print(f"[!] Correction reverted - back to {CURRENT_WRONG_VALUE}")
                
                # Different mark detected (neither expected nor NA)
                elif mark != CURRENT_WRONG_VALUE and mark != EXPECTED_MARK and not self.correction_found:
                    await self.send_telegram(
                        f"ℹ️ <b>Update Detected</b>\n\n"
                        f"{TARGET_SUBJECT_CODE}: {mark} marks\n"
                        f"(Expected: {EXPECTED_MARK})\n"
                        f"🕐 {self.get_time()}"
                    )
                    self.correction_found = True
                    print(f"[*] Different mark detected: {mark}")
                
            except Exception as e:
                print(f"[!] Error in monitoring loop: {str(e)[:80]}")
            
            # Wait for next check
            await asyncio.sleep(CHECK_INTERVAL)


async def main():
    monitor = RailwayMonitor()
    await monitor.run_monitor()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Monitor stopped by user")
    except Exception as e:
        print(f"[!] Fatal error: {e}")
