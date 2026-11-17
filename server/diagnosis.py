"""
NetPulse Rule-Based Diagnosis Engine
Implements the exact fault diagnosis rules from Table 1 of the Project Synopsis:

1. One computer cannot reach the gateway, others can -> Computer Wi-Fi link, network card or cable
2. No computer can reach the gateway -> Router or switch failure
3. Gateway reachable, external IP unreachable -> ISP or WAN outage
4. External IP reachable, local resolver fails but 8.8.8.8 works -> DNS server problem
5. Everything responds, but loss or jitter is above threshold -> Congestion or degraded link
6. Traceroute stops at hop n and all later hops are silent -> Fault at or just after hop n
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from server.database import Agent, ProbeResult, DiagnosisRecord, SnmpStat

LOSS_THRESHOLD_PCT = 10.0      # Packet loss > 10% indicates congestion/degraded link
JITTER_THRESHOLD_MS = 30.0     # Jitter > 30ms indicates link jitter degradation
SLIDING_WINDOW_COUNT = 3       # Number of recent probe samples per agent to evaluate


class DiagnosisResult:
    def __init__(
        self,
        probable_cause: str,
        confidence_pct: int,
        fault_layer: str,
        summary_banner: str,
        evidence: List[str],
        affected_agents: List[str],
        total_agents: int,
        rule_applied: str,
        traceroute_detail: Optional[Dict[str, Any]] = None
    ):
        self.probable_cause = probable_cause
        self.confidence_pct = confidence_pct
        self.fault_layer = fault_layer
        self.summary_banner = summary_banner
        self.evidence = evidence
        self.affected_agents = affected_agents
        self.total_agents = total_agents
        self.rule_applied = rule_applied
        self.traceroute_detail = traceroute_detail

    def to_dict(self) -> Dict[str, Any]:
        return {
            "probable_cause": self.probable_cause,
            "confidence_pct": self.confidence_pct,
            "fault_layer": self.fault_layer,
            "summary_banner": self.summary_banner,
            "evidence": self.evidence,
            "affected_agents": self.affected_agents,
            "total_agents": self.total_agents,
            "rule_applied": self.rule_applied,
            "traceroute_detail": self.traceroute_detail,
        }


def get_latest_window(db: Session, window_size: int = SLIDING_WINDOW_COUNT) -> Dict[str, List[ProbeResult]]:
    """
    Retrieves the latest window of probe results grouped by agent.
    Only considers agents active in the last 2 minutes.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=2)
    active_agents = db.query(Agent).filter(Agent.last_seen >= cutoff, Agent.is_active == True).all()
    
    agent_windows: Dict[str, List[ProbeResult]] = {}
    for agent in active_agents:
        probes = (
            db.query(ProbeResult)
            .filter(ProbeResult.agent_id == agent.id)
            .order_by(ProbeResult.timestamp.desc())
            .limit(window_size)
            .all()
        )
        if probes:
            agent_windows[agent.id] = probes
            
    return agent_windows


def evaluate_rules(agent_windows: Dict[str, List[ProbeResult]], snmp_stat: Optional[SnmpStat] = None) -> DiagnosisResult:
    """
    Evaluates the sliding window of probe results against Table 1 rules.
    """
    total_agents = len(agent_windows)
    if total_agents == 0:
        return DiagnosisResult(
            probable_cause="No Active Agents",
            confidence_pct=0,
            fault_layer="NONE",
            summary_banner="No active monitoring agents reporting.",
            evidence=["No telemetry received in the active window."],
            affected_agents=[],
            total_agents=0,
            rule_applied="NO_DATA"
        )

    # Summarize each agent's latest window
    agent_summaries = {}
    for agent_id, probes in agent_windows.items():
        sample_count = len(probes)
        gw_fails = sum(1 for p in probes if not p.gateway_reachable or not p.local_link_up)
        ext_fails = sum(1 for p in probes if not p.external_reachable)
        dns_local_fails = sum(1 for p in probes if not p.local_dns_ok)
        dns_public_ok = sum(1 for p in probes if p.public_dns_ok)
        avg_loss = sum(p.external_loss_pct or 0.0 for p in probes) / sample_count
        avg_jitter = sum(p.external_jitter_ms or 0.0 for p in probes) / sample_count
        avg_latency = sum(p.external_latency_ms or 0.0 for p in probes) / sample_count

        # Latest probe for detailed state
        latest = probes[0]

        agent_summaries[agent_id] = {
            "gw_fail_ratio": gw_fails / sample_count,
            "ext_fail_ratio": ext_fails / sample_count,
            "dns_local_fail_ratio": dns_local_fails / sample_count,
            "dns_public_ok_ratio": dns_public_ok / sample_count,
            "avg_loss": avg_loss,
            "avg_jitter": avg_jitter,
            "avg_latency": avg_latency,
            "latest_probe": latest,
            "sample_count": sample_count
        }

    # Check failures in latest probe and across sliding window
    gw_failed_agents = [
        aid for aid, s in agent_summaries.items()
        if (not s["latest_probe"].gateway_reachable or not s["latest_probe"].local_link_up or s["gw_fail_ratio"] >= 0.3)
    ]
    
    # Agents with external unreachable while gateway is reachable
    wan_failed_agents = [
        aid for aid, s in agent_summaries.items()
        if (aid not in gw_failed_agents)
        and (not s["latest_probe"].external_reachable or s["ext_fail_ratio"] >= 0.3)
    ]
    
    # Agents with local DNS failing while external and public DNS succeed
    dns_failed_agents = [
        aid for aid, s in agent_summaries.items()
        if (aid not in gw_failed_agents) and (aid not in wan_failed_agents)
        and ((not s["latest_probe"].local_dns_ok and s["latest_probe"].public_dns_ok) or s["dns_local_fail_ratio"] >= 0.3)
    ]

    # Agents with congestion (high loss or high jitter)
    congested_agents = [
        aid for aid, s in agent_summaries.items()
        if (aid not in gw_failed_agents) and (aid not in wan_failed_agents) and (aid not in dns_failed_agents)
        and (
            (s["latest_probe"].external_loss_pct or 0) >= LOSS_THRESHOLD_PCT
            or (s["latest_probe"].external_jitter_ms or 0) >= JITTER_THRESHOLD_MS
            or s["avg_loss"] >= LOSS_THRESHOLD_PCT
        )
    ]

    # Check for active traceroute breakdowns
    traceroute_fail_agent = None
    traceroute_hops = None
    last_hop = None
    for aid, s in agent_summaries.items():
        latest = s["latest_probe"]
        if latest.traceroute_triggered and latest.traceroute_hops:
            traceroute_fail_agent = aid
            traceroute_hops = latest.traceroute_hops
            last_hop = latest.last_responsive_hop
            break

    # -------------------------------------------------------------
    # RULE 1: One computer cannot reach the gateway, the others can
    # -------------------------------------------------------------
    if total_agents > 1 and 0 < len(gw_failed_agents) < total_agents:
        confidence = int(min(95, 75 + (len(gw_failed_agents) / total_agents) * 10))
        affected_str = f"{len(gw_failed_agents)} of {total_agents} computers"
        return DiagnosisResult(
            probable_cause="Local Wi-Fi link, network card or cable failure",
            confidence_pct=confidence,
            fault_layer="LOCAL_LINK",
            summary_banner=f"Local NIC / Wi-Fi issue, {confidence}%, affecting {affected_str}",
            evidence=[
                f"Agent(s) {gw_failed_agents} failed to reach default gateway across sliding window.",
                f"Other monitored hosts on the same network reach the gateway normally.",
                "Default gateway router is operating normally for peer hosts."
            ],
            affected_agents=gw_failed_agents,
            total_agents=total_agents,
            rule_applied="RULE_1"
        )

    # Single-device variant of Rule 1: local link down (e.g. Wi-Fi disconnected / NIC unplugged)
    if total_agents == 1 and len(gw_failed_agents) == 1:
        latest = agent_summaries[gw_failed_agents[0]]["latest_probe"]
        if not latest.local_link_up:
            confidence = 95
            return DiagnosisResult(
                probable_cause="Local Wi-Fi link, network card or cable disconnected",
                confidence_pct=confidence,
                fault_layer="LOCAL_LINK",
                summary_banner=f"Local interface disconnected, {confidence}%, affecting 1 of 1 computer",
                evidence=[
                    f"Host interface {latest.agent_id} reported local link state DOWN.",
                    "Local loopback/adapter is disconnected from LAN."
                ],
                affected_agents=gw_failed_agents,
                total_agents=1,
                rule_applied="RULE_1"
            )

    # -------------------------------------------------------------
    # RULE 2: No computer can reach the gateway (all fail)
    # -------------------------------------------------------------
    if total_agents >= 1 and len(gw_failed_agents) == total_agents:
        confidence = 90 if total_agents > 1 else 80
        affected_str = f"{total_agents} of {total_agents} computers"
        evidence_list = [
            f"All {total_agents} reporting computers lost connectivity to default gateway.",
            "Local ICMP echo requests to the default gateway timed out repeatedly."
        ]
        if snmp_stat and snmp_stat.is_available and (snmp_stat.in_errors or 0) > 0:
            evidence_list.append(f"SNMP router interface reported {snmp_stat.in_errors} input errors.")
            confidence = 95

        return DiagnosisResult(
            probable_cause="Router or switch failure",
            confidence_pct=confidence,
            fault_layer="ROUTER_GATEWAY",
            summary_banner=f"Router or switch failure, {confidence}%, affecting {affected_str}",
            evidence=evidence_list,
            affected_agents=gw_failed_agents,
            total_agents=total_agents,
            rule_applied="RULE_2"
        )

    # -------------------------------------------------------------
    # RULE 6: Traceroute stops at hop n and all later hops are silent
    # -------------------------------------------------------------
    if traceroute_fail_agent and last_hop is not None and last_hop > 0:
        confidence = 88
        return DiagnosisResult(
            probable_cause=f"Upstream route fault at or just after hop {last_hop}",
            confidence_pct=confidence,
            fault_layer="ROUTING_PATH",
            summary_banner=f"Routing break after hop {last_hop}, {confidence}%, affecting {traceroute_fail_agent}",
            evidence=[
                f"Traceroute successfully reached hop {last_hop}.",
                f"All subsequent hops beyond hop {last_hop} timed out with 100% loss.",
                f"Target external destination remained unreachable."
            ],
            affected_agents=[traceroute_fail_agent],
            total_agents=total_agents,
            rule_applied="RULE_6",
            traceroute_detail={"last_hop": last_hop, "hops": traceroute_hops}
        )

    # -------------------------------------------------------------
    # RULE 3: Gateway reachable, external IP address unreachable
    # -------------------------------------------------------------
    if len(wan_failed_agents) > 0:
        # All or majority affected -> ISP/WAN outage
        ratio = len(wan_failed_agents) / total_agents
        confidence = int(min(95, 75 + ratio * 20))
        affected_str = f"{len(wan_failed_agents)} of {total_agents} computers"
        return DiagnosisResult(
            probable_cause="ISP or WAN outage",
            confidence_pct=confidence,
            fault_layer="ISP_WAN",
            summary_banner=f"ISP outage, {confidence}%, affecting {affected_str}",
            evidence=[
                "Default gateway answered ICMP echo requests with low latency.",
                "External destination IP (WAN) failed to reply (100% packet loss).",
                f"Outage consistently observed across {affected_str}."
            ],
            affected_agents=wan_failed_agents,
            total_agents=total_agents,
            rule_applied="RULE_3"
        )

    # -------------------------------------------------------------
    # RULE 4: External IP reachable, local resolver fails but 8.8.8.8 works
    # -------------------------------------------------------------
    if len(dns_failed_agents) > 0:
        ratio = len(dns_failed_agents) / total_agents
        confidence = int(min(95, 80 + ratio * 15))
        affected_str = f"{len(dns_failed_agents)} of {total_agents} computers"
        return DiagnosisResult(
            probable_cause="DNS server problem",
            confidence_pct=confidence,
            fault_layer="DNS",
            summary_banner=f"DNS server problem, {confidence}%, affecting {affected_str}",
            evidence=[
                "External IP connectivity is healthy (ping to external IP succeeds).",
                "Local DNS resolver failed to resolve test domain or timed out.",
                "Public fallback resolver (8.8.8.8) resolved domain successfully.",
                "Application-layer domain resolution is broken due to local resolver fault."
            ],
            affected_agents=dns_failed_agents,
            total_agents=total_agents,
            rule_applied="RULE_4"
        )

    # -------------------------------------------------------------
    # RULE 5: Everything responds, but loss or jitter is above the threshold
    # -------------------------------------------------------------
    if len(congested_agents) > 0:
        affected_str = f"{len(congested_agents)} of {total_agents} computers"
        sample_s = agent_summaries[congested_agents[0]]
        loss_val = sample_s["avg_loss"]
        jitter_val = sample_s["avg_jitter"]
        confidence = 85
        evidence_list = [
            f"All network nodes responded to probes.",
            f"Observed elevated packet loss: {loss_val:.1f}% (threshold: {LOSS_THRESHOLD_PCT}%).",
            f"Observed jitter: {jitter_val:.1f} ms (threshold: {JITTER_THRESHOLD_MS} ms)."
        ]
        if snmp_stat and snmp_stat.is_available and (snmp_stat.in_discards or 0) > 0:
            evidence_list.append(f"Router interface reports {snmp_stat.in_discards} discards (buffer overflow).")
            confidence = 92

        return DiagnosisResult(
            probable_cause="Network congestion or a degraded link",
            confidence_pct=confidence,
            fault_layer="CONGESTION",
            summary_banner=f"Network congestion / degraded link, {confidence}%, affecting {affected_str}",
            evidence=evidence_list,
            affected_agents=congested_agents,
            total_agents=total_agents,
            rule_applied="RULE_5"
        )

    # -------------------------------------------------------------
    # ALL HEALTHY
    # -------------------------------------------------------------
    # Check if all probes across window have zero failures
    healthy_agents = [
        aid for aid, s in agent_summaries.items()
        if s["gw_fail_ratio"] == 0.0 and s["ext_fail_ratio"] == 0.0
        and s["dns_local_fail_ratio"] == 0.0 and s["avg_loss"] < LOSS_THRESHOLD_PCT
    ]
    if len(healthy_agents) == total_agents:
        avg_rtt = sum(s["avg_latency"] for s in agent_summaries.values()) / total_agents
        return DiagnosisResult(
            probable_cause="Network Healthy",
            confidence_pct=98,
            fault_layer="NONE",
            summary_banner=f"All systems operational, 98% confidence ({total_agents} computer{'s' if total_agents > 1 else ''} reporting)",
            evidence=[
                "Default gateway ping is normal.",
                "Local DNS resolver is responding rapidly.",
                f"External internet latency is good (avg {avg_rtt:.1f} ms).",
                "0% packet loss across all active monitors."
            ],
            affected_agents=[],
            total_agents=total_agents,
            rule_applied="HEALTHY"
        )

    # -------------------------------------------------------------
    # FALLBACK: Cause Unclear
    # -------------------------------------------------------------
    return DiagnosisResult(
        probable_cause="Cause Unclear",
        confidence_pct=40,
        fault_layer="UNCLEAR",
        summary_banner="Network anomaly detected, cause unclear (confidence 40%)",
        evidence=[
            "Intermittent probe results detected across the sliding window.",
            "Symptoms do not definitively match a single root-cause rule.",
            "Further probe cycles required to settle diagnosis."
        ],
        affected_agents=list(agent_summaries.keys()),
        total_agents=total_agents,
        rule_applied="CAUSE_UNCLEAR"
    )


def run_diagnosis(db: Session) -> DiagnosisRecord:
    """
    Executes the diagnosis engine on current database state, logs the result,
    and returns the saved DiagnosisRecord.
    """
    windows = get_latest_window(db)
    
    # Check latest SNMP stat if available
    latest_snmp = db.query(SnmpStat).order_by(SnmpStat.timestamp.desc()).first()
    
    res = evaluate_rules(windows, latest_snmp)
    
    record = DiagnosisRecord(
        timestamp=datetime.utcnow(),
        probable_cause=res.probable_cause,
        confidence_pct=res.confidence_pct,
        fault_layer=res.fault_layer,
        summary_banner=res.summary_banner,
        evidence=res.evidence,
        affected_agents=res.affected_agents,
        total_agents=res.total_agents,
        rule_applied=res.rule_applied
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
