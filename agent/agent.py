"""
NetPulse Monitoring Agent
Runs on endpoint computers every 10 to 30 seconds.
Performs:
1. Default Gateway ICMP Ping
2. Dual DNS Resolution (Local resolver vs 8.8.8.8)
3. External IP Probing (Latency, Jitter, Packet Loss)
4. Conditional Traceroute (triggered on failure)
5. Local Offline Buffer (retains telemetry during network/backend outages)
6. Reports JSON payload to NetPulse Backend Ingest API
"""

import os
import sys
import time
import json
import socket
import platform
import argparse
import logging
import statistics
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import requests
import dns.resolver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("NetPulseAgent")

BUFFER_FILE = "agent_buffer.json"


def get_default_gateway() -> Optional[str]:
    """
    Discovers the default gateway IP address from the OS routing table.
    Works reliably on Windows, Linux, and macOS.
    """
    try:
        from scapy.all import conf
        gw = conf.route.route("0.0.0.0")[2]
        if gw and gw != "0.0.0.0":
            return gw
    except Exception:
        pass

    # Windows fallback via route print
    if platform.system().lower() == "windows":
        try:
            output = subprocess.check_output("route print 0.0.0.0", shell=True, text=True)
            for line in output.splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                    return parts[2]
        except Exception:
            pass

    # Linux / macOS fallback
    try:
        if platform.system().lower() == "darwin":
            out = subprocess.check_output("route -n get default", shell=True, text=True)
            for line in out.splitlines():
                if "gateway:" in line:
                    return line.split(":")[1].strip()
        else:
            out = subprocess.check_output("ip route show default", shell=True, text=True)
            for line in out.splitlines():
                parts = line.split()
                if "via" in parts:
                    return parts[parts.index("via") + 1]
    except Exception:
        pass

    return "192.168.1.1"  # Common LAN default


def ping_host(host: str, count: int = 4, timeout_sec: int = 2) -> Tuple[bool, Optional[float], float, Optional[float]]:
    """
    Pings host using OS ping tool.
    Returns: (is_reachable, avg_rtt_ms, loss_pct, jitter_ms)
    """
    is_win = platform.system().lower() == "windows"
    cmd = (
        ["ping", "-n", str(count), "-w", str(timeout_sec * 1000), host]
        if is_win
        else ["ping", "-c", str(count), "-W", str(timeout_sec), host]
    )

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_sec * count + 2)
        output = proc.stdout
        
        # Parse packet loss
        loss_pct = 100.0
        rtts: List[float] = []

        for line in output.splitlines():
            line_lower = line.lower()
            if "% loss" in line_lower:
                # e.g. "Packets: Sent = 4, Received = 4, Lost = 0 (0% loss)"
                try:
                    part = line_lower.split("% loss")[0]
                    loss_str = part.split("(")[-1].strip()
                    loss_pct = float(loss_str)
                except Exception:
                    pass
            elif "% packet loss" in line_lower:
                # e.g. "4 packets transmitted, 4 received, 0% packet loss"
                try:
                    part = line_lower.split("% packet loss")[0]
                    loss_str = part.split(",")[-1].strip()
                    loss_pct = float(loss_str)
                except Exception:
                    pass

            # Parse individual RTTs for jitter
            # Windows: "Reply from 1.1.1.1: bytes=32 time=14ms TTL=57"
            # Linux: "64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=14.2 ms"
            if "time=" in line_lower or "time<" in line_lower:
                try:
                    if "time<" in line_lower:
                        val = 0.5
                    else:
                        time_part = line_lower.split("time=")[1].split()[0]
                        val = float(time_part.replace("ms", ""))
                    rtts.append(val)
                except Exception:
                    pass

        if rtts:
            avg_rtt = round(statistics.mean(rtts), 2)
            jitter = round(statistics.stdev(rtts), 2) if len(rtts) > 1 else 0.0
            return (loss_pct < 100.0, avg_rtt, loss_pct, jitter)
        else:
            return (False, None, 100.0, None)

    except Exception as e:
        logger.debug(f"Ping to {host} failed: {e}")
        return (False, None, 100.0, None)


def check_dns(domain: str, server: Optional[str] = None, timeout_sec: float = 2.0) -> Tuple[bool, Optional[float]]:
    """
    Resolves domain using specified DNS server (or local resolver if server is None).
    Returns (success, rtt_ms).
    """
    res = dns.resolver.Resolver(configure=(server is None))
    if server:
        res.nameservers = [server]
    res.lifetime = timeout_sec
    res.timeout = timeout_sec

    start = time.time()
    try:
        answers = res.resolve(domain, "A")
        elapsed_ms = round((time.time() - start) * 1000, 2)
        return (len(answers) > 0, elapsed_ms)
    except Exception:
        return (False, None)


def run_traceroute(target: str, max_hops: int = 8, timeout_sec: int = 1) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """
    Runs traceroute when a probe fails, mapping each hop.
    Uses bounded hops and 500ms timeout for rapid responsiveness.
    """
    is_win = platform.system().lower() == "windows"
    cmd = (
        ["tracert", "-d", "-h", str(max_hops), "-w", "500", target]
        if is_win
        else ["traceroute", "-n", "-m", str(max_hops), "-w", "1", target]
    )

    hops = []
    last_responsive_hop = None

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=8)
        lines = proc.stdout.splitlines()

        for line in lines:
            parts = line.strip().split()
            if not parts:
                continue

            # Identify hop line: starts with hop number (1, 2, 3...)
            if parts[0].isdigit():
                hop_num = int(parts[0])
                if "*" in line and ("Request timed out" in line or line.count("*") >= 3):
                    hops.append({"hop": hop_num, "ip": None, "rtt_ms": None, "responsive": False})
                else:
                    # Look for IP in the line and parse real RTT values
                    ip = None
                    rtt_vals = []
                    for i, token in enumerate(parts):
                        if token == "ms" and i > 0:
                            prev = parts[i - 1].replace("<", "").replace(">", "").strip()
                            try:
                                rtt_vals.append(float(prev))
                            except ValueError:
                                pass
                        elif token.endswith("ms") and len(token) > 2:
                            val_str = token[:-2].replace("<", "").replace(">", "").strip()
                            try:
                                rtt_vals.append(float(val_str))
                            except ValueError:
                                pass
                        elif token.count(".") == 3 and not token.endswith("ms"):
                            ip = token

                    measured_rtt = round(statistics.mean(rtt_vals), 2) if rtt_vals else None
                    hops.append({"hop": hop_num, "ip": ip or "Router", "rtt_ms": measured_rtt, "responsive": True})
                    last_responsive_hop = hop_num

        return (hops, last_responsive_hop)
    except Exception as e:
        logger.debug(f"Traceroute error: {e}")
        return ([], None)


# =====================================================================
# Local Buffer Management (for offline resilience)
# =====================================================================

def save_to_local_buffer(record: Dict[str, Any]):
    """Appends probe record to local buffer file if backend is down."""
    records = []
    if os.path.exists(BUFFER_FILE):
        try:
            with open(BUFFER_FILE, "r") as f:
                records = json.load(f)
        except Exception:
            records = []
    records.append(record)
    # Retain maximum 500 buffered records
    if len(records) > 500:
        records = records[-500:]
    with open(BUFFER_FILE, "w") as f:
        json.dump(records, f, indent=2)
    logger.warning(f"Backend unreachable. Saved probe to local buffer (Buffered: {len(records)} records).")


def flush_local_buffer(backend_url: str):
    """Flushes buffered records to backend once connection is restored."""
    if not os.path.exists(BUFFER_FILE):
        return
    try:
        with open(BUFFER_FILE, "r") as f:
            records = json.load(f)
        if not records:
            return

        logger.info(f"Attempting to flush {len(records)} buffered records to backend...")
        unsent = []
        for rec in records:
            try:
                resp = requests.post(f"{backend_url}/api/agent/report", json=rec, timeout=3.0)
                if resp.status_code != 200:
                    unsent.append(rec)
            except Exception:
                unsent.append(rec)

        if unsent:
            with open(BUFFER_FILE, "w") as f:
                json.dump(unsent, f, indent=2)
            logger.info(f"Flushed {len(records) - len(unsent)} records; {len(unsent)} still buffered.")
        else:
            os.remove(BUFFER_FILE)
            logger.info("Successfully flushed all buffered records!")
    except Exception as e:
        logger.debug(f"Buffer flush error: {e}")


# =====================================================================
# Main Monitoring Cycle
# =====================================================================

def run_agent(
    agent_id: str,
    backend_url: str,
    interval_sec: int = 10,
    test_domain: str = "google.com",
    external_ip: str = "1.1.1.1",
    simulate_fault: Optional[str] = None
):
    hostname = socket.gethostname()
    os_info = f"{platform.system()} {platform.release()}"
    gateway_ip = get_default_gateway() or "192.168.1.1"

    # Get local IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"

    logger.info("==================================================")
    logger.info(f"NetPulse Agent started: ID={agent_id}")
    logger.info(f"Host={hostname} ({local_ip}), OS={os_info}")
    logger.info(f"Default Gateway: {gateway_ip}")
    logger.info(f"Backend Server: {backend_url}")
    logger.info(f"Polling Interval: {interval_sec}s")
    if simulate_fault:
        logger.info(f"Static Fault Simulation Flag: {simulate_fault}")
    logger.info("==================================================")

    while True:
        try:
            # 0. Check if backend has active fault injection
            active_fault = simulate_fault
            try:
                fault_resp = requests.get(f"{backend_url}/api/fault/current", timeout=1.5)
                if fault_resp.status_code == 200:
                    fault_data = fault_resp.json()
                    target = fault_data.get("target_agent_id")
                    if target is None or target == agent_id:
                        ft = fault_data.get("fault_type", "NONE")
                        if ft != "NONE":
                            active_fault = ft
            except Exception:
                pass

            # 1. Probing: Default Gateway
            gw_ok, gw_rtt, gw_loss, _ = ping_host(gateway_ip, count=3, timeout_sec=1)

            # 2. Probing: Dual DNS Check
            local_dns_ok, local_dns_rtt = check_dns(test_domain, server=None, timeout_sec=2.0)
            public_dns_ok, public_dns_rtt = check_dns(test_domain, server="8.8.8.8", timeout_sec=2.0)

            # 3. Probing: External IP (Latency, Jitter, Loss)
            ext_ok, ext_latency, ext_loss, ext_jitter = ping_host(external_ip, count=4, timeout_sec=2)

            local_link_up = True
            traceroute_triggered = False
            traceroute_hops = None
            last_hop = None

            # ---------------------------------------------------------
            # Apply Fault Simulation (if active for demonstration)
            # ---------------------------------------------------------
            if active_fault == "RULE_1_NIC":
                local_link_up = False
                gw_ok = False
                ext_ok = False
                local_dns_ok = False
                public_dns_ok = False
                ext_loss = 100.0
                traceroute_triggered = True
                last_hop = None
                traceroute_hops = [
                    {"hop": 1, "ip": None, "rtt_ms": None, "responsive": False},
                ]
            elif active_fault == "RULE_2_ROUTER":
                gw_ok = False
                ext_ok = False
                ext_loss = 100.0
                traceroute_triggered = True
                last_hop = None
                traceroute_hops = [
                    {"hop": 1, "ip": None, "rtt_ms": None, "responsive": False},
                ]
            elif active_fault == "RULE_3_ISP":
                gw_ok = True
                ext_ok = False
                ext_loss = 100.0
                public_dns_ok = False
                traceroute_triggered = True
                last_hop = 1
                traceroute_hops = [
                    {"hop": 1, "ip": gateway_ip, "rtt_ms": gw_rtt or 1.5, "responsive": True},
                    {"hop": 2, "ip": None, "rtt_ms": None, "responsive": False},
                    {"hop": 3, "ip": None, "rtt_ms": None, "responsive": False},
                ]
            elif active_fault == "RULE_4_DNS":
                local_dns_ok = False
                public_dns_ok = True
                ext_ok = True
                gw_ok = True
            elif active_fault == "RULE_5_CONGESTION":
                gw_ok = True
                ext_ok = True
                ext_loss = 25.0
                ext_jitter = 48.0
                ext_latency = (ext_latency or 20.0) + 120.0
            elif active_fault == "RULE_6_PATH_BREAK":
                traceroute_triggered = True
                last_hop = 2
                traceroute_hops = [
                    {"hop": 1, "ip": gateway_ip, "rtt_ms": 2.1, "responsive": True},
                    {"hop": 2, "ip": "10.50.1.1", "rtt_ms": 14.5, "responsive": True},
                    {"hop": 3, "ip": None, "rtt_ms": None, "responsive": False},
                    {"hop": 4, "ip": None, "rtt_ms": None, "responsive": False},
                ]
                ext_ok = False
                ext_loss = 100.0

            # 4. Conditional Traceroute (if not simulated and checks fail)
            if not traceroute_triggered and (not ext_ok or not gw_ok or ext_loss >= 50.0):
                logger.info("Probe failure detected -> Triggering traceroute...")
                traceroute_triggered = True
                traceroute_hops, last_hop = run_traceroute(external_ip, max_hops=8)

            payload = {
                "agent_id": agent_id,
                "hostname": hostname,
                "ip_address": local_ip,
                "os_info": os_info,
                "default_gateway": gateway_ip,
                "timestamp": datetime.utcnow().isoformat(),
                "local_link_up": local_link_up,
                "gateway_ip": gateway_ip,
                "gateway_reachable": gw_ok,
                "gateway_rtt_ms": gw_rtt,
                "local_dns_ok": local_dns_ok,
                "local_dns_rtt_ms": local_dns_rtt,
                "public_dns_ok": public_dns_ok,
                "public_dns_rtt_ms": public_dns_rtt,
                "external_ip": external_ip,
                "external_reachable": ext_ok,
                "external_latency_ms": ext_latency,
                "external_jitter_ms": ext_jitter,
                "external_loss_pct": ext_loss,
                "traceroute_triggered": traceroute_triggered,
                "traceroute_target": external_ip if traceroute_triggered else None,
                "traceroute_hops": traceroute_hops,
                "last_responsive_hop": last_hop,
                "injected_fault": active_fault if active_fault != "NONE" else None
            }

            # 5. Report to Backend / Buffer if down
            try:
                resp = requests.post(f"{backend_url}/api/agent/report", json=payload, timeout=3.5)
                if resp.status_code == 200:
                    data = resp.json()
                    diag = data.get("probable_cause", "OK")
                    conf = data.get("confidence_pct", 100)
                    rule = data.get("rule_applied", "")
                    logger.info(
                        f"Report sent. Diagnosis: [{diag}] (Confidence: {conf}%, Rule: {rule}) | "
                        f"GW={'OK' if gw_ok else 'FAIL'}, DNS={'OK' if local_dns_ok else 'FAIL'}, "
                        f"Loss={ext_loss:.0f}%, RTT={ext_latency or 0:.1f}ms"
                    )
                    # Try to flush buffer if previous records were saved
                    flush_local_buffer(backend_url)
                else:
                    logger.warning(f"Backend HTTP {resp.status_code}. Saving to local buffer.")
                    save_to_local_buffer(payload)
            except Exception as e:
                logger.warning(f"Connection to {backend_url} failed: {e}. Buffering locally.")
                save_to_local_buffer(payload)

        except Exception as e:
            logger.error(f"Error in agent cycle: {e}")

        # Fast-react wake-up: sleep in 0.5s increments and check if fault state changed
        start_sleep = time.time()
        while time.time() - start_sleep < interval_sec:
            time.sleep(0.5)
            try:
                fault_resp = requests.get(f"{backend_url}/api/fault/current", timeout=0.8)
                if fault_resp.status_code == 200:
                    current_f = fault_resp.json().get("fault_type", "NONE")
                    if current_f != active_fault:
                        logger.info(f"Fault changed from '{active_fault}' to '{current_f}' -> Waking immediately!")
                        break
            except Exception:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NetPulse Intelligent Monitoring Agent")
    parser.add_argument("--agent-id", default=socket.gethostname().lower(), help="Unique agent identifier (e.g. host-1)")
    parser.add_argument("--backend-url", default="http://localhost:8000", help="NetPulse backend API URL")
    parser.add_argument("--interval", type=int, default=10, help="Polling interval in seconds (10-30s)")
    parser.add_argument("--test-domain", default="google.com", help="Domain for DNS checks")
    parser.add_argument("--external-ip", default="1.1.1.1", help="Target IP for external latency/loss probes")
    parser.add_argument(
        "--simulate-fault",
        choices=["NONE", "RULE_1_NIC", "RULE_2_ROUTER", "RULE_3_ISP", "RULE_4_DNS", "RULE_5_CONGESTION", "RULE_6_PATH_BREAK"],
        default=None,
        help="Simulate a specific fault locally for testing"
    )

    args = parser.parse_args()
    run_agent(
        agent_id=args.agent_id,
        backend_url=args.backend_url,
        interval_sec=args.interval,
        test_domain=args.test_domain,
        external_ip=args.external_ip,
        simulate_fault=args.simulate_fault
    )
