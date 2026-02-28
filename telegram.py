"""Send Telegram messages and files via the Bot API."""

import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _check_config():
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env")


def send_message(text: str, parse_mode: str = "Markdown") -> dict:
    """Send a text message. Supports Markdown or HTML formatting."""
    _check_config()
    resp = requests.post(
        f"{BASE_URL}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def send_file(path: str, caption: str | None = None) -> dict:
    """Send a file as a document."""
    _check_config()
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {path}")
    with open(path, "rb") as f:
        data = {"chat_id": CHAT_ID}
        if caption:
            data["caption"] = caption
        resp = requests.post(
            f"{BASE_URL}/sendDocument",
            data=data,
            files={"document": f},
            timeout=30,
        )
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python telegram.py message 'your text here'")
        print("       python telegram.py file /path/to/file ['caption']")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "message":
        send_message(sys.argv[2])
        print("Message sent.")
    elif cmd == "file":
        cap = sys.argv[3] if len(sys.argv) > 3 else None
        send_file(sys.argv[2], caption=cap)
        print("File sent.")
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)