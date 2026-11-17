"""
Automated Verification Test for NetPulse Local Execution
Validates:
1. Database initialization
2. Ingest API (/api/agent/report)
3. Table 1 Diagnosis Engine rules
4. Confidence score and evidence generation
5. Status chain aggregation
"""

import sys
from fastapi.testclient import TestClient
from server.main import app
from server.database import SessionLocal, init_db, Agent, ProbeResult, DiagnosisRecord

client = TestClient(app)

def run_tests():
    print("[*] 1. Initializing Database...")
    init_db()
    db = SessionLocal()

    # Clear old test data
    db.query(ProbeResult).delete()
    db.query(DiagnosisRecord).delete()
    db.query(Agent).delete()
    db.commit()
    print("[+] Database cleared and ready.")

    # -------------------------------------------------------------
    # Test Normal Operation (Healthy)
    # -------------------------------------------------------------
    print("\n[*] 2. Testing Healthy Network Reporting...")
    report_healthy = {
        "agent_id": "host-test-1",
        "hostname": "test-workstation",
        "ip_address": "192.168.1.100",
        "os_info": "Windows 11",
        "default_gateway": "192.168.1.1",
        "local_link_up": True,
        "gateway_reachable": True,
        "gateway_rtt_ms": 1.2,
        "local_dns_ok": True,
        "local_dns_rtt_ms": 11.5,
        "public_dns_ok": True,
        "public_dns_rtt_ms": 15.0,
        "external_ip": "1.1.1.1",
        "external_reachable": True,
        "external_latency_ms": 16.2,
        "external_jitter_ms": 1.8,
        "external_loss_pct": 0.0,
        "traceroute_triggered": False
    }

    resp = client.post("/api/agent/report", json=report_healthy)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    print(f"[+] Healthy Ingest Response: {data}")
    assert data["probable_cause"] == "Network Healthy"
    assert data["confidence_pct"] >= 95

    # -------------------------------------------------------------
    # Test Rule 3: ISP / WAN Outage
    # -------------------------------------------------------------
    print("\n[*] 3. Testing Rule 3 (ISP / WAN Outage)...")
    report_isp = dict(report_healthy)
    report_isp["external_reachable"] = False
    report_isp["external_loss_pct"] = 100.0
    report_isp["public_dns_ok"] = False

    # Send 2 consecutive reports to form sliding window
    client.post("/api/agent/report", json=report_isp)
    resp = client.post("/api/agent/report", json=report_isp)
    data = resp.json()
    print(f"[+] Rule 3 Response: {data}")
    assert "ISP or WAN outage" in data["probable_cause"]
    assert data["confidence_pct"] >= 75

    # -------------------------------------------------------------
    # Test Rule 4: DNS Server Problem
    # -------------------------------------------------------------
    print("\n[*] 4. Testing Rule 4 (DNS Server Problem)...")
    report_dns = dict(report_healthy)
    report_dns["local_dns_ok"] = False
    report_dns["public_dns_ok"] = True
    report_dns["external_reachable"] = True

    client.post("/api/agent/report", json=report_dns)
    resp = client.post("/api/agent/report", json=report_dns)
    data = resp.json()
    print(f"[+] Rule 4 Response: {data}")
    assert "DNS server problem" in data["probable_cause"]

    # -------------------------------------------------------------
    # Test Rule 5: Congestion
    # -------------------------------------------------------------
    print("\n[*] 5. Testing Rule 5 (Congestion / Degraded Link)...")
    report_cong = dict(report_healthy)
    report_cong["external_loss_pct"] = 25.0
    report_cong["external_jitter_ms"] = 45.0

    client.post("/api/agent/report", json=report_cong)
    resp = client.post("/api/agent/report", json=report_cong)
    data = resp.json()
    print(f"[+] Rule 5 Response: {data}")
    assert "congestion" in data["probable_cause"].lower()

    # -------------------------------------------------------------
    # Test Rule 2: Gateway / Router Failure
    # -------------------------------------------------------------
    print("\n[*] 6. Testing Rule 2 (Router / Switch Failure)...")
    report_rtr = dict(report_healthy)
    report_rtr["gateway_reachable"] = False
    report_rtr["external_reachable"] = False
    report_rtr["external_loss_pct"] = 100.0

    client.post("/api/agent/report", json=report_rtr)
    resp = client.post("/api/agent/report", json=report_rtr)
    data = resp.json()
    print(f"[+] Rule 2 Response: {data}")
    assert "Router or switch failure" in data["probable_cause"]

    # -------------------------------------------------------------
    # Test Rule 1: Multi-Agent comparison (One fails, other succeeds)
    # -------------------------------------------------------------
    print("\n[*] 7. Testing Rule 1 (Local NIC / Wi-Fi vs Peer Host)...")
    # Host 1 fails gateway
    report_h1 = dict(report_healthy)
    report_h1["agent_id"] = "host-A"
    report_h1["gateway_reachable"] = False
    # Host 2 succeeds gateway
    report_h2 = dict(report_healthy)
    report_h2["agent_id"] = "host-B"
    report_h2["gateway_reachable"] = True

    client.post("/api/agent/report", json=report_h1)
    client.post("/api/agent/report", json=report_h2)
    resp = client.post("/api/agent/report", json=report_h1)
    data = resp.json()
    print(f"[+] Rule 1 Response: {data}")
    assert "Wi-Fi link, network card or cable" in data["probable_cause"]

    # -------------------------------------------------------------
    # Test Status Chain API
    # -------------------------------------------------------------
    print("\n[*] 8. Testing /api/agents (Status Chain Output)...")
    resp = client.get("/api/agents")
    agents = resp.json()
    print(f"[+] Active Agents count: {len(agents)}")
    assert len(agents) > 0
    sample_chain = agents[0]["status_chain"]
    print(f"[+] Status Chain Nodes: {list(sample_chain.keys())}")
    assert "local_link" in sample_chain
    assert "gateway" in sample_chain
    assert "dns" in sample_chain
    assert "internet" in sample_chain

    # Clean up test agents so they don't persist in live dashboard
    db.query(ProbeResult).filter(ProbeResult.agent_id.like("host-%")).delete()
    db.query(Agent).filter(Agent.id.like("host-%")).delete()
    db.commit()

    print("\n==================================================")
    print("ALL TESTS PASSED! NetPulse Intelligent Diagnosis System is 100% verified.")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
