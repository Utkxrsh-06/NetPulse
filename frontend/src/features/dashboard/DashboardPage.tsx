import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BellOff, ChartLine, History, Plus, Server } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/AuthContext";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader, Panel, RelativeTime, RowsSkeleton, SeverityBadge, StatusBadge } from "@/components/common";
import { MetricChart, RangePicker } from "@/components/charts";
import { api } from "@/lib/api";
import { fmtMs, fmtPct } from "@/lib/format";
import type { DashboardSummary, MetricPoint, Range } from "@/lib/types";
import { IntelligentDiagnosisSection } from "./IntelligentDiagnosisSection";

function Kpi({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1.5 text-2xl font-semibold tabular-nums tracking-tight">{value}</p>
      <p className="mt-0.5 h-4 text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}

export function DashboardPage() {
  const [range, setRange] = useState<Range>("1h");
  const canWrite = useAuth().user?.role !== "VIEWER";
  const summary = useQuery({ queryKey: ["dashboard", "summary"], queryFn: () => api<DashboardSummary>("/dashboard/summary"), refetchInterval: 30_000 });
  const latency = useQuery({ queryKey: ["dashboard", "latency", range], queryFn: () => api<MetricPoint[]>(`/dashboard/latency?range=${range}`), refetchInterval: 30_000 });
  const s = summary.data;

  return (
    <>
      <PageHeader title="Dashboard" description="Live state of everything NetPulse monitors."
        action={canWrite ? <Button asChild size="sm"><Link to="/devices?new=1"><Plus /> Add device</Link></Button> : undefined} />

      {summary.isError ? (
        <Panel><ErrorState message={summary.error.message} onRetry={() => summary.refetch()} /></Panel>
      ) : !s ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-[104px]" />)}</div>
      ) : (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
          <Kpi label="Total devices" value={s.total} hint={s.paused ? `${s.paused} paused` : undefined} />
          <Kpi label="Up" value={s.up} hint={s.degraded ? `${s.degraded} degraded` : undefined} />
          <Kpi label="Down" value={s.down} hint={s.unknown ? `${s.unknown} unknown` : undefined} />
          <Kpi label="Active alerts" value={s.activeAlerts} hint="open right now" />
          <Kpi label="Avg latency" value={fmtMs(s.avgLatencyMs)} hint="latest ping, all devices" />
          <Kpi label="Network uptime" value={fmtPct(s.networkUptimePct, 2)} hint="last 24 hours" />
        </div>
      )}

      <div className="mt-4">
        <IntelligentDiagnosisSection />
      </div>

      <Panel title="Average latency" className="mt-4" action={<RangePicker value={range} onChange={setRange} />}>
        <div className="p-4">
          {latency.isError ? <ErrorState message={latency.error.message} onRetry={() => latency.refetch()} />
            : !latency.data ? <Skeleton className="h-64" />
            : latency.data.length === 0 ? <EmptyState icon={ChartLine} title="No measurements in this range" description="Latency appears here after the first ping checks complete." />
            : <MetricChart data={latency.data} dataKey="rttAvg" unit="ms" label="Avg RTT" range={range} />}
        </div>
      </Panel>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel title="Top 5 slowest devices">
          {!s ? <RowsSkeleton /> : s.slowest.length === 0
            ? <EmptyState icon={Server} title="No latency data yet" description="Add a device to start measuring."
                action={canWrite ? <Button asChild size="sm" variant="outline"><Link to="/devices?new=1">Add device</Link></Button> : undefined} />
            : <ul className="divide-y">{s.slowest.map((d) => (
                <li key={d.id}>
                  <Link to={`/devices/${d.id}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-muted">
                    <span className="min-w-0 flex-1"><span className="block truncate text-sm">{d.name}</span><span className="block truncate font-mono text-xs text-muted-foreground">{d.host}</span></span>
                    <span className="font-mono text-sm tabular-nums">{fmtMs(d.rttMs)}</span>
                  </Link>
                </li>))}
              </ul>}
        </Panel>
        <Panel title="Recent alerts">
          {!s ? <RowsSkeleton /> : s.recentAlerts.length === 0
            ? <EmptyState icon={BellOff} title="No alerts" description="Alerts appear here when a rule's condition is met." action={<Button asChild size="sm" variant="outline"><Link to="/alerts">Manage rules</Link></Button>} />
            : <ul className="divide-y">{s.recentAlerts.map((a) => (
                <li key={a.id} className="px-4 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <Link to="/alerts" className="truncate text-sm hover:underline" title={a.message}>{a.message}</Link>
                    <SeverityBadge severity={a.severity} />
                  </div>
                  <p className="mt-0.5 text-xs text-muted-foreground">{a.state[0] + a.state.slice(1).toLowerCase()} · <RelativeTime iso={a.triggeredAt} /></p>
                </li>))}
              </ul>}
        </Panel>
        <Panel title="Recent status changes">
          {!s ? <RowsSkeleton /> : s.recentChanges.length === 0
            ? <EmptyState icon={History} title="No status changes yet" description="Transitions between states are listed here." />
            : <ul className="divide-y">{s.recentChanges.slice(0, 6).map((e) => (
                <li key={e.id} className="px-4 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <Link to={`/devices/${e.deviceId}`} className="truncate text-sm hover:underline">{e.deviceName}</Link>
                    <StatusBadge status={e.toStatus} />
                  </div>
                  <p className="mt-0.5 text-xs text-muted-foreground"><RelativeTime iso={e.occurredAt} /></p>
                </li>))}
              </ul>}
        </Panel>
      </div>
    </>
  );
}
