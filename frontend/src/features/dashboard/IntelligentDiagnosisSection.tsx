import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Activity,
  Wifi,
  Router as RouterIcon,
  Globe,
  Database,
  ArrowRight,
  RotateCcw,
  ShieldCheck,
  Server,
  Network
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Panel } from "@/components/common";

interface StatusNode {
  status: "UP" | "DOWN" | "DEGRADED" | "UNKNOWN";
  details?: string;
  ip?: string;
  rtt_ms?: number;
  latency_ms?: number;
  loss_pct?: number;
  jitter_ms?: number;
  local_ok?: boolean;
  public_ok?: boolean;
}

interface AgentData {
  id: string;
  hostname: string;
  ip_address: string;
  os_info: string;
  default_gateway: string;
  last_seen: string;
  is_online: boolean;
  status_chain: {
    local_link: StatusNode;
    gateway: StatusNode;
    dns: StatusNode;
    internet: StatusNode;
  };
  latest_probe?: {
    timestamp: string;
    external_latency_ms?: number;
    external_jitter_ms?: number;
    external_loss_pct?: number;
    traceroute_triggered?: boolean;
    traceroute_hops?: Array<{ hop: number; ip?: string; rtt_ms?: number; responsive: boolean }>;
    last_responsive_hop?: number;
    injected_fault?: string;
  };
}

interface DiagnosisData {
  id: number;
  timestamp: string;
  probable_cause: string;
  confidence_pct: number;
  fault_layer: string;
  summary_banner: string;
  evidence: string[];
  affected_agents: string[];
  total_agents: number;
  rule_applied: string;
}

interface SnmpData {
  status: string;
  is_available: boolean;
  throughput_kbps: string;
  in_errors: string | number;
  in_discards: string | number;
  device_ip: string;
  note?: string;
}

export function IntelligentDiagnosisSection() {
  const qc = useQueryClient();

  const diagnosis = useQuery<DiagnosisData>({
    queryKey: ["diagnosis", "latest"],
    queryFn: async () => {
      const res = await fetch("/api/v1/diagnosis/latest");
      return res.json();
    },
    refetchInterval: 1500,
  });

  const agents = useQuery<AgentData[]>({
    queryKey: ["agents", "list"],
    queryFn: async () => {
      const res = await fetch("/api/v1/agents");
      return res.json();
    },
    refetchInterval: 1500,
  });

  const snmp = useQuery<SnmpData>({
    queryKey: ["snmp", "status"],
    queryFn: async () => {
      const res = await fetch("/api/v1/snmp/status");
      return res.json();
    },
    refetchInterval: 10000,
  });

  const injectFault = useMutation({
    mutationFn: async (fault_type: string) => {
      const res = await fetch("/api/v1/fault/inject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fault_type }),
      });
      return res.json();
    },
    onSuccess: (data) => {
      toast.success(`Injected: ${data.fault.description}`);
      qc.invalidateQueries({ queryKey: ["diagnosis"] });
      qc.invalidateQueries({ queryKey: ["agents"] });
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["diagnosis"] });
        qc.invalidateQueries({ queryKey: ["agents"] });
      }, 1000);
    },
    onError: () => toast.error("Failed to inject fault"),
  });

  const clearFault = useMutation({
    mutationFn: async () => {
      const res = await fetch("/api/v1/fault/clear", { method: "POST" });
      return res.json();
    },
    onSuccess: () => {
      toast.info("Cleared fault injection. Resumed real live network telemetry.");
      qc.invalidateQueries({ queryKey: ["diagnosis"] });
      qc.invalidateQueries({ queryKey: ["agents"] });
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["diagnosis"] });
        qc.invalidateQueries({ queryKey: ["agents"] });
      }, 1000);
    },
  });

  const diag = diagnosis.data;
  const isHealthy = diag?.rule_applied === "HEALTHY" || diag?.fault_layer === "NONE";
  const isFault = diag && !isHealthy && diag.rule_applied !== "NO_DATA";

  return (
    <div className="space-y-4">
      {/* 1. Intelligent Diagnosis Banner (Report Figure 1 & Section 2) */}
      <div
        className={`rounded-xl border p-5 transition-all shadow-sm ${
          isHealthy
            ? "border-emerald-500/30 bg-emerald-950/10 dark:bg-emerald-950/20"
            : isFault
            ? "border-rose-500/40 bg-rose-950/15 dark:bg-rose-950/25"
            : "border-border bg-card"
        }`}
      >
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="flex items-start gap-3.5">
            <div
              className={`mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${
                isHealthy
                  ? "bg-emerald-500/15 text-emerald-500"
                  : isFault
                  ? "bg-rose-500/15 text-rose-500 animate-pulse"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              {isHealthy ? (
                <ShieldCheck className="h-6 w-6" />
              ) : isFault ? (
                <AlertTriangle className="h-6 w-6" />
              ) : (
                <Activity className="h-6 w-6" />
              )}
            </div>

            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold tracking-wider uppercase text-muted-foreground">
                  Intelligent Fault Diagnosis Engine
                </span>
                {diag?.rule_applied && (
                  <span className="rounded bg-muted px-2 py-0.5 font-mono text-[11px] font-medium text-foreground">
                    {diag.rule_applied}
                  </span>
                )}
                {diag && (
                  <span
                    className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                      diag.confidence_pct >= 80
                        ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                        : diag.confidence_pct >= 50
                        ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                        : "bg-muted text-muted-foreground"
                    }`}
                  >
                    {diag.confidence_pct}% Confidence
                  </span>
                )}
              </div>

              <h2 className="mt-1 text-xl font-bold tracking-tight">
                {diag?.probable_cause || "Analyzing live telemetry..."}
              </h2>
              <p className="mt-0.5 text-sm font-medium text-muted-foreground">
                {diag?.summary_banner}
              </p>

              {/* Evidence details */}
              {diag?.evidence && diag.evidence.length > 0 && (
                <div className="mt-3 rounded-lg border bg-background/50 p-3">
                  <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Root-Cause Evidence:
                  </p>
                  <ul className="mt-1.5 space-y-1 text-xs">
                    {diag.evidence.map((item, idx) => (
                      <li key={idx} className="flex items-start gap-2">
                        <span className="text-primary">•</span>
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2 pt-1 text-xs text-muted-foreground">
            <span className="inline-block h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            <span>Live Probing (10s)</span>
          </div>
        </div>
      </div>

      {/* 2. Interactive Fault Injection Bar (Deliverable 2: Live Demonstration) */}
      <Panel
        title="Live Fault Injection Controller (Synopsis Lab Demo)"
        action={
          <Button
            size="sm"
            variant="outline"
            onClick={() => clearFault.mutate()}
            disabled={clearFault.isPending}
            className="gap-1.5"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Restore Real Network
          </Button>
        }
      >
        <div className="p-4">
          <p className="text-xs text-muted-foreground mb-3">
            Inject simulated network anomalies to test and evaluate the 6 diagnosis rules in real time.
          </p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <Button
              variant="outline"
              size="sm"
              className="flex flex-col h-auto py-2.5 px-3 items-start text-left border-rose-500/20 hover:border-rose-500/50 hover:bg-rose-500/5"
              onClick={() => injectFault.mutate("RULE_1_NIC")}
            >
              <span className="font-semibold text-xs flex items-center gap-1.5 text-foreground">
                <Wifi className="h-3.5 w-3.5 text-rose-500" /> Rule 1
              </span>
              <span className="text-[11px] text-muted-foreground mt-0.5">Wi-Fi / NIC Drop</span>
            </Button>

            <Button
              variant="outline"
              size="sm"
              className="flex flex-col h-auto py-2.5 px-3 items-start text-left border-rose-500/20 hover:border-rose-500/50 hover:bg-rose-500/5"
              onClick={() => injectFault.mutate("RULE_2_ROUTER")}
            >
              <span className="font-semibold text-xs flex items-center gap-1.5 text-foreground">
                <RouterIcon className="h-3.5 w-3.5 text-rose-500" /> Rule 2
              </span>
              <span className="text-[11px] text-muted-foreground mt-0.5">Router Down</span>
            </Button>

            <Button
              variant="outline"
              size="sm"
              className="flex flex-col h-auto py-2.5 px-3 items-start text-left border-rose-500/20 hover:border-rose-500/50 hover:bg-rose-500/5"
              onClick={() => injectFault.mutate("RULE_3_ISP")}
            >
              <span className="font-semibold text-xs flex items-center gap-1.5 text-foreground">
                <Globe className="h-3.5 w-3.5 text-rose-500" /> Rule 3
              </span>
              <span className="text-[11px] text-muted-foreground mt-0.5">ISP / WAN Outage</span>
            </Button>

            <Button
              variant="outline"
              size="sm"
              className="flex flex-col h-auto py-2.5 px-3 items-start text-left border-rose-500/20 hover:border-rose-500/50 hover:bg-rose-500/5"
              onClick={() => injectFault.mutate("RULE_4_DNS")}
            >
              <span className="font-semibold text-xs flex items-center gap-1.5 text-foreground">
                <Database className="h-3.5 w-3.5 text-rose-500" /> Rule 4
              </span>
              <span className="text-[11px] text-muted-foreground mt-0.5">DNS Server Fault</span>
            </Button>

            <Button
              variant="outline"
              size="sm"
              className="flex flex-col h-auto py-2.5 px-3 items-start text-left border-amber-500/20 hover:border-amber-500/50 hover:bg-amber-500/5"
              onClick={() => injectFault.mutate("RULE_5_CONGESTION")}
            >
              <span className="font-semibold text-xs flex items-center gap-1.5 text-foreground">
                <Activity className="h-3.5 w-3.5 text-amber-500" /> Rule 5
              </span>
              <span className="text-[11px] text-muted-foreground mt-0.5">Congestion & Jitter</span>
            </Button>

            <Button
              variant="outline"
              size="sm"
              className="flex flex-col h-auto py-2.5 px-3 items-start text-left border-rose-500/20 hover:border-rose-500/50 hover:bg-rose-500/5"
              onClick={() => injectFault.mutate("RULE_6_PATH_BREAK")}
            >
              <span className="font-semibold text-xs flex items-center gap-1.5 text-foreground">
                <Network className="h-3.5 w-3.5 text-rose-500" /> Rule 6
              </span>
              <span className="text-[11px] text-muted-foreground mt-0.5">Traceroute Break</span>
            </Button>
          </div>
        </div>
      </Panel>

      {/* 3. Monitored Computers & 4-Layer Status Chain (Report Figure 1) */}
      <Panel title="Monitored Endpoint Computers & Status Chain">
        <div className="p-4 space-y-4">
          <p className="text-xs text-muted-foreground -mt-1 mb-2">
            Packets path outwards: Local Link &rarr; Gateway &rarr; DNS Resolver &rarr; Internet (WAN).
          </p>
          {agents.isLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : !agents.data || agents.data.length === 0 ? (
            <div className="rounded-lg border border-dashed p-8 text-center">
              <Server className="mx-auto h-8 w-8 text-muted-foreground" />
              <h3 className="mt-2 text-sm font-semibold">No Monitored Agents Connected</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                Start your local agent with:{" "}
                <code className="bg-muted px-1.5 py-0.5 rounded font-mono text-primary">
                  python agent/agent.py
                </code>
              </p>
            </div>
          ) : (
            agents.data.map((agent) => (
              <div key={agent.id} className="rounded-lg border bg-card/60 p-4 shadow-xs">
                {/* Agent Header */}
                <div className="flex flex-wrap items-center justify-between gap-2 border-b pb-3 mb-4">
                  <div className="flex items-center gap-2.5">
                    <span
                      className={`h-2.5 w-2.5 rounded-full ${
                        agent.is_online ? "bg-emerald-500" : "bg-zinc-400"
                      }`}
                    />
                    <span className="font-semibold text-sm">{agent.hostname}</span>
                    <span className="font-mono text-xs text-muted-foreground">
                      ({agent.ip_address || "127.0.0.1"})
                    </span>
                    <span className="rounded bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                      {agent.os_info}
                    </span>
                    {agent.latest_probe?.injected_fault && (
                      <span className="rounded bg-rose-500/10 text-rose-500 border border-rose-500/20 px-2 py-0.5 text-[10px] font-mono">
                        Fault: {agent.latest_probe.injected_fault}
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Gateway: <span className="font-mono text-foreground">{agent.default_gateway}</span>
                  </div>
                </div>

                {/* Status Chain Flow */}
                <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
                  {/* Layer 1: Local Link */}
                  <ChainNode
                    title="1. Local Link / Wi-Fi"
                    icon={Wifi}
                    node={agent.status_chain.local_link}
                  />

                  {/* Layer 2: Default Gateway */}
                  <ChainNode
                    title="2. Default Gateway"
                    icon={RouterIcon}
                    node={agent.status_chain.gateway}
                  />

                  {/* Layer 3: DNS Resolver */}
                  <ChainNode
                    title="3. DNS Resolver"
                    icon={Database}
                    node={agent.status_chain.dns}
                  />

                  {/* Layer 4: Internet (WAN) */}
                  <ChainNode
                    title="4. Internet (WAN)"
                    icon={Globe}
                    node={agent.status_chain.internet}
                  />
                </div>

                {/* Conditional Traceroute Path View (if triggered) */}
                {agent.latest_probe?.traceroute_triggered && agent.latest_probe.traceroute_hops && (
                  <div className="mt-4 rounded-md border bg-muted/30 p-3 text-xs">
                    <div className="flex items-center justify-between font-semibold mb-2">
                      <span className="flex items-center gap-1.5 text-foreground">
                        <Network className="h-4 w-4 text-primary" /> Active Traceroute Path
                      </span>
                      {agent.latest_probe.last_responsive_hop && (
                        <span className="text-rose-500">
                          Route stopped after Hop {agent.latest_probe.last_responsive_hop}
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {agent.latest_probe.traceroute_hops.map((h, i) => (
                        <div key={i} className="flex items-center gap-1">
                          <div
                            className={`px-2 py-1 rounded text-[11px] font-mono border ${
                              h.responsive
                                ? "bg-card border-border text-foreground"
                                : "bg-rose-500/10 border-rose-500/30 text-rose-500 font-bold"
                            }`}
                          >
                            Hop {h.hop}: {h.responsive ? (h.ip || "Router") : "* (Timed Out)"}
                          </div>
                          {i < (agent.latest_probe?.traceroute_hops?.length ?? 0) - 1 && (
                            <ArrowRight className="h-3 w-3 text-muted-foreground shrink-0" />
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </Panel>

      {/* 4. SNMP Router Counters (Report Section 2 & Page 3) */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Router / Switch SNMP Counters">
          <div className="p-4 space-y-3">
            <p className="text-xs text-muted-foreground -mt-1 mb-2">
              Monitors interface throughput, packet errors, and discards (shows N/A when unsupported).
            </p>
            <div className="flex items-center justify-between border-b pb-2 text-xs">
              <span className="text-muted-foreground">SNMP Target</span>
              <span className="font-mono font-medium">{snmp.data?.device_ip || "192.168.1.1"}</span>
            </div>
            <div className="flex items-center justify-between border-b pb-2 text-xs">
              <span className="text-muted-foreground">Interface Status</span>
              <span className="font-medium">{snmp.data?.status || "N/A"}</span>
            </div>
            <div className="flex items-center justify-between border-b pb-2 text-xs">
              <span className="text-muted-foreground">Throughput</span>
              <span className="font-mono font-medium">{snmp.data?.throughput_kbps || "N/A"}</span>
            </div>
            <div className="flex items-center justify-between border-b pb-2 text-xs">
              <span className="text-muted-foreground">Input Errors</span>
              <span className="font-mono font-medium">{snmp.data?.in_errors ?? "N/A"}</span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Input Discards</span>
              <span className="font-mono font-medium">{snmp.data?.in_discards ?? "N/A"}</span>
            </div>
            {snmp.data?.note && (
              <p className="mt-2 text-[11px] text-muted-foreground italic">
                {snmp.data.note}
              </p>
            )}
          </div>
        </Panel>

        <Panel title="Synopsis Diagnosis Rule Map">
          <div className="p-4 space-y-2 text-xs">
            <p className="text-xs text-muted-foreground -mt-1 mb-2">
              Inference logic implemented directly from Table 1.
            </p>
            <div className="flex items-start gap-2">
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">Rule 1</span>
              <span>One host fails gateway, peers succeed &rarr; <strong>Host Wi-Fi / NIC fault</strong></span>
            </div>
            <div className="flex items-start gap-2">
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">Rule 2</span>
              <span>All hosts fail gateway &rarr; <strong>Router or switch failure</strong></span>
            </div>
            <div className="flex items-start gap-2">
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">Rule 3</span>
              <span>Gateway OK, external IP down &rarr; <strong>ISP or WAN outage</strong></span>
            </div>
            <div className="flex items-start gap-2">
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">Rule 4</span>
              <span>External IP OK, local DNS fails, 8.8.8.8 OK &rarr; <strong>DNS server problem</strong></span>
            </div>
            <div className="flex items-start gap-2">
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">Rule 5</span>
              <span>All respond, but loss &gt; 10% or jitter &gt; 30ms &rarr; <strong>Congestion / degraded link</strong></span>
            </div>
            <div className="flex items-start gap-2">
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">Rule 6</span>
              <span>Traceroute stops at hop N, later silent &rarr; <strong>Fault at / after hop N</strong></span>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function ChainNode({
  title,
  icon: Icon,
  node,
}: {
  title: string;
  icon: any;
  node: StatusNode;
}) {
  const isUp = node.status === "UP";
  const isDown = node.status === "DOWN";
  const isDegraded = node.status === "DEGRADED";

  return (
    <div
      className={`rounded-lg border p-3 transition-colors ${
        isUp
          ? "border-emerald-500/25 bg-emerald-500/5 dark:bg-emerald-950/15"
          : isDown
          ? "border-rose-500/35 bg-rose-500/10 dark:bg-rose-950/25"
          : isDegraded
          ? "border-amber-500/30 bg-amber-500/10 dark:bg-amber-950/20"
          : "border-border bg-card/40"
      }`}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-muted-foreground flex items-center gap-1.5">
          <Icon className="h-3.5 w-3.5" />
          {title}
        </span>
        {isUp ? (
          <CheckCircle2 className="h-4 w-4 text-emerald-500" />
        ) : isDown ? (
          <XCircle className="h-4 w-4 text-rose-500" />
        ) : isDegraded ? (
          <AlertTriangle className="h-4 w-4 text-amber-500" />
        ) : (
          <span className="h-2 w-2 rounded-full bg-zinc-400" />
        )}
      </div>

      <div className="mt-2 font-mono text-xs font-bold">
        {node.status}
      </div>
      <p className="mt-0.5 truncate text-[11px] text-muted-foreground font-mono">
        {node.details || "—"}
      </p>
    </div>
  );
}
