# NetPulse: Intelligent Network Monitoring & Fault Diagnosis
## Lab Implementation & Demonstration Guide
*Computer Networks Lab [24B15CS313] — Jaypee Institute of Information Technology (JIIT)*

---

### 1. Architecture Overview (Matching Synopsis Figure 1)

```mermaid
flowchart TD
    subgraph Monitored Network
        A1[Local Agent 1<br/>agent/agent.py] -->|Every 10-30s| P1[Gateway Ping & DNS Check]
        A1 --> P2[Latency, Jitter & Loss Probe]
        A1 --> P3[Traceroute on failure]
        A1 --> B1[(Local Buffer)]
        A2[Simulated Agent 2..N<br/>simulate_multi_agents.py]
    end

    subgraph NetPulse Backend (FastAPI)
        ING[Ingest API<br/>/api/agent/report]
        DB[(SQLite / PostgreSQL<br/>Probes, Diagnoses, SNMP)]
        DE[Diagnosis Engine<br/>Table 1 Rules & Confidence]
        SNMP[SNMP Poller<br/>Router Counters / NA]
        REST[REST API<br/>/api/diagnosis/latest]
    end

    subgraph Network Administrator
        DASH[React Dashboard<br/>Status Chain + Diagnosis Banner]
    end

    A1 -->|HTTPS/HTTP + JSON| ING
    A2 -->|HTTPS/HTTP + JSON| ING
    ING --> DB
    ING --> DE
    SNMP --> DB
    DE --> DB
    DE --> REST
    REST --> DASH
```

---

### 2. Implemented Diagnosis Rules (Table 1 of Synopsis)

| Rule # | Observation | Probable Cause | Action / Threshold |
| :--- | :--- | :--- | :--- |
| **Rule 1** | One computer cannot reach the gateway, others can | **Host Wi-Fi link, network card or cable failure** | Agent interface state or comparison against peer agents |
| **Rule 2** | No computer can reach the gateway | **Router or switch failure** | All reporting computers fail gateway ping |
| **Rule 3** | Gateway reachable, external IP unreachable | **ISP or WAN outage** | Gateway RTT normal, external IP has 100% loss |
| **Rule 4** | External IP reachable, local DNS fails, 8.8.8.8 works | **DNS server problem** | Local resolver fails, fallback 8.8.8.8 succeeds |
| **Rule 5** | All respond, but loss or jitter is above threshold | **Network congestion or degraded link** | Packet loss > 10% or jitter > 30 ms |
| **Rule 6** | Traceroute stops at hop $N$ and all later hops are silent | **Fault at or just after hop $N$** | Traceroute breakdown identified on failure |
| **Unclear** | Intermittent / conflicting probe results | **Cause Unclear (Low Confidence)** | Flags uncertain symptoms for further polling |

---

### 3. How to Run Locally (Local-First Priority)

#### Quick Start (All in one script)
Run either:
```cmd
start_local.bat
```
or in PowerShell:
```powershell
.\start_local.ps1
```

#### Running Components Individually

1. **Start the Backend Server (FastAPI):**
   ```bash
   python run_backend.py
   ```
   *Backend runs at `http://localhost:8000` (API Docs at `http://localhost:8000/docs`).*

2. **Start the Frontend Dashboard (React + Vite):**
   ```bash
   cd frontend
   npm run dev
   ```
   *Dashboard runs at `http://localhost:5173`.*

3. **Start the Local Monitoring Agent:**
   ```bash
   python agent/agent.py
   ```
   *The agent automatically discovers your default gateway, runs probes every 10 seconds, and streams telemetry to the dashboard.*

---

### 4. Demonstrating the 6 Faults Live in the Lab (Deliverable 2)

On the React Dashboard (`http://localhost:5173`), use the **Live Fault Injection Controller** buttons:

1. **Click "Rule 4: DNS Server Fault"**:
   - The agent simulates local resolver failure while external IP and public 8.8.8.8 succeed.
   - Within 1 polling cycle, the dashboard updates to:
     > **Probable Cause: DNS server problem (95% Confidence)**
     > Evidence: Local resolver timed out, 8.8.8.8 resolved successfully.
2. **Click "Rule 3: ISP / WAN Outage"**:
   - Gateway ping responds with low latency, but external WAN target times out.
   - Dashboard flags **"ISP outage (95% Confidence)"**.
3. **Click "Rule 5: Congestion & Jitter"**:
   - Injects 25% packet loss and 48ms jitter.
   - Dashboard flags **"Network congestion or degraded link (85% Confidence)"**.
4. **Click "Rule 6: Traceroute Break"**:
   - Route breaks after Hop 2.
   - Dashboard shows the traceroute hop breakdown visualizer and flags **"Upstream route fault at or just after hop 2"**.
5. **Click "Restore Real Network"**:
   - Clears injection; dashboard returns to **"All Systems Operational (98% Confidence)"**.

---

### 5. Multi-Device Evaluation (Deliverable 1 & Rule 1 vs Rule 2)

To evaluate multi-computer correlation on a single machine:
```bash
python agent/simulate_multi_agents.py --count 3
```
This spawns `computer-01`, `computer-02`, and `computer-03` running in parallel. The backend correlates results across all 3 hosts:
- If `computer-01` is disconnected while `computer-02` and `computer-03` are healthy $\rightarrow$ Diagnoses **Rule 1 (Host Wi-Fi / NIC fault)**.
- If all 3 lose gateway connectivity $\rightarrow$ Diagnoses **Rule 2 (Router / switch failure)**.
