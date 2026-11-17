"""
NetPulse Multi-Device Simulation Runner
Launches multiple simulated computer agents (e.g. PC-1, PC-2, PC-3, PC-4)
to easily demonstrate and evaluate:
- Rule 1: One computer cannot reach the gateway, others can -> Computer Wi-Fi/NIC issue
- Rule 2: All computers lose gateway -> Router failure
- Rule 3: All reach gateway, none reaches internet -> ISP outage
- Rule 4: DNS server outage
"""

import sys
import time
import argparse
import threading
from agent import run_agent

def main():
    parser = argparse.ArgumentParser(description="Run multiple simulated NetPulse agents")
    parser.add_argument("--count", type=int, default=3, help="Number of simulated agents (default: 3)")
    parser.add_argument("--backend-url", default="http://localhost:8000", help="NetPulse backend URL")
    parser.add_argument("--interval", type=int, default=10, help="Polling interval in seconds")
    args = parser.parse_args()

    print(f"[*] Starting {args.count} simulated agents reporting to {args.backend_url}...")

    threads = []
    for i in range(1, args.count + 1):
        agent_id = f"computer-0{i}"
        t = threading.Thread(
            target=run_agent,
            kwargs={
                "agent_id": agent_id,
                "backend_url": args.backend_url,
                "interval_sec": args.interval,
                "simulate_fault": None
            },
            daemon=True
        )
        t.start()
        threads.append(t)
        time.sleep(1.0)

    print(f"[+] All {args.count} agents running in background. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Stopping simulated agents.")

if __name__ == "__main__":
    main()
