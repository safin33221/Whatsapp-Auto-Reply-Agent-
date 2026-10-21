import os
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    WebDriverException,
)

# ==================================================
# 1. Environment and AI configuration
# ==================================================

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")

if not api_key:
    raise ValueError(
        "OPENROUTER_API_KEY পাওয়া যায়নি। .env ফাইল পরীক্ষা করো।"
    )

llm = ChatOpenAI(
    model="openrouter/free",
    api_key=api_key,
    base_url="https://openrouter.ai/api/v1",
    temperature=0.3,
    timeout=30,
    max_retries=1,
)


def generate_busy_reply(incoming_msg: str) -> str:
    """Incoming message-এর ভাষায় সংক্ষিপ্ত busy reply তৈরি করে।"""
    messages = [
        SystemMessage(
            content=(
                "You are a personal WhatsApp auto-reply assistant. "
                "The account owner is busy and will reply later. "
                "Write one short, polite, natural reply. "
                "Use the same language and script as the incoming message: "
                "Bangla, English, or Banglish. "
                "Do not answer the sender's question on the owner's behalf. "
                "Do not invent facts, promises, or a specific return time. "
                "Return only the message text without quotes."
            )
        ),
        HumanMessage(content=incoming_msg),
    ]

    try:
        response = llm.invoke(messages)
        reply = response.content
        if isinstance(reply, str) and reply.strip():
            return reply.strip().strip('"').strip("'")
    except Exception as e:
        print(f"⚠️ AI API call failed ({e}). Using fallback reply.")

    # Smart fallback based on script
    has_bengali = any("\u0980" <= char <= "\u09FF" for char in incoming_msg)
    if has_bengali:
        return "আমি এই মুহূর্তে একটু ব্যস্ত আছি, ফ্রি হয়ে দ্রুতই যোগাযোগ করছি।"
    return "I am currently a bit busy, will get back to you shortly."


# ==================================================
# 2. Chrome and WhatsApp Web
# ==================================================

PROFILE_DIR = str(
    Path("./whatsapp_user_data").resolve()
)

options = uc.ChromeOptions()
options.user_data_dir = PROFILE_DIR

driver = None


def start_whatsapp():
    global driver

    print("📱 Undetected Chrome ব্রাউজার চালু হচ্ছে...")

    driver = uc.Chrome(
        options=options,
        version_main=155,
        use_subprocess=True,
    )

    driver.get("https://web.whatsapp.com")

    print("🌐 WhatsApp Web খোলা হয়েছে।")
    print("👉 নিশ্চিত করো যে তুমি WhatsApp Web-এ লগইন করা আছো।")
    print("⏳ সাইডবার লোড হওয়ার জন্য অপেক্ষা করা হচ্ছে...")

    try:
        WebDriverWait(driver, 120).until(
            lambda d: d.find_elements(By.ID, "pane-side")
        )
        print("✅ WhatsApp Web সফলভাবে লোড হয়েছে!\n")
        return True

    except TimeoutException:
        print(
            "❌ ১২০ সেকেন্ডের মধ্যে সাইডবার পাওয়া যায়নি। "
            "ইন্টারনেট কানেকশন ও লগইন স্ট্যাটাস চেক করো।"
        )
        return False


# ==================================================
# 3. Sidebar: Find & Open unread chats
# ==================================================

JS_OPEN_CHAT = """
    const el = arguments[0];
    if (!el) return false;

    // Target the inner title or badge or row itself
    const titleSpan = el.querySelector('span[title]') || el;
    const badge = el.querySelector('[data-testid*="unread"], span[aria-label*="unread"], span[aria-label*="অপঠিত"]');

    const targets = [titleSpan, badge, el].filter(Boolean);
    for (const t of targets) {
        try {
            t.scrollIntoView({ block: 'center' });
            const opts = { bubbles: true, cancelable: true, view: window, buttons: 1 };
            t.dispatchEvent(new MouseEvent('mousedown', opts));
            t.dispatchEvent(new MouseEvent('mouseup', opts));
            t.dispatchEvent(new MouseEvent('click', opts));
            if (typeof t.click === 'function') {
                t.click();
            }
        } catch(e) {}
    }
    return true;
"""


def find_unread_chat(current_active_title: str = ""):
    """
    Searches the WhatsApp sidebar for unread chat badges.
    Returns (chat_row_element, contact_name).
    """
    if driver is None:
        return None, ""

    badge_selectors = [
        "//*[@id='pane-side']//span[contains(@aria-label, 'unread') or contains(@aria-label, 'Unread')]",
        "//*[@id='pane-side']//span[contains(@aria-label, 'অপঠিত')]",
        "//*[@id='pane-side']//*[@data-testid='icon-unread-count']",
        "//*[@id='pane-side']//*[@data-testid='unread-count']",
    ]

    unread_badges = []
    for selector in badge_selectors:
        try:
            elements = driver.find_elements(By.XPATH, selector)
            for el in elements:
                if el.is_displayed() and el not in unread_badges:
                    unread_badges.append(el)
        except Exception:
            continue

    if not unread_badges:
        return None, ""

    # Map unread badges to their parent chat row
    for badge in unread_badges:
        try:
            row_candidates = badge.find_elements(
                By.XPATH,
                "./ancestor::*[@role='row' or @role='listitem' or @role='gridcell' or @data-testid='cell-frame-container'][1]",
            )

            row = None
            if row_candidates and row_candidates[0].is_displayed():
                row = row_candidates[0]
            else:
                parent = badge.find_element(By.XPATH, "./ancestor::div[contains(@tabindex, '-1') or @role][1]")
                if parent and parent.is_displayed():
                    row = parent

            if row:
                # Extract actual contact name from row
                contact_name = ""
                name_spans = row.find_elements(By.XPATH, ".//span[@title]")
                if name_spans:
                    contact_name = name_spans[0].get_attribute("title") or ""

                if not contact_name:
                    aria = row.get_attribute("aria-label") or ""
                    contact_name = aria.split(",")[0].strip() if aria else ""

                # Don't switch if this chat is already open in #main
                if current_active_title and contact_name and contact_name.lower() == current_active_title.lower():
                    continue

                return row, contact_name

        except (StaleElementReferenceException, Exception):
            continue

    return None, ""


def switch_to_chat(row_element, contact_name: str, current_active_title: str) -> bool:
    """Uses mouse pointer events to reliably open a chat and waits for #main to switch."""
    if driver is None or row_element is None:
        return False

    try:
        # Trigger full JavaScript click sequence
        driver.execute_script(JS_OPEN_CHAT, row_element)

        # Wait up to 4 seconds for #main to switch title
        for _ in range(8):
            time.sleep(0.5)
            info = get_latest_chat_info()
            if info.get("ok"):
                new_title = info.get("title", "")
                if new_title and new_title.lower() != current_active_title.lower():
                    print(f"✅ Successfully switched chat to [{new_title}]!")
                    return True
                if contact_name and contact_name.lower() in new_title.lower():
                    print(f"✅ Successfully switched chat to [{new_title}]!")
                    return True

    except Exception as error:
        print(f"⚠️ Error while switching chat: {error}")

    return False


# ==================================================
# 4. JavaScript Engine: Read Active Chat Info (#main)
# ==================================================

JS_GET_CHAT_INFO = """
    const main = document.getElementById('main');
    if (!main) return { ok: false, reason: 'no_main' };

    // 1. Get Contact / Chat Title
    let title = '';
    const titleEl = main.querySelector('header span[title]') || 
                    main.querySelector('header [dir="auto"]');
    if (titleEl) {
        title = titleEl.getAttribute('title') || titleEl.innerText || '';
    }
    if (!title) title = 'Active Chat';

    // 2. Find Message Elements inside #main
    // In WhatsApp Web, message bubbles have class 'message-in' or 'message-out'
    let bubbles = Array.from(main.querySelectorAll('div.message-in, div.message-out'));

    if (bubbles.length === 0) {
        // Fallback for custom container updates
        bubbles = Array.from(main.querySelectorAll('[data-testid="msg-container"]'));
    }

    if (bubbles.length === 0) {
        return { ok: false, reason: 'no_messages', title: title };
    }

    // 3. Get the absolute last message bubble
    const lastBubble = bubbles[bubbles.length - 1];
    const cls = (lastBubble.className || '').toLowerCase();
    const dataId = lastBubble.getAttribute('data-id') || '';

    // ==========================================
    // Determine Outgoing vs Incoming
    // ==========================================
    let isOutgoing = false;
    let isIncoming = false;

    if (cls.includes('message-out') || !!lastBubble.closest('.message-out')) {
        isOutgoing = true;
    } else if (cls.includes('message-in') || !!lastBubble.closest('.message-in')) {
        isIncoming = true;
    } else {
        // Spatial fallback: outgoing messages are aligned right, incoming left
        const rect = lastBubble.getBoundingClientRect();
        const mainRect = main.getBoundingClientRect();
        if ((rect.right - mainRect.left) > (mainRect.width * 0.70)) {
            isOutgoing = true;
        } else {
            isIncoming = true;
        }
    }

    // Extract text from the message bubble
    let text = '';
    const textSpan = lastBubble.querySelector('span.selectable-text, .selectable-text, .copyable-text span, span[dir]');
    if (textSpan) {
        text = textSpan.innerText || textSpan.textContent || '';
    } else {
        text = lastBubble.innerText || lastBubble.textContent || '';
    }

    text = text.trim();

    return {
        ok: true,
        title: title,
        dataId: dataId,
        isIncoming: isIncoming,
        isOutgoing: isOutgoing,
        text: text
    };
"""


def get_latest_chat_info() -> dict:
    """Uses browser DOM evaluation to reliably extract active chat status."""
    if driver is None:
        return {"ok": False, "reason": "no_driver"}

    try:
        res = driver.execute_script(JS_GET_CHAT_INFO)
        if isinstance(res, dict):
            return res
    except Exception as error:
        return {"ok": False, "reason": str(error)}

    return {"ok": False, "reason": "unknown"}


# ==================================================
# 5. Send Reply to WhatsApp Composer
# ==================================================

def send_reply(reply: str) -> bool:
    """
    Reliably types and sends a reply in WhatsApp Web.
    Uses document.execCommand to support Bengali/Unicode/Emojis
    and clicks the Send button.
    """
    if driver is None:
        return False

    composer_selectors = [
        "//*[@id='main']//*[@contenteditable='true' and @role='textbox']",
        "//*[@id='main']//footer//*[@contenteditable='true']",
        "//*[@id='main']//div[@contenteditable='true']",
        "//div[@data-testid='conversation-compose-box-input']",
        "//div[@data-tab='10' and @contenteditable='true']",
        "//footer//*[@contenteditable='true']",
    ]

    input_box = None
    for selector in composer_selectors:
        try:
            boxes = driver.find_elements(By.XPATH, selector)
            for box in boxes:
                if box.is_displayed():
                    input_box = box
                    break
            if input_box:
                break
        except Exception:
            continue

    if input_box is None:
        print("❌ Message composer (input box) not found.")
        return False

    try:
        # 1. Scroll input box into view and focus it
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'}); arguments[0].focus();",
            input_box,
        )
        time.sleep(0.3)

        # 2. Insert text via document.execCommand (works natively with Lexical & Unicode/Bengali)
        driver.execute_script(
            """
            const el = arguments[0];
            const text = arguments[1];
            el.focus();
            document.execCommand('selectAll', false, null);
            document.execCommand('delete', false, null);
            document.execCommand('insertText', false, text);
            el.dispatchEvent(new InputEvent('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            """,
            input_box,
            reply,
        )
        time.sleep(0.5)

        # 3. Check if text entered; fallback to send_keys if needed
        entered_text = driver.execute_script(
            "return arguments[0].innerText || arguments[0].textContent || '';",
            input_box,
        ).strip()

        if not entered_text:
            input_box.click()
            input_box.send_keys(reply)
            time.sleep(0.5)

        # 4. Find and click the Send button
        send_button_selectors = [
            "//*[@id='main']//button[@data-testid='compose-btn-send']",
            "//*[@id='main']//span[@data-icon='send']/ancestor::button",
            "//*[@id='main']//span[@data-icon='send-light']/ancestor::button",
            "//*[@id='main']//button[.//span[@data-icon='send']]",
            "//*[@id='main']//button[contains(@aria-label, 'Send') or contains(@aria-label, 'পাঠান')]",
            "//button[@data-testid='compose-btn-send']",
        ]

        send_btn = None
        for sel in send_button_selectors:
            try:
                btns = driver.find_elements(By.XPATH, sel)
                for btn in btns:
                    if btn.is_displayed():
                        send_btn = btn
                        break
                if send_btn:
                    break
            except Exception:
                continue

        if send_btn:
            try:
                send_btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", send_btn)
            time.sleep(1)
            print("🚀 Send button clicked.")
            return True
        else:
            # Fallback: Send ENTER key
            input_box.send_keys(Keys.ENTER)
            time.sleep(1)
            print("🚀 Sent using ENTER key.")
            return True

    except Exception as error:
        print(f"❌ Failed to send reply: {error}")
        return False


# ==================================================
# 6. Main Agent Loop
# ==================================================

def run_agent():
    # In-memory tracking of processed messages to avoid duplicate auto-replies
    processed_messages = set()
    last_replied_time_per_chat = {}
    last_status_log_time = 0

    print("🚀 WhatsApp AI Auto-Reply Agent is running!")
    print("👀 Listening for unread chats and active messages...\n")

    while True:
        try:
            current_time = time.time()

            # Inspect current active chat title in #main
            active_info = get_latest_chat_info()
            current_active_title = active_info.get("title", "") if active_info.get("ok") else ""

            # Step 1: Check for unread chats in sidebar (ignoring the currently open chat)
            unread_row, contact_name = find_unread_chat(current_active_title)

            if unread_row is not None:
                display_name = contact_name or "Contact"
                print(f"\n🔔 Unread chat detected from [{display_name}]. Switching chat...")

                switched = switch_to_chat(unread_row, contact_name, current_active_title)
                if switched:
                    # Give WhatsApp 1 second to finish rendering messages
                    time.sleep(1)

            # Step 2: Inspect active chat in #main
            chat_info = get_latest_chat_info()

            if chat_info.get("ok"):
                title = chat_info.get("title", "Active Chat")
                is_incoming = chat_info.get("isIncoming", False)
                is_outgoing = chat_info.get("isOutgoing", False)
                text = (chat_info.get("text") or "").strip()
                data_id = chat_info.get("dataId", "")

                message_key = data_id if data_id else (title, text)

                # Cooldown check: do not reply to the same chat within 10 seconds of sending a reply
                time_since_last_reply = current_time - last_replied_time_per_chat.get(title, 0)

                # Prevent self-reply or duplicate replies:
                is_already_known = (
                    message_key in processed_messages
                    or text in processed_messages
                    or (title, text) in processed_messages
                )

                if is_incoming and text and not is_already_known:
                    if time_since_last_reply < 10:
                        # Cooldown period right after sending reply
                        pass
                    else:
                        print(f"\n💬 New incoming message from [{title}]:")
                        print(f"   \"{text}\"")
                        print("🤖 Generating AI reply...")

                        ai_reply = generate_busy_reply(text)
                        print(f"📤 AI Reply: \"{ai_reply}\"")

                        # Cache incoming text AND outgoing reply to prevent self-reply
                        processed_messages.add(message_key)
                        processed_messages.add(text)
                        processed_messages.add((title, text))
                        processed_messages.add(ai_reply.strip())
                        processed_messages.add((title, ai_reply.strip()))

                        if send_reply(ai_reply):
                            last_replied_time_per_chat[title] = time.time()
                            print("✅ Auto-reply sent successfully!\n")
                        else:
                            print("⚠️ Could not send reply.\n")

                elif is_outgoing:
                    if current_time - last_status_log_time > 15:
                        print(f"⏳ Monitoring [{title}]: Last message was sent by you. Waiting for sender's response...")
                        last_status_log_time = current_time

                elif is_incoming and is_already_known:
                    if current_time - last_status_log_time > 15:
                        print(f"⏳ Monitoring [{title}]: Last message already replied to. Waiting for new messages...")
                        last_status_log_time = current_time

            else:
                # No active chat open
                if current_time - last_status_log_time > 15:
                    print("🔍 Scanning for chats... (No active chat or unread messages)")
                    last_status_log_time = current_time

            time.sleep(3)

        except WebDriverException as error:
            print(f"⚠️ Browser error: {type(error).__name__}: {error}")
            time.sleep(5)

        except Exception as error:
            print(f"⚠️ Agent error: {type(error).__name__}: {error}")
            time.sleep(5)


# ==================================================
# 7. Entry point
# ==================================================

if __name__ == "__main__":
    try:
        if start_whatsapp():
            run_agent()

    except KeyboardInterrupt:
        print("\n🛑 Agent stopped by user.")

    except Exception as error:
        print(f"❌ Startup error: {type(error).__name__}: {error}")

    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

        print("🚪 Browser closed.")
