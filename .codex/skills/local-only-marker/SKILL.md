---
name: local-only-marker
description: Use when you need to confirm you are on the local MacBook and not on the real server by checking for the local-only marker file.
---

# Local Only Marker

Use this skill when you need a fast environment check.

## Rule

If `[LOCAL_ONLY_NOTE.txt](/Users/fgoiriz/private/repos/contadores/LOCAL_ONLY_NOTE.txt)` exists and is readable, you are on the local MacBook workspace, not on the production server data host.

## Interpretation

- File present: local workspace.
- File absent: do not assume anything. Check the runtime environment instead.

## Use

This marker is only a convenience guardrail. It does not replace server-side runtime configuration.
