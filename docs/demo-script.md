# Demo script (3:00)

A 3-minute screen recording of the procurement scenario. It uses only the built-in scripted model, so every take shows the same steps and numbers. Leave `OPENROUTER_API_KEY` empty in `.env`.

Two windows are on screen: a terminal and a browser. The browser has two profiles: **A** for alice (buyer) and **B** for morgan (procurement manager). Two profiles keep the Keycloak sessions apart.

## Shots

| # | Time | On screen | What you say |
|---|---|---|---|
| 1 | 0:00-0:05 | Terminal. `make demo` is already typed. Press Enter. | "This AI agent buys raw material for a factory." |
| 2 | 0:05-0:17 | Terminal. The output appears (about 4 seconds). Point at the line `DENIED draft_po ... "quantity_kg": 250000`. | "A supplier note hides an order for 250,000 kilos." / "The model believes it and tries to order." |
| 3 | 0:17-0:30 | Terminal. Point at `-> ... denied by policy: quantity 250000 kg is outside the allowed range`, then at `ok draft_po ... 13000`. | "The policy server says no. The limit is 20,000 kilos." / "Then the agent drafts the right amount: 13,000 kilos." |
| 4 | 0:30-0:52 | Browser A, tab `https://github.com/DigitalRozen/sovereign-agent-reference`. Scroll to the "What this shows" table. | "Why is this safe? Four parts, all outside the model." / "The agent runs on Kubernetes, on one machine." / "Every model call goes through a gateway with a budget." / "Keycloak checks every user and every role." / "Model code runs in a pod with no network." |
| 5 | 0:52-1:05 | Browser A, `http://localhost:8080/agent/`. Click *Log in*, sign in as `alice`. | "Alice is a buyer. Alice logs in through Keycloak." / "The agent has no rights of its own." / "It works with Alice's token." |
| 6 | 1:05-1:30 | Browser A. Under *Your recent runs*, click the run. Scroll to the `run_python` step. | "Here is every step the agent took." / "First it reads stock, orders and suppliers." / "Then it writes Python to compute the quantity." / "That code runs in a new pod." / "No network, no secrets, fifteen seconds maximum." |
| 7 | 1:30-1:42 | Browser A. Scroll to the red `draft_po` step (*denied / failed*). | "Here is the blocked order, in red." / "The model obeyed the attack. The controls still held." |
| 8 | 1:42-1:57 | Browser A. Click *Drafts*, then *Approve* on draft #1. The banner says `not approved (403): approving requires the procurement_manager role`. | "The agent can only create drafts." / "Can Alice approve it? No. The server refuses." |
| 9 | 1:57-2:22 | Browser B, `http://localhost:8080/agent/`. Click *Log in*, sign in as `morgan`. Click *Drafts*, then *Approve*. The banner says `Draft #1 approved: ERP order #1 (... EUR)`. | "Morgan is the procurement manager." / "Morgan logs in, in a second browser." / "Morgan approves the draft." / "Only now is there a real order in the ERP." / "13,000 kilos, for 37,050 euros." |
| 10 | 2:22-2:40 | Browser B. Click *Audit log*. Point at the red `po.draft_rejected` row and the green `po.approved` row. | "Every step is in the audit log." / "Allowed and denied. Who did it, and when." / "The agent writes here. It cannot change anything." |
| 11 | 2:40-2:52 | Terminal. Press Ctrl+L, type `make audit`, press Enter. Point at `ERROR: audit.events is append-only` and `rows left`. | "Can anyone delete this log? Let's try as the database admin." / "The database refuses. The log is append-only." |
| 12 | 2:52-3:00 | Browser A, tab `https://github.com/DigitalRozen/sovereign-agent-reference`. | "The code and the tests are on GitHub." / "Thanks for watching." |

Shot lengths in seconds: 5 + 12 + 13 + 22 + 13 + 25 + 12 + 15 + 25 + 18 + 12 + 8 = 180, that is 3:00.

Every spoken line has 12 words or fewer. A `/` separates lines; pause briefly at each one.

## Recording checklist

**Screen and windows**

- Record at 1280x720. Set both the terminal and the browser windows to 1280x720 and switch between them; do not show them side by side.
- Terminal: dark theme, monospace font at about 16 px so that 120 columns fit the width. `make demo` lines are up to about 115 characters wide; check that they do not wrap.
- Browser: zoom 100%, bookmarks bar hidden, no extensions visible. Turn off desktop notifications.
- Browser A (alice) has two tabs: the GitHub repo page (you must be logged in to GitHub, the repo is private) and `http://localhost:8080/agent/`. Browser B (morgan) has one tab: `http://localhost:8080/agent/`.

**Before the first take**

```bash
make doctor       # every line PASS or WARN
make up           # about 5 minutes on a new cluster; safe to re-run on an existing one
make reset-demo   # no drafts, no orders, no runs, nobody logged in, empty audit log
make creds        # copy the passwords for alice and morgan
```

`make reset-demo` makes the take start clean even if you ran `make smoke` or `make demo` before: the draft and the ERP order are both #1 and the audit log is empty. The old audit table is not deleted; it is renamed (`audit.events_until_<time>`) and stays append-only.

Type `make demo` in the terminal and do not press Enter yet.

**Between takes**

1. `make reset-demo` (about 30 seconds). It also ends every Keycloak session, so both browser profiles show *Log in* after a reload. The passwords do not change.
2. In both browser profiles, reload `http://localhost:8080/agent/`.
3. In the terminal, press Ctrl+L and type `make demo` again, without Enter.

If the first `make demo` after `make up` takes longer than about 10 seconds, cut the wait in editing; the narration for shot 2 starts when the output appears.
