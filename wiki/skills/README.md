# Skills

## Active product skills

- `website-agent-product`: canonical product boundary and architecture.
- `website-agent-rollout`: production backup, deploy and verification.
- `client-professional-photo*`: portrait creation and edits for Website Agent
  pages or marketing assets.
- `codex-cli-sdk`: generic technology reference only.

Juan's runtime skills live in the separate `website-agent/skills/` directory:
`sales-flow`, `service-policy`, `website-build`, `website-design`,
`image-workflow` and `human-handoff`.

## Preserved business knowledge

- `frankie-fihn/` and `frankie-fihn-*`: source catalog and specialized methods.
- `funnels/`: market research, offer, ads, Loom and video assets. It does not
  configure a CRM.
- `konecta-meta-ads`: creative strategy and asset preparation only.
- call-intake, client and professional-photo skills: operator/client knowledge.

Historical reply banks remain wiki-only. They preserve evidence and copy but
cannot operate Website Agent or define its current price and policy.

## Mirror contract

`.codex/skills/<name>/SKILL.md` is active for Codex. `wiki/skills/` mirrors
those skills for humans. Grouped marketing skills use
`wiki/skills/funnels/<name>/SKILL.md`.

Run this check after changes:

```bash
for f in .codex/skills/*/SKILL.md; do
  name="${f#.codex/skills/}"; name="${name%/SKILL.md}"
  test -f "wiki/skills/$name/SKILL.md" || \
    test -f "wiki/skills/funnels/$name/SKILL.md" || \
    echo "missing wiki mirror: $name"
done
```
