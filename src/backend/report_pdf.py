from __future__ import annotations

import argparse
import io
import json
import math
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from reportlab.lib.colors import Color
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

PAGE_W = 1440
PAGE_H = 3150
CURRENT_PAGE_W = PAGE_W
CURRENT_PAGE_H = PAGE_H


class PointModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class RectModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    w: float
    h: float

    def unpack(self) -> tuple[float, float, float, float]:
        return self.x, self.y, self.w, self.h


class HeroModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str
    url: str
    line_1: str
    line_2_a: str
    line_2_b: str
    context: str
    impact: str
    auth: str


class ContactItemModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    meta: str


class MessageCalloutModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    body: str


class ThreadMessageModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    side: Literal["buyer", "seller"]
    badge: str
    timestamp: str
    text: str
    callout: MessageCalloutModel | None = None


class ThreadInsightBlockModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    text: str


class ThreadQuoteModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote: str
    attribution: str
    observed: str


class ThreadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    channel: str
    objective_text: str = ""
    status_kind: Literal["critical", "warn", "ok", "neutral"]
    status_text: str
    messages: list[ThreadMessageModel]
    insight_title: str
    insight_blocks: list[ThreadInsightBlockModel]
    quote: ThreadQuoteModel | None = None


class MessageLayoutModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bubble: RectModel
    badge: RectModel
    timestamp: RectModel
    callout: RectModel | None = None


class InsightBlockLayoutModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label_rect: RectModel
    text_rect: RectModel


class InsightLayoutModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title_rect: RectModel
    blocks: list[InsightBlockLayoutModel]
    quote_rect: RectModel | None = None
    quote_text_rect: RectModel | None = None
    quote_attr_rect: RectModel | None = None
    quote_obs_rect: RectModel | None = None


class ThreadLayoutModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card: RectModel
    title_xy: PointModel
    sub_xy: PointModel
    status_chip: RectModel
    chat: RectModel
    insights: RectModel


class LineTextModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    y: float
    text: str


class RiskSegmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    color: str
    weight: float = Field(gt=0)


class ReportDocumentModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hero: HeroModel
    risk_level_label: str = "Current risk level"
    risk_badge_label: str = "Critical"
    risk_badge_kind: str = "critical"
    risk_segments: list[RiskSegmentModel] = Field(
        default_factory=lambda: [
            RiskSegmentModel(label="Reply handling", color="good", weight=1.0),
            RiskSegmentModel(label="Trust signals", color="warn", weight=1.0),
            RiskSegmentModel(label="Commercial momentum", color="bad", weight=1.0),
        ]
    )
    contacts: list[ContactItemModel]
    threads: list[ThreadModel]
    thread_layouts: list[ThreadLayoutModel] = Field(default_factory=list)
    message_layouts: list[list[MessageLayoutModel]] = Field(default_factory=list)
    insight_layouts: list[InsightLayoutModel] = Field(default_factory=list)
    conclusion_lines: list[LineTextModel] = Field(default_factory=list)
    conclusion_text: str | None = None
    quote_line_overrides: dict[int, list[LineTextModel]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_lengths(self) -> "ReportDocumentModel":
        thread_count = len(self.threads)
        has_layout = bool(self.thread_layouts or self.message_layouts or self.insight_layouts)
        if not self.risk_segments:
            raise ValueError("risk_segments must include at least one segment")
        if has_layout:
            if len(self.thread_layouts) != thread_count:
                raise ValueError("thread_layouts length must match threads length when provided")
            if len(self.message_layouts) != thread_count:
                raise ValueError("message_layouts length must match threads length when provided")
            if len(self.insight_layouts) != thread_count:
                raise ValueError("insight_layouts length must match threads length when provided")

            for idx, thread in enumerate(self.threads):
                if len(self.message_layouts[idx]) != len(thread.messages):
                    raise ValueError(
                        f"message layout count mismatch on thread index {idx}: "
                        f"{len(self.message_layouts[idx])} != {len(thread.messages)}"
                    )
        return self


class AdaptiveLayoutModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    header_h: float
    contacts_panel_h: float
    thread_layouts: list[ThreadLayoutModel]
    message_layouts: list[list[MessageLayoutModel]]
    insight_layouts: list[InsightLayoutModel]
    conclusion_lines: list[LineTextModel]
    page_h: int


def load_report_document_from_json(path: Path) -> ReportDocumentModel:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ReportDocumentModel.model_validate(payload)


def rgba(r: int, g: int, b: int, a: int = 255) -> Color:
    return Color(r / 255, g / 255, b / 255, alpha=a / 255)


BG = rgba(251, 251, 252)
TEXT = rgba(15, 23, 42)
TEXT_DARK = rgba(11, 18, 32)
MUTED = rgba(102, 112, 133)
LINE = rgba(230, 232, 238)
CARD = rgba(255, 255, 255)

GOOD = rgba(22, 163, 74, 191)
WARN = rgba(245, 158, 11, 217)
BAD = rgba(220, 38, 38, 209)

BUYER_BG = rgba(238, 246, 255)
BUYER_BD = rgba(207, 228, 255)
SELLER_BG = rgba(238, 251, 242)
SELLER_BD = rgba(207, 238, 221)

CHIP_BG = rgba(242, 244, 248)
CHIP_TEXT = rgba(51, 65, 85)
BADGE_BG = rgba(148, 163, 184, 36)
BADGE_BD = rgba(148, 163, 184, 56)
BADGE_TX = rgba(71, 85, 105)

CRITICAL_TX = rgba(220, 38, 38)
CRITICAL_BG = rgba(220, 38, 38, 15)
CRITICAL_BD = rgba(220, 38, 38, 64)

WARN_TX = rgba(180, 83, 9)
WARN_BG = rgba(245, 158, 11, 26)
WARN_BD = rgba(245, 158, 11, 64)

OK_TX = rgba(21, 128, 61)
OK_BG = rgba(22, 163, 74, 20)
OK_BD = rgba(22, 163, 74, 61)

NEUTRAL_TX = rgba(71, 85, 105)
NEUTRAL_BG = rgba(100, 116, 139, 20)
NEUTRAL_BD = rgba(100, 116, 139, 56)

FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_NARROW_BOLD = "Helvetica-Bold"

INSIGHT_TITLE_CHAR_SPACE = 0.96
INSIGHT_TITLE_LINE_HEIGHT = 17.0

CONTACT_PANEL_X = 805.0
CONTACT_PANEL_Y = 50.0
CONTACT_PANEL_W = 457.0
CONTACT_PANEL_INNER_X = 822.0
CONTACT_PANEL_INNER_W = 423.0
CONTACT_LEGEND_Y = 160.0
CONTACT_LIST_START_GAP = 12.0
CONTACT_PANEL_MIN_H = 399.0
CONTACT_PANEL_BOTTOM_PAD = 16.0
LEGEND_CHIP_PAD_L = 14.0
LEGEND_CHIP_PAD_R = 14.0
LEGEND_CHIP_DOT_R = 4.0
LEGEND_CHIP_DOT_GAP = 8.0


def _font_specs() -> list[tuple[str, str]]:
    if sys.platform == "darwin":
        return [
            ("UI-Regular", "/System/Library/Fonts/SFNS.ttf"),
            ("UI-Regular-Arial", "/System/Library/Fonts/Supplemental/Arial.ttf"),
            ("UI-Bold", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
            ("UI-NarrowBold", "/System/Library/Fonts/Supplemental/Arial Narrow Bold.ttf"),
        ]
    return [
        ("UI-Regular", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        ("UI-Regular-Arial", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        ("UI-Bold", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ("UI-NarrowBold", "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Bold.ttf"),
    ]


def _register_fonts() -> None:
    global FONT_REGULAR, FONT_BOLD, FONT_NARROW_BOLD
    loaded: dict[str, str] = {}
    for alias, path in _font_specs():
        try:
            pdfmetrics.registerFont(TTFont(alias, path))
            loaded[alias] = alias
        except Exception:
            continue

    FONT_REGULAR = loaded.get("UI-Regular", loaded.get("UI-Regular-Arial", FONT_REGULAR))
    FONT_BOLD = loaded.get("UI-Bold", FONT_BOLD)
    FONT_NARROW_BOLD = loaded.get("UI-NarrowBold", FONT_BOLD)


def _to_pdf_y(top_y: float, height: float = 0) -> float:
    return CURRENT_PAGE_H - top_y - height


def _split_rgb_alpha(color: Color) -> tuple[Color, float]:
    alpha = getattr(color, "alpha", 1.0)
    if alpha is None:
        alpha = 1.0
    return Color(color.red, color.green, color.blue), float(alpha)


def _set_fill(c: canvas.Canvas, color: Color) -> None:
    rgb, alpha = _split_rgb_alpha(color)
    c.setFillColor(rgb)
    c.setFillAlpha(alpha)


def _set_stroke(c: canvas.Canvas, color: Color, width: float = 1) -> None:
    rgb, alpha = _split_rgb_alpha(color)
    c.setStrokeColor(rgb)
    c.setStrokeAlpha(alpha)
    c.setLineWidth(width)


def _draw_round_rect(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    radius: float,
    fill: Color,
    stroke: Color | None = None,
    stroke_width: float = 1,
) -> None:
    _set_fill(c, fill)
    if stroke:
        _set_stroke(c, stroke, stroke_width)
        c.roundRect(x, _to_pdf_y(y, h), w, h, radius, stroke=1, fill=1)
    else:
        c.roundRect(x, _to_pdf_y(y, h), w, h, radius, stroke=0, fill=1)


def _draw_shadow_rect(c: canvas.Canvas, x: float, y: float, w: float, h: float, radius: float, alpha: float = 0.012) -> None:
    c.saveState()
    shadow_layers = [
        (6, 0, alpha * 0.50),
        (10, 1, alpha * 0.30),
        (14, 2, alpha * 0.18),
    ]
    for offset_y, spread, layer_alpha in shadow_layers:
        _draw_round_rect(
            c,
            x - spread,
            y + offset_y - spread,
            w + spread * 2,
            h + spread * 2,
            radius + spread,
            rgba(2, 6, 23, int(max(1, min(255, round(layer_alpha * 255))))),
            stroke=None,
        )
    c.restoreState()


def _draw_soft_ellipse(
    c: canvas.Canvas,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    color: tuple[int, int, int],
    max_alpha: float,
    steps: int,
) -> None:
    c.saveState()
    for i in range(steps, 0, -1):
        t = i / steps
        layer_alpha = max_alpha * (t * t) * 0.55
        cur_rx = rx * (0.35 + 0.65 * t)
        cur_ry = ry * (0.35 + 0.65 * t)
        _set_fill(c, rgba(color[0], color[1], color[2], int(max(1, min(255, round(layer_alpha * 255))))))
        c.ellipse(
            cx - cur_rx,
            _to_pdf_y(cy - cur_ry),
            cx + cur_rx,
            _to_pdf_y(cy + cur_ry),
            stroke=0,
            fill=1,
        )
    c.restoreState()


def _draw_tracked_text(
    c: canvas.Canvas,
    x: float,
    y: float,
    text: str,
    font: str,
    size: float,
    color: Color,
    char_space: float = 0.0,
) -> None:
    ascent = (pdfmetrics.getAscent(font) / 1000.0) * size
    t = c.beginText()
    t.setTextOrigin(x, CURRENT_PAGE_H - y - ascent)
    t.setFont(font, size)
    rgb, alpha = _split_rgb_alpha(color)
    t.setFillColor(rgb)
    t.setFillAlpha(alpha)
    t.setCharSpace(char_space)
    t.textLine(text)
    c.drawText(t)


def _font_line_height(font: str, size: float) -> float:
    ascent = (pdfmetrics.getAscent(font) / 1000.0) * size
    descent = (pdfmetrics.getDescent(font) / 1000.0) * size
    return ascent - descent


def _draw_text_in_rect(
    c: canvas.Canvas,
    rect: RectModel,
    text: str,
    font: str,
    size: float,
    color: Color,
    *,
    char_space: float = 0.0,
    align: Literal["left", "center"] = "left",
    left_padding: float = 0.0,
) -> None:
    x, y, w, h = rect.unpack()
    text_h = _font_line_height(font, size)
    text_w = _text_width(text, font, size, char_space)
    draw_x = x + left_padding if align == "left" else x + max(0.0, (w - text_w) / 2)
    draw_y = y + max(0.0, (h - text_h) / 2)
    _draw_tracked_text(c, draw_x, draw_y, text, font, size, color, char_space)


def _text_width(text: str, font: str, size: float, char_space: float = 0.0) -> float:
    if not text:
        return 0.0
    base = pdfmetrics.stringWidth(text, font, size)
    return base + max(0, len(text) - 1) * char_space


def _split_long_token(token: str, font: str, size: float, max_width: float, char_space: float = 0.0) -> list[str]:
    if not token:
        return [token]
    if _text_width(token, font, size, char_space) <= max_width:
        return [token]

    parts: list[str] = []
    current = ""
    for char in token:
        candidate = current + char
        if current and _text_width(candidate, font, size, char_space) > max_width:
            parts.append(current)
            current = char
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _wrap_text(text: str, font: str, size: float, max_width: float, char_space: float = 0.0) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if paragraph == "":
            lines.append("")
            continue
        words: list[str] = []
        for token in paragraph.split(" "):
            words.extend(_split_long_token(token, font, size, max_width, char_space))
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if _text_width(candidate, font, size, char_space) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _draw_wrapped_text(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    text: str,
    font: str,
    size: float,
    line_height: float,
    color: Color,
    char_space: float = 0.0,
) -> None:
    lines = _wrap_text(text, font, size, w, char_space)
    for idx, line in enumerate(lines):
        _draw_tracked_text(c, x, y + idx * line_height, line, font, size, color, char_space)


def _resolve_risk_color(value: str) -> Color:
    normalized = (value or "").strip().lower()
    if normalized in {"good", "green"}:
        return GOOD
    if normalized in {"warn", "warning", "amber", "yellow"}:
        return WARN
    if normalized in {"bad", "critical", "red"}:
        return BAD
    if normalized in {"neutral", "gray", "grey"}:
        return rgba(100, 116, 139, 160)
    if normalized.startswith("#") and len(normalized) in {7, 9}:
        try:
            r = int(normalized[1:3], 16)
            g = int(normalized[3:5], 16)
            b = int(normalized[5:7], 16)
            a = int(normalized[7:9], 16) if len(normalized) == 9 else 255
            return rgba(r, g, b, a)
        except ValueError:
            return BAD
    return BAD


def _normalize_risk_segments(segments: list[RiskSegmentModel]) -> list[RiskSegmentModel]:
    clean = [segment for segment in segments if segment.weight > 0 and segment.label.strip()]
    if clean:
        return clean
    return [
        RiskSegmentModel(label="Reply handling", color="good", weight=1.0),
        RiskSegmentModel(label="Trust signals", color="warn", weight=1.0),
        RiskSegmentModel(label="Commercial momentum", color="bad", weight=1.0),
    ]


def _layout_contact_legend(segments: list[RiskSegmentModel], inner_w: float) -> tuple[list[RectModel], float]:
    row_h = 32.0
    row_gap = 8.0
    chip_gap = 8.0
    row_x = 0.0
    row_y = 0.0
    chip_rects: list[RectModel] = []

    for segment in segments:
        text_w = _text_width(segment.label, FONT_REGULAR, 12.5)
        chip_w = (
            LEGEND_CHIP_PAD_L
            + (LEGEND_CHIP_DOT_R * 2.0)
            + LEGEND_CHIP_DOT_GAP
            + text_w
            + LEGEND_CHIP_PAD_R
        )
        if row_x > 0.0 and row_x + chip_w > inner_w:
            row_x = 0.0
            row_y += row_h + row_gap
        chip_rects.append(RectModel(x=row_x, y=row_y, w=chip_w, h=row_h))
        row_x += chip_w + chip_gap

    return chip_rects, row_y + row_h


def _layout_risk_strip(
    x: float,
    y: float,
    w: float,
    h: float,
    segments: list[RiskSegmentModel],
) -> list[tuple[RectModel, Color]]:
    normalized = _normalize_risk_segments(segments)
    total_weight = sum(segment.weight for segment in normalized)
    rects: list[tuple[RectModel, Color]] = []
    cursor_x = x

    for index, segment in enumerate(normalized):
        ratio = segment.weight / total_weight if total_weight > 0 else 1 / len(normalized)
        seg_w = w * ratio if index < len(normalized) - 1 else (x + w - cursor_x)
        seg_rect = RectModel(x=cursor_x, y=y, w=seg_w, h=h)
        rects.append((seg_rect, _resolve_risk_color(segment.color)))
        cursor_x += seg_w

    return rects


def _measure_contacts_panel_height(document: ReportDocumentModel) -> float:
    _, legend_h = _layout_contact_legend(_normalize_risk_segments(document.risk_segments), CONTACT_PANEL_INNER_W)
    y = CONTACT_LEGEND_Y + legend_h + CONTACT_LIST_START_GAP

    for idx, contact in enumerate(document.contacts):
        y += 12.0
        who_lines = _wrap_text(contact.value, FONT_BOLD, 14, CONTACT_PANEL_INNER_W)
        y += max(1, len(who_lines)) * 20.3
        y += 3.0
        meta_lines = _wrap_text(contact.meta, FONT_REGULAR, 12.5, CONTACT_PANEL_INNER_W)
        y += max(1, len(meta_lines)) * 18.125
        y += 6.0 if idx == len(document.contacts) - 1 else 12.0

    panel_h = (y + CONTACT_PANEL_BOTTOM_PAD) - CONTACT_PANEL_Y
    return max(CONTACT_PANEL_MIN_H, panel_h)


def _measure_hero_left_height(document: ReportDocumentModel) -> float:
    hero = document.hero
    y = 50.0
    y += 18.125 + 12.0  # identity strip + margin-bottom

    for segment in [hero.line_1, hero.line_2_a, hero.line_2_b]:
        lines = _wrap_text(segment, FONT_BOLD, 52, 601, -2.08)
        y += max(1, len(lines)) * 53.0

    y += 14.0
    context_lines = _wrap_text(hero.context, FONT_REGULAR, 15, 548)
    y += max(1, len(context_lines)) * 21.75
    y += 10.0
    impact_lines = _wrap_text(hero.impact, FONT_BOLD, 12.5, 601)
    y += max(1, len(impact_lines)) * 20.3
    y += 6.0
    auth_lines = _wrap_text(hero.auth, FONT_REGULAR, 12.5, 601)
    y += max(1, len(auth_lines)) * 18.125
    return y - 50.0


def _thread_header_lines(thread: ThreadModel, title_max_w: float) -> tuple[list[str], list[str], list[str]]:
    """Build wrapped header lines for one thread card."""
    title_lines = _wrap_text(thread.title, FONT_BOLD, 16, title_max_w)
    channel_lines = _wrap_text(f"Channel: {thread.channel}", FONT_REGULAR, 12.5, title_max_w)
    objective = (thread.objective_text or "").strip()
    objective_lines = (
        _wrap_text(f"Objective: {objective}", FONT_REGULAR, 12.5, title_max_w)
        if objective
        else []
    )
    return title_lines, channel_lines, objective_lines


def _measure_message_layouts(
    thread: ThreadModel,
    chat_x: float,
    chat_y: float,
    chat_w: float,
) -> tuple[list[MessageLayoutModel], float]:
    msg_area_x = chat_x + 14.0
    msg_area_w = chat_w - 28.0
    cursor_y = chat_y + 14.0
    layouts: list[MessageLayoutModel] = []

    for message in thread.messages:
        cursor_y += 10.0
        has_callout = message.callout is not None
        callout_w = 220.0 if has_callout else 0.0
        callout_gap = 10.0 if has_callout else 0.0
        bubble_wrap_w = msg_area_w - callout_w - callout_gap if has_callout else msg_area_w
        bubble_wrap_w = max(180.0, bubble_wrap_w)
        bubble_w = bubble_wrap_w

        bubble_lines = _wrap_text(message.text, FONT_REGULAR, 13.5, bubble_w - 24.0)
        bubble_h = 20.0 + max(1, len(bubble_lines)) * 19.17

        if message.side == "buyer" and has_callout:
            bubble_wrap_x = msg_area_x + callout_w + callout_gap
            bubble_x = bubble_wrap_x
        elif message.side == "buyer":
            bubble_wrap_x = msg_area_x
            bubble_x = msg_area_x + (msg_area_w - bubble_w)
        else:
            bubble_wrap_x = msg_area_x
            bubble_x = msg_area_x

        bubble_y = cursor_y
        meta_y = bubble_y + bubble_h + 6.0
        badge_w = _text_width(message.badge, FONT_BOLD, 11.5) + 16.0
        ts_w = _text_width(message.timestamp, FONT_REGULAR, 11.5)
        ts_x = bubble_wrap_x + bubble_wrap_w - ts_w

        callout_rect: RectModel | None = None
        row_h = bubble_h + 6.0 + 25.0
        if has_callout and message.callout is not None:
            callout_x = msg_area_x if message.side == "buyer" else (bubble_wrap_x + bubble_wrap_w + callout_gap)
            body_lines = _wrap_text(message.callout.body, FONT_REGULAR, 12.5, 200.0)
            callout_h = 10.0 + 18.125 + 4.0 + max(1, len(body_lines)) * 16.875 + 10.0
            callout_rect = RectModel(x=callout_x, y=bubble_y, w=220.0, h=callout_h)
            row_h = max(row_h, callout_h)

        layouts.append(
            MessageLayoutModel(
                bubble=RectModel(x=bubble_x, y=bubble_y, w=bubble_w, h=bubble_h),
                badge=RectModel(x=bubble_wrap_x, y=meta_y, w=badge_w, h=25.0),
                timestamp=RectModel(x=ts_x, y=meta_y, w=ts_w, h=25.0),
                callout=callout_rect,
            )
        )
        cursor_y += row_h + 10.0

    chat_h = (cursor_y + 14.0) - chat_y
    return layouts, chat_h


def _measure_insight_layout(
    thread: ThreadModel,
    insights_x: float,
    grid_y: float,
    insights_w: float,
) -> tuple[InsightLayoutModel, float]:
    inner_x = insights_x + 14.0
    inner_w = insights_w - 28.0
    y = grid_y + 14.0

    title_lines = _wrap_text(thread.insight_title.upper(), FONT_BOLD, 12, inner_w, INSIGHT_TITLE_CHAR_SPACE)
    title_h = max(INSIGHT_TITLE_LINE_HEIGHT, len(title_lines) * INSIGHT_TITLE_LINE_HEIGHT)
    title_rect = RectModel(x=inner_x, y=y, w=inner_w, h=title_h)
    y += title_h + 10.0

    blocks: list[InsightBlockLayoutModel] = []
    for block in thread.insight_blocks:
        label_rect = RectModel(x=inner_x, y=y, w=inner_w, h=18.0)
        y += 18.0 + 6.0
        text_lines = _wrap_text(block.text, FONT_REGULAR, 13, inner_w)
        text_h = max(18.85, len(text_lines) * 18.85)
        text_rect = RectModel(x=inner_x, y=y, w=inner_w, h=text_h)
        y += text_h + 12.0
        blocks.append(InsightBlockLayoutModel(label_rect=label_rect, text_rect=text_rect))

    quote_rect: RectModel | None = None
    quote_text_rect: RectModel | None = None
    quote_attr_rect: RectModel | None = None
    quote_obs_rect: RectModel | None = None

    if thread.quote is not None:
        q_inner_w = inner_w - 26.0
        quote_lines = _wrap_text(thread.quote.quote, FONT_REGULAR, 13, q_inner_w)
        attr_lines = _wrap_text(thread.quote.attribution, FONT_REGULAR, 12.5, q_inner_w)
        obs_lines = _wrap_text(thread.quote.observed, FONT_REGULAR, 12.5, q_inner_w)
        q_h = max(18.2, len(quote_lines) * 18.2)
        a_h = max(18.125, len(attr_lines) * 18.125)
        o_h = max(18.125, len(obs_lines) * 18.125)

        rect_h = 12.0 + q_h + 8.0 + a_h + 8.0 + o_h + 12.0
        quote_rect = RectModel(x=inner_x, y=y, w=inner_w, h=rect_h)
        quote_text_rect = RectModel(x=inner_x + 13.0, y=y + 13.0, w=q_inner_w, h=q_h)
        quote_attr_rect = RectModel(x=inner_x + 13.0, y=quote_text_rect.y + q_h + 8.0, w=q_inner_w, h=a_h)
        quote_obs_rect = RectModel(x=inner_x + 13.0, y=quote_attr_rect.y + a_h + 8.0, w=q_inner_w, h=o_h)
        y += rect_h

    insight_layout = InsightLayoutModel(
        title_rect=title_rect,
        blocks=blocks,
        quote_rect=quote_rect,
        quote_text_rect=quote_text_rect,
        quote_attr_rect=quote_attr_rect,
        quote_obs_rect=quote_obs_rect,
    )
    insights_h = (y + 14.0) - grid_y
    return insight_layout, insights_h


def _build_adaptive_layout(document: ReportDocumentModel) -> AdaptiveLayoutModel:
    contacts_panel_h = _measure_contacts_panel_height(document)
    hero_left_h = _measure_hero_left_height(document)
    hero_h = max(hero_left_h, contacts_panel_h)
    header_h = max(540.0, 50.0 + hero_h + 91.0)

    thread_layouts: list[ThreadLayoutModel] = []
    message_layouts: list[list[MessageLayoutModel]] = []
    insight_layouts: list[InsightLayoutModel] = []

    y = header_h + 172.0
    for thread in document.threads:
        x = 178.0
        w = 1084.0
        title_x = x + 19.0
        title_y = y + 19.0
        status_w = max(83.0, _text_width(thread.status_text, FONT_BOLD, 12.5) + 36.0)
        status_h = 34.0
        status_x = x + w - 19.0 - status_w
        title_max_w = max(220.0, status_x - 12.0 - title_x)

        title_lines, channel_lines, objective_lines = _thread_header_lines(thread, title_max_w)
        title_block_h = max(1, len(title_lines)) * 23.2 + 3.0 + max(1, len(channel_lines)) * 18.125
        if objective_lines:
            title_block_h += 4.0 + max(1, len(objective_lines)) * 18.125
        header_block_h = max(status_h, title_block_h)

        grid_y = title_y + header_block_h + 14.0
        inner_w = 1046.0
        chat_w = round((inner_w - 14.0) * 1.7 / (1.7 + 0.95))
        insights_w = inner_w - 14.0 - chat_w
        chat_x = x + 19.0
        insights_x = chat_x + chat_w + 14.0

        measured_message_layouts, chat_h = _measure_message_layouts(
            thread=thread,
            chat_x=chat_x,
            chat_y=grid_y,
            chat_w=chat_w,
        )
        measured_insight_layout, insights_h = _measure_insight_layout(
            thread=thread,
            insights_x=insights_x,
            grid_y=grid_y,
            insights_w=insights_w,
        )

        card_h = (grid_y + max(chat_h, insights_h) + 18.0) - y
        thread_layout = ThreadLayoutModel(
            card=RectModel(x=x, y=y, w=w, h=card_h),
            title_xy=PointModel(x=title_x, y=title_y),
            sub_xy=PointModel(x=title_x, y=title_y + max(1, len(title_lines)) * 23.2 + 3.0),
            status_chip=RectModel(x=status_x, y=title_y, w=status_w, h=status_h),
            chat=RectModel(x=chat_x, y=grid_y, w=chat_w, h=chat_h),
            insights=RectModel(x=insights_x, y=grid_y, w=insights_w, h=insights_h),
        )

        thread_layouts.append(thread_layout)
        message_layouts.append(measured_message_layouts)
        insight_layouts.append(measured_insight_layout)

        y += card_h + 18.0

    conclusion_y = y + 26.0
    if document.conclusion_text is not None and document.conclusion_text.strip():
        conclusion_text = document.conclusion_text.strip()
    elif document.conclusion_lines:
        conclusion_text = " ".join(line.text.strip() for line in document.conclusion_lines if line.text.strip())
    else:
        conclusion_text = ""

    wrapped_conclusion = _wrap_text(conclusion_text, FONT_REGULAR, 15, 1046.0, -0.15) if conclusion_text else [""]
    conclusion_lines = [
        LineTextModel(y=conclusion_y + 19.0 + (idx * 21.75), text=line)
        for idx, line in enumerate(wrapped_conclusion)
    ]
    conclusion_h = 18.0 + max(1, len(wrapped_conclusion)) * 21.75 + 18.0
    page_h = math.ceil(max(float(PAGE_H), conclusion_y + conclusion_h + 79.0))

    return AdaptiveLayoutModel(
        header_h=header_h,
        contacts_panel_h=contacts_panel_h,
        thread_layouts=thread_layouts,
        message_layouts=message_layouts,
        insight_layouts=insight_layouts,
        conclusion_lines=conclusion_lines,
        page_h=page_h,
    )


def _assert_adaptive_layout_fit(document: ReportDocumentModel, layout: AdaptiveLayoutModel) -> None:
    tol = 0.5
    issues: list[str] = []

    _, legend_h = _layout_contact_legend(_normalize_risk_segments(document.risk_segments), CONTACT_PANEL_INNER_W)
    contacts_end_y = CONTACT_LEGEND_Y + legend_h + CONTACT_LIST_START_GAP
    for idx, contact in enumerate(document.contacts):
        contacts_end_y += 12.0
        contacts_end_y += max(1, len(_wrap_text(contact.value, FONT_BOLD, 14, CONTACT_PANEL_INNER_W))) * 20.3
        contacts_end_y += 3.0
        contacts_end_y += max(1, len(_wrap_text(contact.meta, FONT_REGULAR, 12.5, CONTACT_PANEL_INNER_W))) * 18.125
        contacts_end_y += 6.0 if idx == len(document.contacts) - 1 else 12.0
    contacts_end_y += CONTACT_PANEL_BOTTOM_PAD
    if contacts_end_y > CONTACT_PANEL_Y + layout.contacts_panel_h + tol:
        issues.append(
            "contacts panel overflow: "
            f"needed_bottom={contacts_end_y:.1f}px panel_bottom={(CONTACT_PANEL_Y + layout.contacts_panel_h):.1f}px"
        )

    previous_card_bottom = 0.0
    for thread_idx, (thread, thread_layout, message_layouts, insight_layout) in enumerate(
        zip(
            document.threads,
            layout.thread_layouts,
            layout.message_layouts,
            layout.insight_layouts,
            strict=True,
        )
    ):
        card_x, card_y, card_w, card_h = thread_layout.card.unpack()
        card_bottom = card_y + card_h
        if thread_idx > 0 and card_y < previous_card_bottom + 18.0 - tol:
            issues.append(
                f"thread[{thread_idx}] overlaps previous card: "
                f"y={card_y:.1f}px prev_bottom={previous_card_bottom:.1f}px"
            )
        previous_card_bottom = card_bottom

        chat_x, chat_y, chat_w, chat_h = thread_layout.chat.unpack()
        insights_x, insights_y, insights_w, insights_h = thread_layout.insights.unpack()
        if chat_x < card_x + 19.0 - tol or chat_x + chat_w > card_x + card_w - 19.0 + tol:
            issues.append(f"thread[{thread_idx}] chat column out of card bounds")
        if insights_x < card_x + 19.0 - tol or insights_x + insights_w > card_x + card_w - 19.0 + tol:
            issues.append(f"thread[{thread_idx}] insights column out of card bounds")
        if chat_y < card_y + 40.0 - tol or chat_y + chat_h > card_bottom - 18.0 + tol:
            issues.append(f"thread[{thread_idx}] chat height out of card bounds")
        if insights_y < card_y + 40.0 - tol or insights_y + insights_h > card_bottom - 18.0 + tol:
            issues.append(f"thread[{thread_idx}] insights height out of card bounds")

        title_max_w = max(220.0, thread_layout.status_chip.x - 12.0 - thread_layout.title_xy.x)
        title_lines, channel_lines, objective_lines = _thread_header_lines(thread, title_max_w)
        for line in title_lines:
            if _text_width(line, FONT_BOLD, 16) > title_max_w + tol:
                issues.append(f"thread[{thread_idx}] title line overflow")
                break
        for line in channel_lines + objective_lines:
            if _text_width(line, FONT_REGULAR, 12.5) > title_max_w + tol:
                issues.append(f"thread[{thread_idx}] subtitle line overflow")
                break

        insight_title_x, insight_title_y, insight_title_w, insight_title_h = insight_layout.title_rect.unpack()
        insight_title_lines = _wrap_text(
            thread.insight_title.upper(),
            FONT_BOLD,
            12,
            insight_title_w,
            INSIGHT_TITLE_CHAR_SPACE,
        )
        for line in insight_title_lines:
            if _text_width(line, FONT_BOLD, 12, INSIGHT_TITLE_CHAR_SPACE) > insight_title_w + tol:
                issues.append(f"thread[{thread_idx}] insight title overflow")
                break
        needed_title_h = max(INSIGHT_TITLE_LINE_HEIGHT, len(insight_title_lines) * INSIGHT_TITLE_LINE_HEIGHT)
        if needed_title_h > insight_title_h + tol:
            issues.append(
                f"thread[{thread_idx}] insight title height overflow: "
                f"needed={needed_title_h:.1f}px available={insight_title_h:.1f}px"
            )
        if insight_title_y + insight_title_h > insights_y + insights_h - 14.0 + tol:
            issues.append(f"thread[{thread_idx}] insight title exceeds insights height")

        for msg_idx, (message, msg_layout) in enumerate(zip(thread.messages, message_layouts, strict=True)):
            bx, by, bw, bh = msg_layout.bubble.unpack()
            bubble_lines = _wrap_text(message.text, FONT_REGULAR, 13.5, bw - 24.0)
            bubble_needed_h = max(1, len(bubble_lines)) * 19.17
            if bubble_needed_h > bh - 20.0 + tol:
                issues.append(
                    f"thread[{thread_idx}] message[{msg_idx}] bubble overflow: "
                    f"needed={bubble_needed_h:.1f}px available={(bh - 20.0):.1f}px"
                )
            if bx < chat_x + 14.0 - tol or bx + bw > chat_x + chat_w - 14.0 + tol:
                issues.append(f"thread[{thread_idx}] message[{msg_idx}] bubble out of chat bounds")

            badge_x, badge_y, badge_w, badge_h = msg_layout.badge.unpack()
            ts_x, ts_y, ts_w, ts_h = msg_layout.timestamp.unpack()
            meta_bottom = max(badge_y + badge_h, ts_y + ts_h)
            if meta_bottom > chat_y + chat_h - 14.0 + tol:
                issues.append(f"thread[{thread_idx}] message[{msg_idx}] metadata exceeds chat height")
            if badge_x < chat_x + 14.0 - tol or badge_x + badge_w > chat_x + chat_w - 14.0 + tol:
                issues.append(f"thread[{thread_idx}] message[{msg_idx}] badge out of chat bounds")
            if ts_x < chat_x + 14.0 - tol or ts_x + ts_w > chat_x + chat_w - 14.0 + tol:
                issues.append(f"thread[{thread_idx}] message[{msg_idx}] timestamp out of chat bounds")

            if message.callout is not None and msg_layout.callout is not None:
                cx, cy, cw, ch = msg_layout.callout.unpack()
                callout_lines = _wrap_text(message.callout.body, FONT_REGULAR, 12.5, cw - 20.0)
                callout_needed_h = max(1, len(callout_lines)) * 16.875
                if callout_needed_h > ch - 42.0 + tol:
                    issues.append(
                        f"thread[{thread_idx}] message[{msg_idx}] callout overflow: "
                        f"needed={callout_needed_h:.1f}px available={(ch - 42.0):.1f}px"
                    )
                if cx < chat_x + 14.0 - tol or cx + cw > chat_x + chat_w - 14.0 + tol:
                    issues.append(f"thread[{thread_idx}] message[{msg_idx}] callout out of chat bounds")
                if cy + ch > chat_y + chat_h - 14.0 + tol:
                    issues.append(f"thread[{thread_idx}] message[{msg_idx}] callout exceeds chat height")

        for block_idx, (block, block_layout) in enumerate(zip(thread.insight_blocks, insight_layout.blocks, strict=True)):
            tx, ty, tw, th = block_layout.text_rect.unpack()
            text_lines = _wrap_text(block.text, FONT_REGULAR, 13, tw)
            needed_h = max(1, len(text_lines)) * 18.85
            if needed_h > th + tol:
                issues.append(
                    f"thread[{thread_idx}] insight_block[{block_idx}] overflow: "
                    f"needed={needed_h:.1f}px available={th:.1f}px"
                )
            if tx < insights_x + 14.0 - tol or tx + tw > insights_x + insights_w - 14.0 + tol:
                issues.append(f"thread[{thread_idx}] insight_block[{block_idx}] out of bounds")
            if ty + th > insights_y + insights_h - 14.0 + tol:
                issues.append(f"thread[{thread_idx}] insight_block[{block_idx}] exceeds insights height")

        if (
            thread.quote is not None
            and insight_layout.quote_rect is not None
            and insight_layout.quote_text_rect is not None
            and insight_layout.quote_attr_rect is not None
            and insight_layout.quote_obs_rect is not None
        ):
            qx, qy, qw, qh = insight_layout.quote_rect.unpack()
            if qx < insights_x + 14.0 - tol or qx + qw > insights_x + insights_w - 14.0 + tol:
                issues.append(f"thread[{thread_idx}] quote card out of bounds")
            if qy + qh > insights_y + insights_h - 14.0 + tol:
                issues.append(f"thread[{thread_idx}] quote card exceeds insights height")

            _, _, qtw, qth = insight_layout.quote_text_rect.unpack()
            q_lines = _wrap_text(thread.quote.quote, FONT_REGULAR, 13, qtw)
            q_needed_h = max(1, len(q_lines)) * 18.2
            if q_needed_h > qth + tol:
                issues.append(
                    f"thread[{thread_idx}] quote overflow: needed={q_needed_h:.1f}px available={qth:.1f}px"
                )

            _, _, atw, ath = insight_layout.quote_attr_rect.unpack()
            a_lines = _wrap_text(thread.quote.attribution, FONT_REGULAR, 12.5, atw)
            a_needed_h = max(1, len(a_lines)) * 18.125
            if a_needed_h > ath + tol:
                issues.append(
                    f"thread[{thread_idx}] attribution overflow: needed={a_needed_h:.1f}px available={ath:.1f}px"
                )

            _, _, otw, oth = insight_layout.quote_obs_rect.unpack()
            o_lines = _wrap_text(thread.quote.observed, FONT_REGULAR, 12.5, otw)
            o_needed_h = max(1, len(o_lines)) * 18.125
            if o_needed_h > oth + tol:
                issues.append(
                    f"thread[{thread_idx}] observed overflow: needed={o_needed_h:.1f}px available={oth:.1f}px"
                )

    if layout.conclusion_lines:
        conclusion_first_y = min(line.y for line in layout.conclusion_lines)
        conclusion_y = conclusion_first_y - 19.0
        conclusion_h = 18.0 + max(1, len(layout.conclusion_lines)) * 21.75 + 18.0
        if conclusion_y + conclusion_h > layout.page_h - 79.0 + tol:
            issues.append("conclusion card exceeds computed page height buffer")

    if issues:
        sample = "\n".join(issues[:20])
        more = "" if len(issues) <= 20 else f"\n... and {len(issues) - 20} more"
        raise ValueError(f"Adaptive layout integrity check failed:\n{sample}{more}")


def _assert_fixed_layout_fit(document: ReportDocumentModel) -> None:
    issues: list[str] = []

    for thread_idx, thread in enumerate(document.threads):
        message_layouts = document.message_layouts[thread_idx]
        for msg_idx, (message, layout) in enumerate(zip(thread.messages, message_layouts, strict=True)):
            bubble_text_width = layout.bubble.w - 24
            bubble_available_h = layout.bubble.h - 20
            bubble_lines = _wrap_text(message.text, FONT_REGULAR, 13.5, bubble_text_width)
            bubble_needed_h = len(bubble_lines) * 19.17
            if bubble_needed_h > bubble_available_h + 0.5:
                issues.append(
                    f"thread[{thread_idx}] message[{msg_idx}] bubble overflow: "
                    f"needed={bubble_needed_h:.1f}px available={bubble_available_h:.1f}px"
                )

            if message.callout is not None and layout.callout is not None:
                callout_text_width = layout.callout.w - 20
                callout_available_h = layout.callout.h - 42
                callout_lines = _wrap_text(message.callout.body, FONT_REGULAR, 12.5, callout_text_width)
                callout_needed_h = len(callout_lines) * 16.875
                if callout_needed_h > callout_available_h + 0.5:
                    issues.append(
                        f"thread[{thread_idx}] message[{msg_idx}] callout overflow: "
                        f"needed={callout_needed_h:.1f}px available={callout_available_h:.1f}px"
                    )

        insight_layout = document.insight_layouts[thread_idx]
        for block_idx, (block, block_layout) in enumerate(zip(thread.insight_blocks, insight_layout.blocks, strict=True)):
            text_width = block_layout.text_rect.w
            available_h = block_layout.text_rect.h
            lines = _wrap_text(block.text, FONT_REGULAR, 13, text_width)
            needed_h = len(lines) * 18.85
            if needed_h > available_h + 0.5:
                issues.append(
                    f"thread[{thread_idx}] insight_block[{block_idx}] overflow: "
                    f"needed={needed_h:.1f}px available={available_h:.1f}px"
                )

        if (
            thread.quote is not None
            and insight_layout.quote_text_rect is not None
            and insight_layout.quote_attr_rect is not None
            and insight_layout.quote_obs_rect is not None
            and thread_idx not in document.quote_line_overrides
        ):
            q_lines = _wrap_text(thread.quote.quote, FONT_REGULAR, 13, insight_layout.quote_text_rect.w)
            q_needed_h = len(q_lines) * 18.2
            if q_needed_h > insight_layout.quote_text_rect.h + 0.5:
                issues.append(
                    f"thread[{thread_idx}] quote overflow: "
                    f"needed={q_needed_h:.1f}px available={insight_layout.quote_text_rect.h:.1f}px"
                )

            a_lines = _wrap_text(thread.quote.attribution, FONT_REGULAR, 12.5, insight_layout.quote_attr_rect.w)
            a_needed_h = len(a_lines) * 18.125
            if a_needed_h > insight_layout.quote_attr_rect.h + 0.5:
                issues.append(
                    f"thread[{thread_idx}] quote attribution overflow: "
                    f"needed={a_needed_h:.1f}px available={insight_layout.quote_attr_rect.h:.1f}px"
                )

            o_lines = _wrap_text(thread.quote.observed, FONT_REGULAR, 12.5, insight_layout.quote_obs_rect.w)
            o_needed_h = len(o_lines) * 18.125
            if o_needed_h > insight_layout.quote_obs_rect.h + 0.5:
                issues.append(
                    f"thread[{thread_idx}] quote observed overflow: "
                    f"needed={o_needed_h:.1f}px available={insight_layout.quote_obs_rect.h:.1f}px"
                )

    if issues:
        sample = "\n".join(issues[:12])
        more = "" if len(issues) <= 12 else f"\n... and {len(issues) - 12} more"
        raise ValueError(
            "Data does not fit fixed vector layout.\n"
            "Use different content/layout or implement adaptive layout mode.\n"
            f"{sample}{more}"
        )


def _draw_dashed_line(c: canvas.Canvas, x0: float, x1: float, y: float, dash: float = 4, gap: float = 4) -> None:
    c.saveState()
    _set_stroke(c, LINE, 1)
    c.setDash(dash, gap)
    c.line(x0, _to_pdf_y(y), x1, _to_pdf_y(y))
    c.restoreState()


def _draw_status_chip(c: canvas.Canvas, rect: RectModel, label: str, kind: str) -> None:
    x, y, w, h = rect.unpack()
    if kind == "critical":
        text_color, bg_color, bd_color, dot_color = CRITICAL_TX, CRITICAL_BG, CRITICAL_BD, BAD
    elif kind == "warn":
        text_color, bg_color, bd_color, dot_color = WARN_TX, WARN_BG, WARN_BD, WARN
    elif kind == "ok":
        text_color, bg_color, bd_color, dot_color = OK_TX, OK_BG, OK_BD, GOOD
    else:
        text_color, bg_color, bd_color, dot_color = NEUTRAL_TX, NEUTRAL_BG, NEUTRAL_BD, rgba(100, 116, 139, 140)

    _draw_round_rect(c, x, y, w, h, h / 2, bg_color, stroke=bd_color, stroke_width=1)
    _set_fill(c, dot_color)
    c.circle(x + 14, _to_pdf_y(y + h / 2), 4, stroke=0, fill=1)
    _draw_text_in_rect(
        c,
        rect,
        label,
        FONT_BOLD,
        12.5,
        text_color,
        align="left",
        left_padding=22,
    )


def _draw_header(c: canvas.Canvas, document: ReportDocumentModel, layout: AdaptiveLayoutModel) -> None:
    hero = document.hero

    _set_fill(c, BG)
    c.rect(0, 0, CURRENT_PAGE_W, CURRENT_PAGE_H, stroke=0, fill=1)
    _set_fill(c, BG)
    c.rect(0, _to_pdf_y(0, layout.header_h), CURRENT_PAGE_W, layout.header_h, stroke=0, fill=1)

    _draw_soft_ellipse(c, 288, -118, 680, 260, (99, 102, 241), max_alpha=0.03, steps=10)
    _draw_soft_ellipse(c, 1296, -20, 540, 240, (16, 185, 129), max_alpha=0.025, steps=9)

    _set_stroke(c, rgba(230, 232, 238, 102), 1)
    c.line(0, _to_pdf_y(layout.header_h - 1), CURRENT_PAGE_W, _to_pdf_y(layout.header_h - 1))

    _draw_tracked_text(c, 178, 50, hero.company, FONT_REGULAR, 12.5, MUTED, 0.125)
    _draw_tracked_text(c, 274, 50, "·", FONT_REGULAR, 12.5, rgba(152, 162, 179), 0.0)
    _draw_tracked_text(c, 288, 50, hero.url, FONT_REGULAR, 12.5, MUTED, 0.0)

    text_y = 80.0
    for segment in [hero.line_1, hero.line_2_a, hero.line_2_b]:
        segment_lines = _wrap_text(segment, FONT_BOLD, 52, 601.0, -2.08)
        for line in segment_lines:
            _draw_tracked_text(c, 178, text_y, line, FONT_BOLD, 52, TEXT_DARK, -2.08)
            text_y += 53.0

    text_y += 14.0
    for line in _wrap_text(hero.context, FONT_REGULAR, 15, 548.0):
        _draw_tracked_text(c, 178, text_y, line, FONT_REGULAR, 15, MUTED)
        text_y += 21.75

    text_y += 10.0
    for line in _wrap_text(hero.impact, FONT_BOLD, 12.5, 601.0):
        _draw_tracked_text(c, 178, text_y, line, FONT_BOLD, 12.5, rgba(17, 24, 39))
        text_y += 20.3

    text_y += 6.0
    for line in _wrap_text(hero.auth, FONT_REGULAR, 12.5, 601.0):
        _draw_tracked_text(c, 178, text_y, line, FONT_REGULAR, 12.5, MUTED)
        text_y += 18.125

    _draw_shadow_rect(c, CONTACT_PANEL_X, CONTACT_PANEL_Y, CONTACT_PANEL_W, layout.contacts_panel_h, 16, alpha=0.010)
    _draw_round_rect(
        c,
        CONTACT_PANEL_X,
        CONTACT_PANEL_Y,
        CONTACT_PANEL_W,
        layout.contacts_panel_h,
        16,
        CARD,
        stroke=LINE,
        stroke_width=1,
    )

    _draw_tracked_text(c, CONTACT_PANEL_INNER_X, 67, "ANALYZED CONTACTS", FONT_BOLD, 13, CHIP_TEXT, 1.04)
    _draw_tracked_text(c, CONTACT_PANEL_INNER_X, 105, document.risk_level_label, FONT_REGULAR, 12.5, MUTED)
    risk_badge_w = max(83.0, _text_width(document.risk_badge_label, FONT_BOLD, 12.5) + 36.0)
    _draw_status_chip(
        c,
        RectModel(x=1245 - risk_badge_w, y=98, w=risk_badge_w, h=32),
        document.risk_badge_label,
        document.risk_badge_kind,
    )

    _draw_round_rect(c, CONTACT_PANEL_INNER_X, 140, CONTACT_PANEL_INNER_W, 10, 5, CARD, stroke=rgba(230, 232, 238, 179))
    for segment_rect, segment_color in _layout_risk_strip(
        x=823,
        y=141,
        w=421,
        h=8,
        segments=document.risk_segments,
    ):
        sx, sy, sw, sh = segment_rect.unpack()
        _set_fill(c, segment_color)
        c.rect(sx, _to_pdf_y(sy, sh), sw, sh, stroke=0, fill=1)

    legend_segments = _normalize_risk_segments(document.risk_segments)
    legend_rects, legend_h = _layout_contact_legend(legend_segments, CONTACT_PANEL_INNER_W)
    for rect, segment in zip(legend_rects, legend_segments, strict=True):
        x = CONTACT_PANEL_INNER_X + rect.x
        y = CONTACT_LEGEND_Y + rect.y
        w = rect.w
        h = rect.h
        _draw_round_rect(c, x, y, w, h, h / 2, CHIP_BG, stroke=rgba(230, 232, 238, 179), stroke_width=1)
        _set_fill(c, _resolve_risk_color(segment.color))
        dot_cx = x + LEGEND_CHIP_PAD_L + LEGEND_CHIP_DOT_R
        c.circle(dot_cx, _to_pdf_y(y + h / 2), LEGEND_CHIP_DOT_R, stroke=0, fill=1)
        text_x = x + LEGEND_CHIP_PAD_L + (LEGEND_CHIP_DOT_R * 2.0) + LEGEND_CHIP_DOT_GAP
        _draw_text_in_rect(
            c,
            RectModel(
                x=text_x,
                y=y,
                w=max(1.0, w - (text_x - x) - LEGEND_CHIP_PAD_R),
                h=h,
            ),
            segment.label,
            FONT_REGULAR,
            12.5,
            CHIP_TEXT,
            align="left",
        )

    y = CONTACT_LEGEND_Y + legend_h + CONTACT_LIST_START_GAP
    inner_w = CONTACT_PANEL_INNER_W
    for idx, contact in enumerate(document.contacts):
        y += 12.0
        for line in _wrap_text(contact.value, FONT_BOLD, 14, inner_w):
            _draw_tracked_text(c, CONTACT_PANEL_INNER_X, y, line, FONT_BOLD, 14, TEXT_DARK)
            y += 20.3
        y += 3.0
        for line in _wrap_text(contact.meta, FONT_REGULAR, 12.5, inner_w):
            _draw_tracked_text(c, CONTACT_PANEL_INNER_X, y, line, FONT_REGULAR, 12.5, MUTED)
            y += 18.125
        pad = 6.0 if idx == len(document.contacts) - 1 else 12.0
        if idx < len(document.contacts) - 1:
            _draw_dashed_line(c, CONTACT_PANEL_INNER_X, 1245, y + pad - 1.0)
        y += pad


def _draw_message(c: canvas.Canvas, message: ThreadMessageModel, layout: MessageLayoutModel) -> None:
    bx, by, bw, bh = layout.bubble.unpack()
    bubble_fill = BUYER_BG if message.side == "buyer" else SELLER_BG
    bubble_border = BUYER_BD if message.side == "buyer" else SELLER_BD
    _draw_round_rect(c, bx, by, bw, bh, 14, bubble_fill, stroke=bubble_border, stroke_width=1)

    _draw_wrapped_text(c, bx + 12, by + 10, bw - 24, message.text, FONT_REGULAR, 13.5, 19.17, TEXT_DARK)

    badge_x, badge_y, badge_w, badge_h = layout.badge.unpack()
    _draw_round_rect(c, badge_x, badge_y, badge_w, badge_h, badge_h / 2, BADGE_BG, stroke=BADGE_BD, stroke_width=1)
    _draw_text_in_rect(c, layout.badge, message.badge, FONT_BOLD, 11.5, BADGE_TX, align="center")

    _draw_text_in_rect(c, layout.timestamp, message.timestamp, FONT_REGULAR, 11.5, MUTED, align="left")

    if message.callout and layout.callout:
        cx, cy, cw, ch = layout.callout.unpack()
        _draw_shadow_rect(c, cx, cy, cw, ch, 10, alpha=0.06)
        _draw_round_rect(c, cx, cy, cw, ch, 10, CARD, stroke=rgba(220, 38, 38, 46), stroke_width=1)
        _set_stroke(c, rgba(239, 68, 68), 2)
        c.line(cx, _to_pdf_y(cy), cx, _to_pdf_y(cy + ch))
        _draw_tracked_text(c, cx + 10, cy + 10, message.callout.title, FONT_BOLD, 12.5, rgba(185, 28, 28))
        _draw_wrapped_text(c, cx + 10, cy + 32, cw - 20, message.callout.body, FONT_REGULAR, 12.5, 16.875, BADGE_TX)


def _draw_insights(
    c: canvas.Canvas,
    thread: ThreadModel,
    insight_layout: InsightLayoutModel,
) -> None:
    tx, ty, tw, _ = insight_layout.title_rect.unpack()
    for idx, line in enumerate(
        _wrap_text(thread.insight_title.upper(), FONT_BOLD, 12, tw, INSIGHT_TITLE_CHAR_SPACE)
    ):
        _draw_tracked_text(
            c,
            tx,
            ty + idx * INSIGHT_TITLE_LINE_HEIGHT,
            line,
            FONT_BOLD,
            12,
            CHIP_TEXT,
            INSIGHT_TITLE_CHAR_SPACE,
        )

    for block_layout, block in zip(insight_layout.blocks, thread.insight_blocks, strict=True):
        lx, ly, _, _ = block_layout.label_rect.unpack()
        x, y, w, _ = block_layout.text_rect.unpack()
        _draw_tracked_text(c, lx, ly, block.label, FONT_REGULAR, 12.5, MUTED)
        _draw_wrapped_text(c, x, y, w, block.text, FONT_REGULAR, 13, 18.85, TEXT)

    if (
        thread.quote
        and insight_layout.quote_rect
        and insight_layout.quote_text_rect
        and insight_layout.quote_attr_rect
        and insight_layout.quote_obs_rect
    ):
        qx, qy, qw, qh = insight_layout.quote_rect.unpack()
        _draw_round_rect(c, qx, qy, qw, qh, 12, rgba(248, 250, 252, 230), stroke=rgba(230, 232, 238, 230), stroke_width=1)

        x, y, w, _ = insight_layout.quote_text_rect.unpack()
        _draw_wrapped_text(c, x, y, w, thread.quote.quote, FONT_REGULAR, 13, 18.2, TEXT)

        x, y, w, _ = insight_layout.quote_attr_rect.unpack()
        _draw_wrapped_text(c, x, y, w, thread.quote.attribution, FONT_REGULAR, 12.5, 18.125, MUTED)
        x, y, w, _ = insight_layout.quote_obs_rect.unpack()
        _draw_wrapped_text(c, x, y, w, thread.quote.observed, FONT_REGULAR, 12.5, 18.125, BADGE_TX)


def _draw_thread(
    c: canvas.Canvas,
    thread: ThreadModel,
    thread_layout: ThreadLayoutModel,
    message_layouts: list[MessageLayoutModel],
    insight_layout: InsightLayoutModel,
) -> None:
    x, y, w, h = thread_layout.card.unpack()
    _draw_shadow_rect(c, x, y, w, h, 16)
    _draw_round_rect(c, x, y, w, h, 16, CARD, stroke=LINE, stroke_width=1)

    cx, cy, cw, ch = thread_layout.chat.unpack()
    _draw_round_rect(c, cx, cy, cw, ch, 14, CARD, stroke=rgba(230, 232, 238, 230), stroke_width=1)
    ix, iy, iw, ih = thread_layout.insights.unpack()
    _draw_round_rect(c, ix, iy, iw, ih, 14, CARD, stroke=rgba(230, 232, 238, 230), stroke_width=1)

    title_max_w = max(220.0, thread_layout.status_chip.x - 12.0 - thread_layout.title_xy.x)
    title_y = thread_layout.title_xy.y
    title_lines, channel_lines, objective_lines = _thread_header_lines(thread, title_max_w)
    for line in title_lines:
        _draw_tracked_text(c, thread_layout.title_xy.x, title_y, line, FONT_BOLD, 16, TEXT_DARK)
        title_y += 23.2
    title_y += 3.0
    for line in channel_lines:
        _draw_tracked_text(c, thread_layout.title_xy.x, title_y, line, FONT_REGULAR, 12.5, MUTED)
        title_y += 18.125
    if objective_lines:
        title_y += 4.0
        for line in objective_lines:
            _draw_tracked_text(c, thread_layout.title_xy.x, title_y, line, FONT_REGULAR, 12.5, BADGE_TX)
            title_y += 18.125

    _draw_status_chip(c, thread_layout.status_chip, thread.status_text, thread.status_kind)

    for message, layout in zip(thread.messages, message_layouts, strict=True):
        _draw_message(c, message, layout)

    _draw_insights(c, thread, insight_layout)


def _draw_conclusion(c: canvas.Canvas, conclusion_lines: list[LineTextModel]) -> None:
    if not conclusion_lines:
        return
    first_y = min(line.y for line in conclusion_lines)
    conclusion_y = first_y - 19.0
    conclusion_h = 18.0 + max(1, len(conclusion_lines)) * 21.75 + 18.0
    _draw_shadow_rect(c, 178, conclusion_y, 1084, conclusion_h, 16, alpha=0.010)
    _draw_round_rect(c, 178, conclusion_y, 1084, conclusion_h, 16, CARD, stroke=LINE, stroke_width=1)
    for line in conclusion_lines:
        _draw_tracked_text(c, 197, line.y, line.text, FONT_REGULAR, 15, TEXT, -0.15)


def build_vector_pdf(
    document: ReportDocumentModel,
    *,
    strict_layout_fit: bool,
) -> bytes:
    global CURRENT_PAGE_W, CURRENT_PAGE_H

    _register_fonts()
    adaptive_layout = _build_adaptive_layout(document)
    _assert_adaptive_layout_fit(document, adaptive_layout)
    CURRENT_PAGE_W = PAGE_W
    CURRENT_PAGE_H = adaptive_layout.page_h

    if strict_layout_fit and document.message_layouts:
        _assert_fixed_layout_fit(document)

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(CURRENT_PAGE_W, CURRENT_PAGE_H), pageCompression=1)
    c.setTitle("Konecta Labs — Conversation Diagnostic (Vector)")
    c.setAuthor("Konecta Auditor")
    c.setSubject("Manual vector PDF build")

    _draw_header(c, document, adaptive_layout)
    for thread, thread_layout, message_layouts, insight_layout in zip(
        document.threads,
        adaptive_layout.thread_layouts,
        adaptive_layout.message_layouts,
        adaptive_layout.insight_layouts,
        strict=True,
    ):
        _draw_thread(
            c,
            thread,
            thread_layout,
            message_layouts,
            insight_layout,
        )
    _draw_conclusion(c, adaptive_layout.conclusion_lines)

    c.showPage()
    c.save()
    return buffer.getvalue()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render vector PDF from JSON report payload.")
    parser.add_argument("--input-json", type=Path, required=True, help="Path to JSON input")
    parser.add_argument("--output-pdf", type=Path, required=True, help="Path to output PDF")
    parser.add_argument(
        "--strict-layout-fit",
        action="store_true",
        help="Enable legacy fixed-layout fit validation against JSON-provided layout fields.",
    )
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    document = load_report_document_from_json(args.input_json)
    pdf_bytes = build_vector_pdf(document, strict_layout_fit=args.strict_layout_fit)
    args.output_pdf.write_bytes(pdf_bytes)


if __name__ == "__main__":
    main()
