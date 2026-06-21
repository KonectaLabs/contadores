# Skills

Skills y referencias de trabajo.

- `auditor/`: archivo historico importado desde `konecta-auditor`. No son skills activas autodescubiertas por Codex en Contadores; las rutas `/Users/fgoiriz/private/repos/konecta-auditor` y comandos de deploy/test dentro de esa carpeta son referencia historica salvo que el archivo diga explicitamente que fue adaptado para Contadores.
- `client-professional-photo/`: creación de retratos profesionales para clientes de Workstation desde fotos fuente.
- `client-professional-photo-edit/`: modificación/versionado de retratos profesionales ya generados.
- `codex-cli-sdk/`: referencia activa sobre Codex CLI, SDK, app-server y autenticación ChatGPT/API.
- `contadores-bot-sequence/`: secuencia WhatsApp, bot conversacional Codex/DSPy, transcripcion de audios y handoff.
- `contadores-lead-reply-playbook/`: criterio y banco de copys para contestar leads de Contadores/Abogados segun contexto CRM.
- `cursor/`: skills históricas de este repo que estaban en `.cursor/skills`.
- `funnels/`: skills del proceso nuevo para research, oferta Frankie-style, ads, Loom 60s, captions y configuracion CRM por nicho.
- `.codex/skills/`: skills activas que Codex descubre automáticamente para este repo.

## Mirror Contract

`.codex/skills/*/SKILL.md` is the active Codex skill set. `wiki/skills/` is the
human-readable mirror/index:

- root skills mirror active `.codex/skills/<name>/SKILL.md` at
  `wiki/skills/<name>/SKILL.md`;
- funnel skills keep the grouped wiki path
  `wiki/skills/funnels/<name>/SKILL.md`;
- historical auditor/cursor skills can remain wiki-only. Treat `wiki/skills/auditor/`
  as archive-first: do not run old `konecta-auditor` commands in this repo unless
  a file carries an explicit Contadores adaptation note and current commands.

Active grouped mirrors:

- `konecta-frankie-video-offer` ->
  `wiki/skills/funnels/konecta-frankie-video-offer/SKILL.md`
- `konecta-funnel-crm-config` ->
  `wiki/skills/funnels/konecta-funnel-crm-config/SKILL.md`
- `konecta-funnel-raw-memory` ->
  `wiki/skills/funnels/konecta-funnel-raw-memory/SKILL.md`
- `konecta-new-niche-funnel` ->
  `wiki/skills/funnels/konecta-new-niche-funnel/SKILL.md`
- `konecta-niche-ad-images` ->
  `wiki/skills/funnels/konecta-niche-ad-images/SKILL.md`
- `konecta-niche-loom-video` ->
  `wiki/skills/funnels/konecta-niche-loom-video/SKILL.md`
- `konecta-niche-market-research` ->
  `wiki/skills/funnels/konecta-niche-market-research/SKILL.md`
- `konecta-video-model-prompting` ->
  `wiki/skills/funnels/konecta-video-model-prompting/SKILL.md`

Mirror check:

```bash
for f in .codex/skills/*/SKILL.md; do
  name="${f#.codex/skills/}"; name="${name%/SKILL.md}"
  test -f "wiki/skills/$name/SKILL.md" || test -f "wiki/skills/funnels/$name/SKILL.md" || echo "missing wiki mirror: $name"
done
```
