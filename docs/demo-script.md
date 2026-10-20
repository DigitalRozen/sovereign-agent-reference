# Demo script (about 3 minutes)

Recorded straight from `make up`. No API key is needed; with `OPENROUTER_API_KEY` set, the same flow runs on a real model.

**Before recording:** run `make up && make smoke`, then `make creds`. Open three browser windows or profiles, one per user, so sessions do not mix.

| Time | Screen | What to say |
|---|---|---|
| 0:00–0:20 | README top | "Agents that run on a customer's infrastructure touch real systems. Trusting the model is not a control. This is a reference architecture where every control sits outside the model." |
| 0:20–0:45 | `docs/architecture.md` diagram | Walk left to right: identity, gateway, tools, sandbox, data, audit. "The agent holds no privileges of its own. It acts with the user's token and the user's LLM budget." |
| 0:45–1:00 | Terminal: `kubectl get pods -A` | "All of it runs on Kubernetes, here a single-node k3s. CI builds a fresh cluster and runs the same tests on every push." |
| 1:00–1:50 | Browser as **alice** (buyer): log in through Keycloak, run the prefilled question, open the run | Point at the steps: reads over MCP, then `run_python`. "The quantity is computed in a throwaway Kubernetes Job with no network." Then the red `draft_po`: "A supplier note contained an injected instruction. This model obeyed it and tried to order 250,000 kg. The tool server's policy refused it. The model then drafted 13,000 kg correctly." |
| 1:50–2:15 | Browser as **morgan** (manager): *Drafts*, then Approve | "Only now does an ERP order exist, created with the manager's own token. Alice's approve click is refused, and so is self-approval." Show the banner with the ERP order and its EUR total. |
| 2:15–2:40 | *Audit log* page; then terminal `make demo` or the gateway test | "Every allowed and refused decision is here, and the table rejects edits." Optionally run the agent as **val** (viewer) twice to show the sandbox refusing a viewer, and the gateway's 429 when val's rate limit is hit. |
| 2:40–3:00 | `docs/adr/` list, README limitations | "Each tradeoff is an ADR. Limitations are listed honestly: no HA, dev-mode Keycloak, no kernel-level sandbox yet, token forwarding instead of exchange. Built with AI-assisted coding; the tests are the proof." |

**Tips:** keep the terminal font large. Record at 1080p. Pre-warm the cluster so the first sandbox Job does not wait on the image.
