"""
NetPulse Backend API
Built with FastAPI & SQLite / PostgreSQL.
Implements:
- Ingest API for agent reports
- Diagnosis Engine execution and reporting
- Status chain aggregation per monitored computer
- Time-series telemetry metrics for charts
- Live Fault Injection controller for demonstration
- SNMP counter interface
"""

import os
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.database import init_db, get_db, Agent, ProbeResult, DiagnosisRecord, SnmpStat
from server.diagnosis import evaluate_rules, run_diagnosis, get_latest_window
from server.snmp_poller import record_snmp_poll, poll_router_snmp

app = FastAPI(
    title="NetPulse API",
    description="Intelligent Network Monitoring & Fault Diagnosis API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global active injected fault state (can be queried by agents to simulate faults easily)
_active_injected_fault: Dict[str, Any] = {
    "fault_type": "NONE",
    "params": {},
    "injected_at": None,
    "description": "No active fault injection. Live real network monitoring."
}


@app.on_event("startup")
def on_startup():
    init_db()


# =====================================================================
# Telemetry Ingest API
# =====================================================================

class HopModel(BaseModel):
    hop: int
    ip: Optional[str] = None
    rtt_ms: Optional[float] = None
    responsive: bool = True


class AgentReportPayload(BaseModel):
    agent_id: str
    hostname: str
    ip_address: Optional[str] = None
    os_info: Optional[str] = None
    default_gateway: Optional[str] = None
    timestamp: Optional[datetime] = None

    local_link_up: bool = True
    gateway_ip: Optional[str] = None
    gateway_reachable: bool = True
    gateway_rtt_ms: Optional[float] = None

    local_dns_ok: bool = True
    local_dns_rtt_ms: Optional[float] = None
    public_dns_ok: bool = True
    public_dns_rtt_ms: Optional[float] = None

    external_ip: str = "1.1.1.1"
    external_reachable: bool = True
    external_latency_ms: Optional[float] = None
    external_jitter_ms: Optional[float] = None
    external_loss_pct: float = 0.0

    traceroute_triggered: bool = False
    traceroute_target: Optional[str] = None
    traceroute_hops: Optional[List[Dict[str, Any]]] = None
    last_responsive_hop: Optional[int] = None
    injected_fault: Optional[str] = None


@app.post("/api/agent/report")
def ingest_agent_report(payload: AgentReportPayload, db: Session = Depends(get_db)):
    """
    Ingest endpoint: Receives periodic JSON telemetry from monitoring agents.
    Updates agent registry, stores probe record, and runs diagnosis engine.
    """
    now = datetime.utcnow()

    # 1. Update or create Agent
    agent = db.query(Agent).filter(Agent.id == payload.agent_id).first()
    if not agent:
        agent = Agent(
            id=payload.agent_id,
            hostname=payload.hostname,
            ip_address=payload.ip_address,
            os_info=payload.os_info,
            default_gateway=payload.default_gateway,
            registered_at=now,
            last_seen=now,
            is_active=True
        )
        db.add(agent)
    else:
        agent.hostname = payload.hostname
        if payload.ip_address:
            agent.ip_address = payload.ip_address
        if payload.default_gateway:
            agent.default_gateway = payload.default_gateway
        agent.last_seen = now
        agent.is_active = True

    # 2. Store ProbeResult
    probe = ProbeResult(
        agent_id=payload.agent_id,
        timestamp=payload.timestamp or now,
        local_link_up=payload.local_link_up,
        gateway_ip=payload.gateway_ip or payload.default_gateway,
        gateway_reachable=payload.gateway_reachable,
        gateway_rtt_ms=payload.gateway_rtt_ms,
        local_dns_ok=payload.local_dns_ok,
        local_dns_rtt_ms=payload.local_dns_rtt_ms,
        public_dns_ok=payload.public_dns_ok,
        public_dns_rtt_ms=payload.public_dns_rtt_ms,
        external_ip=payload.external_ip,
        external_reachable=payload.external_reachable,
        external_latency_ms=payload.external_latency_ms,
        external_jitter_ms=payload.external_jitter_ms,
        external_loss_pct=payload.external_loss_pct,
        traceroute_triggered=payload.traceroute_triggered,
        traceroute_target=payload.traceroute_target,
        traceroute_hops=payload.traceroute_hops,
        last_responsive_hop=payload.last_responsive_hop,
        injected_fault=payload.injected_fault
    )
    db.add(probe)
    db.commit()

    # 3. Trigger immediate diagnosis
    diag = run_diagnosis(db)

    return {
        "status": "success",
        "probe_id": probe.id,
        "probable_cause": diag.probable_cause,
        "confidence_pct": diag.confidence_pct,
        "rule_applied": diag.rule_applied
    }


# =====================================================================
# Diagnosis & Analytics APIs
# =====================================================================

@app.get("/api/diagnosis/latest")
def get_latest_diagnosis(db: Session = Depends(get_db)):
    """
    Returns the most recent diagnosis record and current status summary.
    """
    latest = db.query(DiagnosisRecord).order_by(DiagnosisRecord.timestamp.desc()).first()
    if not latest:
        # Run one immediately
        latest = run_diagnosis(db)

    return {
        "id": latest.id,
        "timestamp": latest.timestamp.isoformat(),
        "probable_cause": latest.probable_cause,
        "confidence_pct": latest.confidence_pct,
        "fault_layer": latest.fault_layer,
        "summary_banner": latest.summary_banner,
        "evidence": latest.evidence,
        "affected_agents": latest.affected_agents,
        "total_agents": latest.total_agents,
        "rule_applied": latest.rule_applied
    }


@app.get("/api/diagnosis/history")
def get_diagnosis_history(limit: int = 20, db: Session = Depends(get_db)):
    """
    Returns chronological history of diagnosis changes.
    """
    records = (
        db.query(DiagnosisRecord)
        .order_by(DiagnosisRecord.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat(),
            "probable_cause": r.probable_cause,
            "confidence_pct": r.confidence_pct,
            "fault_layer": r.fault_layer,
            "summary_banner": r.summary_banner,
            "evidence": r.evidence,
            "affected_agents": r.affected_agents,
            "total_agents": r.total_agents,
            "rule_applied": r.rule_applied
        }
        for r in records
    ]


@app.get("/api/agents")
def get_monitored_agents(active_only: bool = True, db: Session = Depends(get_db)):
    """
    Returns registered computers with their current 4-layer status chain.
    By default (active_only=True), filters to computers actively reporting in the last 3 minutes.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=3)
    query = db.query(Agent)
    if active_only:
        query = query.filter(Agent.last_seen >= cutoff)
    agents = query.order_by(Agent.last_seen.desc()).all()

    result = []
    for a in agents:
        latest_probe = (
            db.query(ProbeResult)
            .filter(ProbeResult.agent_id == a.id)
            .order_by(ProbeResult.timestamp.desc())
            .first()
        )

        is_online = a.last_seen >= cutoff

        # Compute status chain nodes
        if latest_probe and is_online:
            chain = {
                "local_link": {
                    "status": "UP" if latest_probe.local_link_up else "DOWN",
                    "details": "Interface Connected" if latest_probe.local_link_up else "Disconnected"
                },
                "gateway": {
                    "status": "UP" if latest_probe.gateway_reachable else "DOWN",
                    "ip": latest_probe.gateway_ip,
                    "rtt_ms": latest_probe.gateway_rtt_ms,
                    "details": f"{latest_probe.gateway_rtt_ms:.1f}ms RTT" if latest_probe.gateway_rtt_ms else "Unreachable"
                },
                "dns": {
                    "status": "UP" if latest_probe.local_dns_ok else ("DEGRADED" if latest_probe.public_dns_ok else "DOWN"),
                    "local_ok": latest_probe.local_dns_ok,
                    "public_ok": latest_probe.public_dns_ok,
                    "rtt_ms": latest_probe.local_dns_rtt_ms,
                    "details": "Local DNS OK" if latest_probe.local_dns_ok else ("Fallback 8.8.8.8 OK" if latest_probe.public_dns_ok else "DNS Failed")
                },
                "internet": {
                    "status": "UP" if (latest_probe.external_reachable and latest_probe.external_loss_pct < 10.0) else ("DEGRADED" if latest_probe.external_reachable else "DOWN"),
                    "ip": latest_probe.external_ip,
                    "latency_ms": latest_probe.external_latency_ms,
                    "jitter_ms": latest_probe.external_jitter_ms,
                    "loss_pct": latest_probe.external_loss_pct,
                    "details": f"{latest_probe.external_latency_ms:.1f}ms, {latest_probe.external_loss_pct:.0f}% loss" if latest_probe.external_latency_ms else "Unreachable"
                }
            }
        else:
            chain = {
                "local_link": {"status": "UNKNOWN", "details": "No Data"},
                "gateway": {"status": "UNKNOWN", "details": "No Data"},
                "dns": {"status": "UNKNOWN", "details": "No Data"},
                "internet": {"status": "UNKNOWN", "details": "No Data"}
            }

        result.append({
            "id": a.id,
            "hostname": a.hostname,
            "ip_address": a.ip_address,
            "os_info": a.os_info,
            "default_gateway": a.default_gateway,
            "last_seen": a.last_seen.isoformat(),
            "is_online": is_online,
            "status_chain": chain,
            "latest_probe": {
                "timestamp": latest_probe.timestamp.isoformat() if latest_probe else None,
                "external_latency_ms": latest_probe.external_latency_ms if latest_probe else None,
                "external_jitter_ms": latest_probe.external_jitter_ms if latest_probe else None,
                "external_loss_pct": latest_probe.external_loss_pct if latest_probe else 0.0,
                "traceroute_triggered": latest_probe.traceroute_triggered if latest_probe else False,
                "traceroute_hops": latest_probe.traceroute_hops if latest_probe else None,
                "last_responsive_hop": latest_probe.last_responsive_hop if latest_probe else None,
                "injected_fault": latest_probe.injected_fault if latest_probe else None
            } if latest_probe else None
        })

    return result


@app.get("/api/telemetry/metrics")
def get_telemetry_metrics(agent_id: Optional[str] = None, limit: int = 50, db: Session = Depends(get_db)):
    """
    Returns time-series metrics (RTT, Loss, Jitter) for live charts.
    """
    query = db.query(ProbeResult)
    if agent_id:
        query = query.filter(ProbeResult.agent_id == agent_id)

    probes = query.order_by(ProbeResult.timestamp.desc()).limit(limit).all()
    probes.reverse()  # Chronological order

    return [
        {
            "id": p.id,
            "agent_id": p.agent_id,
            "timestamp": p.timestamp.strftime("%H:%M:%S"),
            "latency_ms": round(p.external_latency_ms, 2) if p.external_latency_ms is not None else None,
            "jitter_ms": round(p.external_jitter_ms, 2) if p.external_jitter_ms is not None else None,
            "loss_pct": round(p.external_loss_pct, 1) if p.external_loss_pct is not None else 0.0,
            "gateway_rtt_ms": round(p.gateway_rtt_ms, 2) if p.gateway_rtt_ms is not None else None,
            "dns_rtt_ms": round(p.local_dns_rtt_ms, 2) if p.local_dns_rtt_ms is not None else None,
        }
        for p in probes
    ]


@app.get("/api/snmp/status")
def get_snmp_status(db: Session = Depends(get_db)):
    """
    Returns latest router SNMP polling metrics or N/A if unsupported.
    """
    latest = db.query(SnmpStat).order_by(SnmpStat.timestamp.desc()).first()
    if not latest:
        return {
            "status": "N/A",
            "is_available": False,
            "throughput_kbps": "N/A",
            "in_errors": "N/A",
            "in_discards": "N/A",
            "device_ip": "192.168.1.1",
            "note": "Router does not offer SNMP or SNMP is disabled. Shown as N/A per synopsis."
        }

    return {
        "status": latest.status_text,
        "is_available": latest.is_available,
        "throughput_kbps": f"{latest.throughput_kbps} kbps" if latest.throughput_kbps is not None else "N/A",
        "in_errors": latest.in_errors if latest.in_errors is not None else "N/A",
        "in_discards": latest.in_discards if latest.in_discards is not None else "N/A",
        "device_ip": latest.device_ip,
        "timestamp": latest.timestamp.isoformat()
    }


# =====================================================================
# Fault Injection & Evaluation Controller (For Lab Demo & Evaluation)
# =====================================================================

class FaultInjectRequest(BaseModel):
    fault_type: str  # "NONE", "RULE_1_NIC", "RULE_2_ROUTER", "RULE_3_ISP", "RULE_4_DNS", "RULE_5_CONGESTION", "RULE_6_PATH_BREAK"
    target_agent_id: Optional[str] = None  # None means all agents
    params: Optional[Dict[str, Any]] = None


@app.get("/api/fault/current")
def get_current_fault():
    """
    Agents poll this to know if a demonstration fault is currently injected.
    """
    return _active_injected_fault


@app.post("/api/fault/inject")
def inject_fault(req: FaultInjectRequest, db: Session = Depends(get_db)):
    """
    Live Demonstration Endpoint:
    Allows injecting any of the 6 fault conditions from Table 1 of the synopsis.
    """
    global _active_injected_fault

    descriptions = {
        "NONE": "Normal healthy network operation.",
        "RULE_1_NIC": "Simulating local Wi-Fi / NIC disconnection on one host.",
        "RULE_2_ROUTER": "Simulating default gateway router / local switch failure.",
        "RULE_3_ISP": "Simulating upstream ISP / WAN outage (gateway responds, WAN drops).",
        "RULE_4_DNS": "Simulating local DNS resolver outage (fallback 8.8.8.8 ok).",
        "RULE_5_CONGESTION": "Simulating severe link congestion (25% packet loss, 45ms jitter).",
        "RULE_6_PATH_BREAK": "Simulating routing break at hop 2 (all later hops silent)."
    }

    _active_injected_fault = {
        "fault_type": req.fault_type,
        "target_agent_id": req.target_agent_id,
        "params": req.params or {},
        "injected_at": datetime.utcnow().isoformat(),
        "description": descriptions.get(req.fault_type, "Custom fault simulation.")
    }

    return {
        "status": "injected",
        "fault": _active_injected_fault
    }


@app.post("/api/fault/clear")
def clear_fault():
    """
    Clears any active fault injection, returning system to real live probes.
    """
    global _active_injected_fault
    _active_injected_fault = {
        "fault_type": "NONE",
        "params": {},
        "injected_at": None,
        "description": "No active fault injection. Live real network monitoring."
    }
    return {"status": "cleared", "fault": _active_injected_fault}


@app.get("/api/health")
def health():
    return {"status": "ok", "app": "NetPulse Intelligent Network Monitor", "version": "1.0.0"}


# =====================================================================
# Frontend Auth & Dashboard v1 Compatibility Endpoints
# =====================================================================
from fastapi import Response, Request

@app.get("/api/v1/auth/csrf")
def auth_csrf(response: Response):
    response.set_cookie(key="XSRF-TOKEN", value="netpulse-csrf-valid-token", samesite="lax")
    return {"status": "ok"}


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/v1/auth/login")
def auth_login(req: LoginRequest, response: Response):
    response.set_cookie(key="XSRF-TOKEN", value="netpulse-csrf-valid-token", samesite="lax")
    return {
        "accessToken": "netpulse-demo-jwt-token",
        "expiresAt": (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z",
        "user": {
            "id": "1",
            "username": req.username or "admin",
            "role": "ADMIN"
        }
    }


@app.post("/api/v1/auth/refresh")
def auth_refresh():
    return {
        "accessToken": "netpulse-demo-jwt-token",
        "expiresAt": (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z",
        "user": {
            "id": "1",
            "username": "admin",
            "role": "ADMIN"
        }
    }


@app.post("/api/v1/auth/logout", status_code=204)
def auth_logout():
    return Response(status_code=204)


@app.get("/api/v1/system/info")
def system_info():
    return {"demoMode": False, "monitoringEnabled": True}


@app.get("/api/v1/dashboard/summary")
def get_dashboard_summary(db: Session = Depends(get_db)):
    cutoff = datetime.utcnow() - timedelta(minutes=3)
    active_agents = db.query(Agent).filter(Agent.last_seen >= cutoff, Agent.is_active == True).all()
    all_agents_count = db.query(Agent).count()
    
    # Active devices currently online
    total = len(active_agents) if active_agents else min(all_agents_count, 1)
    up = len(active_agents)
    down = max(0, total - up)

    recent_probes = db.query(ProbeResult).order_by(ProbeResult.timestamp.desc()).limit(100).all()
    avg_lat = None
    uptime_pct = 100.0
    if recent_probes:
        valid_lats = [p.external_latency_ms for p in recent_probes if p.external_latency_ms is not None]
        if valid_lats:
            avg_lat = round(sum(valid_lats) / len(valid_lats), 2)
        up_count = sum(1 for p in recent_probes if p.external_reachable and p.gateway_reachable)
        uptime_pct = round((up_count / len(recent_probes)) * 100.0, 1)

    diag = db.query(DiagnosisRecord).order_by(DiagnosisRecord.timestamp.desc()).first()

    return {
        "total": total,
        "up": up,
        "degraded": 0,
        "down": down,
        "unknown": 0,
        "paused": 0,
        "avgLatencyMs": avg_lat,
        "networkUptimePct": uptime_pct,
        "slowest": [],
        "recentChanges": [],
        "activeAlerts": 1 if (diag and diag.fault_layer not in ("NONE", "HEALTHY")) else 0,
        "recentAlerts": []
    }


@app.get("/api/v1/dashboard/latency")
def get_dashboard_latency(range: str = "1h", db: Session = Depends(get_db)):
    probes = db.query(ProbeResult).order_by(ProbeResult.timestamp.desc()).limit(30).all()
    probes.reverse()
    return [
        {
            "t": p.timestamp.isoformat() + "Z",
            "rttAvg": round(p.external_latency_ms, 2) if p.external_latency_ms is not None else None,
            "rttMin": round(p.external_latency_ms, 2) if p.external_latency_ms is not None else None,
            "rttMax": round(p.external_latency_ms, 2) if p.external_latency_ms is not None else None,
            "lossPct": p.external_loss_pct or 0.0,
            "jitter": p.external_jitter_ms or 0.0
        }
        for p in probes
    ]


# Alias /api/v1 endpoints to root /api endpoints for convenience
@app.get("/api/v1/diagnosis/latest")
def v1_diag_latest(db: Session = Depends(get_db)):
    return get_latest_diagnosis(db)

@app.get("/api/v1/agents")
def v1_agents(active_only: bool = True, db: Session = Depends(get_db)):
    return get_monitored_agents(active_only=active_only, db=db)

@app.get("/api/v1/telemetry/metrics")
def v1_metrics(db: Session = Depends(get_db)):
    return get_telemetry_metrics(db=db)

@app.post("/api/v1/fault/inject")
def v1_fault_inject(req: FaultInjectRequest, db: Session = Depends(get_db)):
    return inject_fault(req, db)

@app.post("/api/v1/fault/clear")
def v1_fault_clear():
    return clear_fault()

@app.get("/api/v1/fault/current")
def v1_fault_current():
    return get_current_fault()

@app.get("/api/v1/snmp/status")
def v1_snmp_status(db: Session = Depends(get_db)):
    return get_snmp_status(db)

