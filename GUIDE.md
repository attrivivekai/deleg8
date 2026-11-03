# Using Dex: the 5-minute guide

Dex is your AI junior engineer. It takes tickets, writes code with your **local model** (via dsh), opens a
pull request, and waits for **you** to review and merge. Everything runs on your machine; Claude is optional.

**Control panel → http://127.0.0.1:8808** (always on; starts at login. Dex itself stays **off** until you switch it on.)

---

## 1. Start Dex
1. **Load a model**: open the Local AI panel (http://127.0.0.1:8090), pick a model (Qwen3.8-27B works well),
   set **Context ≥ 65536**, click **Save & start**.
2. **Open the deleg8 panel** (http://127.0.0.1:8808). On **Overview**, the top bar should show **MODEL** green.
3. Flip **Shift control** to **ON**. The readout turns **ON SHIFT**.
   - **STANDBY** = Dex is running but waiting (usually: no model loaded). It starts working by itself once the
     model is up, and pauses safely if you switch or unload models.
   - Want Dex to start with your computer? Turn on **Start at login** (off by default).

## 2. Give Dex work
- **Panel → Tickets → Dispatch a ticket**: choose Task / Bug / Story / Epic, write a title plus *what, why and
  acceptance criteria*, then click **Dispatch to Dex**.
- **Hand over an existing ticket**: Tickets → enter its number → **Assign**.
- **On GitHub**: New issue → **"… for Dex"** templates (after merging PR #20), or add the `deleg8` label plus a
  `type:` label.

| type | use for | what Dex does |
|---|---|---|
| task / bug | one concrete change | codes it → one PR |
| story / epic | a bigger goal | researches, splits into tasks, a PR per task, then a summary |

Vague ticket? Dex asks questions on it and marks it **Blocked**. Reply on the ticket and Dex continues.

## 3. Review its work
Follow along on **Overview** (activity + live log) or **Tickets** (board). When a PR is AI-reviewed and CI is
green, the ticket moves to **Awaiting your review**. Review the PR on GitHub and merge it with the
**bypass rules** checkbox (or `gh pr merge <N> --squash --admin`). Dex then closes the ticket by itself.

## 4. Stop Dex
| you want to... | in the panel | terminal |
|---|---|---|
| finish the current ticket, then idle | switch to **PAUSE** | `dex pause` / `dex resume` |
| stop now (the ticket is retried next time) | switch to **OFF** | `dex stop` |
| don't start at login | **Start at login** off | `dex disable` |

## 5. Configure, or point Dex at another project
**Config** page, with one tab per area. Changes apply after **Save config** (restart Dex if it's running):
- **Tracker**: GitHub Issues, Plane or Jira. API keys/tokens go into a private secrets file
  (`~/.config/deleg8/secrets.env`, mode 600), never into the config. **Prepare tracker** creates Dex's labels.
- **Repos**: which repos Dex may change, plus setup and check commands (checks must pass before any PR).
- **Harness**: who codes and who plans/reviews: **Local · dsh**, **Claude Code**, or **pi**, each with its options.
- **Knowledge**: wiki folders and read-only database URLs Dex can research.
- **Policy**: auto-merge (keep **off** for review-first), AI review, CI wait, retry limits.
- **Employee**: name and title shown on tickets and PRs.

**New project:** click **+** next to the project picker, give it a name, then fill in Tracker and Repos and
Save. Each project has its own switch, logs, journal and workspaces. Make sure your `gh` login and SSH key can
push to its repos, and add an `AGENTS.md` (stack, commands, conventions) to the repo for best results.

**Run diagnostics** (Overview or Config) checks the model, GitHub, the tracker, databases and the wiki in one go.

---

## Terminal cheat sheet (same controls as the panel)
```
dex panel                         open the panel          dex status | logs        what is Dex doing?
dex start | stop | pause | resume                         dex enable | disable     autostart at login
dex new "title" --body "..."      new ticket for Dex      dex assign N / unassign N
dex once 42                       work ticket 42 now      dex doctor               check everything
dex -p acme <command>             another project (acme.yaml)
```
Re-install the services after moving the folder: `dex install`. Remove everything: `dex uninstall`
(configs and data are kept). How it all works: [README.md](README.md) · integrations:
[docs/integrations.md](docs/integrations.md).
