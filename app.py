
import asyncio
import datetime
import logging
import getpass
import re
import aiohttp
import os
import random
import json
import threading  # Import the threading module

from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession
from telethon.tl.types import InputMediaPhotoExternal
# from telethon.tl.types import ReplyKeyboardMarkup, KeyboardButton #REMOVED
# --- Configuration ---
API_ID = "20701122"
API_HASH = "5da9975a8293d61e4404a389dfd61f7d"
SESSION_STRING = "1BVtsOL8Bu1PO7XQp2P93xf43rfLjYso-DEn-xav3eey4Lw-XPabOW1p2_H_qG5qvZiZwnCt1rH-cQS7N8vkPZTNYPAlzfIQ72bdrFAKtDR6UPnCbW80FIfm-zp421iM4EsK_vbxyM1b0ba3jXuDi22ZDpKDhOaZcAQ1_ddcYVp2I5CC4resKIstMCPayIUmOam39WkQuvZ058hK_nBnPFFpjDgPwJ8BWyS7Z3mn7tLZ000XdesXEJNR9a-3VhIwMu8wcUm_9MAZbb5MC02uk1TWcLHMSe347_n9yx5jOgejSa0RWqg64DA8qg64DA8qYhSRE3MMmOITAzZF-acDuJEotL3b5KCXjlxrTAs="
BOT_TOKEN = "8134824419:AAHBKDpbmQMSzXS4oyTGyfrQsLFoniqHDAA"


FORWARD_GROUP_ID = -1002930067925
MONITOR_GROUP_ID = [-1002682944548, -1002647815753, --1002917979890]  # Added new monitor group


client = None
bot = None
start_time = None
is_active = False
last_online_time = None
emoji_index = 0

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('cc_monitor.log'),
        logging.StreamHandler()
    ]
)

CCS_FILE = "kafkascrapper.txt"
WEEKLY_CCS_FILE = "kafkascrapperw.txt"  # Weekly file name
PROCESSED_MESSAGES_FILE = "processed_messages.json"
scraped_ccs = []
weekly_scraped_ccs = []  # CCs for the week
hourly_task_started = False  # To prevent starting the task multiple times
hourly_start_time = None  # Reset to None
daily_reset_time = None  # Added for the daily reset
weekly_start_time = None  # ADD this as well

processed_messages = set()
processing_queue = asyncio.Queue()
is_processing = False

# --- Regular Expressions ---
CC_REGEX = re.compile(
    r"""
    (?P<cc>(?:4\d{12}(?:\d{3})?          # Visa 13 or 16 digits
    |5[1-5]\d{14}                        # MasterCard 16 digits
    |3[47]\d{13}                        # AMEX 15 digits
    |3(?:0[0-5]|[68]\d)\d{11}           # Diners Club
    |6(?:011|5\d{2})\d{12}              # Discover
    |(?:2131|1800|35\d{3})\d{11}))      # JCB
    [\s|:,\-/\\\.]*                     # Separator (optional)
    (?P<month>0[1-9]|1[0-2])            # Month 01-12
    [\s|:,\-/\\\.]*                     # Separator (optional)
    (?P<year>(?:20)?\d{2})              # Year (2 or 4 digits)
    [\s|:,\-/\\\.]*                     # Separator (optional)
    (?P<cvv>\d{3,4})                    # CVV 3 or 4 digits
    """,
    re.VERBOSE | re.IGNORECASE
)

TELEGRAPH_REGEX = re.compile(r'(https?://telegra\.ph/[^\s]+)', re.IGNORECASE)

XFORCE_BOT_LINK_RE = re.compile(
    r"https://t\.me/(?P<botname>[A-Za-z0-9_]+)/(?:Drops)?\\?startapp=(?P<startapp>[a-fA-F0-9]+)",
    re.IGNORECASE
)

# Adding regex for tg://resolve links
TG_RESOLVE_LINK_RE = re.compile(
    r"tg://resolve\?domain=(?P<botname>[A-Za-z0-9_]+)&start=(?P<startapp>[a-zA-Z0-9_-]+)",
    re.IGNORECASE
)

# Regex for the new chat format
ASIANPRO_CC_REGEX = re.compile(
    r"CC: (?P<cc>\d{15,16})\|(?P<month>\d{2})\|(?P<year>\d{4})\|(?P<cvv>\d{3,4})",
    re.IGNORECASE
)

# --- Helper Functions ---
def get_uptime():
    global start_time
    if start_time:
        uptime = datetime.datetime.now() - start_time
        hours, remainder = divmod(uptime.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
    else:
        return "N/A"

def get_last_online_string():
    global last_online_time
    if last_online_time:
        return f"Last seen offline at: {last_online_time.strftime('%Y-%m-%d %H:%M:%S')}"
    else:
        return "…"

def append_cc_to_file(cc_line):
    try:
        with open(CCS_FILE, "a", encoding="utf-8") as f:
            f.write(cc_line + "\n")
    except Exception as e:
        logging.error(f"Error appending CC to file: {e}")

def append_cc_to_weekly_file(cc_line):
    try:
        with open(WEEKLY_CCS_FILE, "a", encoding="utf-8") as f:
            f.write(cc_line + "\n")
    except Exception as e:
        logging.error(f"Error appending CC to WEEKLY file: {e}")

async def get_random_motivation():
    filename = "motivation.txt"
    default_text = "Have a nice day. 😊"
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
            if lines:
                return random.choice(lines)
        except Exception as e:
            logging.error(f"Error reading motivation.txt: {e}")
    return default_text

# --- Async extraction functions ---
async def extract_ccs_from_text(text):
    results = []
    try:
        clean_text = re.sub(r'[^\w\s|:,\-/\\\.0-9]', ' ', text)
        for match in CC_REGEX.finditer(clean_text):
            cc = match.group('cc')
            month = match.group('month')
            year = match.group('year')
            if len(year) == 4:
                year = year[-2:]
            elif len(year) == 1:
                year = '2' + year
            cvv = match.group('cvv')
            if len(cc) >= 13 and 1 <= int(month) <= 12 and int(year) >= 24:
                results.append((cc, month, year, cvv))
    except Exception as e:
        logging.error(f"Error extracting CCs from text: {e}")
    return results

async def fetch_telegraph_text(url):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        text = re.sub(r'<[^>]+>', '', html)
                        return text
        except Exception as e:
            logging.error(f"Attempt {attempt + 1} failed to fetch Telegraph: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
    return ""

async def fetch_ccs_from_xforce_link(client, botname, startapp_token):
    max_retries = 2
    for attempt in range(max_retries):
        try:
            bot_entity = await client.get_entity(botname)
            async with client.conversation(bot_entity, timeout=45) as conv:
                await conv.send_message(f"/start {startapp_token}")
                await asyncio.sleep(7)
                responses = []
                for _ in range(5):
                    try:
                        response = await asyncio.wait_for(conv.get_response(), timeout=5)
                        responses.append(response)
                    except asyncio.TimeoutError:
                        break
                ccs = []
                for resp in responses:
                    ccs.extend(await extract_ccs_from_text(resp.text))
                return ccs
        except Exception as e:
            logging.error(f"Attempt {attempt + 1} failed for xForce bot: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(3)
    return []

async def fetch_bin_data(bin_number):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            timeout = aiohttp.ClientTimeout(total=8)
            url = f'https://bins.antipublic.cc/bins/{bin_number}'
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            logging.error(f"Attempt {attempt + 1} failed to fetch bin data: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
    return None

async def fetch_vbv_response(cc_full):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            url = f'http://ronak.whf.bz/vbv.php?lista={cc_full}' # Change here
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.text()
        except Exception as e:
            logging.error(f"Attempt {attempt + 1} failed to fetch VBV: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
    return "N/A"

# --- Processing queue ---
async def process_message_queue():
    global is_processing
    while True:
        try:
            if not is_processing:
                await asyncio.sleep(1)
                continue
            message_data = await processing_queue.get()
            await process_single_message(message_data)
            processing_queue.task_done()
        except Exception as e:
            logging.error(f"Error in message queue processing: {e}")
            await asyncio.sleep(1)

async def process_single_message(message_data):
    try:
        message_text, message_id = message_data
        if message_id in processed_messages:
            return
        processed_messages.add(message_id)
        ccs = await extract_ccs_from_text(message_text)
        telegraph_links = TELEGRAPH_REGEX.findall(message_text)
        for link in telegraph_links:
            try:
                telegraph_text = await fetch_telegraph_text(link)
                if telegraph_text:
                    ccs.extend(await extract_ccs_from_text(telegraph_text))
            except Exception as e:
                logging.error(f"Failed to fetch from Telegraph: {e}")
        xforce_links = XFORCE_BOT_LINK_RE.findall(message_text)
        for botname, startapp_token in xforce_links:
            try:
                ccs_from_bot = await fetch_ccs_from_xforce_link(client, botname, startapp_token)
                ccs.extend(ccs_from_bot)
            except Exception as e:
                logging.error(f"Failed to fetch from xForce bot: {e}")

        # Processing new tg://resolve links
        tg_links = TG_RESOLVE_LINK_RE.findall(message_text)
        for botname, startapp_token in tg_links:
            try:
                ccs_from_bot = await fetch_ccs_from_xforce_link(client, botname, startapp_token)
                ccs.extend(ccs_from_bot)
            except Exception as e:
                logging.error(f"Failed to fetch from tg://resolve bot: {e}")

        # Processing AsianPro format
        asianpro_match = ASIANPRO_CC_REGEX.search(message_text)
        if asianpro_match:
            cc = asianpro_match.group('cc')
            month = asianpro_match.group('month')
            year = asianpro_match.group('year')
            cvv = asianpro_match.group('cvv')

            year = year[-2:] if len(year) == 4 else year

            ccs.append((cc, month, year, cvv))

        for cc, month, year, cvv in ccs:
            await process_single_cc(cc, month, year, cvv)

        if len(processed_messages) % 10 == 0:
            save_processed_messages()
    except Exception as e:
        logging.error(f"Error processing single message: {e}")

async def process_single_cc(cc, month, year, cvv):
    global emoji_index
    try:
        cc_line = f"{cc}|{month}|{year}|{cvv}"
        if cc_line in scraped_ccs:
            return
        scraped_ccs.append(cc_line)
        append_cc_to_file(cc_line)

        # Weekly Processing
        if cc_line not in weekly_scraped_ccs:  # Add check to avoid duplicates in weekly list
            weekly_scraped_ccs.append(cc_line)  # Append to weekly list
            append_cc_to_weekly_file(cc_line)  # Append to weekly file

        bin_number = cc[:6]

        bin_data_task = fetch_bin_data(bin_number)
        vbv_task = fetch_vbv_response(cc_line)
        motivation_task = get_random_motivation()

        bin_data, vbv_response, motivation_text = await asyncio.gather(
            bin_data_task, vbv_task, motivation_task, return_exceptions=True
        )

        if isinstance(bin_data, Exception):
            logging.error(f"Bin data fetch failed: {bin_data}")
            bin_data = None
        if isinstance(vbv_response, Exception):
            logging.error(f"VBV fetch failed: {vbv_response}")
            vbv_response = "N/A"
        else:
            vbv_response = str(vbv_response).strip()
        if isinstance(motivation_text, Exception):
            logging.error(f"Motivation fetch failed: {motivation_text}")
            motivation_text = "Have a nice day. 😊"

        scheme = bin_data.get('brand', 'N/A').upper() if bin_data else 'N/A'
        card_type = bin_data.get('type', 'N/A').upper() if bin_data else 'N/A'
        brand = bin_data.get('level', 'N/A').upper() if bin_data else 'N/A'
        bank_name = bin_data.get('bank', 'N/A').upper() if bin_data else 'N/A'
        country_name = bin_data.get('country_name', 'N/A').upper() if bin_data else 'N/A'
        country_emoji = bin_data.get('country_flag', 'N/A') if bin_data else 'N/A'
        currency = bin_data.get('country_currencies', ['N/A'])[0].upper() if bin_data and bin_data.get('country_currencies') else 'N/A'

        formatted = FORWARD_FORMAT.format(
            cc=cc, month=month, year=year, cvv=cvv,
            vbv_response=vbv_response,
            card_type=card_type, brand=brand,
            bank_name=bank_name, country_name=country_name,
            country_emoji=country_emoji, currency=currency,
            Motivational_text=motivation_text,
            emoji=get_next_emoji()
        )

        # Forward using the bot with image and caption
        try:
            image_url = "https://i.ibb.co/M5gL22TQ/grok-image-xx1digi.jpg"
            await bot.send_file(
                FORWARD_GROUP_ID,
                InputMediaPhotoExternal(url=image_url),
                caption=formatted,
                parse_mode='html'  # Enable HTML formatting for code tags
            )

            logging.info(f"Sent CC: {cc_line} via bot with image")
        except Exception as e:
            logging.exception(f"Error sending message with image via bot: {e}")  # MORE detailed logging!

    except Exception as e:
        logging.error(f"Error processing CC {cc}: {e}")

# --- Forward message template ---
def get_next_emoji():
    global emoji_index
    emojis = ["💮", "🌸", "🏵️", "🌺", "🌻", "🌼", "🌷", "🌱", "🌿", "🍀", "🌹", "💐", "🍃", "🍁", "🍂", "🌴", "🌵", "🌾"]  #expanded list
    emoji = emojis[emoji_index % len(emojis)]
    emoji_index += 1
    return emoji


FORWARD_FORMAT = (
    "𝙆𝙖𝙛𝙠𝙖 • 𝘅-𝗙𝗼𝗿𝗰𝗲 𝗰𝗰 {emoji}\n"
    "▬▬▬▬▬⌁・⌁▬▬▬▬▬\n"
    "カ 𝐂𝐚𝐫𝐝: <code>{cc}|{month}|{year}|{cvv}</code>\n"
    "❀ 𝐕𝐁𝐕: <code>{vbv_response}</code>\n"
    "┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
    "✿ 𝑻𝒚𝒑𝒆 ➜ {card_type}\n"
    "✿ 𝑳𝒆𝒗𝒆𝒍 ➜ {brand}\n"
    "✿ 𝑩𝒂𝒏𝒌 ➜ {bank_name}\n"
    "✿ 𝑪𝒐𝒖𝒏𝒕𝒓𝒚 ➜ {country_name} {country_emoji}\n"
    "✿ 𝑪𝒖𝒓𝒓𝒆𝒏𝒄𝒚 ➜ {currency}\n"
    "▬▬▬▬▬⌁・⌁▬▬▬▬▬\n"
    "{Motivational_text}\n"
    "▬▬▬▬▬⌁・⌁▬▬▬▬▬\n"
    "◉ 𝙑𝙚𝙧𝙨𝙞𝙤𝙣: 𝘢𝘭𝘱𝘩alpha.5.1-1\n"
    "◉ 𝙐𝙥𝙙𝙖𝙩𝙚: @kafkaupdatesx\n"
    "◉ 𝙊𝙬𝙣𝙚𝙧:  @xRonak\n"
    "˖ ❀ ⋆｡˚▬▬▬▬▬▬▬୨୧⋆ ˚"
    )

# --- Hourly dropper ---
async def hourly_dropper(client):
    global scraped_ccs, hourly_start_time, daily_reset_time
    while True:
        try:
            now = datetime.datetime.now()

            # Hourly Drop Logic
            if hourly_start_time is None:
                hourly_start_time = now

            elapsed_time = now - hourly_start_time
            if elapsed_time >= datetime.timedelta(hours=1):
                if scraped_ccs:
                    caption = (f"Kafka Hour Drop\n"
                               f"Total CCs: {len(scraped_ccs)}\n"
                               f"Backup Group: @kafkaupdatesx\n\n"
                               f"Another Drop under 1 hour...")
                    try:
                        if os.path.exists(CCS_FILE) and os.path.getsize(CCS_FILE) > 0:  # Check if the file exists AND not empty

                            msg = await client.send_file(
                                FORWARD_GROUP_ID,
                                CCS_FILE,
                                caption=caption
                            )
                            await client.pin_message(FORWARD_GROUP_ID, msg.id, notify=False)
                        else:
                            logging.warning(f"Hourly CC file {CCS_FILE} does not exist or is empty. Skipping sending.")

                    except Exception as e:
                        logging.exception(f"Error sending/pinning Hourly CC file: {e}")
                hourly_start_time = now  # Reset for the next hourly drop

            # Daily Reset Logic (occurs independently of the hourly drop)
            if daily_reset_time is None:
                daily_reset_time = now

            time_since_reset = now - daily_reset_time
            if time_since_reset >= datetime.timedelta(hours=24):
                scraped_ccs = []  # Reset the list *only* every 24 hours
                if os.path.exists(CCS_FILE):
                    os.remove(CCS_FILE)
                daily_reset_time = now  # Reset the daily reset timer
                logging.info("Daily CC list reset complete.")

        except Exception as e:
            logging.error(f"Error in hourly dropper: {e}")
        await asyncio.sleep(60)  # Check every 60 seconds

# --- Weekly dropper ---
async def weekly_dropper(client):
    global weekly_scraped_ccs, weekly_start_time
    while True:
        try:
            now = datetime.datetime.now()

            # Drop on Sunday at the same hour as the script's start
            if weekly_start_time is None:
                # If it's the first time, initialize weekly_start_time
                weekly_start_time = now

            if now.weekday() == 6 and now.hour == weekly_start_time.hour and now.minute >= weekly_start_time.minute:
                # Read existing CCs from the weekly file
                existing_ccs = set()
                if os.path.exists(WEEKLY_CCS_FILE):
                    try:
                        with open(WEEKLY_CCS_FILE, "r", encoding="utf-8") as f:
                            existing_ccs = set(line.strip() for line in f)
                    except Exception as e:
                        logging.error(f"Error reading WEEKLY_CCS_FILE: {e}")

                ccs_to_send = [cc for cc in weekly_scraped_ccs if cc not in existing_ccs]  # Filter CCs

                if ccs_to_send:
                    caption = (f"Kafka Week Drop\n"
                               f"Total New CCs: {len(ccs_to_send)}\n"
                               f"Backup Group: @kafkaupdatesx\n\n"
                               f"Another Drop under 1 week...")
                    try:
                        # Create a temporary file to write the new CCs
                        temp_file_path = "temp_weekly_ccs.txt"
                        with open(temp_file_path, "w", encoding="utf-8") as temp_file:
                            for cc in ccs_to_send:
                                temp_file.write(cc + "\n")

                        # Send the temporary file
                        msg = await client.send_file(
                            FORWARD_GROUP_ID,
                            temp_file_path,
                            caption=caption
                        )
                        await client.pin_message(FORWARD_GROUP_ID, msg.id, notify=False)

                        # Remove the temporary file after sending
                        os.remove(temp_file_path)

                        # Append the newly sent CCs to the main WEEKLY_CCS_FILE
                        try:
                            with open(WEEKLY_CCS_FILE, "a", encoding="utf-8") as weekly_file:
                                for cc in ccs_to_send:
                                    weekly_file.write(cc + "\n")  # Append new CCs to the permanent file
                        except Exception as e:
                            logging.error(f"Error appending to WEEKLY_CCS_FILE after drop: {e}")

                    except Exception as e:
                        logging.exception(f"Error sending/pinning WEEKLY CC file: {e}")

                weekly_scraped_ccs = []  # Reset the list after processing

                weekly_start_time = datetime.datetime.now()  # Reset start time

        except Exception as e:
            logging.error(f"Error in weekly dropper: {e}")
        await asyncio.sleep(3600)  # Check every hour

# --- Load/Save processed messages ---
def load_processed_messages():
    global processed_messages
    try:
        if os.path.exists(PROCESSED_MESSAGES_FILE):
            with open(PROCESSED_MESSAGES_FILE, 'r') as f:
                processed_messages = set(json.load(f))
        else:
            processed_messages = set()
        logging.info(f"Loaded {len(processed_messages)} processed message IDs")
    except Exception as e:
        logging.error(f"Error loading processed messages: {e}")
        processed_messages = set()

def save_processed_messages():
    try:
        with open(PROCESSED_MESSAGES_FILE, 'w') as f:
            json.dump(list(processed_messages), f)
        logging.info(f"Saved {len(processed_messages)} processed message IDs")
    except Exception as e:
        logging.error(f"Error saving processed messages: {e}")

# --- Main ---
async def main():
    global client, bot, SESSION_STRING, hourly_task_started, is_processing, is_active, start_time, last_online_time, weekly_start_time, daily_reset_time

    load_processed_messages()

    try:
        client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
        await client.connect()

        if not await client.is_user_authorized():
            print("Not authorized. Please authorize manually.")
            logging.warning("User not authorized. Attempting to authorize...")
            try:
                await client.start()
            except errors.SessionPasswordNeededError:
                logging.info("Two-step verification is enabled.")
                password = getpass.getpass("Enter your 2FA password: ")
                try:
                    await client.sign_in(password=password)
                except errors.PasswordHashInvalidError:
                    print("Incorrect password.")
                    logging.error("Incorrect password provided.")
                    return
                except Exception as e:
                    print(f"An error occurred during sign-in: {e}")
                    logging.exception("Error during sign-in")
                    return
            except Exception as e:
                print(f"An error occurred during authorization: {e}")
                logging.exception("Error during authorization")
                return
        else:
            logging.info("Client connected successfully")

        if not SESSION_STRING or not await client.is_user_authorized():
            SESSION_STRING = client.session.save()
            print("New session string generated.")
            logging.info("New session string generated.")

        me = await client.get_me()
        print(f"User {me.username} started")
        logging.info(f"User {me.username} started")

        # Removed handle_message event: No longer needed.


        @client.on(events.NewMessage(chats=MONITOR_GROUP_ID))
        async def monitor_cc_numbers(event):
            global is_active, is_processing
            if not is_active or not is_processing:
                return
            try:
                message_text = event.message.message or ""
                message_id = event.message.id

                # Adding to queue for processing
                await processing_queue.put((message_text, message_id))
                logging.info(f"Added message {message_id} to processing queue")

                # Additional processing for tg://resolve links (automatically)
                tg_links = TG_RESOLVE_LINK_RE.findall(message_text)
                for botname, startapp_token in tg_links:
                    logging.info(f"Found tg://resolve link: bot={botname}, start={startapp_token}")
                    ccs_from_bot = await fetch_ccs_from_xforce_link(client, botname, startapp_token)
                    for cc, month, year, cvv in ccs_from_bot:
                        await process_single_cc(cc, month, year, cvv)

                # Processing AsianPro format directly in monitor group
                asianpro_match = ASIANPRO_CC_REGEX.search(message_text)
                if asianpro_match:
                    cc = asianpro_match.group('cc')
                    month = asianpro_match.group('month')
                    year = asianpro_match.group('year')
                    cvv = asianpro_match.group('cvv')

                    year = year[-2:] if len(year) == 4 else year

                    await process_single_cc(cc, month, year, cvv)

            except Exception as e:
                logging.error(f"Error handling monitor message: {e}")

        asyncio.create_task(process_message_queue())

        bot = TelegramClient('bot', API_ID, API_HASH)
        await bot.start(bot_token=BOT_TOKEN)

        @bot.on(events.NewMessage(pattern='/xx'))
        async def start_handler(event):
            global is_active, start_time, is_processing, hourly_start_time, daily_reset_time, weekly_start_time
            if not is_active:
                is_active = True
                is_processing = True
                start_time = datetime.datetime.now()
                hourly_start_time = datetime.datetime.now()
                daily_reset_time = datetime.datetime.now()  # Initialize daily_reset_time
                weekly_start_time = datetime.datetime.now()  # Initialize weekly start time

                await event.respond("Services started!")
                logging.info("Services started")
            else:
                await event.respond("Services are already running.")

        @bot.on(events.NewMessage(pattern='/off'))
        async def stop_handler(event):
            global is_active, start_time, last_online_time, is_processing
            if is_active:
                is_active = False
                is_processing = False
                start_time = None
                last_online_time = datetime.datetime.now()
                save_processed_messages()
                await event.respond("Services stopped!")
                logging.info("Services stopped")
            else:
                await event.respond("Services are already stopped.")

        @bot.on(events.NewMessage(pattern='/xvxv'))
        async def xvxv_handler(event):
            global is_active, is_processing
            if not is_active:
                is_active = True
                is_processing = True
                await event.respond("CC number monitoring started!")
                logging.info("CC monitoring started")
            else:
                await event.respond("CC number monitoring already running.")

        @bot.on(events.NewMessage(pattern='/status'))
        async def status_handler(event):
            queue_size = processing_queue.qsize()
            processed_count = len(processed_messages)
            cc_count = len(scraped_ccs)
            uptime = get_uptime()
            status_msg = (f"ðŸ¤– Bot Status:\n"
                         f"Active: {is_active}\n"
                         f"Processing: {is_processing}\n"
                         f"Uptime: {uptime}\n"
                         f"Queue Size: {queue_size}\n"
                         f"Processed Messages: {processed_count}\n"
                         f"Scraped CCs: {cc_count}")
            await event.respond(status_msg)

        if not hourly_task_started:
            asyncio.create_task(hourly_dropper(client))
            asyncio.create_task(weekly_dropper(client))  # ADD THIS LINE
            hourly_task_started = True

        print("Bot is running... Press Ctrl+C to stop")
        logging.info("Bot started successfully")

        await bot.run_until_disconnected()

    except Exception as e:
        print(f"An error occurred: {e}")
        logging.exception("An unexpected error occurred:")
    finally:
        save_processed_messages()
        if client:
            await client.disconnect()
        if bot:
            await bot.disconnect()

# --- Graceful shutdown helper ---

async def shutdown(client, bot):
    try:
        logging.info("Saving processed messages before shutdown...")
        save_processed_messages()
    except Exception as e:
        logging.error(f"Error saving processed messages at shutdown: {e}")
    try:
        if client:
            await client.disconnect()
            logging.info("Client disconnected")
    except Exception as e:
        logging.error(f"Error disconnecting client: {e}")
    try:
        if bot:
            await bot.disconnect()
            logging.info("Bot disconnected")
    except Exception as e:
        logging.error(f"Error disconnecting bot: {e}")


# --- Entry point ---

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("KeyboardInterrupt received. Shutting down...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(shutdown(client, bot))
        loop.close()
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(shutdown(client, bot))
        loop.close() 