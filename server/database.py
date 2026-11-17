"""
Database models and session management for NetPulse.
Supports SQLite (for instant local zero-config testing) and PostgreSQL.
"""

import os
from datetime import datetime
from typing import Optional
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./netpulse.db")

# SQLite needs check_same_thread=False
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Agent(Base):
    __tablename__ = "agents"

    id = Column(String(64), primary_key=True, index=True)
    hostname = Column(String(128), nullable=False)
    ip_address = Column(String(64), nullable=True)
    os_info = Column(String(128), nullable=True)
    default_gateway = Column(String(64), nullable=True)
    registered_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow, index=True)
    is_active = Column(Boolean, default=True)

    probes = relationship("ProbeResult", back_populates="agent", cascade="all, delete-orphan")


class ProbeResult(Base):
    __tablename__ = "probe_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(64), ForeignKey("agents.id"), index=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    # Local link / interface status
    local_link_up = Column(Boolean, default=True)
    
    # Default Gateway ping
    gateway_ip = Column(String(64), nullable=True)
    gateway_reachable = Column(Boolean, default=True)
    gateway_rtt_ms = Column(Float, nullable=True)

    # DNS check (local resolver vs 8.8.8.8)
    local_dns_ok = Column(Boolean, default=True)
    local_dns_rtt_ms = Column(Float, nullable=True)
    public_dns_ok = Column(Boolean, default=True)
    public_dns_rtt_ms = Column(Float, nullable=True)

    # External IP check (e.g. 1.1.1.1 or 8.8.8.8)
    external_ip = Column(String(64), default="1.1.1.1")
    external_reachable = Column(Boolean, default=True)
    external_latency_ms = Column(Float, nullable=True)
    external_jitter_ms = Column(Float, nullable=True)
    external_loss_pct = Column(Float, default=0.0)

    # Traceroute details (stored when checks fail or on request)
    traceroute_triggered = Column(Boolean, default=False)
    traceroute_target = Column(String(128), nullable=True)
    traceroute_hops = Column(JSON, nullable=True)  # List of {hop, ip, rtt_ms, responsive}
    last_responsive_hop = Column(Integer, nullable=True)

    # Injected fault label (if active during probe)
    injected_fault = Column(String(64), nullable=True)

    agent = relationship("Agent", back_populates="probes")


class DiagnosisRecord(Base):
    __tablename__ = "diagnoses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    probable_cause = Column(String(256), nullable=False)
    confidence_pct = Column(Integer, nullable=False)  # e.g. 85 for 85%
    fault_layer = Column(String(64), nullable=False)  # "LOCAL_LINK", "ROUTER_GATEWAY", "ISP_WAN", "DNS", "CONGESTION", "NONE", "UNCLEAR"
    summary_banner = Column(String(512), nullable=False)
    evidence = Column(JSON, nullable=False)  # list of bullet points / evidence observations
    affected_agents = Column(JSON, nullable=False)  # list of agent IDs
    total_agents = Column(Integer, default=1)
    rule_applied = Column(String(64), nullable=True)  # "RULE_1", "RULE_2", ..., "HEALTHY", "UNCLEAR"


class SnmpStat(Base):
    __tablename__ = "snmp_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    device_ip = Column(String(64), nullable=False)
    is_available = Column(Boolean, default=False)
    interface_name = Column(String(64), nullable=True)
    in_octets = Column(Float, nullable=True)
    out_octets = Column(Float, nullable=True)
    in_errors = Column(Integer, nullable=True)
    out_errors = Column(Integer, nullable=True)
    in_discards = Column(Integer, nullable=True)
    out_discards = Column(Integer, nullable=True)
    throughput_kbps = Column(Float, nullable=True)
    status_text = Column(String(64), default="N/A")


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
