"""CLI entry point: python -m poly_crypto."""

import sys

from poly_crypto.paper import generate_dashboard, run_scan_and_trade

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        generate_dashboard()
    else:
        run_scan_and_trade()
