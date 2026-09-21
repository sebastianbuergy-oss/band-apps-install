# Buergys Builds - HTTP-Vertrag

Exakte Antwortformen fuer Clients, die die API direkt sprechen (Buergys Agent
ist Electron/TypeScript und tut genau das). Die Typen unten sind aus dem
laufenden Code abgeleitet und durch Tests festgenagelt.

## Regeln, die immer gelten

1. **Jede Antwort ist ein JSON-Objekt**, nie ein nacktes Array. Ein
   Top-Level-Array haette keinen Platz fuer die Version.
2. **Jede Antwort traegt `api_version`** im Body **und**
   `X-Burgys-API-Version` im Header - auch Fehlerantworten.
3. `api_version` steigt, wenn sich eine Form so aendert, dass ein Client es
   merken muss. Aktuell: **1**.
4. Alle Zeitangaben sind lokale ISO-8601-Strings ohne Zeitzone
   (`2026-09-21T14:58:37`), so wie der Controller sie schreibt.
5. Nur `127.0.0.1`. Ein fremder `Host`-Header wird mit 403 abgelehnt.

## Statuscodes

| Code | Bedeutung | Reaktion |
|---|---|---|
| 200 / 202 | ok | |
| 400 | Eingabe ungueltig, oder Aktion braucht ein anderes Token | Eingabe korrigieren; nicht wiederholen |
| 401 | Token fehlt oder hat den Scope nicht | **Nicht** wiederholen |
| 403 | fremder Host-Header | Ueber `127.0.0.1` gehen |
| 404 | Route oder Objekt gibt es nicht | |
| 409 | Cost Guard, Build-Limit, unzulaessiger Zustand | **Nicht** umgehen |
| 429 | Rate Limit | `retry_after` abwarten |
| 500 | interner Fehler | Nur der Ausnahmetyp, Details im Audit-Log |

## TypeScript

```ts
// ---- Grundlagen -----------------------------------------------------------

export const API_VERSION = 1;

export interface Versioned { api_version: number; }

export type BuildState =
  | "DISCOVERED" | "PREFLIGHT" | "READY" | "WAITING_APPROVAL" | "QUEUED"
  | "WINDOWS_TESTING" | "WAITING_MAC" | "MAC_BUILDING" | "SIGNING"
  | "EXPORTING" | "VERIFYING" | "SUCCESS" | "FAILED" | "BLOCKED"
  | "BLOCKED_BY_COST_GUARD" | "CANCELLED";

export const TERMINAL: BuildState[] =
  ["SUCCESS", "FAILED", "BLOCKED", "BLOCKED_BY_COST_GUARD", "CANCELLED"];

export type BuildMode = "DEVELOPMENT" | "AD_HOC" | "APP_STORE_RELEASE";
export type Scope = "read" | "preflight" | "prepare" | "build" | "release";

export interface ApiError extends Versioned {
  error: string;
  status?: number;        // bei 4xx/5xx
  state?: BuildState;     // bei 409: der Zustand, in den der Build geht
  scope?: Scope;          // bei 401: welcher Scope gefehlt haette
  retry_after?: number;   // bei 429: Sekunden
}

// ---- GET /health  (ohne Token) --------------------------------------------

export interface Health extends Versioned {
  status: "ok";
  service: "burgys-builds";
}

// ---- GET /capabilities  (scope: read)  >>> ZUERST FRAGEN <<< --------------

export interface Capabilities extends Versioned {
  service: "burgys-builds";
  version: string;                    // Softwareversion, z.B. "0.1.0"
  identity: { name: string; scopes: Scope[] };
  routes: Array<{
    method: "GET" | "POST";
    path: string;                     // Regex-Form, z.B. "/builds/(?P<build_id>...)"
    scope: Scope;
    allowed_for_you: boolean;
  }>;
  build_states: BuildState[];
  terminal_states: BuildState[];
  modes: BuildMode[];
  projects: string[];
  policy: {
    paid_services_allowed: boolean;               // false = Cost Guard aktiv
    approval_required_for_real_builds: boolean;
    max_real_builds_per_project_per_day: number;
    publish_configured: boolean;
    executor: string;                             // "none" | "dryrun" | "github" | "local"
    executor_produces_real_ipa: boolean;          // false = nur Dry Runs sinnvoll
  };
  notes: string[];
}

// ---- GET /status  (scope: read) -------------------------------------------

export interface Status extends Versioned {
  windows_controller: "ONLINE";
  mac_executor: {
    name: string;
    availability: "AVAILABLE" | "BUSY" | "OFFLINE";
    cost_resource: string;
    runner_label: string;
    produces_real_ipa: boolean;
    checked_at: string;
  };
  mac_executors_per_project: Record<string, unknown>;
  cost_guard: {
    paid_services_allowed: boolean;
    period: string;                               // "2026-09"
    metered: Record<string, number>;              // Ressource -> Minuten
    resources: Record<string, "FREE" | "FREE_TIER" | "PAID">;
  };
  queue: QueueSnapshot;
  builds_today: { total: number; success: number; failed: number; dry_runs: number };
  disk: { free_bytes: number; free_gb: number; level: "OK" | "WARN" | "CRITICAL" };
  retention: { prunable_builds: number; prunable_artifacts: number;
               prunable_logs: number; freed_mb: number } | { error: string };
  worker: { running: boolean; completed?: number; errors?: number; note?: string };
}

// ---- GET /queue  (scope: read) --------------------------------------------

export interface QueueEntry {
  build_id: string; project: string; mode: BuildMode;
  priority: number; queued_at: string;
  claimed_at?: string; executor?: string; owner_pid?: number;
}

export interface QueueSnapshot extends Versioned {
  waiting: QueueEntry[];
  running: Record<string, QueueEntry>;
  length: number;
  updated_at: string;
}

// ---- GET /projects  (scope: read) -----------------------------------------

export interface Project {
  id: string; name: string; code: string;
  repository: string; branch: string; kind: string;
  bundle_id: string; scheme: string; display_name: string;
  team_id: string; marketing_version: string;
  modes: BuildMode[];
  migration_state: "CODEMAGIC_ACTIVE" | "BURGYS_BUILDS_PARALLEL"
                 | "BURGYS_BUILDS_VERIFIED" | "CODEMAGIC_DISABLED";
  enabled: boolean;
  local_path_configured: boolean;
  ota_slug: string | null;
}

export interface ProjectList extends Versioned { projects: Project[]; }

// ---- GET /projects/{id}  (scope: read) ------------------------------------

export interface ProjectDetail extends Versioned {
  project: Project;
  limit: { project: string; used: number; limit: number;
           remaining: number; window_hours: 24 };
  builds: BuildManifest[];
}

// ---- POST /preflight  (scope: preflight) ----------------------------------
// Body: { project: string, mode?: BuildMode, commit?: string }

export type CheckStatus = "PASS" | "FAIL" | "WARN" | "SKIP";

export interface PreflightReport extends Versioned {
  project: string; mode: BuildMode; at: string;
  ok: boolean;                                    // false, sobald ein FAIL dabei ist
  summary: { pass: number; fail: number; warn: number; skip: number };
  results: Array<{ check: string; status: CheckStatus;
                   message: string; detail: unknown }>;
}

// ---- POST /builds  (scope: prepare; echter Build zusaetzlich: build) ------
// Body: { project: string, mode?: BuildMode, commit?: string, dry_run?: boolean }
// Antwort: 202 + BuildManifest.
// Mit dry_run:false und nur dem agent-Token: 400 mit Hinweis auf das
// Release-Token. Das ist Absicht, kein Fehler.

export interface BuildManifest extends Versioned {
  schema_version: number;
  build_id: string;                 // "BB-YYYYMMDD-CODE-NNN"
  project: string; project_name: string;
  repository: string; branch: string; commit: string;
  version: string; build_number: string; bundle_id: string;
  mode: BuildMode;
  requested_by: string;
  status: BuildState;
  display_status: string;           // >>> DAS ANZEIGEN, nicht status <<<
  executor: string;
  dry_run: boolean;
  reused_from: string | null;
  artifact_sha256: string | null;   // 64 hex
  artifact_path: string | null;
  artifact_bytes: number | null;
  created_at: string; updated_at: string; finished_at: string | null;
  failure_reason: string | null;
  approval: { by: string; at: string } | null;
  preflight: PreflightReport | null;
  mac_minutes: number;
  windows_seconds: number;
  ota: OtaRelease | null;
  state_history: Array<{ state: BuildState; at: string; note?: string }>;
  state_history_states: BuildState[];
}

// ---- GET /builds/{id}/logs?tail=n  (scope: read) --------------------------

export interface BuildLogs extends Versioned { build_id: string; lines: string[]; }

// ---- GET /builds/{id}/artifacts  (scope: read) ----------------------------

export interface Artifacts extends Versioned {
  build_id: string;
  dry_run: boolean;
  artifact_sha256: string | null;
  artifact_bytes: number | null;
  ota: OtaRelease | null;
  files: Array<{ name: string; bytes: number }>;   // Namen, nie Inhalte
}

export interface OtaRelease {
  build_id: string; project: string; app: string; slug: string;
  bundle_id: string; version: string; build_number: string;
  commit: string; commit_short: string; created_at: string;
  ipa_name: string; ipa_sha256: string; ipa_bytes: number; ipa_mb: number;
  plist_name: string; icon_name: string;
  install_url: string;              // itms-services://...  -> QR-Ziel
  page_url: string;
  qr_svg: string;
  profile_name: string; profile_expires: string;
  device_count: number; minimum_os: string;
}

// ---- GET /audit  (scope: read) --------------------------------------------

export interface AuditLog extends Versioned {
  entries: Array<{
    at: string; actor: string; action: string;
    project: string | null; build_id: string | null; commit: string | null;
    executor: string | null; result: string; detail: unknown;
  }>;
}

// ---- GET /published  (scope: read) ----------------------------------------

export interface Published extends Versioned {
  published: Record<string, OtaRelease & { published_at: string }>;
}

// ---- release-only ---------------------------------------------------------
// POST /builds/{id}/approve            -> BuildManifest
// POST /builds/{id}/publish            -> PublishResult  (Body: {dry_run?: boolean}, Default true)
// POST /builds/{id}/cancel  (prepare)  -> BuildManifest

export interface PublishResult extends Versioned {
  build_id: string; project: string; app: string;
  version: string; build_number: string; commit: string; sha256: string;
  target: string;
  copies: Array<{ name: string; bytes: number; replaces: boolean }>;
  icon_name: string; icon_present: boolean;
  replaces_build: string | null;
  index_html: string;
  dry_run: boolean;
  published_at?: string;
  index_written?: boolean;
}
```

## Drei Dinge, die man leicht falsch macht

**`display_status` anzeigen, nicht `status`.** Ein Dry Run hat
`status: "SUCCESS"`, aber `display_status: "SUCCESS (DRY RUN - kein echter
iOS-Build)"`. Wer `status` anzeigt, behauptet einen Build, den es nicht gibt.

**`WAITING_APPROVAL` ist kein Zwischenzustand.** Dort wartet ein Mensch. Eine
Warteschleife darauf laeuft ewig - melden und aufhoeren.

**Ohne Worker passiert nichts.** `burgys serve` nimmt Builds an und legt sie in
die Queue; `serve --worker` fuehrt sie auch aus. `status.worker.running` sagt,
was los ist.

## Polling

Fuer den Anfang reicht Polling. Sinnvolle Abstaende: Queue und Status alle
5-10 s, ein laufender Build alle 5 s. Das Rate Limit liegt bei 120 Anfragen
pro Minute **pro Token**, und bei 429 steht `retry_after` in der Antwort.

Status-Events pro Build (SSE oder Long-Poll) sind als BB-018 vorgemerkt -
gebaut wird das, wenn Polling nicht mehr reicht, nicht vorher.
