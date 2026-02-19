"""CLI entry point: python -m poly_crypto."""

import sys

from poly_crypto.paper import generate_dashboard, run_scan_and_trade
from poly_crypto.paper_daily import (
    generate_daily_dashboard,
    run_daily_scan_and_trade,
)
from poly_crypto.paper_range import (
    generate_range_dashboard,
    run_range_scan_and_trade,
)

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    sub = sys.argv[2] if len(sys.argv) > 2 else ""
    if cmd == "stats":
        generate_dashboard()
    elif cmd == "range":
        if sub == "stats":
            generate_range_dashboard()
        else:
            run_range_scan_and_trade()
    elif cmd == "daily":
        if sub == "stats":
            generate_daily_dashboard()
        else:
            run_daily_scan_and_trade()
    else:
        run_scan_and_trade()
