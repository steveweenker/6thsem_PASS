import asyncio
import os
import time
import aiohttp
import pytz
import urllib.parse
from datetime import datetime
from typing import Optional
from playwright.async_api import async_playwright

# --- CONFIGURATION ---
# Only these come from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

# --- HARDCODED CONFIGURATION ---
# Your personal details - Change these in the code directly
YOUR_REG_NO = "22156148040"
TARGET_SUBJECT_CODE = "156606P"
TARGET_SUBJECT_NAME = "NPTEL Course-II Lab"
CURRENT_WRONG_VALUE = "NA"
EXPECTED_MARK = "68"

# Exam details - Hardcoded for 6th sem Nov 2025
EXAM_CONFIG = {
    "ordinal_sem": "6th",
    "roman_sem": "VI",
    "session": "2025",
    "held_month": "November",
    "held_year": "2025"
}

# --- MONITORING SETTINGS ---
CHECK_INTERVAL = 30  # Check every 30 seconds
SITE_DOWN_CHECK_INTERVAL = 3600  # Notify if site is down every 1 hour
SITE_DOWN_GRACE_PERIOD = 300  # Wait 5 minutes before declaring site down
MAX_RETRIES = 3  # Telegram retry attempts

class ResultCorrectionMonitor:
    def __init__(self):
        # State tracking
        self.site_down_since = None
        self.site_down_notified = False
        self.correction_found = False
        self.verified_count = 0
        self.consecutive_failures = 0
        self.last_site_check = time.time()
        
        # Timezone
        self.ist = pytz.timezone('Asia/Kolkata')
        
        # Browser optimization args
        self.browser_args = [
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--no-sandbox',
            '--single-process'
        ]
        
        # Log startup
        print("=" * 60)
        print("🚀 RESULT CORRECTION MONITOR - 6TH SEMESTER")
        print("=" * 60)
        print(f"📝 Registration: {YOUR_REG_NO}")
        print(f"🎯 Subject: {TARGET_SUBJECT_CODE} ({TARGET_SUBJECT_NAME})")
        print(f"❌ Current: {CURRENT_WRONG_VALUE} → ✅ Expected: {EXPECTED_MARK}")
        print(f"⏰ Check Interval: Every {CHECK_INTERVAL} seconds")
        print(f"🌐 Monitoring: https://beu-bih.ac.in")
        print(f"🕐 Started: {self.get_time()}")
        print("=" * 60)

    def get_time(self) -> str:
        """Get current IST time"""
        return datetime.now(self.ist).strftime("%d-%m-%Y %I:%M:%S %p IST")

    def build_url(self, reg_no: str) -> str:
        """Build result URL for 6th sem Nov 2025"""
        params = {
            'name': 'B.Tech. 6th Semester Examination, 2025',
            'semester': 'VI',
            'session': '2025',
            'regNo': reg_no,
            'exam_held': 'November/2025'
        }
        return f"https://beu-bih.ac.in/result-three?{urllib.parse.urlencode(params)}"

    async def send_telegram(self, text: str) -> bool:
        """Send message to Telegram"""
        if not BOT_TOKEN or not CHAT_ID:
            print("❌ Telegram credentials missing!")
            return False
        
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
        
        for attempt in range(MAX_RETRIES):
            try:
                timeout = aiohttp.ClientTimeout(total=20)
                async with aiohttp.ClientSession(timeout=timeout) as s:
                    async with s.post(url, json=data) as r:
                        if r.status == 200:
                            return True
            except:
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(1)
        
        print("❌ Failed to send Telegram message")
        return False

    async def check_site_access(self) -> bool:
        """Quick HTTP check"""
        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.get(self.build_url(YOUR_REG_NO)) as r:
                    return r.status == 200
        except:
            return False

    async def check_result(self) -> dict:
        """Check result page for correction"""
        url = self.build_url(YOUR_REG_NO)
        
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
                
                await page.goto(url, timeout=35000)
                
                # Verify page loaded
                try:
                    await page.wait_for_selector(f"text={YOUR_REG_NO}", timeout=12000)
                except:
                    result["error"] = "Registration not found"
                    await browser.close()
                    return result
                
                # Get page content
                content = await page.content()
                
                # Check result status
                if "RESULT : PASS" in content:
                    result["status"] = "PASS"
                elif "RESULT : FAIL" in content:
                    result["status"] = "FAIL"
                
                # Find subject
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
                result["error"] = str(e)[:150]
        
        return result

    async def capture_screenshot(self) -> Optional[bytes]:
        """Take full page screenshot"""
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True, args=self.browser_args)
                page = await browser.new_page()
                
                await page.goto(self.build_url(YOUR_REG_NO), timeout=35000)
                await page.wait_for_selector("table", timeout=10000)
                
                screenshot = await page.screenshot(full_page=True)
                await browser.close()
                return screenshot
                
            except:
                return None

    async def send_screenshot(self, image_bytes: bytes, caption: str) -> bool:
        """Send screenshot to Telegram"""
        try:
            form = aiohttp.FormData()
            form.add_field('chat_id', CHAT_ID)
            form.add_field('photo', image_bytes, filename='proof.png')
            form.add_field('caption', caption)
            form.add_field('parse_mode', 'HTML')
            
            timeout = aiohttp.ClientTimeout(total=45)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
                async with s.post(url, data=form) as r:
                    return r.status == 200
        except:
            return False

    async def handle_downtime(self, is_up: bool):
        """Manage site up/down notifications"""
        now = time.time()
        
        if not is_up:
            if not self.site_down_since:
                self.site_down_since = now
                self.consecutive_failures += 1
                
                if self.consecutive_failures >= (SITE_DOWN_GRACE_PERIOD / CHECK_INTERVAL):
                    if not self.site_down_notified:
                        await self.send_telegram(
                            f"🔴 <b>BEU Website DOWN</b>\n"
                            f"⏰ Since: {self.get_time()}\n"
                            f"📡 Will notify when back online."
                        )
                        self.site_down_notified = True
            
            elif self.site_down_notified and (now - self.last_site_check) >= SITE_DOWN_CHECK_INTERVAL:
                minutes = int((now - self.site_down_since) / 60)
                await self.send_telegram(
                    f"🔴 <b>Still DOWN</b> ({minutes}m)\n"
                    f"🕐 {self.get_time()}"
                )
                self.last_site_check = now
                
        else:
            if self.site_down_since:
                minutes = int((now - self.site_down_since) / 60)
                await self.send_telegram(
                    f"✅ <b>Website BACK ONLINE!</b>\n"
                    f"⏰ Was down: {minutes} minutes\n"
                    f"🕐 {self.get_time()}"
                )
                self.site_down_since = None
                self.site_down_notified = False
                self.consecutive_failures = 0
            else:
                self.consecutive_failures = 0

    async def monitor(self):
        """Main monitoring loop"""
        # Send startup notification
        if BOT_TOKEN and CHAT_ID:
            await self.send_telegram(
                f"🚀 <b>6th Sem Result Monitor Started</b>\n"
                f"📝 Registration: {YOUR_REG_NO}\n"
                f"🎯 Monitoring: {TARGET_SUBJECT_CODE}\n"
                f"✅ Expected: {EXPECTED_MARK} marks\n"
                f"⏰ Started: {self.get_time()}\n"
                f"🔄 Checking every {CHECK_INTERVAL} seconds\n\n"
                f"<i>Will notify when correction is made...</i>"
            )
        
        print(f"[*] Starting 24/7 monitoring...")
        
        while True:
            current_time = self.get_time()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking...")
            
            try:
                # Check site access
                site_up = await self.check_site_access()
                await self.handle_downtime(site_up)
                
                if not site_up:
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue
                
                # Check result
                result = await self.check_result()
                
                if not result["success"]:
                    print(f"[!] Check failed: {result.get('error', 'Unknown')}")
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue
                
                mark = result["mark"]
                status = result["status"]
                
                print(f"[*] Found: {mark} | Status: {status}")
                
                if mark == EXPECTED_MARK or (mark.isdigit() and mark != CURRENT_WRONG_VALUE):
                    # Correction detected!
                    if not self.correction_found:
                        self.correction_found = True
                        
                        await self.send_telegram(
                            f"🚨 <b>RESULT CORRECTED!</b>\n\n"
                            f"✅ {TARGET_SUBJECT_CODE}: {mark} marks\n"
                            f"📊 Result: {status}\n"
                            f"🕐 Detected: {current_time}\n\n"
                            f"<i>Verifying...</i>"
                        )
                        
                        # Send proof
                        screenshot = await self.capture_screenshot()
                        if screenshot:
                            await self.send_screenshot(
                                screenshot,
                                f"📸 Proof: {TARGET_SUBJECT_CODE} = {mark}"
                            )
                    
                    self.verified_count += 1
                    
                    # Confirm after 3 successful checks
                    if self.verified_count == 3:
                        await self.send_telegram(
                            f"✅ <b>CORRECTION CONFIRMED!</b>\n\n"
                            f"🎉 Your 6th sem result is now correct!\n"
                            f"📚 {TARGET_SUBJECT_NAME}: {mark} marks\n"
                            f"🏆 Final Status: {status}\n"
                            f"⏰ Confirmed: {current_time}\n\n"
                            f"<b>You can now use your result card!</b>"
                        )
                
                elif mark == CURRENT_WRONG_VALUE and self.correction_found:
                    # Reverted back to NA
                    await self.send_telegram(
                        f"⚠️ <b>WARNING: Reverted to NA</b>\n"
                        f"{TARGET_SUBJECT_CODE} shows NA again\n"
                        f"🕐 {current_time}"
                    )
                    self.correction_found = False
                    self.verified_count = 0
                
                elif mark != CURRENT_WRONG_VALUE and mark != EXPECTED_MARK and not self.correction_found:
                    # Different value detected
                    await self.send_telegram(
                        f"ℹ️ <b>Change Detected</b>\n"
                        f"{TARGET_SUBJECT_CODE}: {mark}\n"
                        f"(Expected: {EXPECTED_MARK})\n"
                        f"🕐 {current_time}"
                    )
                    self.correction_found = True
            
            except Exception as e:
                print(f"[!] Error: {str(e)[:100]}")
            
            # Wait for next check
            await asyncio.sleep(CHECK_INTERVAL)


# --- MAIN EXECUTION ---
async def main():
    # Check credentials
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ ERROR: Telegram credentials not set!")
        print("Set environment variables:")
        print("  BOT_TOKEN=your_telegram_bot_token")
        print("  CHAT_ID=your_telegram_chat_id")
        print("\nOr edit the code to add them directly.")
        return
    
    monitor = ResultCorrectionMonitor()
    await monitor.monitor()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Monitor stopped by user")
    except Exception as e:
        print(f"[!] Fatal error: {e}")
