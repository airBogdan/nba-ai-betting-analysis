"""OpenRouter LLM client."""

import asyncio
import json
import os
import re
from typing import Any, Optional

import aiohttp
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
# DEFAULT_MODEL = "google/gemini-3-pro-preview"
DEFAULT_MODEL = "anthropic/claude-opus-4.5"

# Retry configuration
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 2


def _get_api_key() -> str:
    """Get OpenRouter API key from environment."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise ValueError("OPENROUTER_API_KEY environment variable not set")
    return key


def _get_model() -> str:
    """Get model from environment or use default."""
    return os.environ.get("LLM_MODEL", DEFAULT_MODEL)


async def complete(
    prompt: str,
    system: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> Optional[str]:
    """
    Send completion request to OpenRouter.
    Returns response text or None on error.
    Includes retry logic for transient failures.
    """
    api_key = _get_api_key()
    model = model or _get_model()

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            timeout = aiohttp.ClientTimeout(total=120)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    OPENROUTER_URL, json=payload, headers=headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["choices"][0]["message"]["content"]

                    error_text = await resp.text()
                    # Don't retry on 4xx client errors (except 429 rate limit)
                    if 400 <= resp.status < 500 and resp.status != 429:
                        print(f"LLM error ({resp.status}): {error_text}")
                        return None

                    last_error = f"HTTP {resp.status}: {error_text}"
        except Exception as e:
            last_error = str(e)

        # Retry with backoff
        if attempt < MAX_RETRIES:
            delay = RETRY_DELAY_SECONDS * (attempt + 1)
            print(f"LLM request failed (attempt {attempt + 1}), retrying in {delay}s...")
            await asyncio.sleep(delay)

    print(f"LLM request failed after {MAX_RETRIES + 1} attempts: {last_error}")
    return None


def _strip_markdown_json(text: str) -> str:
    """Strip markdown code blocks from JSON response."""
    # Match ```json ... ``` or ``` ... ```
    pattern = r"```(?:json)?\s*([\s\S]*?)```"
    match = re.search(pattern, text)
    if match:
        return match.group(1).strip()
    return text.strip()


async def complete_json(
    prompt: str,
    system: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.3,
) -> Optional[Any]:
    """
    Request JSON response from LLM.
    Strips markdown code blocks, parses JSON.
    Returns None on parse failure.
    """
    response = await complete(prompt, system, model, temperature)
    if response is None:
        return None

    try:
        cleaned = _strip_markdown_json(response)
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        print(f"Response was: {response[:500]}...")
        return None
