"""Live football score monitor with Polymarket odds lookup."""

import asyncio

from dotenv import load_dotenv

from sports.football.live import run

if __name__ == "__main__":
    load_dotenv()
    asyncio.run(run())
