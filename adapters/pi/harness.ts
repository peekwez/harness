/**
 * harness × pi (earendil-works/pi) — extension adapter.
 *
 * Install: copy to `.pi/extensions/harness.ts` (project) or
 * `~/.pi/agent/extensions/harness.ts` (global); reload with `/reload`.
 * Set HARNESS_BIN to the absolute path of `<harness-checkout>/bin/harness`,
 * and HARNESS_SLICE (or run `harness slice`) to bind the active slice.
 *
 * Bindings:
 *   session_start      -> session_start   (engine side effects)
 *   before_agent_start -> pre_context     (context injection each turn;
 *                                          the engine dedupes re-injection)
 *   tool_call          -> pre_change      ({ block: true, reason } denies)
 *   tool_result        -> post_change     (records touches, regen at turn end)
 *   turn_end           -> unit_complete   (findings surface next turn via
 *                                          before_agent_start injection)
 *
 * Repos without a .harness/ substrate are inert. Engine errors in an
 * initialised repo fail closed (tool_call blocked).
 */
import { spawnSync } from "node:child_process";
import * as path from "node:path";

const HARNESS =
  process.env.HARNESS_BIN ??
  path.join(path.dirname(new URL(import.meta.url).pathname), "..", "..", "bin", "harness");

const EDIT_TOOLS = new Set(["edit", "write", "create", "apply_patch", "multi_edit"]);

type Verdict = {
  verdict: "allow" | "allow_with_findings" | "block";
  findings: Array<{ code: string; rule_ref: string; message: string; inject?: string[] }>;
  injections: string[];
  inert?: boolean;
  engine_error?: string;
};

function callEngine(
  event: string,
  session: string,
  files: string[] = [],
  prompt: string | null = null,
): Verdict {
  const payload = {
    event,
    session_id: session || "pi-session",
    work_unit_id: process.env.HARNESS_SLICE ?? null,
    payload: {
      files: files.map((f) => ({ path: f, proposed_content_hash: null })),
      context_loaded: [],
      diff: null,
      prompt,
    },
  };
  const proc = spawnSync("python3", [HARNESS, "event"], {
    input: JSON.stringify(payload),
    encoding: "utf-8",
  });
  if (proc.status !== 0) {
    const err = (proc.stdout || proc.stderr || "").trim();
    if (err.includes("no .harness substrate")) {
      return { verdict: "allow", findings: [], injections: [], inert: true };
    }
    return { verdict: "block", findings: [], injections: [], engine_error: err };
  }
  return JSON.parse(proc.stdout) as Verdict;
}

function reasons(v: Verdict): string {
  if (v.engine_error) return `harness engine error: ${v.engine_error}`;
  return v.findings
    .map(
      (f) =>
        `[${f.code} ${f.rule_ref}] ${f.message}` +
        (f.inject?.length ? "\n" + f.inject.join("\n") : ""),
    )
    .join("; ");
}

function filesFromInput(input: unknown): string[] {
  const out: string[] = [];
  const walk = (node: unknown): void => {
    if (Array.isArray(node)) return node.forEach(walk);
    if (node && typeof node === "object") {
      for (const key of ["file_path", "path", "absolute_path", "filePath"]) {
        const v = (node as Record<string, unknown>)[key];
        if (typeof v === "string" && v) out.push(v);
      }
      Object.values(node as Record<string, unknown>).forEach(walk);
    }
  };
  walk(input);
  return [...new Set(out)];
}

// pi ExtensionAPI — typed loosely so this file tracks pi versions without
// a hard dependency; see packages/coding-agent/docs/extensions.md.
export default function harness(pi: any) {
  let session = "pi-session";

  pi.on("session_start", (event: any) => {
    session = event?.session_id ?? event?.sessionId ?? session;
    callEngine("session_start", session); // snapshot + G1; injection happens below
  });

  pi.on("before_agent_start", () => {
    const v = callEngine("pre_context", session);
    if (v.inert) return;
    const ctx = [v.injections.join("\n\n"), reasons(v)].filter(Boolean).join("\n\n");
    if (ctx) {
      return { message: { content: `harness context:\n${ctx}`, display: false } };
    }
  });

  pi.on("tool_call", (event: any) => {
    const tool = String(event?.name ?? event?.tool ?? "").toLowerCase();
    if (!EDIT_TOOLS.has(tool)) return;
    const v = callEngine("pre_change", session, filesFromInput(event?.input));
    if (v.inert) return;
    if (v.verdict === "block") {
      return { block: true, reason: reasons(v) || "blocked by harness gates" };
    }
  });

  pi.on("tool_result", (event: any) => {
    const tool = String(event?.name ?? event?.tool ?? "").toLowerCase();
    if (!EDIT_TOOLS.has(tool)) return;
    callEngine("post_change", session, filesFromInput(event?.input));
  });

  pi.on("turn_end", () => {
    // shadows regenerate + edges append; a block surfaces as injected
    // findings on the next before_agent_start (pi has no stop-block verdict)
    const v = callEngine("unit_complete", session);
    if (!v.inert && v.verdict === "block") {
      console.error(`harness: unit_complete blocked — ${reasons(v)}`);
    }
  });
}
