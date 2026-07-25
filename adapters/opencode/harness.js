/**
 * harness × OpenCode (anomalyco/opencode) — plugin adapter.
 *
 * Install: copy to `<repo>/.opencode/plugins/harness.js` (project) or
 * `~/.config/opencode/plugins/harness.js` (global).
 * Set HARNESS_BIN to the absolute path of `<harness-checkout>/bin/harness`.
 *
 * Bindings:
 *   session.created (event)  -> session_start   (G1 + G6 baseline snapshot)
 *   tool.execute.before      -> pre_change      (throw = deny; edit/write/patch/bash)
 *   tool.execute.after       -> post_change     (touch recording)
 *   session.idle (event)     -> unit_complete   (shadow regen, edges, G4-G8)
 *   session.compacted (event)-> COMPACTION_REACHED telemetry (defect signal)
 *
 * Context injection: OpenCode has no additionalContext hook — Phase-1
 * context arrives via AGENTS.md plus the build workflow running
 * `harness resolve --slice <id>` (see README). G2 still verifies at
 * pre_change and denies with a pointer if context wasn't loaded.
 *
 * Contract: repos without a .harness/ substrate are inert; engine errors in
 * an initialised repo fail closed (throw).
 */
import { spawnSync } from "node:child_process";

const EDIT_TOOLS = new Set(["edit", "write", "patch", "bash"]);

function makeEngine(root) {
  const bin = process.env.HARNESS_BIN;
  return function callEngine(event, session, files = [], slice = null) {
    if (!bin) {
      // fail loud once, never silently unenforced
      console.error(
        "harness plugin: HARNESS_BIN is not set — enforcement disabled. " +
          "export HARNESS_BIN=/abs/path/to/harness/bin/harness",
      );
      return { verdict: "allow", findings: [], injections: [], inert: true };
    }
    const payload = {
      event,
      session_id: session || "opencode-session",
      work_unit_id: slice ?? process.env.HARNESS_SLICE ?? null,
      payload: {
        files: files.map((f) => ({ path: f, proposed_content_hash: null })),
        context_loaded: [],
        diff: null,
        prompt: null,
      },
    };
    const proc = spawnSync("python3", [bin, "--root", root, "event"], {
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
    return JSON.parse(proc.stdout);
  };
}

function reasons(v) {
  if (v.engine_error) return `harness engine error: ${v.engine_error}`;
  return v.findings
    .map(
      (f) =>
        `[${f.code} ${f.rule_ref}] ${f.message}` +
        (f.inject && f.inject.length ? "\n" + f.inject.join("\n") : ""),
    )
    .join("; ");
}

function filesFromArgs(args) {
  const out = [];
  const walk = (node) => {
    if (Array.isArray(node)) return node.forEach(walk);
    if (node && typeof node === "object") {
      for (const key of ["filePath", "file_path", "path", "absolute_path"]) {
        if (typeof node[key] === "string" && node[key]) out.push(node[key]);
      }
      Object.values(node).forEach(walk);
    }
  };
  walk(args);
  return [...new Set(out)];
}

export const HarnessPlugin = async ({ directory, worktree }) => {
  const root = worktree || directory;
  const callEngine = makeEngine(root);

  return {
    "tool.execute.before": async (input, output) => {
      if (!EDIT_TOOLS.has(input.tool)) return;
      const files = input.tool === "bash" ? [] : filesFromArgs(output.args);
      if (input.tool !== "bash" && files.length === 0) return;
      const v = callEngine("pre_change", input.sessionID, files);
      if (v.inert) return;
      if (v.verdict === "block") {
        // throwing is OpenCode's documented deny mechanism
        throw new Error(reasons(v) || "blocked by harness gates");
      }
    },

    "tool.execute.after": async (input, _output) => {
      if (!EDIT_TOOLS.has(input.tool) || input.tool === "bash") return;
      const files = filesFromArgs(input.args);
      if (files.length) callEngine("post_change", input.sessionID, files);
    },

    event: async ({ event }) => {
      const sid =
        event?.properties?.sessionID ?? event?.properties?.info?.id ?? "opencode-session";
      if (event.type === "session.created") {
        callEngine("session_start", sid);
      } else if (event.type === "session.idle") {
        // turn end: regenerate shadows, append edges, run unit_complete gates
        const v = callEngine("unit_complete", sid);
        if (!v.inert && v.verdict === "block") {
          console.error(`harness: unit_complete blocked — ${reasons(v)}`);
        }
      } else if (event.type === "session.compacted") {
        // compaction is a decomposition-defect signal, recorded loudly
        if (process.env.HARNESS_BIN) {
          spawnSync(
            "python3",
            [process.env.HARNESS_BIN, "--root", root, "memory", "flush",
             "--session", sid, "--compaction"],
            { encoding: "utf-8" },
          );
        }
      }
    },
  };
};
