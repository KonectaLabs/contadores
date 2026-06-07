#!/usr/bin/env python3
"""Simple CLI to create, check, and delete WhatsApp templates.

Usage examples:
  uv run python scripts/whatsapp_templates.py create --name my_template --body "Hola {{nombre}}" -e nombre=Juan --dry-run
  uv run python scripts/whatsapp_templates.py check --name my_template
  uv run python scripts/whatsapp_templates.py delete --name my_template --dry-run
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import typer
from dotenv import load_dotenv


ENV_WA_ACCESS_TOKEN = "WA_ACCESS_TOKEN"
ENV_WA_BUSINESS_ACCOUNT_ID = "WA_BUSINESS_ACCOUNT_ID"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env", override=False)

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="WhatsApp templates helper for operators/AI.",
)


def _get_client(token: str | None, business_account_id: str | None) -> Any:
    business_account_id = business_account_id or os.getenv("WA_BUSINESS_ID")
    if not token:
        raise typer.BadParameter(
            f"Missing token. Pass --token or set {ENV_WA_ACCESS_TOKEN}."
        )
    if not business_account_id:
        raise typer.BadParameter(
            "Missing business account id. "
            f"Pass --business-account-id or set {ENV_WA_BUSINESS_ACCOUNT_ID}."
        )
    try:
        from pywa import WhatsApp
    except ImportError as exc:
        raise RuntimeError(
            "pywa is required. Install with: uv sync --extra messenger"
        ) from exc
    return WhatsApp(token=token, business_account_id=business_account_id)


def _parse_examples(example_items: list[str]) -> dict[str, str]:
    examples: dict[str, str] = {}
    for item in example_items:
        if "=" not in item:
            raise typer.BadParameter(
                f"Invalid --example '{item}'. Use key=value format."
            )
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise typer.BadParameter(
                f"Invalid --example '{item}'. Key cannot be empty."
            )
        examples[key] = value
    return examples


def _load_specs(spec_file: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(spec_file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise typer.BadParameter(f"Spec file not found: {spec_file}") from exc
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"Invalid JSON in {spec_file}: {exc}") from exc

    if isinstance(payload, dict) and "templates" in payload:
        payload = payload["templates"]
    if not isinstance(payload, list):
        raise typer.BadParameter(
            "Spec file must be a list or {\"templates\": [...]}."
        )

    specs: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise typer.BadParameter("Each template spec must be an object.")
        name = str(item.get("name", "")).strip()
        body = str(item.get("body", "")).strip()
        if not name or not body:
            raise typer.BadParameter("Each template spec requires non-empty name and body.")
        examples_raw = item.get("examples") or {}
        example_values_raw = item.get("example_values") or []
        if not isinstance(examples_raw, dict):
            raise typer.BadParameter(
                f"examples for template '{name}' must be an object."
            )
        if not isinstance(example_values_raw, list):
            raise typer.BadParameter(
                f"example_values for template '{name}' must be a list."
            )
        specs.append(
            {
                "name": name,
                "body": body,
                "language": str(item.get("language", "es")).strip() or "es",
                "category": str(item.get("category", "MARKETING")).strip() or "MARKETING",
                "parameter_format": str(item.get("parameter_format", "NAMED")).strip() or "NAMED",
                "footer": item.get("footer"),
                "examples": {str(k): str(v) for k, v in examples_raw.items()},
                "example_values": [str(v) for v in example_values_raw],
            }
        )
    return specs


def _collect_names(names: list[str], spec_file: Path | None) -> list[str]:
    final_names = [name.strip() for name in names if name.strip()]
    if spec_file:
        final_names.extend(spec["name"] for spec in _load_specs(spec_file))
    return sorted(set(final_names))


def create_templates(
    wa: Any,
    specs: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Create templates and return one result per template."""
    if dry_run:
        return [
            {"name": spec["name"], "ok": True, "status": "DRY_RUN", "template_id": None}
            for spec in specs
        ]

    from pywa.types.templates import (
        BodyText,
        FooterText,
        ParamFormat,
        Template,
        TemplateCategory,
        TemplateLanguage,
    )

    language_map = {
        "es": TemplateLanguage.SPANISH,
        "es_es": TemplateLanguage.SPANISH,
        "en": TemplateLanguage.ENGLISH_US,
        "en_us": TemplateLanguage.ENGLISH_US,
    }
    category_map = {
        "MARKETING": TemplateCategory.MARKETING,
        "UTILITY": TemplateCategory.UTILITY,
        "AUTHENTICATION": TemplateCategory.AUTHENTICATION,
    }
    format_map = {
        "NAMED": ParamFormat.NAMED,
        "POSITIONAL": ParamFormat.POSITIONAL,
    }

    results: list[dict[str, Any]] = []
    for spec in specs:
        try:
            lang_key = spec["language"].lower().replace("-", "_")
            language = language_map.get(lang_key)
            if language is None:
                raise ValueError(f"unsupported language '{spec['language']}'")

            category = category_map.get(spec["category"].upper())
            if category is None:
                raise ValueError(f"unsupported category '{spec['category']}'")

            parameter_format = format_map.get(spec["parameter_format"].upper())
            if parameter_format is None:
                raise ValueError(
                    f"unsupported parameter_format '{spec['parameter_format']}'"
                )

            named_examples = spec.get("examples", {})
            positional_examples = spec.get("example_values", [])
            if (
                parameter_format == ParamFormat.POSITIONAL
                and not positional_examples
                and named_examples
                and all(str(key).isdigit() for key in named_examples)
            ):
                positional_examples = [
                    named_examples[key]
                    for key in sorted(named_examples.keys(), key=lambda key: int(key))
                ]

            if parameter_format == ParamFormat.POSITIONAL:
                components = [BodyText(spec["body"], *positional_examples)]
            else:
                components = [BodyText(spec["body"], **named_examples)]
            if spec.get("footer"):
                components.append(FooterText(text=str(spec["footer"])))

            template = Template(
                name=spec["name"],
                language=language,
                category=category,
                parameter_format=parameter_format,
                components=components,
            )
            response = wa.create_template(template)
            results.append(
                {
                    "name": spec["name"],
                    "ok": True,
                    "status": str(getattr(response, "status", "UNKNOWN")),
                    "template_id": str(getattr(response, "id", "")) or None,
                }
            )
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            lowered = message.lower()
            if "already exists" in lowered or "duplicate" in lowered:
                results.append(
                    {
                        "name": spec["name"],
                        "ok": True,
                        "status": "ALREADY_EXISTS",
                        "template_id": None,
                    }
                )
            else:
                results.append(
                    {
                        "name": spec["name"],
                        "ok": False,
                        "status": "ERROR",
                        "template_id": None,
                        "error": message,
                    }
                )
    return results


def check_templates(wa: Any, names: list[str]) -> list[dict[str, Any]]:
    """Check template status by names."""
    from pywa.types.templates import TemplateStatus

    results: list[dict[str, Any]] = []
    for name in names:
        try:
            templates = wa.get_templates(name=name)
            if not templates:
                results.append(
                    {
                        "name": name,
                        "found": False,
                        "approved": False,
                        "status": "NOT_FOUND",
                        "template_id": None,
                    }
                )
                continue
            template = templates[0]
            status = getattr(template, "status", "UNKNOWN")
            results.append(
                {
                    "name": name,
                    "found": True,
                    "approved": status == TemplateStatus.APPROVED,
                    "status": str(status),
                    "template_id": str(getattr(template, "id", "")) or None,
                    "category": str(getattr(template, "category", "")) or None,
                    "language": str(getattr(template, "language", "")) or None,
                }
            )
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            lowered = message.lower()
            if "not found" in lowered or "does not exist" in lowered:
                results.append(
                    {
                        "name": name,
                        "found": False,
                        "approved": False,
                        "status": "NOT_FOUND",
                        "template_id": None,
                    }
                )
            else:
                results.append(
                    {
                        "name": name,
                        "found": False,
                        "approved": False,
                        "status": "ERROR",
                        "template_id": None,
                        "error": message,
                    }
                )
    return results


def delete_templates(
    wa: Any | None,
    names: list[str],
    *,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Delete templates by names."""
    if dry_run:
        return [
            {
                "name": name,
                "ok": True,
                "status": "DRY_RUN",
                "deleted_count": None,
            }
            for name in names
        ]

    if wa is None:
        raise ValueError("WhatsApp client is required when dry_run is False.")

    results: list[dict[str, Any]] = []
    for name in names:
        try:
            templates = wa.get_templates(name=name)
            if not templates:
                results.append(
                    {
                        "name": name,
                        "ok": True,
                        "status": "NOT_FOUND",
                        "deleted_count": 0,
                    }
                )
                continue
            deleted_count = 0
            if not dry_run:
                wa.delete_template(template_name=name)
            deleted_count = len(templates)
            results.append(
                {
                    "name": name,
                    "ok": True,
                    "status": "DRY_RUN" if dry_run else "DELETED",
                    "deleted_count": deleted_count,
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "name": name,
                    "ok": False,
                    "status": "ERROR",
                    "deleted_count": 0,
                    "error": str(exc),
                }
            )
    return results


def _print_results(results: list[dict[str, Any]], as_json: bool, title: str) -> None:
    if as_json:
        typer.echo(json.dumps(results, indent=2, sort_keys=True))
        return
    typer.echo(title)
    for result in results:
        typer.echo(f"- {result}")


@app.command("create")
def create_command(
    spec_file: Path | None = typer.Option(
        None,
        "--spec-file",
        help='JSON file (list or {"templates":[...]}).',
    ),
    name: str | None = typer.Option(None, "--name", help="Template name (inline mode)."),
    body: str | None = typer.Option(None, "--body", help="Template body (inline mode)."),
    language: str = typer.Option("es", "--language", help="es or en."),
    category: str = typer.Option("MARKETING", "--category", help="MARKETING/UTILITY/AUTHENTICATION."),
    parameter_format: str = typer.Option("NAMED", "--parameter-format", help="NAMED/POSITIONAL."),
    example: list[str] = typer.Option([], "--example", "-e", help="Example placeholder key=value."),
    example_value: list[str] = typer.Option(
        [],
        "--example-value",
        help="Positional example value. Repeat in order for POSITIONAL templates.",
    ),
    footer: str | None = typer.Option(None, "--footer", help="Optional footer."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate/prepare only."),
    as_json: bool = typer.Option(False, "--json", help="JSON output."),
    token: str | None = typer.Option(
        None, "--token", envvar=ENV_WA_ACCESS_TOKEN, help="WhatsApp access token."
    ),
    business_account_id: str | None = typer.Option(
        None,
        "--business-account-id",
        envvar=ENV_WA_BUSINESS_ACCOUNT_ID,
        help="WhatsApp business account id.",
    ),
) -> None:
    """Create templates from inline flags and/or spec file."""
    specs: list[dict[str, Any]] = []
    if spec_file:
        specs.extend(_load_specs(spec_file))

    if name or body:
        if not name or not body:
            raise typer.BadParameter("--name and --body must be provided together.")
        specs.append(
            {
                "name": name.strip(),
                "body": body,
                "language": language,
                "category": category,
                "parameter_format": parameter_format,
                "footer": footer,
                "examples": _parse_examples(example),
                "example_values": [str(value) for value in example_value],
            }
        )

    if not specs:
        raise typer.BadParameter("No templates provided. Use --spec-file and/or --name + --body.")

    if dry_run:
        results = create_templates(wa=None, specs=specs, dry_run=True)
    else:
        wa = _get_client(token, business_account_id)
        results = create_templates(wa=wa, specs=specs, dry_run=False)

    _print_results(results, as_json, "CREATE RESULTS")
    if any(not result.get("ok", False) for result in results):
        raise typer.Exit(code=1)


@app.command("check")
def check_command(
    name: list[str] = typer.Option([], "--name", help="Template name. Repeat for multiple."),
    spec_file: Path | None = typer.Option(
        None, "--spec-file", help="Optional spec file; names are taken from it."
    ),
    fail_on_unapproved: bool = typer.Option(
        False, "--fail-on-unapproved", help="Exit non-zero if any template is not approved."
    ),
    poll_until_found: bool = typer.Option(
        False,
        "--poll-until-found",
        help="Poll until all names are found (or timeout).",
    ),
    timeout_minutes: int = typer.Option(
        30,
        "--timeout-minutes",
        min=1,
        help="Polling timeout in minutes when --poll-until-found is enabled.",
    ),
    poll_interval_seconds: int = typer.Option(
        30,
        "--poll-interval-seconds",
        min=1,
        help="Polling interval in seconds when --poll-until-found is enabled.",
    ),
    as_json: bool = typer.Option(False, "--json", help="JSON output."),
    token: str | None = typer.Option(
        None, "--token", envvar=ENV_WA_ACCESS_TOKEN, help="WhatsApp access token."
    ),
    business_account_id: str | None = typer.Option(
        None,
        "--business-account-id",
        envvar=ENV_WA_BUSINESS_ACCOUNT_ID,
        help="WhatsApp business account id.",
    ),
) -> None:
    """Check template approval/status."""
    names = _collect_names(name, spec_file)
    if not names:
        raise typer.BadParameter("Provide --name and/or --spec-file.")

    wa = _get_client(token, business_account_id)
    results = check_templates(wa, names)
    if poll_until_found:
        deadline = datetime.now(timezone.utc) + timedelta(minutes=timeout_minutes)
        while not all(result.get("found", False) for result in results):
            if datetime.now(timezone.utc) >= deadline:
                break
            time.sleep(poll_interval_seconds)
            results = check_templates(wa, names)
    _print_results(results, as_json, "CHECK RESULTS")

    has_error = any(result.get("status") == "ERROR" for result in results)
    has_unapproved = any(not result.get("approved", False) for result in results)
    if has_error or (fail_on_unapproved and has_unapproved):
        raise typer.Exit(code=1)


@app.command("delete")
def delete_command(
    name: list[str] = typer.Option([], "--name", help="Template name. Repeat for multiple."),
    spec_file: Path | None = typer.Option(
        None, "--spec-file", help="Optional spec file; names are taken from it."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be deleted."),
    as_json: bool = typer.Option(False, "--json", help="JSON output."),
    token: str | None = typer.Option(
        None, "--token", envvar=ENV_WA_ACCESS_TOKEN, help="WhatsApp access token."
    ),
    business_account_id: str | None = typer.Option(
        None,
        "--business-account-id",
        envvar=ENV_WA_BUSINESS_ACCOUNT_ID,
        help="WhatsApp business account id.",
    ),
) -> None:
    """Delete templates by name."""
    names = _collect_names(name, spec_file)
    if not names:
        raise typer.BadParameter("Provide --name and/or --spec-file.")

    if dry_run:
        results = delete_templates(None, names, dry_run=True)
    else:
        wa = _get_client(token, business_account_id)
        results = delete_templates(wa, names, dry_run=False)
    _print_results(results, as_json, "DELETE RESULTS")

    if any(not result.get("ok", False) for result in results):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
