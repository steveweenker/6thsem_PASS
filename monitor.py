import asyncio
import os
import time
import aiohttp
import pytz
import urllib.parse
from datetime import datetime
from typing import Optional
from playwright.async_api import async_playwright

# --- CONFIGURATION (Railway Environment Variables) ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "7241311281:AAE1_ATW_oJqpRlT_R7TE2ECmFXAc-y00v4")
CHAT_ID = os.getenv("CHAT_ID", "1293460387")
YOUR_REG_NO = os.getenv("YOUR_REG_NO", "22156148040")
TARGET_SUBJECT_CODE = os.getenv("TARGET_SUBJECT_CODE", "156512P")
EXPECTED_MARK = os.getenv("EXPECTED_MARK", "30")
CURRENT_WRONG_VALUE = os.getenv("CURRENT_WRONG_VALUE", "NA")

# Exam configuration
EXAM_CONFIG = {
    "ordinal_sem": "5th",
    "roman_sem": "V",
    "session": "2024",
    "held_month": "July",
    "held_year": "2025"
}

# --- MONITORING SETTINGS ---
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "30"))
SITE_DOWN_CHECK_INTERVAL = int(os.getenv("SITE_DOWN_CHECK_INTERVAL", "3600"))
SITE_DOWN_GRACE_PERIOD = int(os.getenv("SITE_DOWN_GRACE_PERIOD", "300"))

class RailwayResultMonitor:
    def __init__(self):
        # State management
        self.site_down_since = None
        self.site_down_notified = False
        self.correction_detected = False
        self.correction_verified_count = 0
        self.consecutive_failures = 0
        self.last_site_check_time = time.time()
        
        # Timezone
        self.ist_timezone = pytz.timezone('Asia/Kolkata')
        
        # Railway optimizations
        self.browser_args = [
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-accelerated-2d-canvas',
            '--disable-background-timer-throttling'
        ]
        
        # Log startup
        self.log("=" * 60)
        self.log("🚀 RESULT CORRECTION MONITOR - Railway Deployment")
        self.log("=" * 60)
        self.log(f"📝 Registration: {YOUR_REG_NO}")
        self.log(f"🎯 Subject: {TARGET_SUBJECT_CODE}")
        self.log(f"✅ Expected Mark: {EXPECTED_MARK}")
        self.log(f"⏰ Check Interval: {CHECK_INTERVAL} seconds")
        self.log(f"🕐 Start Time: {self.get_indian_time()}")
        self.log("=" * 60)

    def log(self, message: str):
        """Railway-friendly logging"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {message}")

    def get_indian_time(self) -> str:
        utc_now = datetime.now(pytz.utc)
        ist_now = utc_now.astimezone(self.ist_timezone)
        return ist_now.strftime("%d-%m-%Y %I:%M:%S %p IST")

    def construct_url(self, reg_no):
        name_param = f"B.Tech. {EXAM_CONFIG['ordinal_sem']} Semester Examination, {EXAM_CONFIG['session']}"
        held_param = f"{EXAM_CONFIG['held_month']}/{EXAM_CONFIG['held_year']}"
        params = {
            'name': name_param,
            'semester': EXAM_CONFIG['roman_sem'],
            'session': EXAM_CONFIG['session'],
            'regNo': str(reg_no),
            'exam_held': held_param
        }
        return f"https://beu-bih.ac.in/result-three?{urllib.parse.urlencode(params)}"

    async def send_telegram_message(self, text: str, max_retries: int = 3) -> bool:
        """Send Telegram with retry logic for Railway"""
        if not BOT_TOKEN or not CHAT_ID:
            self.log("⚠️ Telegram credentials not set")
            return False
        
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
        
        for attempt in range(max_retries):
            try:
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, json=payload) as resp:
                        if resp.status == 200:
                            return True
                        else:
                            self.log(f"Telegram API error: {resp.status}")
            except Exception as e:
                self.log(f"Telegram attempt {attempt + 1} failed: {str(e)[:100]}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        self.log("❌ All Telegram attempts failed")
        return False

    async def check_website_accessibility(self) -> bool:
        """Lightweight HTTP check for Railway"""
        url = self.construct_url(YOUR_REG_NO)
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.head(url, allow_redirects=True) as resp:
                    return resp.status == 200
        except:
            return False

    async def check_result_correction(self) -> dict:
        """Check result with Railway-optimized browser"""
        url = self.construct_url(YOUR_REG_NO)
        
        result_info = {
            "status": "error",
            "subject_found": False,
            "mark": None,
            "result_status": None,
            "has_na": False,
            "is_corrected": False,
            "error": None
        }

        async with async_playwright() as p:
            try:
                # Railway-optimized browser launch
                browser = await p.chromium.launch(
                    headless=True,
                    args=self.browser_args,
                    timeout=30000
                )
                
                page = await browser.new_page()
                
                try:
                    # Set longer timeout for Railway
                    await page.goto(url, timeout=45000, wait_until="networkidle")
                    
                    # Wait for result table
                    try:
                        await page.wait_for_selector("table", timeout=20000)
                    except:
                        result_info["error"] = "Result table not found"
                        await browser.close()
                        return result_info
                    
                    # Check registration number
                    try:
                        await page.wait_for_selector(f"text={YOUR_REG_NO}", timeout=15000)
                    except:
                        result_info["error"] = "Registration not found"
                        await browser.close()
                        return result_info
                    
                    # Check result status
                    content = await page.content()
                    if "RESULT : PASS" in content:
                        result_info["result_status"] = "PASS"
                    elif "RESULT : FAIL" in content:
                        result_info["result_status"] = "FAIL"
                    
                    # Find subject
                    rows = await page.query_selector_all("table tr")
                    for row in rows:
                        row_text = await row.text_content()
                        if TARGET_SUBJECT_CODE in row_text:
                            result_info["subject_found"] = True
                            cells = await row.query_selector_all("td")
                            
                            if len(cells) >= 4:
                                mark_text = (await cells[3].text_content()).strip()
                                result_info["mark"] = mark_text
                                
                                if mark_text == CURRENT_WRONG_VALUE:
                                    result_info["has_na"] = True
                                    result_info["is_corrected"] = False
                                elif mark_text == EXPECTED_MARK:
                                    result_info["is_corrected"] = True
                                    result_info["has_na"] = False
                                else:
                                    result_info["is_corrected"] = mark_text.isdigit() and mark_text != CURRENT_WRONG_VALUE
                            break
                    
                    result_info["status"] = "success"
                    
                except Exception as e:
                    result_info["error"] = str(e)[:200]  # Truncate long errors
                
                finally:
                    await browser.close()
                    
            except Exception as e:
                result_info["error"] = f"Browser error: {str(e)[:200]}"
        
        return result_info

    async def take_screenshot(self) -> Optional[bytes]:
        """Take screenshot for Railway"""
        url = self.construct_url(YOUR_REG_NO)
        
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(
                    headless=True,
                    args=self.browser_args
                )
                page = await browser.new_page()
                
                await page.goto(url, timeout=45000, wait_until="networkidle")
                await page.wait_for_selector("table", timeout=15000)
                
                screenshot = await page.screenshot(full_page=True)
                await browser.close()
                return screenshot
                
            except:
                return None

    async def send_screenshot_to_telegram(self, screenshot_bytes: bytes, caption: str) -> bool:
        """Send screenshot optimized for Railway"""
        if not BOT_TOKEN or not CHAT_ID:
            return False
        
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        
        try:
            form_data = aiohttp.FormData()
            form_data.add_field('chat_id', CHAT_ID)
            form_data.add_field('photo', screenshot_bytes, filename='proof.png')
            form_data.add_field('caption', caption)
            form_data.add_field('parse_mode', 'HTML')
            
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, data=form_data) as resp:
                    return resp.status == 200
        except:
            return False

    async def handle_site_status(self, is_accessible: bool):
        """Handle downtime notifications"""
        now = time.time()
        
        if not is_accessible:
            if self.site_down_since is None:
                self.site_down_since = now
                self.consecutive_failures += 1
                
                if self.consecutive_failures >= (SITE_DOWN_GRACE_PERIOD / CHECK_INTERVAL):
                    if not self.site_down_notified:
                        await self.send_telegram_message(
                            f"🔴 <b>Website DOWN</b>\n"
                            f"⏰ Since: {self.get_indian_time()}\n"
                            f"📡 Monitoring continues..."
                        )
                        self.site_down_notified = True
            
            elif self.site_down_notified and (now - self.last_site_check_time) >= SITE_DOWN_CHECK_INTERVAL:
                down_duration = int((now - self.site_down_since) / 60)
                await self.send_telegram_message(
                    f"🔴 <b>Still DOWN</b>\n"
                    f"⏰ {down_duration} minutes and counting...\n"
                    f"🕐 {self.get_indian_time()}"
                )
                self.last_site_check_time = now
                
        else:
            if self.site_down_since is not None:
                down_duration = int((now - self.site_down_since) / 60)
                await self.send_telegram_message(
                    f"✅ <b>Website BACK ONLINE!</b>\n"
                    f"⏰ Was down: {down_duration} minutes\n"
                    f"🕐 {self.get_indian_time()}"
                )
                self.site_down_since = None
                self.site_down_notified = False
                self.consecutive_failures = 0
            else:
                self.consecutive_failures = 0

    async def run_monitor(self):
        """Main monitoring loop optimized for Railway"""
        # Send startup notification
        await self.send_telegram_message(
            f"🚀 <b>Monitor Started on Railway</b>\n"
            f"📝 Registration: {YOUR_REG_NO}\n"
            f"🎯 Subject: {TARGET_SUBJECT_CODE}\n"
            f"✅ Expected: {EXPECTED_MARK}\n"
            f"⏰ Started: {self.get_indian_time()}\n"
            f"🔄 Checks: Every {CHECK_INTERVAL}s"
        )
        
        while True:
            current_time = self.get_indian_time()
            self.log(f"Checking...")
            
            try:
                # Check site accessibility
                is_accessible = await self.check_website_accessibility()
                await self.handle_site_status(is_accessible)
                
                if not is_accessible:
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue
                
                # Check result
                result_info = await self.check_result_correction()
                
                if result_info["status"] == "error":
                    self.log(f"Check error: {result_info.get('error', 'Unknown')}")
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue
                
                if result_info["subject_found"]:
                    mark = result_info["mark"]
                    status = result_info["result_status"]
                    
                    self.log(f"Mark: {mark} | Status: {status}")
                    
                    if result_info["is_corrected"] and not self.correction_detected:
                        self.correction_detected = True
                        
                        await self.send_telegram_message(
                            f"🚨 <b>CORRECTION DETECTED!</b>\n"
                            f"✅ {TARGET_SUBJECT_CODE}: {mark}\n"
                            f"📊 Result: {status}\n"
                            f"🕐 {current_time}"
                        )
                        
                        screenshot = await self.take_screenshot()
                        if screenshot:
                            await self.send_screenshot_to_telegram(
                                screenshot,
                                f"📸 Proof: {mark}"
                            )
                    
                    elif result_info["is_corrected"]:
                        self.correction_verified_count += 1
                        
                        if self.correction_verified_count == 3:
                            await self.send_telegram_message(
                                f"✅ <b>CORRECTION CONFIRMED!</b>\n"
                                f"🎉 Your result is now correct!\n"
                                f"📚 {TARGET_SUBJECT_CODE}: {mark}\n"
                                f"🏆 Final: {status}\n"
                                f"⏰ {current_time}"
                            )
                    
                    elif result_info["has_na"] and self.correction_detected:
                        await self.send_telegram_message(
                            f"⚠️ <b>WARNING: Reverted to NA</b>\n"
                            f"{TARGET_SUBJECT_CODE} back to {CURRENT_WRONG_VALUE}\n"
                            f"🕐 {current_time}"
                        )
                        self.correction_detected = False
                        self.correction_verified_count = 0
                
            except Exception as e:
                self.log(f"Loop error: {str(e)[:100]}")
            
            await asyncio.sleep(CHECK_INTERVAL)

async def main():
    monitor = RailwayResultMonitor()
    await monitor.run_monitor()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Monitor stopped")
    except Exception as e:
        print(f"[!] Fatal: {e}")
