"""Generate a portable funnel config JSON file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from backend.funnel_config import FunnelDefinition, FunnelStrategyDefinition, slugify_funnel_id


def split_csv(values: list[str]) -> list[str]:
    """Normalize repeated comma-separated CLI values."""
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        for item in raw_value.split(","):
            clean_item = item.strip()
            if not clean_item or clean_item in seen:
                continue
            seen.add(clean_item)
            normalized.append(clean_item)
    return normalized


def build_funnel(args: argparse.Namespace) -> FunnelDefinition:
    """Build one complete disabled-by-default funnel from CLI options."""
    funnel_id = slugify_funnel_id(args.funnel_id)
    label = args.label.strip() if args.label else funnel_id.replace("-", " ").title()
    mp4_path = args.mp4_path.strip() if args.mp4_path else f"data/{funnel_id}/videos/loom_60_seconds_captions.mp4"

    return FunnelDefinition(
        id=funnel_id,
        label=label,
        kind="campaign",
        enabled=args.enabled,
        sheet_url=args.sheet_url.strip() or None,
        sheet_gid=args.sheet_gid.strip() or None,
        sheet_source_filter=args.sheet_source_filter.strip() or None,
        sheet_poll_seconds=args.sheet_poll_seconds,
        template_language=args.template_language,
        opener_text=args.opener_text,
        opener_template_name=args.opener_template_name or f"{funnel_id.replace('-', '_')}_intro_nombre_pais_es_v1",
        opener_followup_text=args.opener_followup_text,
        opener_followup_template_name=args.opener_followup_template_name
        or f"{funnel_id.replace('-', '_')}_opener_followup_24h_es_v1",
        manual_ping_text=args.manual_ping_text,
        manual_ping_template_name=args.manual_ping_template_name or f"{funnel_id.replace('-', '_')}_manual_ping_es_v1",
        loom_intro_text=args.loom_intro_text,
        loom_url=args.loom_url,
        video_check_text=args.video_check_text,
        calendly_intro_text=args.calendly_intro_text,
        calendly_base_url=args.calendly_base_url,
        alert_emails=split_csv(args.alert_email),
        whatsapp_referral_source_ids=split_csv(args.whatsapp_referral_source_id),
        initial_reply_quiet_seconds=args.initial_reply_quiet_seconds,
        post_loom_min_seconds=args.post_loom_min_seconds,
        post_loom_quiet_seconds=args.post_loom_quiet_seconds,
        strategies=[
            FunnelStrategyDefinition(
                step="loom",
                id="loom_mp4",
                label="WhatsApp MP4",
                weight=100,
                delivery="video",
                sequence_step="loom_video",
                message_text="Video de explicacion enviado por WhatsApp.",
                media_type="video",
                media_path=mp4_path,
                media_caption=None,
            )
        ],
    )


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("funnel_id", help="Stable slug, for example abogados or dentistas.")
    parser.add_argument("--label", default="", help="Operator-facing funnel label.")
    parser.add_argument("--enabled", action="store_true", help="Enable the funnel immediately.")
    parser.add_argument("--sheet-url", default="", help="Google Sheet URL used for lead import.")
    parser.add_argument("--sheet-gid", default="", help="Google Sheet tab GID used for lead import.")
    parser.add_argument("--sheet-source-filter", default="", help="Optional source filter applied during import.")
    parser.add_argument("--sheet-poll-seconds", type=int, default=30, help="Polling interval. Minimum is 30.")
    parser.add_argument("--template-language", default="es", help="WhatsApp template language.")
    parser.add_argument("--opener-template-name", default="", help="Approved WhatsApp opener template name.")
    parser.add_argument("--opener-text", default="Hola {nombre}, completaste el formulario sobre como podemos ayudarte. Es correcto?")
    parser.add_argument("--opener-followup-template-name", default="", help="Approved WhatsApp follow-up template name.")
    parser.add_argument(
        "--opener-followup-text",
        default="Queria compartirte informacion sobre la propuesta que viste en el anuncio.",
    )
    parser.add_argument("--manual-ping-template-name", default="", help="Approved WhatsApp manual ping template name.")
    parser.add_argument(
        "--manual-ping-text",
        default="Hola, queria saber en que situacion quedamos y si queres que retomemos la conversacion",
    )
    parser.add_argument("--loom-intro-text", default="Perfecto. Te cuento rapido como funciona y que obtenes si trabajamos juntos:")
    parser.add_argument("--loom-url", default="", help="Optional Loom URL for reference.")
    parser.add_argument("--mp4-path", default="", help="Path to the WhatsApp MP4 inside the mounted data volume.")
    parser.add_argument("--video-check-text", default="conseguiste ver el video?")
    parser.add_argument("--calendly-intro-text", default="Para avanzar, el siguiente paso es elegir un horario en el calendario:")
    parser.add_argument("--calendly-base-url", default="", help="Booking URL for this funnel.")
    parser.add_argument("--alert-email", action="append", default=[], help="Alert email. Can be repeated or comma-separated.")
    parser.add_argument(
        "--whatsapp-referral-source-id",
        action="append",
        default=[],
        help="Meta Click-to-WhatsApp referral.source_id. Can be repeated or comma-separated.",
    )
    parser.add_argument("--initial-reply-quiet-seconds", type=int, default=30)
    parser.add_argument("--post-loom-min-seconds", type=int, default=600)
    parser.add_argument("--post-loom-quiet-seconds", type=int, default=30)
    parser.add_argument("--output", type=Path, help="Write the config JSON to this path instead of stdout.")
    parser.add_argument("--force", action="store_true", help="Overwrite --output if it already exists.")
    return parser


def main() -> None:
    """Run the CLI."""
    parser = build_parser()
    args = parser.parse_args()
    if args.sheet_poll_seconds < 30:
        parser.error("--sheet-poll-seconds must be at least 30.")

    funnel = build_funnel(args)
    payload = {
        "version": 1,
        "funnels": [funnel.model_dump(mode="json")],
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    if args.output is None:
        print(text, end="")
        return

    if args.output.exists() and not args.force:
        parser.error(f"{args.output} already exists. Use --force to overwrite.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
