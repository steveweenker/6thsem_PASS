#!/usr/bin/env python3
"""
BEU Result Correction Monitor - 6th Semester
Monitors for correction of NPTEL Course-II Lab ESE marks
Deploy on Railway for 24/7 monitoring
"""

import asyncio
import os
import sys
import time
import aiohttp
import pytz
from datetime import datetime
from typing import Optional, Dict
from playwright.async_api import async_playwright

# ==================== CONFIGURATION ====================
# Get from Railway Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

# Validate credentials
if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN environment variable is not set!")
    print("Set it in Railway dashboard: BOT_TOKEN=your_bot_token_here")
    sys.exit(1)

if not CHAT_ID:
    print("❌ ERROR: CHAT_ID environment variable is not set!")
    print("Set it in Railway dashboard: CHAT_ID=your_chat_id_here")
    sys.exit(1)

# ==================== PERSONAL DETAILS ====================
# Your personal information - Edit these as needed
YOUR_REG_NO = "22156148040"                     # Your registration number
TARGET_SUBJECT_CODE = "156606P"                 # NPTEL Course-II Lab ESE
TARGET_SUBJECT_NAME = "NPTEL Course-II Lab" # Full subject name
CURRENT_WRONG_VALUE = "NA"                      # Currently shows "NA"
EXPECTED_MARK = "68"                            # Your actual score

# Exam details - Hardcoded for 6th semester Nov 2025
EXAM_DETAILS = {
    "name": "B.Tech. 6th Semester Examination, 2025",
    "semester": "VI",
    "session": "2025",
    "held": "November/2025"
}

# ==================== MONITORING SETTINGS ====================
CHECK_INTERVAL = 30                     # Check every 30 seconds
SITE_DOWN_GRACE = 300                   # 5 minutes before declaring site down
SITE_DOWN_REMINDER = 3600               # Remind every 1 hour if still down
MAX_TELEGRAM_RETRIES = 3                # Telegram retry attempts
BROWSER_TIMEOUT = 35000                 # Browser timeout in ms (35 seconds)

# ==================== LOGGING ====================
def log(message: str, level: str = "INFO"):
    """Simple logging function"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")

# ==================== MONITOR CLASS ====================
class BEUResultMonitor:
    """Main monitor class for BEU result correction"""
    
    def __init__(self):
        # State tracking
        self.site_down_since = None
        self.site_down_notified = False
        self.correction_detected = False
        self.verification_count = 0
        self.consecutive_failures = 0
        self.total_checks = 0
        
        # Timezone for Indian Standard Time
        self.ist_timezone = pytz.timezone('Asia/Kolkata')
        
        # Browser configuration for Railway
        self.browser_args = [
            '--disable-dev-shm-usage',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-gpu',
            '--disable-software-rasterizer',
            '--disable-background-timer-throttling'
        ]
        
        # Display startup banner
        self._print_startup_banner()
    
    def _print_startup_banner(self):
        """Display startup information"""
        print("=" * 70)
        print("🚀 BEU 6TH SEMESTER RESULT CORRECTION MONITOR")
        print("=" * 70)
        print(f"📝 Registration Number: {YOUR_REG_NO}")
        print(f"🎯 Target Subject: {TARGET_SUBJECT_CODE} - {TARGET_SUBJECT_NAME}")
        print(f"❌ Current Value: {CURRENT_WRONG_VALUE}")
        print(f"✅ Expected Marks: {EXPECTED_MARK}")
        print(f"⏰  Monitoring Interval: Every {CHECK_INTERVAL} seconds")
        print(f"🔔  Telegram Notifications: ✅ Active")
        print(f"🌐  Website: https://beu-bih.ac.in")
        print(f"🕐  Start Time: {self._get_indian_time()}")
        print(f"🏢  Platform: Railway (24/7 Deployment)")
        print("=" * 70)
        log("Monitor initialized successfully")
    
    def _get_indian_time(self) -> str:
        """Get current Indian Standard Time"""
        utc_now = datetime.now(pytz.utc)
        ist_now = utc_now.astimezone(self.ist_timezone)
        return ist_now.strftime("%d-%m-%Y %I:%M:%S %p IST")
    
    def _build_result_url(self) -> str:
        """Build the BEU result URL for your registration"""
        # URL encode the parameters
        params = {
            'name': EXAM_DETAILS['name'],
            'semester': EXAM_DETAILS['semester'],
            'session': EXAM_DETAILS['session'],
            'regNo': YOUR_REG_NO,
            'exam_held': EXAM_DETAILS['held']
        }
        
        # Simple URL encoding
        encoded_params = []
        for key, value in params.items():
            encoded_value = str(value).replace(' ', '%20').replace(',', '%2C').replace('/', '%2F')
            encoded_params.append(f"{key}={encoded_value}")
        
        query_string = '&'.join(encoded_params)
        return f"https://beu-bih.ac.in/result-three?{query_string}"
    
    async def _send_telegram_message(self, message: str) -> bool:
        """Send message to Telegram with retry logic"""
        if not BOT_TOKEN or not CHAT_ID:
            log("Telegram credentials not available", "ERROR")
            return False
        
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        
        for attempt in range(MAX_TELEGRAM_RETRIES):
            try:
                timeout = aiohttp.ClientTimeout(total=20)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, json=payload) as response:
                        if response.status == 200:
                            return True
                        else:
                            log(f"Telegram API error: HTTP {response.status}", "WARNING")
            except Exception as e:
                log(f"Telegram attempt {attempt + 1} failed: {str(e)[:50]}", "WARNING")
                if attempt < MAX_TELEGRAM_RETRIES - 1:
                    await asyncio.sleep(1)  # Wait before retry
        
        log("All Telegram send attempts failed", "ERROR")
        return False
    
    async def _check_website_availability(self) -> bool:
        """Quick HTTP check to see if website is accessible"""
        try:
            url = self._build_result_url()
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    return response.status == 200
        except Exception as e:
            log(f"Website check failed: {str(e)[:50]}", "DEBUG")
            return False
    
    async def _fetch_result_page(self) -> Dict:
        """
        Fetch and parse the result page using Playwright
        Returns dictionary with result information
        """
        result = {
            "success": False,
            "mark": None,
            "result_status": None,
            "error": None,
            "page_loaded": False
        }
        
        url = self._build_result_url()
        
        async with async_playwright() as p:
            try:
                # Launch browser with Railway-optimized settings
                browser = await p.chromium.launch(
                    headless=True,
                    args=self.browser_args,
                    timeout=BROWSER_TIMEOUT
                )
                
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                
                page = await context.new_page()
                
                # Navigate to result page
                log(f"Fetching result page: {YOUR_REG_NO}", "DEBUG")
                await page.goto(url, timeout=BROWSER_TIMEOUT, wait_until="domcontentloaded")
                
                # Check if registration number appears on page
                try:
                    await page.wait_for_selector(f"text={YOUR_REG_NO}", timeout=15000)
                    result["page_loaded"] = True
                except:
                    result["error"] = "Registration number not found on page"
                    await browser.close()
                    return result
                
                # Get page content to check overall result status
                page_content = await page.content()
                
                # Check for PASS/FAIL status
                if "RESULT : PASS" in page_content.upper():
                    result["result_status"] = "PASS"
                elif "RESULT : FAIL" in page_content.upper():
                    result["result_status"] = "FAIL"
                else:
                    result["result_status"] = "UNKNOWN"
                
                # Look for the specific subject row
                rows = await page.query_selector_all("table tr")
                
                for row in rows:
                    row_text = await row.text_content()
                    
                    # Check if this row contains our target subject
                    if TARGET_SUBJECT_CODE in row_text or TARGET_SUBJECT_NAME in row_text:
                        # Found the subject row
                        cells = await row.query_selector_all("td")
                        
                        if len(cells) >= 4:  # Assuming marks are in 4th column
                            mark_text = await cells[3].text_content()
                            mark_text = mark_text.strip()
                            result["mark"] = mark_text
                            result["success"] = True
                        
                        break  # Stop searching after finding the subject
                
                # Close browser
                await browser.close()
                
                if not result["success"]:
                    result["error"] = f"Subject {TARGET_SUBJECT_CODE} not found in result table"
                
            except Exception as e:
                error_msg = str(e)
                result["error"] = error_msg[:150]  # Truncate long errors
                log(f"Browser error: {error_msg[:100]}", "ERROR")
        
        return result
    
    async def _capture_screenshot(self) -> Optional[bytes]:
        """Capture full-page screenshot for proof"""
        url = self._build_result_url()
        
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(
                    headless=True,
                    args=self.browser_args
                )
                
                page = await browser.new_page()
                
                # Navigate and wait for page to load
                await page.goto(url, timeout=BROWSER_TIMEOUT)
                await page.wait_for_selector("table", timeout=10000)
                
                # Take full-page screenshot
                screenshot = await page.screenshot(full_page=True, type='png')
                
                await browser.close()
                return screenshot
                
            except Exception as e:
                log(f"Screenshot capture failed: {str(e)[:50]}", "WARNING")
                return None
    
    async def _send_screenshot(self, screenshot_data: bytes, caption: str) -> bool:
        """Send screenshot to Telegram"""
        try:
            form_data = aiohttp.FormData()
            form_data.add_field('chat_id', CHAT_ID)
            form_data.add_field('photo', screenshot_data, filename='result_proof.png')
            form_data.add_field('caption', caption)
            form_data.add_field('parse_mode', 'HTML')
            
            timeout = aiohttp.ClientTimeout(total=45)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
                async with session.post(url, data=form_data) as response:
                    return response.status == 200
                    
        except Exception as e:
            log(f"Screenshot send failed: {str(e)[:50]}", "WARNING")
            return False
    
    async def _handle_website_status(self, is_accessible: bool):
        """Handle website up/down status and send notifications"""
        current_time = time.time()
        
        if not is_accessible:
            # Website is down
            if not self.site_down_since:
                self.site_down_since = current_time
                self.consecutive_failures += 1
                
                # Wait for grace period before notifying
                if self.consecutive_failures >= (SITE_DOWN_GRACE / CHECK_INTERVAL):
                    if not self.site_down_notified:
                        log("Website is DOWN - sending notification", "WARNING")
                        await self._send_telegram_message(
                            f"🔴 <b>BEU Website is DOWN</b>\n\n"
                            f"⏰ Since: {self._get_indian_time()}\n"
                            f"📡 Last check failed\n\n"
                            f"<i>Will notify when it's back online...</i>"
                        )
                        self.site_down_notified = True
            
            # Send reminder if still down after specified interval
            elif (self.site_down_notified and 
                  (current_time - self.site_down_since) >= SITE_DOWN_REMINDER):
                
                down_minutes = int((current_time - self.site_down_since) / 60)
                log(f"Website still down for {down_minutes} minutes", "WARNING")
                
                await self._send_telegram_message(
                    f"🔴 <b>Website STILL DOWN</b>\n\n"
                    f"⏰ Down for: {down_minutes} minutes\n"
                    f"🕐 Last check: {self._get_indian_time()}\n\n"
                    f"<i>Continuing to monitor...</i>"
                )
                
        else:
            # Website is accessible
            if self.site_down_since is not None:
                # Website just came back online
                down_duration = int((current_time - self.site_down_since) / 60)
                
                log(f"Website is BACK ONLINE after {down_duration} minutes", "INFO")
                
                await self._send_telegram_message(
                    f"✅ <b>BEU Website is BACK ONLINE!</b>\n\n"
                    f"⏰ Was down for: {down_duration} minutes\n"
                    f"🕐 Back online at: {self._get_indian_time()}\n\n"
                    f"<i>Resuming result correction monitoring...</i>"
                )
                
                # Reset down status
                self.site_down_since = None
                self.site_down_notified = False
                self.consecutive_failures = 0
            else:
                self.consecutive_failures = 0
    
    async def _process_result(self, result_data: Dict):
        """Process the fetched result and check for corrections"""
        if not result_data["success"]:
            log(f"Result fetch failed: {result_data.get('error', 'Unknown error')}", "ERROR")
            return
        
        current_mark = result_data["mark"]
        result_status = result_data["result_status"]
        
        log(f"Subject found - Mark: '{current_mark}', Result: {result_status}", "INFO")
        
        # Check if correction has been made
        is_corrected = False
        
        if current_mark == EXPECTED_MARK:
            # Exact match with expected marks
            is_corrected = True
            log(f"✅ Exact match found: {current_mark} = {EXPECTED_MARK}", "SUCCESS")
            
        elif current_mark.isdigit() and current_mark != CURRENT_WRONG_VALUE:
            # Any numeric value that's not "NA"
            is_corrected = True
            log(f"✅ Numeric value found: {current_mark} (was {CURRENT_WRONG_VALUE})", "SUCCESS")
        
        if is_corrected:
            # Correction detected!
            if not self.correction_detected:
                self.correction_detected = True
                self.verification_count = 1
                
                log("🚨 CORRECTION DETECTED! Sending notification...", "SUCCESS")
                
                # Send immediate notification
                await self._send_telegram_message(
                    f"🚨 <b>RESULT CORRECTION DETECTED!</b>\n\n"
                    f"✅ <b>Subject:</b> {TARGET_SUBJECT_CODE}\n"
                    f"📊 <b>New Mark:</b> {current_mark}\n"
                    f"📝 <b>Result Status:</b> {result_status}\n"
                    f"🕐 <b>Detected at:</b> {self._get_indian_time()}\n\n"
                    f"<i>Verifying correction...</i>"
                )
                
                # Capture and send screenshot as proof
                screenshot = await self._capture_screenshot()
                if screenshot:
                    log("Sending screenshot as proof...", "INFO")
                    await self._send_screenshot(
                        screenshot,
                        f"📸 <b>Verification Proof</b>\n"
                        f"{TARGET_SUBJECT_CODE}: {current_mark} marks\n"
                        f"Detected: {self._get_indian_time()}"
                    )
                else:
                    log("Could not capture screenshot", "WARNING")
            
            else:
                # Already detected, increment verification count
                self.verification_count += 1
                log(f"Correction verified {self.verification_count}/3 times", "INFO")
                
                # Send confirmation after 3 verifications
                if self.verification_count == 3:
                    log("✅ CORRECTION CONFIRMED! Sending final confirmation...", "SUCCESS")
                    
                    await self._send_telegram_message(
                        f"✅ <b>CORRECTION CONFIRMED!</b>\n\n"
                        f"🎉 <b>Your result has been officially corrected!</b>\n"
                        f"📚 <b>Subject:</b> {TARGET_SUBJECT_NAME}\n"
                        f"📈 <b>Marks:</b> {current_mark} (was {CURRENT_WRONG_VALUE})\n"
                        f"🏆 <b>Final Result:</b> {result_status}\n"
                        f"⏰ <b>Confirmed at:</b> {self._get_indian_time()}\n\n"
                        f"<b>You can now use your 6th semester result card for applications!</b>"
                    )
        
        elif current_mark == CURRENT_WRONG_VALUE:
            # Still shows "NA" - not corrected yet
            if self.correction_detected:
                # Was corrected before but reverted to NA
                log(f"⚠️ Correction reverted! Back to {CURRENT_WRONG_VALUE}", "WARNING")
                
                await self._send_telegram_message(
                    f"⚠️ <b>CORRECTION REVERTED!</b>\n\n"
                    f"Subject {TARGET_SUBJECT_CODE} shows '{CURRENT_WRONG_VALUE}' again\n"
                    f"This might be temporary. Continuing to monitor...\n"
                    f"🕐 {self._get_indian_time()}"
                )
                
                self.correction_detected = False
                self.verification_count = 0
            
            else:
                # Still waiting for correction
                if self.total_checks % 20 == 0:  # Log every 20 checks
                    log(f"Still waiting... Current: {CURRENT_WRONG_VALUE}, Expected: {EXPECTED_MARK}", "INFO")
        
        else:
            # Different value (not NA, not expected)
            if not self.correction_detected:
                log(f"ℹ️ Different value detected: {current_mark}", "INFO")
                
                await self._send_telegram_message(
                    f"ℹ️ <b>Update Detected</b>\n\n"
                    f"Subject {TARGET_SUBJECT_CODE} now shows: {current_mark}\n"
                    f"(Expected: {EXPECTED_MARK}, Was: {CURRENT_WRONG_VALUE})\n"
                    f"Result Status: {result_status}\n"
                    f"🕐 {self._get_indian_time()}"
                )
                
                self.correction_detected = True
    
    async def run_monitor(self):
        """Main monitoring loop - runs 24/7"""
        # Send startup notification
        log("Sending startup notification to Telegram...", "INFO")
        
        await self._send_telegram_message(
            f"🚀 <b>BEU Result Correction Monitor Started</b>\n\n"
            f"📝 <b>Registration:</b> {YOUR_REG_NO}\n"
            f"🎯 <b>Monitoring:</b> {TARGET_SUBJECT_CODE} - {TARGET_SUBJECT_NAME}\n"
            f"❌ <b>Current:</b> {CURRENT_WRONG_VALUE}\n"
            f"✅ <b>Expected:</b> {EXPECTED_MARK} marks\n"
            f"⏰ <b>Start Time:</b> {self._get_indian_time()}\n"
            f"🔄 <b>Check Interval:</b> Every {CHECK_INTERVAL} seconds\n"
            f"🌙 <b>Monitoring:</b> 24/7 (No breaks)\n\n"
            f"<i>Will notify instantly when correction is detected...</i>"
        )
        
        log("Starting 24/7 monitoring loop...", "INFO")
        
        while True:
            try:
                self.total_checks += 1
                current_time_str = datetime.now().strftime("%H:%M:%S")
                
                log(f"Check #{self.total_checks} at {current_time_str}", "DEBUG")
                
                # 1. Check website availability
                is_accessible = await self._check_website_availability()
                await self._handle_website_status(is_accessible)
                
                if not is_accessible:
                    log("Website not accessible, skipping result check", "WARNING")
                    await asyncio.sleep(CHECK_INTERVAL)
                    continue
                
                # 2. Fetch and check result
                log("Website accessible, fetching result...", "DEBUG")
                result_data = await self._fetch_result_page()
                
                # 3. Process the result
                await self._process_result(result_data)
                
                # 4. Periodic status log (every 10 checks)
                if self.total_checks % 10 == 0:
                    status = "CORRECTED ✅" if self.correction_detected else "PENDING 🔄"
                    log(f"Status check: {status} | Total checks: {self.total_checks}", "INFO")
                
            except Exception as e:
                log(f"Unexpected error in monitoring loop: {str(e)}", "ERROR")
                # Don't crash on errors, just log and continue
            
            # Wait for next check
            log(f"Waiting {CHECK_INTERVAL} seconds for next check...", "DEBUG")
            await asyncio.sleep(CHECK_INTERVAL)

# ==================== MAIN EXECUTION ====================
async def main():
    """Main entry point"""
    try:
        monitor = BEUResultMonitor()
        await monitor.run_monitor()
        
    except KeyboardInterrupt:
        log("Monitor stopped by user (Ctrl+C)", "INFO")
        print("\n👋 Monitor stopped gracefully")
        
    except Exception as e:
        log(f"FATAL ERROR: {str(e)}", "ERROR")
        print(f"\n💥 Critical error occurred. Monitor stopped.")
        print(f"Error details: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Set UTF-8 encoding for console
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    
    print("\n" + "="*70)
    print("BEU 6th Semester Result Correction Monitor")
    print("Deployed on Railway - 24/7 Monitoring")
    print("="*70 + "\n")
    
    # Run the monitor
    asyncio.run(main())
