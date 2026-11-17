"""
NetPulse SNMP Poller
Reads ifInErrors, ifInDiscards, ifInOctets, and ifOutOctets where supported.
Calculates throughput from counter differences.
Gracefully handles devices without SNMP by recording 'N/A'.
"""

import time
import socket
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from server.database import SnmpStat

logger = logging.getLogger(__name__)

# Standard MIB-2 OIDs
OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2.1"
OID_IF_IN_OCTETS = "1.3.6.1.2.1.2.2.1.10.1"
OID_IF_OUT_OCTETS = "1.3.6.1.2.1.2.2.1.16.1"
OID_IF_IN_ERRORS = "1.3.6.1.2.1.2.2.1.14.1"
OID_IF_OUT_ERRORS = "1.3.6.1.2.1.2.2.1.20.1"
OID_IF_IN_DISCARDS = "1.3.6.1.2.1.2.2.1.13.1"
OID_IF_OUT_DISCARDS = "1.3.6.1.2.1.2.2.1.19.1"

_last_poll_state: Dict[str, Any] = {}


def poll_router_snmp(router_ip: str, community: str = "public", port: int = 161) -> Dict[str, Any]:
    """
    Attempts to poll router via SNMP. If host is unreachable or SNMP is disabled,
    returns an N/A status payload without throwing exceptions.
    """
    global _last_poll_state

    # First test UDP reachability quickly
    try:
        # Check if pysnmp is available
        from pysnmp.hlapi import (
            getCmd, SnmpEngine, CommunityData, UdpTransportTarget,
            ContextData, ObjectType, ObjectIdentity
        )
        
        errorIndication, errorStatus, errorIndex, varBinds = next(
            getCmd(
                SnmpEngine(),
                CommunityData(community, mpModel=1),  # SNMP v2c
                UdpTransportTarget((router_ip, port), timeout=1.0, retries=1),
                ContextData(),
                ObjectType(ObjectIdentity(OID_IF_IN_OCTETS)),
                ObjectType(ObjectIdentity(OID_IF_OUT_OCTETS)),
                ObjectType(ObjectIdentity(OID_IF_IN_ERRORS)),
                ObjectType(ObjectIdentity(OID_IF_IN_DISCARDS))
            )
        )

        if errorIndication or errorStatus:
            return {"is_available": False, "status_text": "N/A", "router_ip": router_ip}

        in_octets = int(varBinds[0][1])
        out_octets = int(varBinds[1][1])
        in_errors = int(varBinds[2][1])
        in_discards = int(varBinds[3][1])
        now = time.time()

        # Calculate throughput
        throughput_kbps = 0.0
        if router_ip in _last_poll_state:
            prev_time = _last_poll_state[router_ip]["time"]
            prev_in = _last_poll_state[router_ip]["in_octets"]
            prev_out = _last_poll_state[router_ip]["out_octets"]
            dt = max(1.0, now - prev_time)
            
            delta_bytes = max(0, (in_octets - prev_in) + (out_octets - prev_out))
            throughput_kbps = round((delta_bytes * 8) / (dt * 1000.0), 2)

        _last_poll_state[router_ip] = {
            "time": now,
            "in_octets": in_octets,
            "out_octets": out_octets
        }

        return {
            "is_available": True,
            "status_text": "Active",
            "router_ip": router_ip,
            "interface_name": "eth0",
            "in_octets": in_octets,
            "out_octets": out_octets,
            "in_errors": in_errors,
            "out_errors": 0,
            "in_discards": in_discards,
            "out_discards": 0,
            "throughput_kbps": throughput_kbps
        }

    except Exception as e:
        logger.debug(f"SNMP poll for {router_ip} unavailable: {e}")
        return {
            "is_available": False,
            "status_text": "N/A",
            "router_ip": router_ip
        }


def record_snmp_poll(db: Session, router_ip: str = "192.168.1.1") -> SnmpStat:
    """
    Polls the router and stores the record in database.
    """
    res = poll_router_snmp(router_ip)
    stat = SnmpStat(
        timestamp=datetime.utcnow(),
        device_ip=router_ip,
        is_available=res.get("is_available", False),
        interface_name=res.get("interface_name"),
        in_octets=res.get("in_octets"),
        out_octets=res.get("out_octets"),
        in_errors=res.get("in_errors"),
        out_errors=res.get("out_errors"),
        in_discards=res.get("in_discards"),
        out_discards=res.get("out_discards"),
        throughput_kbps=res.get("throughput_kbps"),
        status_text=res.get("status_text", "N/A")
    )
    db.add(stat)
    db.commit()
    db.refresh(stat)
    return stat
