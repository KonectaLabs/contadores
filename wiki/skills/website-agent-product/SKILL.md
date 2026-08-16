---
name: website-agent-product
description: Operate, explain, inspect, or change the current Contadores product, which now means Website Agent only. Use for architecture, WhatsApp behavior, Juan, published pages, admin panel, queues, follow-ups, activity, AI costs, storage, product code, or any request that mentions Contadores as a running system.
---

# Website Agent Product

Treat Website Agent as the only active Contadores product.

## Repositories

- `website-agent/`: separate Git repo for FastAPI, frontend, WhatsApp, page
  publishing and Juan's skills.
- `../agent-runtime`: separate Git repo for durable agent execution.

Check Git state and the current README in the relevant repo before making a
claim or change. Do not use the historical root runtime as current evidence.

## Runtime

Website Agent Compose owns `gateway`, `app`, `agent-server` and `postgres`.
FastAPI uses `website-agent/data/website-agent.sqlite`. Agent Runtime uses the
PostgreSQL volume `website-agent_agent-runtime-postgres`. Treat both stores as
required production state.

Agent Runtime is generic and does not contain a project agent or project
skills. `website-agent/Dockerfile.agent` owns the concrete `agent-server` image
and combines the sibling runtime source with Website Agent's graph and skills.

## Agent behavior

Read only the relevant skill under `website-agent/skills/`:

- `sales-flow`
- `service-policy`
- `website-build`
- `website-design`
- `image-workflow`
- `human-handoff`

These files are the source of truth for Juan. Frankie Fihn and Konecta
marketing skills are operator knowledge and are not automatically part of
Juan's runtime.

## Change boundary

Make application and runtime changes in their owning repos. Validate each repo
separately. A product change is complete only after compatible `main` commits
are pushed, deployed under `/root/projects/`, and verified through internal and
public health checks.
