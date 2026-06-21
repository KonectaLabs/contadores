# Plan 141: Classify Versioned Media Binaries With Manifest

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- media README.md .gitignore`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: repository-hygiene
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: RETENTION-04

## Why This Matters

The repo intentionally keeps some media as examples, templates, and presentation assets. It also tracks uploads, screenshots, ZIPs, preview videos, and generated professional photos. Without a manifest, future reviewers cannot tell what is safe reference material versus client-private or generated output that should live in `data/`.

Versioned media needs an explicit classification gate.

## Current State

- Examples README says new generated outputs should stay untracked:

```markdown
media/examples/README.md:5
These files are kept because they document working creative/output patterns.
```

```markdown
media/examples/README.md:6
throwaway screenshots, Playwright snapshots, local exports, and generated output
```

- Templates README says generated client work belongs in `data/`:

```markdown
media/templates/README.md:8
Generated client work belongs in `data/`.
```

- The repo tracks media paths with risky names such as uploads, screenshots, previews, ZIPs, and generated photos:

```text
media/examples/workstation/marielis-workstation-test/preview.mp4
media/examples/workstation/marielis-workstation-test/professional-photo.jpg
media/presentations/loom-video-vender-a-contadores/Loom Video vender a contadores.zip
media/presentations/loom-video-vender-a-contadores/uploads/WhatsApp Image 2026-04-20 at 18.43.54.jpeg
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Media classification scan | `git ls-files media | rg -n "uploads|WhatsApp Image|preview|screenshots|\\.zip|professional-photo|\\.mov|\\.mp4|\\.jpg|\\.jpeg|\\.png"` | every risky tracked media path is classified or removed |
| Manifest check | `rg -n "client-private|reference|template|generated|public|media manifest" media README.md .gitignore` | media policy is documented |
| Git check | `git status --short -- media README.md .gitignore` | only intended manifest/docs/media moves changed |

## Scope

**In scope**:
- Add a `media/MANIFEST.md` or structured manifest classifying committed binaries.
- Mark each binary as template, reference, public, client-private, or generated.
- Move or remove raw uploads/generated previews only after owner review.
- Add a lightweight verification command for risky filenames.
- Update docs for what belongs in `media/` versus `data/`.

**Out of scope**:
- Runtime Workstation pruning; plan 048 owns runtime Workstation artifacts.
- Workstation ZIP export safety; plan 050 owns export sanitization.
- Provider identifier cleanup; plan 124 owns docs/provider IDs.

## Git Workflow

- Branch: `codex/classify-versioned-media`
- Commit message: `Classify versioned media binaries`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Inventory tracked media

Use `git ls-files media` and group files by type, source, and sensitivity.

Do not delete or move files in this step unless the owner has already approved that class.

### Step 2: Add a manifest

Create `media/MANIFEST.md` or a simple structured file with:

- path,
- classification,
- owner/source,
- reason for versioning,
- allowed retention/removal action.

### Step 3: Tighten policy docs

Update media README files and `.gitignore` if needed so new generated outputs default to `data/`.

### Step 4: Add a verification command

Document a command that highlights risky names such as `uploads`, `WhatsApp Image`, `preview`, `screenshots`, `.zip`, and generated photos.

## Test Plan

- Manifest covers every tracked risky media path.
- Git status shows only intentional manifest/docs/media moves.
- No source code changes are required.

## Done Criteria

- [ ] Every tracked binary has a classification.
- [ ] Risky generated/client-private assets are flagged for owner review or moved after approval.
- [ ] Docs explain what future media may be committed.
- [ ] Verification command catches risky filenames.

## STOP Conditions

- Owner review is needed before classifying or removing client-specific media.
- A binary is required by tests or docs but has no clear source/license.
- Moving files would break existing presentations or examples without a replacement.

## Maintenance Notes

Do not normalize all media as safe just because it is already committed. Classify first, then decide.
