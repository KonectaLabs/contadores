# Instrucciones obligatorias para agentes

1. Leer completo `/root/projects/MUST_READ.md` antes de actuar.
2. Tratar Contadores exclusivamente como Website Agent.
3. Leer `.codex/skills/website-agent-product/SKILL.md` y, para cualquier
   operación de server o rollout,
   `.codex/skills/website-agent-rollout/SKILL.md`.
4. Tratar `website-agent/` y `agent-runtime/` como repos Git separados; comprobar
   branch, HEAD y worktree de ambos.
5. No mezclar `.codex/skills/` con `website-agent/skills/`: las primeras son para
   operadores y las segundas son el runtime de Juan.
6. No usar referencias históricas de CRM, funnels de Sheets, workstation, bots
   antiguos, `src/` del viejo Contadores ni `agent-runtime-release-*`.
7. No imprimir ni reemplazar `.env`; no borrar SQLite ni el volumen PostgreSQL.
8. Mantener `main`, fast-forward y worktrees limpios. Nunca usar force-push o
   resets destructivos.
9. Diferenciar siempre código, commit, push, deploy, health y QA funcional.
10. El estado vivo y el código actual del server prevalecen sobre documentación
    que haya quedado desactualizada.
