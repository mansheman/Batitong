# Batitong — Rancangan Lengkap GUI MCP Tools (Kali MCP + HexStrike-AI)

> Dokumen rancangan ini adalah **blueprint** sebelum implementasi. Tujuannya menyatukan: alur kerja user, arsitektur teknis, integrasi LLM, UI/UX sesuai brief, dan strategi deployment Docker. Setelah Anda setujui, baru kita mulai implementasi bertahap.

---

## 0. Ringkasan Keputusan (TL;DR)

| Aspek | Keputusan |
|---|---|
| **Frontend** | Django + Django Templates + HTMX + Alpine.js + Tailwind CSS (dark theme kustom, JetBrains Mono) — *bukan* React SPA, supaya tetap minimal & developer-feel. |
| **Backend** | Django 5 + Django REST Framework (DRF) + Channels (WebSocket untuk live log) |
| **Async** | Celery (worker + beat) dengan Redis sebagai broker |
| **Database** | PostgreSQL 16 |
| **Object Storage** | MinIO lokal (S3-compatible) untuk artefak & report PDF |
| **MCP Execution** | Kali MCP (HTTP `:5000/mcp`) + HexStrike API (`:8888`) di container terpisah |
| **LLM Strategy** | **Hybrid Default**: Ollama lokal (default, gratis) + opsional GitHub Models API (BUKAN Copilot plugin) sebagai cloud provider, pilih per-workspace |
| **Deployment** | Single `docker-compose.yml` dengan profile `core` / `tools` / `llm` agar fleksibel untuk dev/prod |
| **Tema UI** | Dark, terminal-inspired, monospace, badge sistem, severity color-coded, numbered sections `01 / 03` |

---

## 1. Konteks & Goal

Anda sudah memiliki:

- **Kali MCP server** (`kali_mcp_server.py`, 82 tools, FastMCP, transport `streamable-http` di `:5000/mcp`)
- **HexStrike AI** (Flask API di `:8888` + MCP bridge) sebagai control-plane reasoning/planning
- **Hybrid orchestrator** (`Scripts/hybrid_orchestrator.py`) yang sudah membuktikan: HexStrike = planner, Kali MCP = executor
- Dokumen arsitektur awal (`GUI_MCP_DJANGO_ARCHITECTURE.md`)

**Masalah yang harus dijawab GUI:**

1. **Akses non-VS-Code**: tim AppSec/Pentester tidak harus install VS Code Copilot untuk menjalankan tools.
2. **Multi-user & audit**: setiap run punya jejak (siapa, kapan, scope, hasil).
3. **Reproducible deployment**: clone → `docker compose up` → semua tool jalan, tidak perlu install nmap/sqlmap di host.
4. **LLM fleksibel**: bisa pakai LLM lokal (privasi) atau cloud (kualitas), user pilih.
5. **Output bernilai**: bukan raw log, tapi report + visualisasi attack chain.

---

## 2. Alur Kerja User (UX Flow)

### 2.1 Persona & Mental Model

| Persona | Goal | Frekuensi pakai |
|---|---|---|
| Pentester | Jalankan recon + exploit, lihat output cepat | Harian |
| AppSec Engineer | Audit aplikasi internal, generate report ke manajemen | Mingguan |
| Security Lead | Review temuan, approve high-risk action | Mingguan |

User TIDAK mau: nge-CLI tiap kali, copy-paste command, atau memikirkan "tool mana yang dipakai dulu". User MAU: ketik target → AI bikin rencana → tinggal Approve/Run → lihat hasil di dashboard.

### 2.2 Alur Utama (Happy Path)

```
01 / 06 — Login & Pilih Workspace
   └─> auth (email+password / OIDC opsional), pilih workspace (multi-tenant)

02 / 06 — Buat "Engagement"
   └─> Definisikan target (domain/IP/CIDR), scope rules (allowlist/denylist),
       objective (recon | web-audit | ad-audit | full-pentest), pilih LLM provider

03 / 06 — AI Planning (LLM Router)
   └─> LLM membaca scope + objective → menghasilkan "execution plan":
       array of steps: [tool, args, rationale, severity-impact, estimated_time]
   └─> User melihat plan dalam tampilan timeline + bisa Edit/Approve/Reject per-step

04 / 06 — Eksekusi (Run)
   └─> Celery worker enqueue per step
   └─> Setiap step memanggil Kali MCP atau HexStrike via tool registry
   └─> Output mentah disimpan sebagai RawArtifact (di MinIO + metadata di Postgres)
   └─> Live stream output ke browser via WebSocket (terminal-style panel)

05 / 06 — Analisis & Findings
   └─> Parser per-tool menormalkan output → Finding (title, severity, evidence, cve?, remediation)
   └─> LLM merangkum & cluster duplicate findings
   └─> Risk engine hitung CVSS proxy & confidence score

06 / 06 — Report & Visualisasi
   └─> Attack-chain graph (D3 / Cytoscape.js)
   └─> Asset exposure map
   └─> Severity timeline
   └─> Export: Markdown / JSON SARIF / PDF
```

### 2.3 Alur Sekunder

- **Chat Mode (Free-form)**: panel chat seperti ChatGPT. User ketik *"scan acme.corp untuk SQLi di /api/login"* → LLM langsung pilih tool & jalankan via tool-calling. Cocok untuk pentester berpengalaman.
- **Manual Mode**: user pilih satu tool dari katalog (82 Kali tools + N HexStrike endpoints), isi parameter form, klik Run. Tanpa LLM. Cocok saat butuh kontrol penuh.
- **Replay Mode**: ambil engagement lama → klone parameter → re-run untuk cek apakah finding sudah di-fix.

---

## 3. Arsitektur Sistem

### 3.1 Diagram High-Level

```
┌────────────────────────────────────────────────────────────────────┐
│                        BROWSER (User Analyst)                      │
│      Django Templates + HTMX + Alpine.js + Tailwind (dark)         │
└─────────────┬────────────────────────────────────┬─────────────────┘
              │ HTTPS                              │ WebSocket (live log)
              ▼                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    CONTROL PLANE (Docker network: core)             │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐    │
│  │ django-web   │──>│ django-api   │──>│ celery-worker (xN)   │    │
│  │ (gunicorn)   │   │ (DRF)        │   │  - default queue     │    │
│  │              │   │              │   │  - heavy queue       │    │
│  │  + Channels  │   │ LLM Router ─┐│   │  - llm queue         │    │
│  │  (ASGI)      │   │             ││   └──────────────────────┘    │
│  └──────┬───────┘   └─────┬────────┘                  │            │
│         │                 │                           │            │
│         ▼                 ▼                           ▼            │
│  ┌────────────┐   ┌────────────┐   ┌────────────────────────────┐  │
│  │ postgres   │   │ redis      │   │  MinIO (S3-compatible)     │  │
│  │ :5432      │   │ :6379      │   │  artifacts/, reports/      │  │
│  └────────────┘   └────────────┘   └────────────────────────────┘  │
└─────────────────────────────────────┬───────────────────────────────┘
                                      │ HTTP (internal docker network)
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   EXECUTION PLANE (Docker network: tools)           │
│                                                                     │
│  ┌────────────────────┐   ┌────────────────────┐                    │
│  │ kali-mcp           │   │ hexstrike-api      │                    │
│  │ FastMCP :5000/mcp  │   │ Flask :8888        │                    │
│  │ 82 tools           │   │ planner/optimizer  │                    │
│  │ (nmap, sqlmap,...) │   │                    │                    │
│  └────────────────────┘   └────────────────────┘                    │
└─────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   LLM PLANE (Docker network: llm, opsional)         │
│                                                                     │
│  ┌────────────────────┐                                             │
│  │ ollama :11434      │   ← lokal, default                          │
│  │ models: llama3.1,  │                                             │
│  │ qwen2.5-coder, ... │                                             │
│  └────────────────────┘                                             │
│                                                                     │
│  ┌────────────────────┐                                             │
│  │ GitHub Models API  │   ← cloud, opsional, butuh PAT              │
│  │ (api.github.com/   │     gpt-4o-mini, llama-3.3-70b, dll         │
│  │  inference)        │     gratis dgn rate limit                   │
│  └────────────────────┘                                             │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 Mengapa Django Templates + HTMX (bukan React)

| Kriteria | Django + HTMX | React SPA |
|---|---|---|
| Dev speed | **Cepat** (1 framework) | Lebih lambat (FE+BE) |
| Bundle size | ~30 KB | 200+ KB |
| Real-time log | Channels + HTMX SSE | Perlu state mgmt |
| Audience teknis | Cocok (no over-engineering) | Overkill |
| Brief "minimal & clean" | **Match** | Tendensi over-design |

HTMX memberi interaktivitas mirip SPA (partial swap, polling, SSE) tanpa build pipeline JS yang berat. Alpine.js dipakai untuk state UI ringan (tabs, modal, dropdown). Tailwind untuk styling konsisten dengan tema kustom.

### 3.3 Modul Django (Apps)

```
batitong/
├── config/                  # settings, urls, asgi, wsgi
├── apps/
│   ├── accounts/            # User, Workspace, Membership, RBAC
│   ├── targets/             # Target, ScopeRule
│   ├── engagements/         # Engagement (= WorkflowRun), Step, Approval
│   ├── mcp/                 # MCPClient, ToolRegistry, HealthCheck
│   ├── llm/                 # Provider, Adapter (Ollama, GitHubModels), Router, Trace
│   ├── findings/            # Finding, Evidence, Severity engine
│   ├── reports/             # ReportBundle, Markdown/PDF/SARIF exporter
│   ├── visualization/       # Graph data builder (attack chain, timeline)
│   ├── audit/               # AuditEvent (immutable)
│   └── ui/                  # Templates, components, static
├── workers/
│   ├── tasks_mcp.py         # Celery tasks: call_kali_tool, call_hexstrike_endpoint
│   ├── tasks_llm.py         # Celery tasks: plan, summarize, judge
│   └── tasks_report.py      # Celery tasks: render_pdf, build_graph
└── docker/
    ├── django/Dockerfile
    ├── kali-mcp/Dockerfile
    ├── hexstrike/Dockerfile
    └── docker-compose.yml
```

### 3.4 Data Model (Inti)

```
Workspace (1) ─── (N) Membership ─── (N) User
Workspace (1) ─── (N) Target
Target (1) ─── (N) ScopeRule          # allowlist/denylist regex/CIDR
Workspace (1) ─── (N) Engagement
Engagement (1) ─── (N) Step
Step (1) ─── (N) ToolExecution
ToolExecution (1) ─── (N) RawArtifact  # MinIO key + metadata
ToolExecution (1) ─── (N) Finding
Finding (N) ─── (1) RiskScore
Engagement (1) ─── (1) ReportBundle
Engagement (1) ─── (N) LLMTrace        # prompt, response, model, cost, latency
* (1) ─── (N) AuditEvent               # immutable log
```

Penting:
- **Engagement** = `WorkflowRun` di doc lama, dirubah ke nama yang lebih pentest-natural.
- **ToolExecution** menyimpan: tool_name, provider (kali|hexstrike), args, exit_code, started_at, finished_at, output_hash.
- **Finding.evidence** referensi ke RawArtifact (file di MinIO) — bukan blob besar di Postgres.

### 3.5 Tool Registry & MCP Adapter

Service `apps/mcp/registry.py`:

- Pada startup (atau via cron), panggil `list_tools()` ke Kali MCP & HexStrike → cache ke Postgres tabel `mcp_tool` dengan kolom: `name, provider, description, schema_json, tactic (MITRE ATT&CK), risk_level (low/med/high)`.
- `risk_level` dipakai untuk **approval gate**: high-risk (msfvenom, hydra, sqlmap_dump) WAJIB approval dari Security Lead sebelum eksekusi.
- Schema dipakai untuk **auto-generate form** di Manual Mode dan untuk **tool-calling spec** ke LLM (function calling format).

### 3.6 Keamanan & Governance

- **RBAC sederhana**: Owner / Lead / Operator / Viewer per workspace.
- **Scope guard**: setiap call ke tool MCP cek `target` lawan `ScopeRule` workspace. Reject jika out-of-scope.
- **Approval gate**: tool dengan `risk_level=high` masuk antrian `pending_approval` sebelum dikirim ke worker.
- **Audit log immutable**: append-only, hash-chain (hash(prev) + hash(payload)) untuk integritas.
- **Secrets**: API key (Shodan, GitHub PAT, dll) disimpan via Django `django-environ` + `cryptography.fernet` encrypted-at-rest, atau opsional integrasi Vault.

---

## 4. Integrasi LLM — Rekomendasi

### 4.1 Klarifikasi Penting tentang "GitHub Copilot Free"

Anda menyebut "model gratis seperti pemakaian Copilot di VS Code". Ini perlu diluruskan supaya rancangan tidak salah arah:

| Option | Apa | Bisa dipakai backend? |
|---|---|---|
| **GitHub Copilot Plugin** (di VS Code) | Plugin editor pakai akun GitHub | **TIDAK** — itu plugin, bukan API publik. Memakainya dari server Django melanggar ToS. |
| **GitHub Models** ([github.com/marketplace/models](https://github.com/marketplace/models)) | API resmi, pakai GitHub PAT, gratis dengan rate limit (per menit / hari) | **YA** — endpoint OpenAI-compatible: `https://models.inference.ai.azure.com`. Mendukung `gpt-4o`, `gpt-4o-mini`, `llama-3.3-70b`, `phi-3.5`, dll. |

**Rekomendasi**: pakai **GitHub Models API** (bukan Copilot plugin) sebagai cloud provider. Itu legal, gratis dengan limit, dan secara API mirip OpenAI sehingga adapter bisa di-reuse.

### 4.2 Strategi LLM Hybrid

```
┌─────────────────────────────────────────────────────────────┐
│               LLM Router (apps/llm/router.py)               │
│                                                             │
│  Input: task_type ∈ {plan, summarize, classify, judge}      │
│         workspace_settings, prompt, schema                  │
│                                                             │
│  Decision matrix:                                           │
│  ┌────────────────┬───────────────────┬──────────────────┐  │
│  │ task_type      │ default provider  │ fallback         │  │
│  ├────────────────┼───────────────────┼──────────────────┤  │
│  │ plan (multi-   │ GitHub Models     │ Ollama           │  │
│  │   step reason) │ (gpt-4o-mini)     │ (qwen2.5-coder)  │  │
│  ├────────────────┼───────────────────┼──────────────────┤  │
│  │ summarize      │ Ollama            │ GitHub Models    │  │
│  │ (per finding)  │ (llama3.1:8b)     │                  │  │
│  ├────────────────┼───────────────────┼──────────────────┤  │
│  │ classify       │ Ollama (small)    │ —                │  │
│  │ (severity)     │ (phi3:mini)       │                  │  │
│  ├────────────────┼───────────────────┼──────────────────┤  │
│  │ tool-calling   │ GitHub Models     │ Ollama (qwen)    │  │
│  │ (chat mode)    │ (gpt-4o-mini)     │                  │  │
│  └────────────────┴───────────────────┴──────────────────┘  │
│                                                             │
│  Privacy mode (workspace flag): force Ollama only           │
│  Cost mode: force Ollama only (gratis selamanya)            │
└─────────────────────────────────────────────────────────────┘
```

### 4.3 Mengapa Hybrid (bukan satu saja)?

| Kriteria | Ollama lokal | GitHub Models cloud |
|---|---|---|
| Privasi data | **Tinggi** (tidak keluar) | Sedang (terms GitHub) |
| Kualitas reasoning | Sedang (8B model) | **Tinggi** (gpt-4o) |
| Latency | Cepat (no network) | 1–3s |
| Cost | **0 selamanya** | 0 sampai limit |
| Offline | **Ya** | Tidak |
| Tool-calling | Bagus dgn qwen2.5-coder | **Sangat bagus** dgn gpt-4o-mini |

→ **Default**: Ollama untuk task ringan, GitHub Models untuk planning multi-step.
→ Workspace bisa set "Privacy Mode" untuk force lokal.

### 4.4 Adapter Pattern

```
apps/llm/
├── base.py            # BaseAdapter (chat, tool_call, stream)
├── adapters/
│   ├── ollama.py      # POST /api/chat ke ollama:11434
│   └── github.py      # POST /chat/completions ke models.inference.ai.azure.com
├── router.py          # decision logic, fallback, retry
└── tracing.py         # save LLMTrace (prompt, response, model, latency, cost)
```

Semua adapter expose interface OpenAI-compatible (chat completions + tool calls), jadi router cukup tukar `base_url` & `auth header`.

### 4.5 Tool-Calling Bridge (LLM → MCP)

Ini bagian paling penting untuk integrasi **LLM ↔ MCP**:

```
1. Saat user buka chat / submit objective:
   Router.fetch_tools() → ambil tool registry dari Postgres (82 Kali + N HexStrike)
                       → convert ke OpenAI function-calling JSON schema
                       → kirim sebagai `tools` parameter ke LLM

2. LLM merespons dengan tool_calls = [{name, arguments}, ...]

3. Router.execute_tool_calls():
   a. Validasi: nama tool ada di registry, args sesuai schema
   b. Validasi scope: target ∈ workspace.scope_rules
   c. Cek risk_level: jika high → buat ApprovalRequest, tunggu user approve
   d. Enqueue Celery task `tasks_mcp.call_tool(provider, tool_name, args, step_id)`

4. Worker:
   a. Buka MCP client session ke kali-mcp atau HTTP call ke hexstrike-api
   b. Stream output via Redis Pub/Sub channel `engagement:{id}` → Channels → WebSocket → browser
   c. Simpan RawArtifact ke MinIO + metadata ke Postgres

5. Hasil tool dikirim balik ke LLM sbg `role=tool` message → LLM lanjutkan reasoning
   sampai goal tercapai atau max_iter terlampaui.
```

Pattern ini = **agent loop** standar (mirip OpenAI Assistants / LangGraph), tapi dijalankan di Celery worker supaya non-blocking & resumable.

---

## 5. Rancangan UI/UX (Sesuai Brief)

### 5.1 Design Tokens

```css
/* Tailwind config — colors */
--bg-primary:    #0a0a0a;     /* near-black, dominan */
--bg-secondary:  #111111;     /* card surface */
--bg-tertiary:   #1a1a1a;     /* hover / nested */
--border:        #262626;     /* subtle */
--border-hover:  #404040;
--text-primary:  #fafafa;
--text-secondary:#a3a3a3;     /* muted */
--text-tertiary: #525252;     /* hint */
--accent:        #00ff88;     /* terminal-green primary */
--accent-dim:    #00cc6a;
--severity-low:  #3b82f6;     /* blue */
--severity-med:  #f59e0b;     /* amber */
--severity-high: #ef4444;     /* red */
--severity-crit: #a855f7;     /* purple */

/* Fonts */
--font-display: 'Inter', sans-serif;          /* headlines */
--font-mono:    'JetBrains Mono', monospace;  /* code, terminal, labels */
```

### 5.2 Halaman Utama

```
01 / Landing (publik, opsional jika SaaS-like)
02 / Login
03 / Dashboard
04 / Engagements (list + detail)
05 / Tool Catalog (browse 82+N tools)
06 / LLM Chat (free-form)
07 / Reports
08 / Settings (workspace, providers, RBAC)
```

### 5.3 Layout Skeleton

```
┌───────────────────────────────────────────────────────────────┐
│ ▌ batitong  /  acme-workspace ▾                  [Live] user▾ │  ← topbar (h-12, border-b)
├───────────┬───────────────────────────────────────────────────┤
│           │                                                   │
│  SIDEBAR  │                  MAIN CONTENT                     │
│  (w-56)   │                                                   │
│           │                                                   │
│  Dashboard│  ~/engagement · ptai run --target acme.corp       │  ← breadcrumb mono
│  Engage.. │                                                   │
│  Catalog  │  ┌─────────────────────────────────────────┐      │
│  Chat     │  │ 01 / 03  Reconnaissance                 │      │  ← numbered section
│  Reports  │  │ ─────────────────────────────────────── │      │
│  Settings │  │ Card content...                         │      │
│           │  └─────────────────────────────────────────┘      │
│           │                                                   │
│           │  ┌─────────────────────────────────────────┐      │
│  ───      │  │ 02 / 03  Web Audit         [med] [run]  │      │
│  v0.1.0   │  └─────────────────────────────────────────┘      │
│  [open    │                                                   │
│   source] │                                                   │
└───────────┴───────────────────────────────────────────────────┘
```

### 5.4 Komponen Utama

#### Badge System
```
[ Live ]          → status realtime, ada pulse green dot
[ v0.1.0 ]        → versi
[ open source ]   → meta
[ MIT ]           → lisensi
[ MCP ]           → kapabilitas
[ low | med | high | crit ]  → severity, color-coded
```
Gaya: `text-[10px] px-2 py-0.5 border border-neutral-700 rounded-sm font-mono uppercase tracking-wide`.

#### Numbered Section Header
```
01 / 03   RECONNAISSANCE
─────────────────────────────────────────
```
- Angka pakai font display tipis, angle separator `/` muted.
- Line bawah penuh (border-b border-neutral-800).
- Mengikuti pola "01 / 03" dari brief.

#### Card (Engagement, Tool, Pricing)
```
┌─────────────────────────────────────┐
│ [recon]                  [12 tools] │  ← top row: tag + meta badge
│                                     │
│ Network Reconnaissance              │  ← bold display
│ Discover live hosts, services, OS   │  ← muted secondary
│                                     │
│ ~/recon · nmap -sV target           │  ← mono code line
│                                     │
│ ──────────────                      │
│ → Run                          [↗]  │  ← CTA
└─────────────────────────────────────┘
```
Border subtle (`border border-neutral-800`), hover `border-neutral-700`, no shadow heavy.

#### Terminal Panel (Live Output)
```
┌─ kali-mcp · nmap_scan · run #4827 ────── [running] ⏱ 00:42 ┐
│ $ nmap -sV -p- 10.10.10.5                                  │
│ Starting Nmap 7.94 ( https://nmap.org )                    │
│ Nmap scan report for target.local (10.10.10.5)             │
│ Host is up (0.038s latency).                               │
│ PORT     STATE SERVICE   VERSION                           │
│ 22/tcp   open  ssh       OpenSSH 8.2p1                     │
│ 80/tcp   open  http      nginx 1.18.0                      │
│ ...                                                        │
│ ▮                                                          │  ← cursor blink
└────────────────────────────────────────────────────────────┘
```
- Font: JetBrains Mono, 13px.
- Background: `#0a0a0a`, border `#262626`.
- Header bar: tool name + status pill + elapsed time.
- Auto-scroll, ada tombol Pause/Copy/Download Raw.
- Streamed via WebSocket (Channels) chunk by chunk.

#### Severity Pill (untuk Findings)
```
[ low ]     bg-blue-950/30   text-blue-400   border-blue-900
[ med ]     bg-amber-950/30  text-amber-400  border-amber-900
[ high ]    bg-red-950/30    text-red-400    border-red-900
[ crit ]    bg-purple-950/30 text-purple-400 border-purple-900
```

#### Attack Chain Graph
- Library: **Cytoscape.js** (lebih ringan dari D3 untuk graph, dan punya layout otomatis).
- Node: target / port / service / vuln / credential / privilege.
- Edge: discovered_by / exploited_by / escalated_to (animated dashed line).
- Color node by severity terkait.
- Click node → side panel dengan evidence + remediation.

### 5.5 Halaman Engagement Detail (paling penting)

```
~/engagement/eng_4827 · ptai run --target acme.corp
─────────────────────────────────────────────────────────────

[ running ]  [ 01:24 elapsed ]  [ web-audit ]  [ Pause ] [ Stop ]

┌─────────────────────────────────────────────────────────────┐
│  TIMELINE                                                   │
│                                                             │
│  ●─── 01 recon          [done]  3 findings    14s          │
│  │                                                          │
│  ●─── 02 web-fingerprint [done] 2 findings    8s           │
│  │                                                          │
│  ●─── 03 dir-fuzz        [done] 18 paths      42s          │
│  │                                                          │
│  ●─── 04 vuln-scan       [running]            12s ●        │  ← live
│  │                                                          │
│  ○─── 05 sqli-test       [pending]            —            │
│  │                                                          │
│  ○─── 06 report          [pending]            —            │
└─────────────────────────────────────────────────────────────┘

[Tabs:  Plan  |  Live Log  |  Findings (23)  |  Graph  |  Report]
```

Tab `Live Log` = terminal panel (komponen di atas).
Tab `Findings` = list dengan filter severity, search, kelompok by host.
Tab `Graph` = Cytoscape attack chain.
Tab `Report` = preview Markdown + tombol Export PDF/JSON.

### 5.6 Halaman Chat Mode

```
~/chat · session #s_991                          [GitHub Models · gpt-4o-mini ▾]

┌────────────────────────────────────────────────────────────────┐
│ user                                                           │
│   scan acme.corp untuk SQLi di /api/login                      │
│                                                                │
│ assistant                                                      │
│   Saya akan menjalankan 2 tool secara berurutan:               │
│                                                                │
│   ┌─ tool_call: nmap_scan ────────────────────────┐            │
│   │ target: acme.corp                             │            │
│   │ flags:  -sV -p 80,443                         │ [approve]  │
│   │ rationale: konfirmasi /api/login responsive   │            │
│   └───────────────────────────────────────────────┘            │
│                                                                │
│   ┌─ tool_call: sqlmap_scan ──────────────────────┐            │
│   │ url: https://acme.corp/api/login              │            │
│   │ flags: --data="user=test&pass=test" --batch   │ [approve]  │
│   │ risk:  high — needs lead approval             │            │
│   └───────────────────────────────────────────────┘            │
│                                                                │
│   [ approve all ]  [ reject ]  [ edit args ]                   │
└────────────────────────────────────────────────────────────────┘

[ ▮ ketik perintah... ]                                  [ send ↵ ]
```

- Setiap `tool_call` di-card-kan dgn tombol approve per-call (bukan auto-run).
- High-risk auto-flag dan butuh approval Lead.
- Streaming token by token (SSE).

### 5.7 Typography

```
H1 display:   Inter 48px / 700 / -0.02em tracking
H2 display:   Inter 32px / 600
H3 display:   Inter 22px / 600

mono-label:   JetBrains Mono 11px / uppercase / 0.05em tracking
mono-code:    JetBrains Mono 13px / line-height 1.6
mono-cmd:     JetBrains Mono 14px (untuk breadcrumb command-line)

body:         Inter 14px / 400 / line-height 1.6
muted:        text-neutral-400
hint:         text-neutral-600
```

Untuk halaman *landing/marketing* (jika ada), pakai display 64–80px super-bold mirip referensi PT-AI/HexStrike landing.

### 5.8 Aksesibilitas & Keyboard Shortcut

- `⌘/Ctrl + K`: command palette (cari engagement, tool, target).
- `⌘/Ctrl + Enter`: submit form di halaman chat & manual mode.
- `g d`: go dashboard, `g e`: engagements (gaya Vim/Linear).
- ARIA roles untuk panel terminal & graph.
- Kontras AA: text-neutral-400 di atas #0a0a0a = ratio 7.1:1 ✓.

---

## 6. Strategi Deployment Docker

### 6.1 Struktur File

```
batitong/
├── docker-compose.yml
├── docker-compose.override.yml      # dev only
├── .env.example
├── docker/
│   ├── django/Dockerfile             # python:3.12-slim + poetry + django + gunicorn
│   ├── kali-mcp/Dockerfile           # kalilinux/kali-rolling + 82 tools
│   ├── hexstrike/Dockerfile          # python:3.12 + flask + dependencies
│   └── ollama/Dockerfile             # opsional, biasanya pakai image resmi
├── scripts/
│   ├── bootstrap.sh                  # first-run: migrate, createsuperuser, pull ollama models
│   └── healthcheck.sh
└── batitong/                         # Django project
```

### 6.2 docker-compose.yml (Konseptual)

```yaml
x-django-base: &django-base
  build: { context: ., dockerfile: docker/django/Dockerfile }
  env_file: .env
  depends_on:
    postgres: { condition: service_healthy }
    redis:    { condition: service_started }
    minio:    { condition: service_started }
  networks: [core, tools, llm]

services:
  # ==== CORE / Control Plane ===========================================
  django-web:
    <<: *django-base
    command: gunicorn -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 config.asgi:application
    ports: ["8000:8000"]

  celery-worker:
    <<: *django-base
    command: celery -A config worker -Q default,heavy,llm -l info -c 4

  celery-beat:
    <<: *django-base
    command: celery -A config beat -l info

  postgres:
    image: postgres:16-alpine
    environment: { POSTGRES_DB: batitong, POSTGRES_USER: batitong, POSTGRES_PASSWORD: ${DB_PASS} }
    volumes: [pg_data:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "batitong"]
      interval: 5s
    networks: [core]

  redis:
    image: redis:7-alpine
    volumes: [redis_data:/data]
    networks: [core]

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment: { MINIO_ROOT_USER: ${S3_USER}, MINIO_ROOT_PASSWORD: ${S3_PASS} }
    volumes: [minio_data:/data]
    ports: ["9001:9001"]
    networks: [core]

  # ==== TOOLS / Execution Plane ========================================
  kali-mcp:
    build: { context: ./docker/kali-mcp, dockerfile: Dockerfile }
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:5000/mcp/health"]
      interval: 10s
    networks: [tools]
    profiles: [tools, full]

  hexstrike-api:
    build: { context: ./hexstrike-ai, dockerfile: ../docker/hexstrike/Dockerfile }
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8888/health"]
      interval: 10s
    networks: [tools]
    profiles: [tools, full]

  # ==== LLM Plane ======================================================
  ollama:
    image: ollama/ollama:latest
    volumes: [ollama_data:/root/.ollama]
    deploy:
      resources:
        reservations:
          devices: [{ driver: nvidia, count: all, capabilities: [gpu] }]    # opsional
    networks: [llm]
    profiles: [llm, full]

networks:
  core:  { driver: bridge }
  tools: { driver: bridge }    # bisa internal: true di prod
  llm:   { driver: bridge }

volumes: { pg_data: {}, redis_data: {}, minio_data: {}, ollama_data: {} }
```

### 6.3 Profiles untuk Fleksibilitas

```bash
# Core only (dev tanpa tool nyata, mock MCP)
docker compose up -d

# Core + tools (tanpa LLM lokal, pakai cloud)
docker compose --profile tools up -d

# Full stack (tools + ollama lokal)
docker compose --profile full up -d
```

### 6.4 Build Strategy untuk kali-mcp Container

`docker/kali-mcp/Dockerfile` (multi-stage):

```dockerfile
# Stage 1: install Kali tools
FROM kalilinux/kali-rolling AS tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap masscan sqlmap nikto whatweb gobuster ffuf wfuzz feroxbuster \
    dnsenum dnsrecon hydra medusa john hashcat hashid \
    impacket-scripts smbclient enum4linux netexec \
    nuclei amass theharvester dirb commix \
    python3 python3-pip \
 && rm -rf /var/lib/apt/lists/*

# Stage 2: MCP server
FROM tools AS runtime
WORKDIR /app
COPY kali_mcp_server.py .
RUN pip install --break-system-packages mcp uvicorn
EXPOSE 5000
HEALTHCHECK CMD curl -f http://127.0.0.1:5000/mcp/health || exit 1
CMD ["python3", "kali_mcp_server.py"]
```

Ukuran image: ~3-5 GB (kali base besar). Untuk produksi: pisahkan per-domain (Opsi B di doc lama: kali-mcp-recon, kali-mcp-web, kali-mcp-ad), tapi mulai dari single image dulu.

### 6.5 First-Run UX

User clone repo → satu perintah jalan:

```bash
git clone https://github.com/mansheman/Batitong.git
cd Batitong
cp .env.example .env
# edit .env: SECRET_KEY, DB_PASS, GITHUB_MODELS_TOKEN (opsional)
docker compose --profile full up -d --build
docker compose exec django-web python manage.py migrate
docker compose exec django-web python manage.py createsuperuser
# auto-pull ollama model default
docker compose exec ollama ollama pull qwen2.5-coder:7b
```

Atau lebih simple: `make setup` yang membungkus semuanya.

### 6.6 Production Hardening Roadmap

| Item | Phase |
|---|---|
| Reverse proxy (Caddy/Traefik) + HTTPS | Phase 1 |
| Database backup cron (pg_dump → S3) | Phase 1 |
| Log aggregation (Loki + Grafana) | Phase 2 |
| Image vulnerability scan (Trivy di CI) | Phase 2 |
| SBOM per image | Phase 3 |
| Multi-tenant network isolation | Phase 3 |
| Rate limiting (nginx + Redis) | Phase 2 |
| Secret manager (Vault/SOPS) | Phase 3 |

---

## 7. Roadmap Implementasi (4 Fase)

### Fase 1 — Foundation (1–2 minggu)
- [ ] Skeleton Django project + apps (accounts, targets, engagements, mcp)
- [ ] Docker Compose: django-web, postgres, redis, minio
- [ ] MCP adapter: client ke kali-mcp + hexstrike, tool registry sync
- [ ] Manual Mode: katalog tool + form auto-generated dari schema
- [ ] Run satu engagement (nmap → nikto → whatweb), live log via WebSocket
- [ ] Tema dark + 5 halaman dasar (login, dashboard, engagements, tools, settings)

### Fase 2 — LLM Integration (1 minggu)
- [ ] Adapter Ollama + GitHub Models
- [ ] LLM Router + tool-calling bridge
- [ ] Chat Mode page
- [ ] LLMTrace logging
- [ ] Approval gate untuk high-risk tools

### Fase 3 — Findings & Reports (1–2 minggu)
- [ ] Parser per-tool (nmap XML → host/port/svc, sqlmap → injection point, dll)
- [ ] Risk engine (CVSS proxy + confidence)
- [ ] LLM summarizer & deduplicator
- [ ] Report exporter: Markdown / JSON SARIF / PDF (WeasyPrint)
- [ ] Cytoscape attack chain graph

### Fase 4 — Hardening (1 minggu)
- [ ] RBAC granular + audit log immutable hash chain
- [ ] Scope guard di semua tool call
- [ ] Rate limit per user + per workspace
- [ ] Retention policy (auto-archive engagement >90 hari)
- [ ] CI: lint, test, docker build, trivy scan

Total estimasi: **5–6 minggu** untuk MVP siap demo.

---

## 8. Risiko & Mitigasi

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Container Kali besar (3–5 GB) | Build lambat, registry mahal | Multi-stage build, prune apt cache, opsi split per domain di Phase 2 |
| Ollama butuh GPU | Tidak semua user punya | Default model kecil (phi3:mini, qwen2.5-coder:7b) yang jalan di CPU; user bisa upgrade |
| GitHub Models rate limit | Block planning | Auto-fallback ke Ollama; cache plan untuk target serupa |
| Tool call out-of-scope | Legal & etis | Scope guard wajib di setiap call, denylist domain populer (google.com, dll) |
| Output tool berisi PII | Privacy | Opsi auto-redact di parser (regex email/phone/credit card) |
| LLM hallucinate tool args | Tool gagal / berbahaya | Schema validation + dry-run preview + human approval untuk high-risk |

---

## 9. Pertanyaan Klarifikasi untuk Anda

Sebelum saya mulai implementasi, ada **5 pertanyaan** yang berdampak ke arsitektur:

1. **LLM cloud**: setuju pakai **GitHub Models API** (bukan Copilot plugin)? Anda akan generate Personal Access Token (PAT) atau saya pakai env var saja?
2. **Multi-tenant**: butuh sekarang (workspace untuk beberapa tim) atau single-tenant dulu (cuma Anda + tim kecil)?
3. **MinIO** untuk artifact storage atau cukup `MEDIA_ROOT` di filesystem (lebih simple, kurang skalabel)?
4. **Ollama default model**: `qwen2.5-coder:7b` (4.7 GB, bagus untuk tool-calling) atau `llama3.1:8b` (4.7 GB, general)? Bisa keduanya di-pull saat bootstrap.
5. **Scope deployment awal**: target dev di laptop sendiri, atau langsung VPS/server lab? (Mempengaruhi keputusan TLS, secret manager, dll.)

---

## 10. Apa yang Saya Butuh dari Anda untuk Mulai Implementasi

Setelah Anda review dokumen ini:

1. ✱ **Approve / revisi** keputusan di Section 0 (TL;DR) dan jawaban 5 pertanyaan di atas.
2. ✱ Konfirmasi **branding/naming**: `Batitong` tetap, atau ada alias internal?
3. ✱ Apakah ada **logo/asset** yang sudah ada, atau saya buat placeholder text-mark dulu?
4. ✱ **GitHub PAT** dengan scope `models:read` jika setuju pakai GitHub Models (bisa nanti, tidak blocking).

Setelah itu saya akan mulai dari **Fase 1 — Foundation** dan kirim PR pertama dalam 2–3 commit awal: skeleton Django + Docker Compose + halaman dashboard kosong dengan tema dark.

---

> Dokumen ini akan jadi `DESIGN.md` di repo setelah Anda setujui, supaya jadi single source of truth untuk implementasi.
