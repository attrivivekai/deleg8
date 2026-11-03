// deleg8 dispatch console. Vanilla JS, no build step; talks to the local panel API.
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const h = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clone = (o) => JSON.parse(JSON.stringify(o ?? null));

const S = {
  view: "overview",
  project: localStorageGet("deleg8.project") || "deleg8",
  overview: null,
  activity: null,
  tickets: null,
  cfg: null,        // { name, config, secrets, presets }
  draft: null,      // edited copy of cfg.config
  secrets: {},      // NAME -> new value (only edited ones)
  secretPaths: {},  // NAME -> config path that references it
  brainSame: false,
  tab: "tracker",
  busy: false,
  follow: true,
};

function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } }

async function api(method, path, body) {
  const res = await fetch(`/api${path}`, {
    method,
    headers: method === "GET" ? {} : { "Content-Type": "application/json", "X-Deleg8": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), kind === "err" ? 7000 : 3500);
}

const proj = () => S.overview?.projects.find((p) => p.name === S.project);

// ------------------------------------------------------------------ status model
function shiftState(p) {
  if (!p) return { key: "off", label: "No project", why: "" };
  if (p.error) return { key: "fault", label: "Config error", why: p.error };
  const svc = p.service || {};
  const ready = p.harness?.coding;
  if (svc.active === "failed") return { key: "fault", label: "Fault", why: "The service crashed. Check the logs, then switch On to retry." };
  if (svc.active === "activating") return { key: "standby", label: "Starting", why: "Booting the employee..." };
  if (svc.active !== "active") return { key: "off", label: "Off duty", why: "Dex is off. Switch On to start working the backlog." };
  if (svc.paused) return { key: "paused", label: "Paused", why: "Finishes any ticket in progress, then idles until resumed." };
  if (ready && !ready.ok) return { key: "standby", label: "Standby", why: ready.detail };
  return { key: "on", label: "On shift", why: ready?.detail ? `Working with ${ready.detail}` : "Working the backlog." };
}
const ledFor = (k) => ({ on: "ok", standby: "warn blink", paused: "warn", fault: "err", off: "" }[k] || "");

// ------------------------------------------------------------------ top bar
function renderBus() {
  const sys = S.overview?.system;
  if (!sys) return;
  const model = sys.llama.models.length ? sys.llama.models.join(", ") : sys.llama.service === "active" ? "loading..." : "not loaded";
  const pips = [
    ["Model", sys.llama.models.length ? "ok" : sys.llama.service === "active" ? "warn blink" : "", model],
    ["DSH UI", sys.dsh_web === "active" ? "ok" : "", sys.dsh_web],
    ["GitHub", sys.github ? "ok" : "err", sys.github || "not signed in"],
    ["Panel", "ok", "online"],
  ];
  $("#bus").innerHTML = pips.map(([n, led, v]) => `<span class="pip"><span class="led ${led}"></span>${n} <small>${h(v)}</small></span>`).join("");
}
function tickClock() { $("#clock").textContent = new Date().toLocaleTimeString([], { hour12: false }); }

function renderProjectSelect() {
  const names = (S.overview?.projects || []).map((p) => p.name);
  if (names.length && !names.includes(S.project)) S.project = names[0];
  const opts = names.map((n) => `<option value="${h(n)}" ${n === S.project ? "selected" : ""}>${h(n)}</option>`).join("");
  $("#project-select").innerHTML = opts;
  const mobile = $("#mobile-project");
  if (mobile) mobile.innerHTML = opts;
}

// ------------------------------------------------------------------ overview
function viewOverview() {
  return `
  <div class="page-head">
    <h1 class="page-title">${h(S.project)}<span class="slash">//</span>overview</h1>
    <select class="mobile-project" id="mobile-project" aria-label="Project"></select>
  </div>
  <div class="grid g-shift">
    <section class="module hot" id="shift-mod"></section>
    <section class="module" id="model-mod"></section>
  </div>
  <div class="grid g-4" id="counters"></div>
  <div class="grid g-2">
    <section class="module"><div class="mod-head"><span class="mod-title"><i>04</i>Recent activity</span>
      <a href="#activity" class="micro">All activity →</a></div><ul class="feed" id="mini-feed"></ul></section>
    <section class="module"><div class="mod-head"><span class="mod-title"><i>05</i>Live log</span>
      <a href="#logs" class="micro">Full log →</a></div><div class="term" id="mini-log"></div></section>
  </div>`;
}

function fillOverview() {
  const p = proj();
  if (!p || !$("#shift-mod")) return;
  const st = shiftState(p);
  const svc = p.service || {};
  const pos = svc.active === "active" ? (svc.paused ? "pause" : "on") : "off";
  $("#shift-mod").innerHTML = `
    <div class="mod-head"><span class="mod-title"><i>01</i>Shift control</span>
      <span class="micro">deleg8@${h(p.name)}</span></div>
    <div class="shift">
      <div class="callsign">${h(p.employee || "Dex")}<small>AI junior engineer · ${h(p.pm || "?")} · ${h((p.repos || []).join(", ") || "no repo yet")}</small></div>
      <div class="readout">
        <div class="state s-${st.key}"><span class="led ${ledFor(st.key)}"></span>${h(st.label)}</div>
        <div class="why">${h(st.why)}</div>
      </div>
      <div class="switch3" role="group" aria-label="Employee shift">
        ${[["off", "Off"], ["pause", "Pause"], ["on", "On"]].map(([k, l]) =>
          `<button class="k-${k}" data-action="shift" data-pos="${k}" aria-pressed="${pos === k}" ${S.busy ? "disabled" : ""}><span class="led"></span>${l}</button>`).join("")}
      </div>
      <div class="shift-foot">
        <label class="rocker"><input type="checkbox" data-action="autostart" ${svc.enabled === "enabled" ? "checked" : ""}>
          <span class="track"></span><span class="r-label">Start at login<small>${svc.enabled === "enabled" ? "Dex starts with your session" : "Off by default; you start Dex here"}</small></span></label>
        <div class="btn-row">
          <button class="btn ghost" data-action="svc" data-op="restart" ${svc.active === "active" ? "" : "disabled"}><span>Restart</span></button>
          <button class="btn ghost" data-action="doctor"><span>Run diagnostics</span></button>
        </div>
      </div>
    </div>`;

  const c = p.harness?.coding || {};
  const b = p.harness?.brain || {};
  const sys = S.overview.system;
  $("#model-mod").innerHTML = `
    <div class="mod-head"><span class="mod-title"><i>02</i>Brain &amp; hands</span>
      <span class="led ${c.ok && b.ok ? "ok" : "warn blink"}"></span></div>
    <dl class="kv">
      <dt>Coding</dt><dd>${h(label(c.provider))}${c.model ? ` · ${h(c.model)}` : ""}</dd>
      <dt>Planning/review</dt><dd>${h(label(b.provider))}${b.model ? ` · ${h(b.model)}` : ""}</dd>
      <dt>Context</dt><dd>${c.context ? `${Number(c.context).toLocaleString()} tokens${c.context < 65536 ? " ⚠ raise to 64k+" : ""}` : "n/a"}</dd>
      <dt>Status</dt><dd class="${c.ok ? "" : "dim"}">${h(c.ok ? "ready" : c.detail)}</dd>
      <dt>Merge</dt><dd>${p.auto_merge ? "auto-merge" : "waits for your review"}</dd>
    </dl>
    ${c.provider === "dsh" ? `<div class="btn-row mt"><a class="btn ghost" href="${h(sys.local_ai_panel)}" target="_blank" rel="noopener"><span>Open Local AI panel ↗</span></a></div>` : ""}`;
}
const label = (prov) => ({ dsh: "dsh · local model", claude_code: "Claude Code", pi: "pi" }[prov] || prov || "?");

function fillCounters() {
  const el = $("#counters");
  if (!el) return;
  const t = S.tickets?.tickets || [];
  const count = (s) => t.filter((x) => x.status === s).length;
  const total = Math.max(t.length, 1);
  const tot = S.activity?.totals || {};
  const cells = [
    ["c-todo", "To do", count("todo")],
    ["c-prog", "In progress", count("in-progress")],
    ["c-rev", "Awaiting you", count("in-review")],
    ["c-blk", "Blocked", count("blocked")],
  ];
  el.innerHTML = cells.map(([cls, name, n]) => `
    <section class="module counter ${cls}"><div class="micro">${name}</div>
      <div class="n ${n ? "" : "zero"}">${String(n).padStart(2, "0")}</div><div class="bar"><i data-w="${(n / total) * 100}"></i></div></section>`).join("")
    + `<section class="module lifetime"><span class="micro">Lifetime</span>
      <span class="lt"><b>${tot.completed ?? 0}</b> completed</span><span class="lt"><b>${(tot.agent_minutes ?? 0).toFixed(1)}</b> agent min</span>
      <span class="lt"><b>$${(tot.cost ?? 0).toFixed(2)}</b> model spend</span><span class="lt"><b>${tot.tickets ?? 0}</b> tickets touched</span></section>`;
  $$("[data-w]", el).forEach((i) => i.style.setProperty("--w", `${i.dataset.w}%`));
}

function feedHTML(events, limit) {
  if (!events?.length) return `<li class="empty">No activity yet. Give ${h(proj()?.employee || "Dex")} a ticket.</li>`;
  return events.slice(0, limit).map((e) => {
    const d = new Date(e.ts * 1000);
    const tk = e.ticket === "-" ? "" : (/^\d+$/.test(e.ticket) ? `#${e.ticket}` : e.ticket);
    const msg = e.link ? `<a href="${h(e.link)}" target="_blank" rel="noopener">${h(e.message)}</a>` : h(e.message);
    return `<li><span class="t">${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}</span>
      <span class="tk">${h(tk)}</span><span class="ph p-${h(e.phase)}">${h(e.phase)}</span><span class="msg">${msg}</span>
      <span class="cost">${e.cost ? `$${e.cost.toFixed(2)}` : ""}</span></li>`;
  }).join("");
}

function termHTML(lines) {
  if (!lines?.length) return `<span class="ts">no log output yet; the service writes here once it runs</span>`;
  return lines.map((l) => {
    const m = l.match(/^(\S+)\s+\S+\s+[^:]+:\s?(.*)$/);
    const ts = m ? m[1].slice(11, 19) : "";
    const body = (m ? m[2] : l).replace(/^\[\d\d:\d\d:\d\d\]\s*/, "");
    const cls = /error|Traceback|failed|✘/i.test(body) ? "e" : /waiting|paused|blocked|warn/i.test(body) ? "w" : /ready|done|merged|passed|✔/i.test(body) ? "g" : "";
    return `<span class="ts">${h(ts)}</span> <span class="${cls}">${h(body)}</span>`;
  }).join("\n");
}

// ------------------------------------------------------------------ tickets
function viewTickets() {
  return `
  <div class="page-head"><h1 class="page-title">${h(S.project)}<span class="slash">//</span>tickets</h1>
    <div class="btn-row"><button class="btn ghost" data-action="refresh-tickets"><span>Refresh</span></button></div></div>
  <div class="grid g-shift">
    <section class="module hot">
      <div class="mod-head"><span class="mod-title"><i>01</i>Dispatch a ticket</span></div>
      <form id="new-ticket" class="stack">
        <div class="seg" role="group" aria-label="Ticket type">
          ${[["task", "Task"], ["bug", "Bug"], ["story", "Story"], ["epic", "Epic"]].map(([v, l], i) =>
            `<button type="button" data-action="ticket-type" data-v="${v}" aria-pressed="${i === 0}">${l}</button>`).join("")}
        </div>
        <label class="field"><span>Title</span><input type="text" name="title" required placeholder="Add a /api/version endpoint"></label>
        <label class="field"><span>What, why &amp; acceptance criteria</span>
          <textarea name="body" rows="6" placeholder="Context Dex needs...&#10;&#10;Acceptance criteria&#10;- returns 200 with ...&#10;- tests cover ..."></textarea>
          <small>Specific tickets get code; vague ones get questions back on the ticket.</small></label>
        <div class="btn-row"><button class="btn solid" type="submit"><span>Dispatch to ${h(proj()?.employee || "Dex")}</span></button>
          <label class="rocker"><input type="checkbox" name="assign" checked><span class="track"></span><span class="r-label">Assign now</span></label></div>
      </form>
    </section>
    <section class="module">
      <div class="mod-head"><span class="mod-title"><i>02</i>Hand over an existing ticket</span></div>
      <form id="assign-ticket" class="stack">
        <label class="field"><span>Ticket number / key</span><input type="text" name="id" required placeholder="42  or  DEL-12"></label>
        <div class="btn-row"><button class="btn" type="submit"><span>Assign</span></button></div>
        <p class="hint">On GitHub you can also add the <b>deleg8</b> label plus a <b>type:</b> label, or use the
          “… for Dex” issue templates.</p>
      </form>
    </section>
  </div>
  <section class="module"><div class="mod-head"><span class="mod-title"><i>03</i>Board</span>
    <span class="micro" id="board-src"></span></div><div class="board" id="board"></div></section>`;
}

function fillBoard() {
  const el = $("#board");
  if (!el) return;
  if (!S.tickets) { el.innerHTML = `<div class="empty">Loading tickets...</div>`; return; }
  $("#board-src").textContent = `${S.tickets.provider} · assigned to ${proj()?.employee || "Dex"}`;
  const cols = [["todo", "To do", "var(--dim)"], ["in-progress", "In progress", "var(--amber)"],
    ["in-review", "Awaiting your review", "var(--cyan)"], ["blocked", "Blocked · needs you", "var(--red)"]];
  el.innerHTML = cols.map(([st, name, c]) => {
    const items = S.tickets.tickets.filter((t) => t.status === st);
    return `<div class="col" data-c="${c}"><div class="col-head"><span class="micro">${name}</span><span class="count">${items.length}</span></div>
      ${items.map((t) => `<article class="card"><div class="meta"><span class="id">${h(t.ref)}</span><span class="type">${h(t.type)}</span></div>
        <a class="title" href="${h(t.url)}" target="_blank" rel="noopener">${h(t.title)}</a>
        <div class="meta"><span class="dim">${t.parent ? `part of ${h(t.parent)}` : t.planned ? "planned" : ""}</span>
        <button data-action="unassign" data-id="${h(t.id)}">Unassign</button></div></article>`).join("") || `<div class="empty">empty</div>`}
    </div>`;
  }).join("");
  $$(".col", el).forEach((col) => { col.style.setProperty("--c", col.dataset.c); $$(".card", col).forEach((c) => c.style.setProperty("--c", col.dataset.c)); });
}

// ------------------------------------------------------------------ activity & logs
function viewActivity() {
  return `<div class="page-head"><h1 class="page-title">${h(S.project)}<span class="slash">//</span>activity</h1></div>
  <section class="module"><div class="mod-head"><span class="mod-title"><i>01</i>Journal</span><span class="micro">every action, with time &amp; cost</span></div>
  <ul class="feed" id="feed-full"></ul></section>`;
}
function viewLogs() {
  return `<div class="page-head"><h1 class="page-title">${h(S.project)}<span class="slash">//</span>logs</h1>
    <label class="rocker"><input type="checkbox" data-action="follow" ${S.follow ? "checked" : ""}><span class="track"></span><span class="r-label">Follow</span></label></div>
  <div class="term tall" id="log-full"></div>`;
}

// ------------------------------------------------------------------ config editor
const TABS = [["employee", "Employee"], ["tracker", "Tracker"], ["repos", "Repos"], ["harness", "Harness"], ["knowledge", "Knowledge"], ["policy", "Policy"]];
const DSH_DEFAULTS = {
  provider: "dsh",
  command: ["/usr/lib/augmentor/node/bin/node", "~/.local/share/augmentor/dsh-runtime/node_modules/@deepseek-ai/dsh/lib/bin.js"],
  env: { DSH_HOME: "~/.local/share/augmentor/dsh-home", DSH_TELEMETRY_MODE: "DISABLED" },
  env_file: "~/.local/state/augmentor-install/model.env",
};
const CLAUDE_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"];

function getPath(obj, path) { return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj); }
function setPath(obj, path, val) {
  const keys = path.split(".");
  let o = obj;
  keys.slice(0, -1).forEach((k, i) => {
    if (o[k] == null || typeof o[k] !== "object") o[k] = /^\d+$/.test(keys[i + 1]) ? [] : {};
    o = o[k];
  });
  o[keys.at(-1)] = val;
}

function input(path, labelText, opts = {}) {
  const v = getPath(S.draft, path);
  const type = opts.type || "text";
  const val = opts.list ? (v || []).join("\n") : v ?? "";
  const ctl = opts.list || opts.textarea
    ? `<textarea data-path="${path}" ${opts.list ? 'data-list="1"' : ""} rows="${opts.rows || 3}" placeholder="${h(opts.ph || "")}">${h(val)}</textarea>`
    : opts.options
      ? `<select data-path="${path}">${opts.options.map((o) => `<option ${o === val ? "selected" : ""}>${h(o)}</option>`).join("")}</select>`
      : `<input type="${type}" data-path="${path}" ${type === "number" ? 'data-num="1"' : ""} value="${h(val)}" placeholder="${h(opts.ph || "")}">`;
  return `<label class="field ${opts.wide ? "span-2" : ""}"><span>${labelText}</span>${ctl}${opts.help ? `<small>${opts.help}</small>` : ""}</label>`;
}

function secretVarFor(path, fallback) {
  const v = getPath(S.draft, path);
  const m = typeof v === "string" && v.match(/^\$\{([A-Z][A-Z0-9_]*)\}$/);
  return m ? m[1] : fallback;
}
function secretInput(path, labelText, defaultVar, help = "") {
  const name = secretVarFor(path, defaultVar);
  const known = S.cfg.secrets[name];
  const edited = S.secrets[name] !== undefined;
  const state = edited ? `<span class="secret-state set">new value staged</span>` : known?.set
    ? `<span class="secret-state set">set · ${h(known.hint)}</span>` : `<span class="secret-state unset">not set</span>`;
  return `<label class="field"><span>${labelText} ${state}</span>
    <input type="password" autocomplete="off" data-secret="${name}" data-secret-path="${path}" placeholder="${known?.set ? "leave blank to keep" : "paste token"}">
    <small>Stored privately in ~/.config/deleg8/secrets.env as <b class="mono">${h(name)}</b>; never written to the config. ${help}</small></label>`;
}

function viewConfig() {
  if (!S.draft) return `<div class="empty">Loading config...</div>`;
  const dirty = isDirty();
  return `
  <div class="page-head"><h1 class="page-title">${h(S.project)}<span class="slash">//</span>config</h1>
    <div class="btn-row"><button class="btn ghost" data-action="doctor"><span>Run diagnostics</span></button></div></div>
  <div class="tabs" role="tablist">${TABS.map(([k, l]) => `<button role="tab" data-action="tab" data-tab="${k}" aria-selected="${S.tab === k}">${l}</button>`).join("")}</div>
  <div id="tab-body">${tabBody()}</div>
  <div class="savebar ${dirty ? "show" : ""}" id="savebar"><span class="msg" id="save-msg">Unsaved changes</span>
    <div class="btn-row"><button class="btn ghost" data-action="discard"><span>Discard</span></button>
    <button class="btn solid" data-action="save"><span>Save config</span></button></div></div>`;
}

function tabBody() {
  const d = S.draft;
  const P = S.project.toUpperCase().replace(/-/g, "_");
  switch (S.tab) {
    case "employee":
      return `<section class="module"><div class="mod-head"><span class="mod-title"><i>01</i>Identity</span></div>
        <div class="form-grid">${input("employee.name", "Name", { ph: "Dex" })}${input("employee.title", "Title", { ph: "Junior Software Engineer (AI)" })}</div>
        <p class="hint">Shown in ticket comments and PRs. Use a distinct name per project if you run several.</p></section>`;
    case "tracker": {
      const prov = d.pm?.provider || "github";
      const opts = [["github", "GitHub Issues"], ["plane", "Plane"], ["jira", "Jira"]];
      let fields = "";
      if (prov === "github") fields = input("pm.github.repo", "Repository with the issues", { ph: "owner/repo", help: "Tickets labelled <b>deleg8</b> here are Dex's work queue." });
      if (prov === "plane") fields = input("pm.plane.base_url", "Plane URL", { ph: "http://localhost:8088  or  https://api.plane.so" })
        + input("pm.plane.workspace", "Workspace slug", { ph: "deleg8" }) + input("pm.plane.project", "Project identifier", { ph: "DEL" })
        + secretInput("pm.plane.api_key", "API key", `${P}_PLANE_API_KEY`, "Plane → Profile settings → Personal access tokens.");
      if (prov === "jira") fields = input("pm.jira.base_url", "Jira site", { ph: "https://your-site.atlassian.net" })
        + input("pm.jira.email", "Account email", { ph: "you@company.com" }) + input("pm.jira.project", "Project key", { ph: "DEL" })
        + secretInput("pm.jira.api_token", "API token", `${P}_JIRA_API_TOKEN`, "id.atlassian.com → Security → API tokens.");
      return `<section class="module hot"><div class="mod-head"><span class="mod-title"><i>01</i>Project tracker</span></div>
        <div class="stack"><div class="seg" role="group">${opts.map(([v, l]) => `<button data-action="pm" data-v="${v}" aria-pressed="${prov === v}"><span class="led"></span>${l}</button>`).join("")}</div>
        <div class="form-grid">${fields}</div>
        <div class="btn-row"><button class="btn" data-action="setup-tracker"><span>Prepare tracker</span></button>
        <span class="dim">Creates the labels/states Dex uses. Safe to repeat. Save first.</span></div></div></section>
        <p class="hint">${prov === "jira" ? "Jira Cloud Free covers up to 10 users." : prov === "plane" ? "Plane Community Edition is free and open source with no user limit (self-hosted)." : "GitHub Issues is free and sits right next to the code and CI."}</p>`;
    }
    case "repos": {
      const repos = d.repos || [];
      return `<div class="stack">${repos.map((r, i) => `
        <section class="module repo-card"><div class="mod-head"><span class="mod-title"><i>${String(i + 1).padStart(2, "0")}</i>${h(r.name || "new repo")}</span>
          <button class="btn danger" data-action="repo-del" data-i="${i}"><span>Remove</span></button></div>
          <div class="form-grid">${input(`repos.${i}.name`, "Name", { ph: "website" })}${input(`repos.${i}.github`, "GitHub repo", { ph: "owner/repo" })}
          ${input(`repos.${i}.default_branch`, "Default branch", { ph: "main" })}${input(`repos.${i}.deploy_url`, "Deploy URL (optional)", { ph: "https://..." })}
          ${input(`repos.${i}.setup`, "Setup commands", { list: true, ph: "uv sync -q\nnpm ci", help: "One per line. Run in a fresh checkout before Dex codes." })}
          ${input(`repos.${i}.checks`, "Checks that must pass", { list: true, ph: "npm run lint\nnpm test", help: "One per line. Dex fixes failures before opening a PR." })}</div></section>`).join("")}
        <div class="btn-row"><button class="btn" data-action="repo-add"><span>+ Add repository</span></button></div>
        <p class="hint">Your <b>gh</b> login and SSH key must be able to read and push these repos. An <b>AGENTS.md</b> in each repo boosts quality the most.</p></div>`;
    }
    case "harness":
      return `<div class="stack">${harnessEditor("coding_agent", "01", "Coding agent · writes the code")}
        <section class="module"><label class="rocker"><input type="checkbox" data-action="brain-same" ${S.brainSame ? "checked" : ""}>
          <span class="track"></span><span class="r-label">Planning &amp; review use the same harness<small>Planning, code review and reports always run read-only.</small></span></label></section>
        ${S.brainSame ? "" : harnessEditor("brain", "02", "Planning, review & reports")}</div>`;
    case "knowledge": {
      const dbs = Object.entries(d.knowledge?.databases || {});
      return `<div class="stack"><section class="module"><div class="mod-head"><span class="mod-title"><i>01</i>Wiki</span></div>
        ${input("knowledge.wiki_dirs", "Markdown folders Dex can search", { list: true, ph: "demo/wiki\n/home/you/acme/docs", help: "Relative to the deleg8 folder, or absolute." })}</section>
        <section class="module"><div class="mod-head"><span class="mod-title"><i>02</i>Read-only databases</span></div>
        <div class="stack">${dbs.map(([name], i) => `<div class="form-grid">
          <label class="field"><span>Name</span><input type="text" data-dbname="${h(name)}" value="${h(name)}"></label>
          ${input(`knowledge.databases.${name}.url`, "URL", { ph: "postgresql://readonly:pw@host/db · duckdb:///path.duckdb · sqlite:///app.db", help: "Use a read-only login. Put passwords in ${NAME} secrets." })}
          ${input(`knowledge.databases.${name}.description`, "What's in it", { ph: "Production app DB (users, orders)" })}
          <div class="field"><span>&nbsp;</span><button class="btn danger" data-action="db-del" data-name="${h(name)}"><span>Remove</span></button></div></div>`).join("") || `<div class="empty">No databases.</div>`}
          <div class="btn-row"><button class="btn" data-action="db-add"><span>+ Add database</span></button></div></div></section></div>`;
    }
    case "policy":
      return `<section class="module"><div class="mod-head"><span class="mod-title"><i>01</i>Guardrails</span></div><div class="stack">
        ${rocker("policy.auto_merge", "Auto-merge", "Off: every PR waits for your review (recommended with protected branches).")}
        ${rocker("policy.ai_review", "AI code review", "A separate read-only model run reviews each PR before CI.")}
        ${rocker("policy.wait_for_ci", "Wait for CI", "Feed CI failures back to the coder before handing over.")}
        <div class="form-grid">${input("policy.max_fix_attempts", "Fix attempts per failure", { type: "number" })}
        ${input("policy.max_review_rounds", "Review rounds", { type: "number" })}${input("policy.max_tasks_per_run", "Tasks per pass", { type: "number" })}
        ${input("policy.max_tasks_per_epic", "Max tasks per epic", { type: "number" })}${input("policy.ci_timeout_s", "CI timeout (s)", { type: "number" })}</div></div></section>`;
  }
  return "";
}

function rocker(path, title, help) {
  return `<label class="rocker"><input type="checkbox" data-path="${path}" data-bool="1" ${getPath(S.draft, path) ? "checked" : ""}>
    <span class="track"></span><span class="r-label">${title}<small>${help}</small></span></label>`;
}

function harnessEditor(role, idx, title) {
  const a = S.draft[role] || {};
  const prov = a.provider || "dsh";
  const opts = [["dsh", "Local · dsh"], ["claude_code", "Claude Code"], ["pi", "pi"]];
  const live = proj()?.harness?.[role === "coding_agent" ? "coding" : "brain"];
  let fields = "";
  if (prov === "dsh") {
    fields = input(`${role}.command`, "dsh command", { list: true, rows: 2, wide: true, help: "Node + dsh entry point (one per line), or just <b>dsh</b> if it's on PATH." })
      + input(`${role}.env.DSH_HOME`, "DSH home", { wide: true, help: "Its settings.yaml decides the model; the Local AI panel keeps it in sync." })
      + input(`${role}.env_file`, "Env file (model API key)", { wide: true })
      + (role === "coding_agent" ? input(`${role}.permission_mode`, "Sandbox while coding", { options: ["workspace-write", "danger-full-access"], help: "Use full access only if the sandbox blocks test runs." }) : "")
      + input(`${role}.timeout_s`, "Timeout per call (s)", { type: "number" });
  } else if (prov === "claude_code") {
    const model = a.model || "";
    fields = `<label class="field"><span>Model</span><select data-path="${role}.model">${CLAUDE_MODELS.map((m) => `<option ${m === model ? "selected" : ""}>${m}</option>`).join("")}
      ${model && !CLAUDE_MODELS.includes(model) ? `<option selected>${h(model)}</option>` : ""}</select><small>Requires the <b>claude</b> CLI signed in. Billed per token.</small></label>`
      + input(`${role}.max_budget_usd`, "Budget per call (USD)", { type: "number" }) + input(`${role}.timeout_s`, "Timeout per call (s)", { type: "number" });
  } else {
    fields = input(`${role}.model`, "Model", { ph: "provider/model-id", help: "Any model pi is configured for (pi --list-models)." })
      + input(`${role}.timeout_s`, "Timeout per call (s)", { type: "number" });
  }
  fields += input(`${role}.extra_args`, "Extra CLI arguments", { list: true, rows: 2, help: "Advanced. One per line." });
  return `<section class="module ${role === "coding_agent" ? "hot" : ""}"><div class="mod-head"><span class="mod-title"><i>${idx}</i>${title}</span>
    ${live ? `<span class="pip"><span class="led ${live.ok ? "ok" : "warn blink"}"></span><small>saved config · ${h(live.detail || (live.ok ? "ready" : "not ready"))}</small></span>` : ""}</div>
    <div class="stack"><div class="seg" role="group">${opts.map(([v, l]) => `<button data-action="provider" data-role="${role}" data-v="${v}" aria-pressed="${prov === v}"><span class="led"></span>${l}</button>`).join("")}</div>
    <div class="form-grid">${fields}</div>
    ${prov === "dsh" ? `<div class="btn-row"><button class="btn ghost" data-action="dsh-defaults" data-role="${role}"><span>Use Local AI panel defaults</span></button></div>` : ""}</div></section>`;
}

const isDirty = () => S.cfg && (JSON.stringify(S.draft) !== JSON.stringify(S.cfg.config) || Object.keys(S.secrets).length > 0);
function markDirty() {
  const bar = $("#savebar");
  if (bar) bar.classList.toggle("show", isDirty());
  const msg = $("#save-msg");
  if (msg) { msg.className = "msg"; msg.textContent = "Unsaved changes"; }
}
function rerenderTab() { const b = $("#tab-body"); if (b) b.innerHTML = tabBody(); $$(".tabs button").forEach((t) => t.setAttribute("aria-selected", t.dataset.tab === S.tab)); markDirty(); }

async function loadConfig() {
  S.cfg = await api("GET", `/projects/${S.project}/config`);
  S.draft = clone(S.cfg.config);
  for (const k of ["employee", "pm", "knowledge", "policy", "coding_agent"]) S.draft[k] ??= {};
  S.draft.repos ??= [];
  S.cfg.config = clone(S.draft);
  S.secrets = {};
  S.secretPaths = {};
  S.brainSame = JSON.stringify(withoutKeys(S.draft.brain, ["permission_mode", "timeout_s"])) === JSON.stringify(withoutKeys(S.draft.coding_agent, ["permission_mode", "timeout_s"]));
}
function withoutKeys(o, keys) { const c = clone(o || {}); keys.forEach((k) => delete c[k]); return c; }

async function saveConfig() {
  const cfg = clone(S.draft);
  if (S.brainSame) { cfg.brain = withoutKeys(cfg.coding_agent, ["permission_mode"]); cfg.brain.timeout_s = S.draft.brain?.timeout_s || 1800; }
  // secret fields store only a ${NAME} reference; the value goes to the private secrets file
  for (const [name, path] of Object.entries(S.secretPaths)) setPath(cfg, path, `\${${name}}`);
  try {
    const res = await api("PUT", `/projects/${S.project}/config`, { config: cfg, secrets: S.secrets });
    toast(res.restart_needed ? "Saved. Restart Dex to apply." : "Config saved.", res.restart_needed ? "warn" : "");
    await loadConfig();
    render();
  } catch (e) {
    const msg = $("#save-msg");
    msg.className = "msg err";
    msg.textContent = e.message;
  }
}

// ------------------------------------------------------------------ actions
async function shift(pos) {
  const p = proj();
  if (!p) return;
  const svc = p.service || {};
  S.busy = true; fillOverview();
  try {
    if (pos === "off") await api("POST", `/projects/${S.project}/service/stop`);
    if (pos === "on") {
      await api("POST", `/projects/${S.project}/service/resume`);
      if (svc.active !== "active") await api("POST", `/projects/${S.project}/service/start`);
    }
    if (pos === "pause") {
      await api("POST", `/projects/${S.project}/service/pause`);
      if (svc.active !== "active") await api("POST", `/projects/${S.project}/service/start`);
    }
    toast({ off: "Dex is off duty.", on: "Dex is on shift.", pause: "Dex will finish the current ticket, then idle." }[pos]);
  } catch (e) { toast(e.message, "err"); }
  S.busy = false;
  setTimeout(refreshOverview, 700);
}

async function doctor() {
  const m = $("#modal");
  m.innerHTML = `<div class="modal-head"><span class="mod-title"><i>⌁</i>Diagnostics · ${h(S.project)}</span>
    <button class="btn ghost" data-action="close-modal"><span>Close</span></button></div>
    <div class="modal-body"><div class="term" id="doctor-out">running checks...</div></div>`;
  m.showModal();
  try {
    const r = await api("POST", `/projects/${S.project}/doctor`);
    $("#doctor-out").innerHTML = r.output.split("\n").map((l) => `<span class="${l.includes("✘") ? "e" : l.includes("!") ? "w" : l.includes("✔") ? "g" : ""}">${h(l)}</span>`).join("\n");
  } catch (e) { $("#doctor-out").textContent = e.message; }
}

function newProjectModal() {
  const m = $("#modal");
  m.innerHTML = `<div class="modal-head"><span class="mod-title"><i>+</i>New project</span>
    <button class="btn ghost" data-action="close-modal"><span>Cancel</span></button></div>
    <form class="modal-body" id="new-project-form">
      <label class="field"><span>Project name</span><input type="text" name="name" required pattern="[a-z0-9][a-z0-9_\-]{0,31}" placeholder="acme">
      <small>Lowercase, digits, - or _. Creates <b class="mono">name.yaml</b> using the current harness setup; you then point it at a repo and tracker.</small></label>
      <div class="btn-row"><button class="btn solid" type="submit"><span>Create project</span></button></div></form>`;
  m.showModal();
}

document.addEventListener("click", async (ev) => {
  const el = ev.target.closest("[data-action]");
  if (!el) return;
  const a = el.dataset.action;
  if (["autostart", "follow", "brain-same"].includes(a)) return; // handled on change
  ev.preventDefault();
  try {
    if (a === "shift") return shift(el.dataset.pos);
    if (a === "svc") { await api("POST", `/projects/${S.project}/service/${el.dataset.op}`); toast(`${el.dataset.op} sent`); return setTimeout(refreshOverview, 700); }
    if (a === "doctor") return doctor();
    if (a === "close-modal") return $("#modal").close();
    if (a === "new-project") return newProjectModal();
    if (a === "refresh-tickets") { S.tickets = null; fillBoard(); return refreshTickets(true); }
    if (a === "ticket-type") { $$("[data-action=ticket-type]").forEach((b) => b.setAttribute("aria-pressed", b === el)); return; }
    if (a === "unassign") { await api("POST", `/projects/${S.project}/tickets/${encodeURIComponent(el.dataset.id)}/unassign`); toast(`Unassigned ${el.dataset.id}`); return refreshTickets(true); }
    if (a === "tab") { S.tab = el.dataset.tab; return rerenderTab(); }
    if (a === "pm") { setPath(S.draft, "pm.provider", el.dataset.v); return rerenderTab(); }
    if (a === "provider") {
      const role = el.dataset.role; const v = el.dataset.v; const cur = S.draft[role] || {};
      if (cur.provider === v) return;
      const keep = { timeout_s: cur.timeout_s };
      S.draft[role] = v === "dsh" ? { ...clone(DSH_DEFAULTS), ...keep, ...(role === "coding_agent" ? { permission_mode: "workspace-write" } : {}) }
        : v === "claude_code" ? { provider: v, model: role === "brain" ? "claude-opus-5-5" : "claude-sonnet-5-5", max_budget_usd: 5, ...keep }
          : { provider: v, ...keep };
      return rerenderTab();
    }
    if (a === "dsh-defaults") { Object.assign(S.draft[el.dataset.role], clone(DSH_DEFAULTS)); return rerenderTab(); }
    if (a === "repo-add") { S.draft.repos.push({ name: "", github: "", default_branch: "main", setup: [], checks: [] }); return rerenderTab(); }
    if (a === "repo-del") { S.draft.repos.splice(Number(el.dataset.i), 1); return rerenderTab(); }
    if (a === "db-add") { const k = S.draft.knowledge; k.databases ??= {}; let n = "db"; let i = 1; while (k.databases[n]) n = `db${++i}`; k.databases[n] = { url: "", description: "" }; return rerenderTab(); }
    if (a === "db-del") { delete S.draft.knowledge.databases[el.dataset.name]; return rerenderTab(); }
    if (a === "discard") { S.draft = clone(S.cfg.config); S.secrets = {}; S.secretPaths = {}; return rerenderTab(); }
    if (a === "save") return saveConfig();
    if (a === "setup-tracker") {
      if (isDirty()) return toast("Save the config first.", "warn");
      await api("POST", `/projects/${S.project}/setup-tracker`); return toast("Tracker prepared: labels and states are in place.");
    }
  } catch (e) { toast(e.message, "err"); }
});

document.addEventListener("input", (ev) => {
  const el = ev.target;
  if (el.dataset.path && !el.dataset.bool) {
    let v = el.value;
    if (el.dataset.list) v = v.split("\n").map((s) => s.trim()).filter(Boolean);
    if (el.dataset.num) v = v === "" ? undefined : Number(v);
    setPath(S.draft, el.dataset.path, v);
    markDirty();
  }
  if (el.dataset.secret) {
    if (el.value) { S.secrets[el.dataset.secret] = el.value; S.secretPaths[el.dataset.secret] = el.dataset.secretPath; }
    else { delete S.secrets[el.dataset.secret]; delete S.secretPaths[el.dataset.secret]; }
    markDirty();
  }
});

document.addEventListener("change", async (ev) => {
  const el = ev.target;
  if (el.dataset.bool) { setPath(S.draft, el.dataset.path, el.checked); markDirty(); }
  if (el.tagName === "SELECT" && el.dataset.path) { setPath(S.draft, el.dataset.path, el.value); markDirty(); }
  if (el.dataset.dbname !== undefined) {
    const dbs = S.draft.knowledge.databases; const old = el.dataset.dbname; const nu = el.value.trim();
    if (nu && nu !== old && !dbs[nu]) { dbs[nu] = dbs[old]; delete dbs[old]; rerenderTab(); }
  }
  if (el.dataset.action === "brain-same") { S.brainSame = el.checked; rerenderTab(); }
  if (el.dataset.action === "follow") S.follow = el.checked;
  if (el.dataset.action === "autostart") {
    try { await api("POST", `/projects/${S.project}/service/${el.checked ? "enable" : "disable"}`); toast(el.checked ? "Dex will start at login." : "Dex won't start at login."); }
    catch (e) { toast(e.message, "err"); el.checked = !el.checked; }
    refreshOverview();
  }
  if (el.id === "project-select" || el.id === "mobile-project") switchProject(el.value);
});

document.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  try {
    if (f.id === "new-ticket") {
      const type = $("[data-action=ticket-type][aria-pressed=true]")?.dataset.v || "task";
      const r = await api("POST", `/projects/${S.project}/tickets`, { title: f.title.value, body: f.body.value, type, assign: f.assign.checked });
      toast(`Created ${r.id}`); f.reset(); refreshTickets(true);
    }
    if (f.id === "assign-ticket") {
      await api("POST", `/projects/${S.project}/tickets/${encodeURIComponent(f.id.value.replace(/^#/, ""))}/assign`);
      toast(`Assigned ${f.id.value}`); f.reset(); refreshTickets(true);
    }
    if (f.id === "new-project-form") {
      const r = await api("POST", "/projects", { name: f.name.value.trim() });
      $("#modal").close(); toast(`Project ${r.created} created. Point it at a repo and tracker.`);
      await refreshOverview(); switchProject(r.created); location.hash = "#config";
    }
  } catch (e) { toast(e.message, "err"); }
});

// ------------------------------------------------------------------ routing & polling
async function switchProject(name) {
  if (isDirty() && !confirm("Discard unsaved config changes?")) { renderProjectSelect(); return; }
  S.project = name; localStorageSet("deleg8.project", name);
  S.tickets = null; S.activity = null; S.cfg = null; S.draft = null;
  render(); refreshAll();
}

async function render() {
  const view = (location.hash || "#overview").slice(1);
  S.view = ["overview", "tickets", "activity", "config", "logs"].includes(view) ? view : "overview";
  $$(".rail a[data-view]").forEach((a) => a.classList.toggle("active", a.dataset.view === S.view));
  const main = $("#main");
  if (S.view === "config" && !S.draft) { main.innerHTML = viewConfig(); try { await loadConfig(); } catch (e) { toast(e.message, "err"); } }
  main.innerHTML = { overview: viewOverview, tickets: viewTickets, activity: viewActivity, config: viewConfig, logs: viewLogs }[S.view]();
  renderProjectSelect();
  fillOverview(); fillCounters(); fillBoard(); fillFeeds(); refreshLogs();
}

function fillFeeds() {
  const ev = S.activity?.events;
  if ($("#mini-feed")) $("#mini-feed").innerHTML = feedHTML(ev, 9);
  if ($("#feed-full")) $("#feed-full").innerHTML = feedHTML(ev, 200);
}

async function refreshOverview() {
  try { S.overview = await api("GET", "/overview"); } catch (e) { return; }
  renderBus(); renderProjectSelect();
  if (!S.busy) fillOverview();
}
async function refreshActivity() { try { S.activity = await api("GET", `/projects/${S.project}/activity`); fillFeeds(); fillCounters(); } catch { /* transient */ } }
async function refreshTickets(fresh = false) {
  try { S.tickets = await api("GET", `/projects/${S.project}/tickets${fresh ? "?fresh=1" : ""}`); fillBoard(); fillCounters(); }
  catch (e) { const b = $("#board"); if (b) b.innerHTML = `<div class="empty">Tracker unavailable: ${h(e.message)}</div>`; }
}
async function refreshLogs() {
  const el = $("#mini-log") || $("#log-full");
  if (!el) return;
  try {
    const r = await api("GET", `/projects/${S.project}/logs?n=${el.id === "log-full" ? 600 : 60}`);
    el.innerHTML = termHTML(r.lines);
    if (S.follow || el.id === "mini-log") el.scrollTop = el.scrollHeight;
  } catch { /* transient */ }
}
function refreshAll() { refreshOverview(); refreshActivity(); refreshTickets(); }

window.addEventListener("hashchange", render);
window.addEventListener("beforeunload", (e) => { if (isDirty()) e.preventDefault(); });
$("#rail-port").textContent = location.host;
tickClock(); setInterval(tickClock, 1000);
setInterval(refreshOverview, 3000);
setInterval(refreshLogs, 3000);
setInterval(refreshActivity, 6000);
setInterval(() => refreshTickets(), 30000);
refreshOverview().then(render);
refreshActivity(); refreshTickets();
