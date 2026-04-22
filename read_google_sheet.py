#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv


READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"


@dataclass(frozen=True)
class SpreadsheetTarget:
    spreadsheet_id: str
    gid: int | None


def build_parser() -> argparse.ArgumentParser:
    default_sheet = os.getenv("GOOGLE_SHEET_URL")
    default_gid = parse_int_env("GOOGLE_SHEET_GID")

    parser = argparse.ArgumentParser(
        description="Lee una Google Sheet y devuelve sus filas como JSON.",
    )
    parser.add_argument(
        "--sheet",
        default=default_sheet,
        help=(
            "URL completa de Google Sheets o directamente el spreadsheet_id. "
            "Si no se indica, usa GOOGLE_SHEET_URL."
        ),
    )
    parser.add_argument(
        "--gid",
        type=int,
        default=default_gid,
        help="gid de la pestaña. Si no se indica, se usa el del URL o la primera pestaña.",
    )
    parser.add_argument(
        "--range",
        dest="range_name",
        help="Rango A1. Ejemplo: \"Hoja 1!A1:D20\".",
    )
    parser.add_argument(
        "--service-account",
        default=os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE"),
        help="Ruta al JSON de la service account. También puede venir de GOOGLE_SERVICE_ACCOUNT_FILE.",
    )
    parser.add_argument(
        "--as-records",
        action="store_true",
        help="Convierte la primera fila en headers y devuelve records además de rows.",
    )
    return parser


def parse_int_env(env_name: str) -> int | None:
    raw_value = os.getenv(env_name)
    if raw_value in {None, ""}:
        return None
    return int(raw_value)


def parse_target(sheet_value: str, explicit_gid: int | None) -> SpreadsheetTarget:
    if re.fullmatch(r"[A-Za-z0-9-_]+", sheet_value):
        return SpreadsheetTarget(spreadsheet_id=sheet_value, gid=explicit_gid)

    match = re.search(r"/spreadsheets/d/([A-Za-z0-9-_]+)", sheet_value)
    if not match:
        raise ValueError("No pude extraer el spreadsheet_id desde el valor de --sheet.")

    gid = explicit_gid
    if gid is None:
        parsed = urllib.parse.urlparse(sheet_value)
        query_params = urllib.parse.parse_qs(parsed.query)
        fragment_params = urllib.parse.parse_qs(parsed.fragment)

        raw_gid = query_params.get("gid", [None])[0] or fragment_params.get("gid", [None])[0]
        if raw_gid is not None:
            gid = int(raw_gid)

    return SpreadsheetTarget(spreadsheet_id=match.group(1), gid=gid)


def try_public_csv(target: SpreadsheetTarget) -> list[list[str]] | None:
    if target.gid is None:
        return None

    url = (
        f"https://docs.google.com/spreadsheets/d/{target.spreadsheet_id}/export"
        f"?format=csv&gid={target.gid}"
    )

    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            return None
        raise

    reader = csv.reader(io.StringIO(text))
    return [row for row in reader]


def build_sheets_service(service_account_file: str):
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Faltan dependencias. Ejecuta: uv sync"
        ) from exc

    credentials = Credentials.from_service_account_file(
        service_account_file,
        scopes=[READONLY_SCOPE],
    )
    return build("sheets", "v4", credentials=credentials)


def read_with_api(
    target: SpreadsheetTarget,
    range_name: str | None,
    service_account_file: str,
) -> tuple[str, list[list[str]]]:
    service = build_sheets_service(service_account_file)

    resolved_range = range_name or resolve_range_from_gid(service, target)
    response = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=target.spreadsheet_id,
            range=resolved_range,
        )
        .execute()
    )
    rows = response.get("values", [])
    return resolved_range, rows


def resolve_range_from_gid(service, target: SpreadsheetTarget) -> str:
    metadata = (
        service.spreadsheets()
        .get(
            spreadsheetId=target.spreadsheet_id,
            fields="sheets(properties(sheetId,title))",
        )
        .execute()
    )
    sheets = metadata.get("sheets", [])

    if not sheets:
        raise RuntimeError("La spreadsheet no tiene pestañas visibles.")

    if target.gid is None:
        first_title = sheets[0]["properties"]["title"]
        return quote_sheet_title(first_title)

    for sheet in sheets:
        properties = sheet["properties"]
        if properties["sheetId"] == target.gid:
            return quote_sheet_title(properties["title"])

    raise RuntimeError(f"No encontré ninguna pestaña con gid={target.gid}.")


def quote_sheet_title(title: str) -> str:
    escaped = title.replace("'", "''")
    return f"'{escaped}'"


def build_payload(
    target: SpreadsheetTarget,
    resolved_range: str,
    rows: list[list[str]],
    as_records: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "spreadsheet_id": target.spreadsheet_id,
        "gid": target.gid,
        "range": resolved_range,
        "row_count": len(rows),
        "rows": rows,
    }

    if as_records and rows:
        headers = rows[0]
        data_rows = rows[1:]
        payload["headers"] = headers
        payload["records"] = rows_to_records(headers, data_rows)

    return payload


def rows_to_records(headers: list[str], data_rows: list[list[str]]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for row in data_rows:
        record = {}
        for index, header in enumerate(headers):
            record[header] = row[index] if index < len(row) else ""
        records.append(record)
    return records


def main() -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    if not args.sheet:
        print(
            "Falta la sheet. Pasá --sheet o definí GOOGLE_SHEET_URL en .env.",
            file=sys.stderr,
        )
        return 1

    try:
        target = parse_target(args.sheet, args.gid)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.range_name is None:
        public_rows = try_public_csv(target)
        if public_rows is not None:
            payload = build_payload(target, f"gid={target.gid}", public_rows, args.as_records)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

    if not args.service_account:
        print(
            "La hoja no es pública. Define --service-account o GOOGLE_SERVICE_ACCOUNT_FILE "
            "con el JSON de una service account que tenga acceso a la sheet.",
            file=sys.stderr,
        )
        return 1

    try:
        resolved_range, rows = read_with_api(
            target=target,
            range_name=args.range_name,
            service_account_file=args.service_account,
        )
    except Exception as exc:
        print(f"No pude leer la sheet: {exc}", file=sys.stderr)
        return 1

    payload = build_payload(target, resolved_range, rows, args.as_records)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
