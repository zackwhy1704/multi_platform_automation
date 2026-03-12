"""
LinkedIn Celery tasks — Selenium-based browser automation.
Adapted from the original linkedin-automation-bot.
"""

import logging
import os
import time

from workers.celery_app import celery_app
from shared.database import BotDatabase
from shared.encryption import decrypt

logger = logging.getLogger(__name__)

db = BotDatabase()
MAX_LOGIN_ATTEMPTS = 3


def _notify(phone: str, msg: str):
    from workers.notification import send_whatsapp_notification
    send_whatsapp_notification.delay(phone, msg)


def _get_credentials(phone_number_id: str):
    creds = db.get_platform_credentials(phone_number_id, "linkedin")
    if not creds:
        raise ValueError(f"No LinkedIn credentials for user {phone_number_id}")
    return creds["email"], decrypt(creds["encrypted_password"])


def _create_bot(email: str, password: str):
    """Create a LinkedIn bot instance with Selenium."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    # Anti-detection
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })

    return driver


def _login(driver, email: str, password: str, phone: str) -> bool:
    """Login to LinkedIn with retry."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    for attempt in range(1, MAX_LOGIN_ATTEMPTS + 1):
        _notify(phone, f"Signing in to LinkedIn... (attempt {attempt}/{MAX_LOGIN_ATTEMPTS})")
        try:
            driver.get("https://www.linkedin.com/login")
            time.sleep(2)

            email_field = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "username"))
            )
            email_field.clear()
            for char in email:
                email_field.send_keys(char)
                time.sleep(0.05)

            pw_field = driver.find_element(By.ID, "password")
            pw_field.clear()
            for char in password:
                pw_field.send_keys(char)
                time.sleep(0.05)

            driver.find_element(By.XPATH, "//button[@type='submit']").click()
            time.sleep(5)

            if "feed" in driver.current_url or "mynetwork" in driver.current_url:
                return True

        except Exception as e:
            logger.error("Login attempt %d failed: %s", attempt, e)

        if attempt < MAX_LOGIN_ATTEMPTS:
            time.sleep(10)

    _notify(
        phone,
        "LinkedIn sign-in failed after 3 attempts.\n"
        "Check your credentials with *setup* or approve any security prompts in your browser.",
    )
    return False


@celery_app.task(bind=True, name="services.linkedin.tasks.post_task", max_retries=2)
def post_task(self, phone_number_id: str, content: str, media: str = None):
    """Post content to LinkedIn via Selenium."""
    driver = None
    try:
        email, password = _get_credentials(phone_number_id)
        driver = _create_bot(email, password)

        if not _login(driver, email, password, phone_number_id):
            return {"success": False, "error": "Login failed"}

        _notify(phone_number_id, "Signed in. Creating your LinkedIn post...")

        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        driver.get("https://www.linkedin.com/feed/")
        time.sleep(3)

        # Click "Start a post"
        start_post = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'share-box-feed-entry__trigger')]"))
        )
        start_post.click()
        time.sleep(2)

        # Type content
        editor = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//div[@role='textbox' and @contenteditable='true']"))
        )
        for char in content:
            editor.send_keys(char)
            time.sleep(0.02)

        time.sleep(1)

        # Click Post button
        post_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'share-actions__primary-action')]"))
        )
        post_btn.click()
        time.sleep(5)

        db.log_automation_action(phone_number_id, "linkedin", "post", 1, session_id=self.request.id)
        _notify(phone_number_id, f"LinkedIn post published!\n\n{content[:100]}...")

        return {"success": True, "task_id": self.request.id}

    except Exception as e:
        logger.error("LinkedIn post failed for %s: %s", phone_number_id, e)
        _notify(phone_number_id, f"LinkedIn post failed: {str(e)}")

        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        return {"success": False, "error": str(e)}

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


@celery_app.task(bind=True, name="services.linkedin.tasks.ai_post_task", max_retries=2)
def ai_post_task(self, phone_number_id: str):
    """Generate AI content and post to LinkedIn."""
    profile = db.get_user_profile(phone_number_id)
    if not profile:
        _notify(phone_number_id, "Profile not set up. Send *start* to set up your profile.")
        return {"success": False, "error": "No profile"}

    from services.ai.ai_service import generate_post
    content = generate_post("linkedin", profile)
    if not content:
        _notify(phone_number_id, "AI content generation failed. Please try again.")
        return {"success": False, "error": "AI generation failed"}

    _notify(phone_number_id, f"*AI-Generated Post:*\n\n{content}\n\nPublishing now...")
    return post_task(phone_number_id, content)


@celery_app.task(bind=True, name="services.linkedin.tasks.reply_task", max_retries=1)
def reply_task(self, phone_number_id: str, max_replies: int = 5):
    """Auto-reply to comments on LinkedIn posts."""
    driver = None
    try:
        email, password = _get_credentials(phone_number_id)
        driver = _create_bot(email, password)

        if not _login(driver, email, password, phone_number_id):
            return {"success": False, "error": "Login failed"}

        _notify(phone_number_id, "Signed in. Scanning for comments to reply to...")

        from selenium.webdriver.common.by import By
        import time

        driver.get("https://www.linkedin.com/notifications/")
        time.sleep(3)

        # Find notification cards related to comments
        notifications = driver.find_elements(By.XPATH, "//li[contains(@class, 'notification-card')]")
        replies_sent = 0

        for notif in notifications[:max_replies]:
            try:
                text_el = notif.find_element(By.XPATH, ".//p")
                notif_text = text_el.text.lower()

                if "commented" in notif_text or "replied" in notif_text:
                    notif.click()
                    time.sleep(3)

                    # Find comment box and reply
                    from services.ai.ai_service import generate_reply
                    profile = db.get_user_profile(phone_number_id)
                    tone = ", ".join(profile.get("tone", ["professional"])) if profile else "professional"

                    reply = generate_reply("linkedin", "", notif_text, tone)
                    if reply:
                        comment_box = driver.find_element(
                            By.XPATH, "//div[@role='textbox' and contains(@aria-label, 'comment')]"
                        )
                        for char in reply:
                            comment_box.send_keys(char)
                            time.sleep(0.03)

                        from selenium.webdriver.common.keys import Keys
                        comment_box.send_keys(Keys.CONTROL, Keys.ENTER)
                        time.sleep(2)
                        replies_sent += 1

                    driver.back()
                    time.sleep(2)

            except Exception as e:
                logger.warning("Error processing notification: %s", e)
                continue

        db.log_automation_action(phone_number_id, "linkedin", "comment", replies_sent, session_id=self.request.id)
        _notify(phone_number_id, f"LinkedIn reply engagement complete!\nReplied to {replies_sent} comments.")

        return {"success": True, "replies_sent": replies_sent}

    except Exception as e:
        logger.error("LinkedIn reply task failed for %s: %s", phone_number_id, e)
        _notify(phone_number_id, f"Reply engagement failed: {str(e)}")
        return {"success": False, "error": str(e)}

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
