#!/usr/bin/env python3
"""Two-stage Kimi K2.6 localization pipeline for Tales of Destiny 2 (PS2).

Version 5.1 separates localization quality from final console layout safety and
adds the missing per-page text-budget guard discovered through PCSX2 testing:

  --mode quality
      Full second-pass localization. Uses generous sanity ceilings (80 visible
      columns and four English lines by default) so Kimi can prioritize meaning,
      natural English, voice, terminology, and scene continuity. This output is
      suitable for an Unrestricted/Experimental patch, but it is not guaranteed
      to fit every original PS2 dialogue window.

  --mode safe
      Targeted third-pass layout repair. Ordinary control-free dialogue uses the
      36-column / five-line policy plus a conservative 126-visible-character
      budget for each four-row page. Four rows display at once and a fifth line
      advances normally, but PCSX2 testing showed that packing too much text into
      one four-row page can still corrupt glyphs even when every individual line
      is at most 36 columns. The safe pass first performs page-aware deterministic
      lossless reflow locally, then sends only unresolved condensation/runtime
      cases to Kimi. It does not limit ordinary English to the Japanese source-line
      count.

      By default, target blocks containing runtime codes are preserved rather than
      rewritten automatically. Use --safe-revise-runtime-code-blocks only for an
      intentional, separately audited control-sensitive run.

Both modes preserve Japanese source text, command blocks, runtime placeholders,
character-name placeholders, divider/block order, CP932 compatibility, and every
known PCSX2-tested crash/layout repair. Known-good records remain locked by default.

Standard-library only. Requests use Vercel AI Gateway's OpenAI-compatible Chat
Completions endpoint with structured JSON, checkpointing, partial-batch
acceptance, provider-error handling, deterministic safe reflow, and a local spend
guard.

Required project-root reference files:
    glossary.txt
    code_glossary.txt
    character_voice_guide.txt

API key environment variable:
    AI_GATEWAY_API_KEY
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

DIVIDER = "-----------------------"
JP_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff01-\uff65]"
)
SPEAKER_RE = re.compile(r"^#?\s*<([A-Za-z][A-Za-z0-9_-]*)>")
ANGLE_TAG_RE = re.compile(r"<[^>\r\n]+>")
CURLY_CODE_RE = re.compile(r"(?:\{[0-9A-Fa-f]{2,8}\})+")
PRINTF_RE = re.compile(
    r"%(?:\d+\$)?[-+ #0]*(?:\d+|\*)?(?:\.\d+|\.\*)?"
    r"[hlLzjt]*[diuoxXfFeEgGaAcspn%]"
)
FORMAT_RE = re.compile(r"\{\d+(?::[^{}]+)?\}")
LITERAL_NEWLINE_RE = re.compile(r"\\n")
# Match immutable codes in their true left-to-right source order. Running separate
# regex substitutions by code type can reorder mixed angle/curly tags.
IMMUTABLE_CODE_RE = re.compile(
    "|".join(
        f"(?:{pattern.pattern})"
        for pattern in (
            ANGLE_TAG_RE,
            CURLY_CODE_RE,
            LITERAL_NEWLINE_RE,
            PRINTF_RE,
            FORMAT_RE,
        )
    )
)
TOKEN_RE = re.compile(r"\[\[B\d{5}C\d{3}\]\]")
# {02} is an in-record renderer break used by long tutorial/notice records.
# It separates independently rendered text segments even though the .sced.txt
# extractor stores them on one physical source/English line.
RUNTIME_RENDER_BREAK_RE = re.compile(r"(?:\{02\})+")
RAW_RENDER_BREAK_SPLIT_RE = re.compile(r"\{02\}|\\n")
LEADING_REASONING_BLOCK_RE = re.compile(
    r"\A\s*<(think|analysis|reasoning)>.*?</\1>\s*",
    re.IGNORECASE | re.DOTALL,
)

REFERENCE_FILENAMES = (
    "glossary.txt",
    "code_glossary.txt",
    "character_voice_guide.txt",
)

SPEAKER_TAGS = {
    "<Kyle>", "<Reala>", "<Loni>", "<Judas>", "<Nanaly>",
    "<Harold>", "<Barbatos>", "<Elrane>", "<Elraine>",
}

VERCEL_BASE_URL = "https://ai-gateway.vercel.sh/v1"
DEFAULT_MODEL = "moonshotai/kimi-k2.6"


class GatewayError(RuntimeError):
    """AI Gateway transport, access, billing, or provider failure."""


class FatalGatewayError(GatewayError):
    """Gateway failure that cannot be fixed by retrying or splitting a batch."""


# These ranges are known-good after real PCSX2 testing. They are skipped by default
# so a later quality pass cannot reintroduce the fixed crashes. Use
# --revise-known-good-scenes only when intentionally revising them; strict limits
# still apply in that mode.
KNOWN_GOOD_SCENE_RULES: dict[str, list[dict[str, Any]]] = {
    # Previously protected, PCSX2-tested scenes.
    "06434_31.sced.txt": [
        {"start": 212, "end": 232, "max_lines": 3, "max_width": 36,
         "label": "first Heidelberg visit / city guide"},
        {"start": 278, "end": 342, "max_lines": 3, "max_width": 36,
         "label": "first Heidelberg visit / Kyle and Reala park sequence"},
    ],
    "06450_20.sced.txt": [
        {"start": 112, "end": 138, "max_lines": 3, "max_width": 36,
         "label": "later Heidelberg reconstruction scene"},
    ],
    "06463_14.sced.txt": [
        {"start": 13, "end": 31, "max_lines": 3, "max_width": 36,
         "label": "Heidelberg bell and nearby dialogue"},
    ],
    "06465_35.sced.txt": [
        {"start": 541, "end": 577, "max_lines": 3, "max_width": 36,
         "label": "later Heidelberg throne-room scene"},
    ],
    "06573_40.sced.txt": [
        {"start": 7, "end": 13, "max_lines": 3, "max_width": 36,
         "label": "Dycroft / Littra ending speech"},
    ],
    "06627_29.sced.txt": [
        {"start": 86, "end": 86, "max_lines": 3, "max_width": 36,
         "label": "Stairs of Life / Elrane comet speech"},
    ],
    "06718_24.sced.txt": [
        {"start": 55, "end": 67, "max_lines": 3, "max_width": 36,
         "label": "finale party farewell"},
    ],
    "06740_37.sced.txt": [
        {"start": 49, "end": 55, "max_lines": 3, "max_width": 36,
         "label": "Kyle and Stahn finale scene"},
    ],
    "06788_20.sced.txt": [
        {"start": 3, "end": 3, "max_lines": 3, "max_width": 36,
         "label": "Heidelberg Memorial Park snowy panorama"},
        {"start": 47, "end": 47, "max_lines": 3, "max_width": 36,
         "label": "Heidelberg Memorial Park Judas/Loni remark"},
    ],

    # Ladislav crash-scene repair set.
    # These IDs use the second-pass script's zero-based divider-block numbering.
    "06582_19.sced.txt": [
        {"start": value, "end": value, "max_lines": 3, "max_width": 36,
         "label": "Ladislav / Dymlos private-office crash repair"}
        for value in (88, 90, 94, 96, 98, 100)
    ],
    "06575_21.sced.txt": [
        {"start": 47, "end": 51, "max_lines": 3, "max_width": 36,
         "label": "Ladislav refugee and town-NPC crash repair"},
    ],
    "06565_34.sced.txt": [
        {"start": value, "end": value, "max_lines": 3, "max_width": 36,
         "label": "post-strategy-room party-scene crash repair"}
        for value in (147, 153, 155, 157, 159, 163, 165, 167)
    ],

    # Later PCSX2-confirmed visual-layout repairs.
    "06436_29.sced.txt": [
        {"start": 4, "end": 4, "max_lines": 3, "max_width": 36,
         "label": "Heidelberg Memorial Park statue inscription repair"},
    ],
    "06459_28.sced.txt": [
        {"start": value, "end": value, "max_lines": 3, "max_width": 36,
         "label": "Heidelberg post-park time-anomaly dialogue repair"}
        for value in (149, 151)
    ],
    "06566_14.sced.txt": [
        {"start": 10, "end": 10, "max_lines": 3, "max_width": 36,
         "label": "Stanislav rookie-officer dialogue repair"},
    ],
    "06576_23.sced.txt": [
        {"start": value, "end": value, "max_lines": 3, "max_width": 36,
         "label": "Stanislav NPC and inspection-text repair"}
        for value in (8, 24)
    ],

    # PCSX2-confirmed ordinary five-line paging: four rows display, then the
    # fifth line advances on the next input without clipping or corruption.
    "06360_26.sced.txt": [
        {"start": 100, "end": 100, "max_lines": 5, "max_width": 36,
         "label": "Aigrette Scholar five-line runtime validation"},
    ],
}

# Some tutorial records are duplicated across many scenario files at different block
# indices. Locking them by exact Japanese source is safer than maintaining 17 fragile
# per-file block IDs. The matching fixed English must already be present in TXT_EN before
# starting the second pass.
KNOWN_GOOD_SOURCE_RULES: list[dict[str, Any]] = [
    {
        "japanese": (
            "うむ　スピリッツも含め、",
            "仲間たちとの連携が勇気を与えているので、",
            "敵により分断されていると様々な",
            "回復速度が落ちてしまうようだな",
        ),
        "max_lines": 3,
        "max_width": 36,
        "label": "Impact Area tutorial freeze repair (all duplicated copies)",
    },
]



@dataclass
class Block:
    index: int
    lines: list[str] = field(default_factory=list)
    kind: str = "command"
    japanese_indices: list[int] = field(default_factory=list)
    english_indices: list[int] = field(default_factory=list)
    speaker: str | None = None
    marker: str | None = None
    preceding_marker: str | None = None
    exact_line_count: bool = False

    @property
    def translated(self) -> bool:
        return bool(self.japanese_indices and self.english_indices)

    @property
    def japanese_lines(self) -> list[str]:
        result: list[str] = []
        for index in self.japanese_indices:
            value = self.lines[index].lstrip()
            result.append(value[1:] if value.startswith("#") else value)
        return result

    @property
    def english_lines(self) -> list[str]:
        return [self.lines[index] for index in self.english_indices]

    def replace_english(self, translations: list[str]) -> None:
        remove = set(self.english_indices)
        retained = [line for index, line in enumerate(self.lines) if index not in remove]
        while retained and not retained[-1].strip():
            retained.pop()
        retained.extend(translations)
        self.lines = retained
        self.english_indices = list(range(len(retained) - len(translations), len(retained)))


@dataclass
class PreparedBlock:
    block: Block
    protector: "BlockProtector"
    protected_source: list[str]
    protected_draft: list[str]

    @property
    def id(self) -> int:
        return self.block.index


class BlockProtector:
    """Protect immutable source codes with block-unique tokens in lexical order."""

    def __init__(self, block_id: int) -> None:
        self.block_id = block_id
        self.saved: list[tuple[str, str]] = []
        self.source_line_tokens: list[list[str]] = []
        self.line_leading_speaker_tokens: list[str] = []
        self.runtime_break_tokens: list[str] = []

    def _new_token(self, original: str) -> str:
        token = f"[[B{self.block_id:05d}C{len(self.saved) + 1:03d}]]"
        self.saved.append((token, original))
        return token

    def _protect_source_line(self, value: str) -> tuple[str, list[str]]:
        line_tokens: list[str] = []

        def save(match: re.Match[str]) -> str:
            token = self._new_token(match.group(0))
            line_tokens.append(token)
            return token

        # One combined scan preserves the actual source order of mixed codes such as
        # <0B:...>{14}{34}{08}{C0}<0B:...>.
        return IMMUTABLE_CODE_RE.sub(save, value), line_tokens

    def protect_source(self, lines: list[str]) -> list[str]:
        protected: list[str] = []
        self.source_line_tokens = []
        self.line_leading_speaker_tokens = []
        self.runtime_break_tokens = []

        for line in lines:
            before = len(self.saved)
            value, tokens = self._protect_source_line(line)
            protected.append(value)
            self.source_line_tokens.append(tokens)

            token_to_original = dict(self.saved[before:])
            stripped = line.lstrip()
            for token in tokens:
                original = token_to_original.get(token)
                if original in SPEAKER_TAGS and stripped.startswith(original):
                    self.line_leading_speaker_tokens.append(token)
                if original is not None and RUNTIME_RENDER_BREAK_RE.fullmatch(original):
                    self.runtime_break_tokens.append(token)

        return protected

    def split_render_segments(self, line: str) -> list[str]:
        """Split a protected physical line at source {02}/literal-newline codes."""
        tokens = [token for token in self.runtime_break_tokens if token in line]
        if not tokens:
            return [line]
        pattern = re.compile("|".join(re.escape(token) for token in tokens))
        return pattern.split(line)

    def runtime_break_tokens_for_source_line(self, line_index: int) -> list[str]:
        if line_index < 0 or line_index >= len(self.source_line_tokens):
            return []
        break_set = set(self.runtime_break_tokens)
        return [
            token
            for token in self.source_line_tokens[line_index]
            if token in break_set
        ]

    def protect_draft(self, lines: list[str]) -> list[str]:
        available: dict[str, deque[str]] = defaultdict(deque)
        for token, original in self.saved:
            available[original].append(token)

        def reuse(match: re.Match[str]) -> str:
            original = match.group(0)
            queue = available.get(original)
            if queue:
                return queue.popleft()
            # A code found only in the old English draft is not authoritative.
            return ""

        protected: list[str] = []
        for line in lines:
            # Use the same combined lexical scan as the Japanese source.
            protected.append(IMMUTABLE_CODE_RE.sub(reuse, line).strip())
        return protected

    @property
    def required_tokens(self) -> list[str]:
        return [token for token, _ in self.saved]

    def restore(self, lines: list[str]) -> list[str]:
        restored: list[str] = []
        for line in lines:
            value = line
            for token, original in self.saved:
                value = value.replace(token, original)
            restored.append(value.strip())
        return restored

    def speaker_tokens(self) -> list[str]:
        """Return only name tags that began their Japanese source line.

        Inline character-name tags are ordinary runtime placeholders and may be
        positioned naturally inside the English sentence.
        """
        return list(self.line_leading_speaker_tokens)


@dataclass
class ReferenceBundle:
    glossary: str
    code_glossary: str
    voice_guide: str
    hashes: dict[str, str]


@dataclass
class RevisionResult:
    block_id: int
    protected_lines: list[str]
    restored_lines: list[str]


class ValidationError(ValueError):
    pass


class OutputTokenLimitError(ValidationError):
    """A valid response exhausted its output budget before returning usable JSON."""


class PartialBatchValidationError(ValidationError):
    """Some blocks validated, while a smaller subset still needs regeneration."""

    def __init__(
        self,
        accepted_results: list[RevisionResult],
        pending: list[PreparedBlock],
        message: str,
    ) -> None:
        super().__init__(message)
        self.accepted_results = accepted_results
        self.pending = pending


@dataclass(frozen=True)
class SceneRule:
    filename: str
    start: int
    end: int
    max_lines: int
    max_width: int
    label: str

    def contains(self, block_id: int) -> bool:
        return self.start <= block_id <= self.end


@dataclass
class BlockLimits:
    locked: bool
    strict: bool
    max_lines: int
    max_width: int
    label: str | None = None


@dataclass
class UsageRecord:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    estimated_cost_usd: Decimal = Decimal("0")
    provider: str | None = None
    model: str | None = None


@dataclass
class BudgetTracker:
    path: Path
    max_cost_usd: Decimal
    input_price_per_million: Decimal
    output_price_per_million: Decimal
    cache_read_price_per_million: Decimal
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    estimated_cost_usd: Decimal = Decimal("0")
    requests: int = 0

    @classmethod
    def load(
        cls,
        path: Path,
        max_cost_usd: Decimal,
        input_price_per_million: Decimal,
        output_price_per_million: Decimal,
        cache_read_price_per_million: Decimal,
        resume: bool,
    ) -> "BudgetTracker":
        tracker = cls(
            path=path,
            max_cost_usd=max_cost_usd,
            input_price_per_million=input_price_per_million,
            output_price_per_million=output_price_per_million,
            cache_read_price_per_million=cache_read_price_per_million,
        )
        if not resume or not path.is_file():
            return tracker
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            tracker.prompt_tokens = int(data.get("prompt_tokens", 0))
            tracker.completion_tokens = int(data.get("completion_tokens", 0))
            tracker.cached_tokens = int(data.get("cached_tokens", 0))
            tracker.estimated_cost_usd = Decimal(str(data.get("estimated_cost_usd", "0")))
            tracker.requests = int(data.get("requests", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError, InvalidOperation):
            pass
        return tracker

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
            "estimated_cost_usd": str(self.estimated_cost_usd.quantize(Decimal("0.000001"))),
            "requests": self.requests,
            "max_cost_usd": str(self.max_cost_usd),
            "input_price_per_million": str(self.input_price_per_million),
            "output_price_per_million": str(self.output_price_per_million),
            "cache_read_price_per_million": str(self.cache_read_price_per_million),
        }
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temp, self.path)

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int, cached_tokens: int) -> Decimal:
        cached = max(0, min(cached_tokens, prompt_tokens))
        uncached = max(0, prompt_tokens - cached)
        million = Decimal("1000000")
        return (
            Decimal(uncached) * self.input_price_per_million / million
            + Decimal(cached) * self.cache_read_price_per_million / million
            + Decimal(completion_tokens) * self.output_price_per_million / million
        )

    def ensure_room(self, estimated_next_cost: Decimal) -> None:
        if self.max_cost_usd <= 0:
            return
        projected = self.estimated_cost_usd + estimated_next_cost
        if projected > self.max_cost_usd:
            raise FatalGatewayError(
                "Local spend guard stopped before the next request. "
                f"Tracked cost=${self.estimated_cost_usd:.4f}; "
                f"estimated next=${estimated_next_cost:.4f}; "
                f"limit=${self.max_cost_usd:.2f}."
            )

    def add(self, usage: UsageRecord) -> None:
        self.prompt_tokens += usage.prompt_tokens
        self.completion_tokens += usage.completion_tokens
        self.cached_tokens += usage.cached_tokens
        self.estimated_cost_usd += usage.estimated_cost_usd
        self.requests += 1
        self.save()

    @property
    def remaining(self) -> Decimal:
        return self.max_cost_usd - self.estimated_cost_usd


def contains_japanese(text: str) -> bool:
    return bool(JP_RE.search(text))


def trim_boundary_blanks(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def speaker_marker(lines: list[str]) -> str | None:
    nonempty = [line.strip() for line in lines if line.strip()]
    if len(nonempty) != 1:
        return None
    match = re.fullmatch(r"<([A-Za-z][A-Za-z0-9_-]*)>", nonempty[0])
    return match.group(1) if match else None


def command_marker(lines: list[str]) -> str | None:
    nonempty = [line.strip().lower() for line in lines if line.strip()]
    if len(nonempty) != 1:
        return None
    return nonempty[0] if nonempty[0] in {"notice", "select"} else None


def classify_blocks(chunks: list[list[str]]) -> list[Block]:
    blocks: list[Block] = []
    previous_marker: str | None = None
    active_speaker: str | None = None

    for block_id, raw_lines in enumerate(chunks):
        lines = trim_boundary_blanks(raw_lines)
        # In this project format every source line starts with '#'. Do not require a
        # Japanese character: source records can be names, tags, numbers, or codes.
        jp_indices = [
            index
            for index, line in enumerate(lines)
            if line.lstrip().startswith("#")
        ]

        if not jp_indices:
            marker = command_marker(lines)
            named_speaker = speaker_marker(lines)
            block = Block(
                index=block_id,
                lines=lines,
                kind="command",
                marker=marker,
                speaker=named_speaker,
            )
            blocks.append(block)
            if named_speaker is not None:
                active_speaker = named_speaker
                previous_marker = None
            elif marker is not None:
                previous_marker = marker
            elif any(line.strip() for line in lines):
                previous_marker = None
            continue

        last_jp = max(jp_indices)
        en_indices = [
            index
            for index in range(last_jp + 1, len(lines))
            if lines[index].strip() and not lines[index].lstrip().startswith("#")
        ]
        kind = "choice" if any("<03:" in lines[index] for index in jp_indices) else "dialogue"
        speaker = None
        for index in jp_indices:
            match = SPEAKER_RE.match(lines[index].strip())
            if match:
                speaker = match.group(1)
                break

        exact = kind == "choice" or previous_marker in {"notice", "select"}
        if speaker is None and not exact:
            speaker = active_speaker
        blocks.append(
            Block(
                index=block_id,
                lines=lines,
                kind=kind,
                japanese_indices=jp_indices,
                english_indices=en_indices,
                speaker=speaker,
                preceding_marker=previous_marker,
                exact_line_count=exact,
            )
        )
        active_speaker = None
        previous_marker = None

    return blocks

def split_blocks(content: str) -> tuple[list[Block], bool]:
    trailing_newline = content.endswith(("\n", "\r"))
    chunks = re.split(r"^\s*" + re.escape(DIVIDER) + r"\s*$", content, flags=re.MULTILINE)
    raw = [chunk.splitlines() for chunk in chunks]
    return classify_blocks(raw), trailing_newline


def render_blocks(blocks: list[Block], trailing_newline: bool) -> str:
    rendered = ["\n".join(trim_boundary_blanks(block.lines)) for block in blocks]
    result = ("\n" + DIVIDER + "\n").join(rendered)
    if trailing_newline and not result.endswith("\n"):
        result += "\n"
    elif not trailing_newline and result.endswith("\n"):
        result = result[:-1]
    return result


def read_references(root: Path) -> ReferenceBundle:
    contents: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for filename in REFERENCE_FILENAMES:
        path = root / filename
        if not path.is_file():
            raise FileNotFoundError(f"Required reference file not found: {path}")
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        if not text.strip():
            raise RuntimeError(f"Required reference file is empty: {path}")
        contents[filename] = text.strip()
        hashes[filename] = hashlib.sha256(raw).hexdigest()
    return ReferenceBundle(
        glossary=contents["glossary.txt"],
        code_glossary=contents["code_glossary.txt"],
        voice_guide=contents["character_voice_guide.txt"],
        hashes=hashes,
    )


def scene_rule_for(filename: str, block_id: int) -> SceneRule | None:
    for raw in KNOWN_GOOD_SCENE_RULES.get(filename, []):
        rule = SceneRule(
            filename=filename,
            start=int(raw["start"]),
            end=int(raw["end"]),
            max_lines=int(raw["max_lines"]),
            max_width=int(raw["max_width"]),
            label=str(raw.get("label") or "known-good scene"),
        )
        if rule.contains(block_id):
            return rule
    return None


def source_rule_for(block: Block) -> SceneRule | None:
    japanese = tuple(block.japanese_lines)
    for raw in KNOWN_GOOD_SOURCE_RULES:
        if japanese != tuple(raw["japanese"]):
            continue
        return SceneRule(
            filename="*",
            start=block.index,
            end=block.index,
            max_lines=int(raw["max_lines"]),
            max_width=int(raw["max_width"]),
            label=str(raw.get("label") or "known-good source-signature record"),
        )
    return None


def known_good_rule_for(filename: str, block: Block) -> SceneRule | None:
    return scene_rule_for(filename, block.index) or source_rule_for(block)


def effective_limits(block: Block, filename: str, args: argparse.Namespace) -> BlockLimits:
    """Return the active mode's hard validation limits for one block."""
    rule = known_good_rule_for(filename, block)
    source_count = max(1, len(block.japanese_indices))

    # Tested repairs remain console-safe and locked in both output branches.
    if rule is not None:
        return BlockLimits(
            locked=not args.revise_known_good_scenes,
            strict=True,
            max_lines=max(1, rule.max_lines),
            max_width=min(rule.max_width, 36),
            label=rule.label,
        )

    if block.exact_line_count:
        return BlockLimits(
            locked=False,
            strict=True,
            max_lines=source_count,
            max_width=args.active_max_line_width,
            label=(
                "quality-pass NOTICE/SELECT/choice exact structure"
                if args.mode == "quality"
                else "safe-pass NOTICE/SELECT/choice exact structure"
            ),
        )

    if args.mode == "quality":
        # Deliberately generous: enough room for natural localization, while still
        # rejecting pathological model output. Unlike the safe pass, English may use
        # more lines than the Japanese source.
        return BlockLimits(
            locked=False,
            strict=False,
            max_lines=args.quality_max_lines,
            max_width=args.active_max_line_width,
            label="quality-pass unrestricted dialogue sanity ceiling",
        )

    # Safe mode is the targeted console-layout pass. Ordinary dialogue may
    # expand beyond the Japanese physical line count: PCSX2 testing confirmed
    # that five-line records page correctly as four visible rows plus one line
    # after advancing.
    return BlockLimits(
        locked=False,
        strict=True,
        max_lines=max(1, args.safe_max_lines),
        max_width=args.active_max_line_width,
        label="third-pass verified ordinary dialogue layout",
    )

def compact_text(value: str, limit: int) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def build_file_context(blocks: list[Block], max_chars: int) -> str:
    """Build a stable, read-only scene map to exploit Kimi's long context window."""
    entries: list[dict[str, Any]] = []
    for block in blocks:
        if block.kind == "command":
            command_lines = [line for line in block.lines if line.strip()]
            if not command_lines:
                continue
            entries.append(
                {
                    "id": block.index,
                    "kind": "command",
                    "speaker_marker": block.speaker,
                    "lines": command_lines,
                }
            )
        else:
            entries.append(
                {
                    "id": block.index,
                    "kind": block.kind,
                    "speaker": block.speaker,
                    "japanese": block.japanese_lines,
                    "current_english": block.english_lines,
                }
            )

    full = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
    if len(full) <= max_chars:
        return full

    # Compact every block rather than dropping the end of a long scene. This gives
    # the model the complete narrative order while local context supplies exact text.
    for text_limit in (240, 140, 80):
        compact: list[dict[str, Any]] = []
        for entry in entries:
            if entry["kind"] == "command":
                compact.append(
                    {
                        "id": entry["id"],
                        "k": "c",
                        "s": entry.get("speaker_marker"),
                        "t": compact_text(" | ".join(entry.get("lines", [])), text_limit),
                    }
                )
            else:
                compact.append(
                    {
                        "id": entry["id"],
                        "k": entry["kind"],
                        "s": entry.get("speaker"),
                        "j": compact_text(" / ".join(entry.get("japanese", [])), text_limit),
                        "e": compact_text(" / ".join(entry.get("current_english", [])), text_limit),
                    }
                )
        rendered = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        if len(rendered) <= max_chars:
            return rendered

    # Last-resort complete index/speaker map. Local exact context remains available.
    skeleton = [
        {"id": entry["id"], "k": entry["kind"], "s": entry.get("speaker") or entry.get("speaker_marker")}
        for entry in entries
    ]
    rendered = json.dumps(skeleton, ensure_ascii=False, separators=(",", ":"))
    return rendered[:max_chars]


def build_system_prompt(refs: ReferenceBundle, args: argparse.Namespace) -> str:
    if args.mode == "quality":
        role = (
            "You are the senior English localization editor performing the QUALITY "
            "SECOND PASS on the Japan-only PlayStation 2 game Tales of Destiny 2."
        )
        mode_goals = f"""
QUALITY-PASS POLICY
- Prioritize accurate meaning, natural English, character voice, terminology, humor,
  emotional nuance, and scene continuity.
- Do not compress wording merely to fit the original 36-column PS2 window.
- Ordinary dialogue may use up to {args.quality_max_lines} English lines and
  {args.active_max_line_width} visible columns per line.
- These are generous sanity ceilings, not a claim of console safety.
- This output may be released only as an Unrestricted/Experimental localization.
"""
        ordinary_rule = (
            f"For ordinary blocks, reflow naturally up to {args.quality_max_lines} "
            f"lines and {args.active_max_line_width} visible columns."
        )
        task_name = "second-pass quality localization"
    else:
        role = (
            "You are the senior console-layout editor performing the TARGETED THIRD "
            "PASS on a polished English localization of Tales of Destiny 2 for PS2."
        )
        mode_goals = f"""
SAFE-PASS POLICY
- Treat current_english as the polished quality-pass draft. Preserve every factual
  point, attribution, reason, destination, quantity, gameplay detail, speaker
  experience, joke, and emotional beat.
- Compare every Japanese source line against the proposed output before answering.
  Every source-line proposition must remain represented somewhere in the English.
- Never solve a layout problem by dropping a final clause such as "thanks to X,"
  "even I have never entered," a cause, a warning, or an instruction.
- Do not retranslate merely for stylistic preference.
- Ordinary dialogue must also respect the per-page text budget: the combined
  visible length of each group of {args.safe_page_lines} displayed rows must not
  exceed {args.safe_page_visible_budget} characters. A fifth line starts a new page.
- Rewrite only as much as needed to fit the supplied console-safe layout.
- Ordinary control-free dialogue is limited to {args.safe_max_lines} English lines
  and {args.active_max_line_width} visible columns. It may use more English lines
  than the Japanese source record.
- Five-line ordinary records are valid: four rows display first and the fifth line
  appears after advancing. Do not compress below five lines unless wording must be
  shortened to satisfy the 36-column limit.
- Every requested ordinary block normally still violates one of those limits after
  deterministic lossless reflow, or contains a runtime-code sequence problem.
"""
        ordinary_rule = (
            "For ordinary blocks, compress/reflow within max_output_lines and "
            "max_visible_width. Preserve the quality draft as closely as possible."
        )
        task_name = "third-pass console-safety compression"

    return f"""{role}

You are using a large-context model. Analyze the complete scene context, neighboring
blocks, speaker continuity, terminology, and emotional arc silently. Return only the
required JSON.

PRIMARY GOALS
- Correct mistranslations, omissions, invented details, grammar, terminology drift,
  and character-voice mistakes.
- Preserve Japanese meaning, intent, humor, foreshadowing, emotional subtext, and
  gameplay information.
- Maintain continuity across the full scene.
- Never move material between block IDs or speakers.

{mode_goals}

MANDATORY OUTPUT
Return exactly one JSON object:
{{"blocks":[{{"id":12,"translations":["English line 1","English line 2"]}}]}}
Return one object for every requested editable block ID, in the same order. Do not add
Markdown, explanations, Japanese, confidence scores, notes, or extra keys.

REFERENCE PRECEDENCE
1. Japanese source and immutable runtime placeholders
2. Per-block structural limits supplied by the host
3. This {task_name} policy
4. code_glossary.txt
5. glossary.txt
6. character_voice_guide.txt
7. Natural English localization judgment

BLOCK SAFETY RULES
- Every block supplies max_output_lines and max_visible_width. They are hard limits.
- Some editable blocks list runtime_render_break_placeholders. These placeholders
  represent the source {{02}} renderer-break code. They split one physical JSON string
  into independently displayed text segments. Preserve them exactly, and apply
  max_visible_width to EACH rendered segment rather than to the combined physical string.
- For exact_line_count=true, return exactly source_line_count lines in one-to-one order.
- For strict_scene=true, obey its tested layout exactly.
- {ordinary_rule}
- Prefer balanced phrase breaks. Avoid one- or two-word orphan lines.
- Never split names, placeholders, tags, or tightly bound phrases.

RUNTIME PLACEHOLDERS
- Tokens like [[B00012C001]] represent executable codes, tags, variables, names, or
  formatting controls.
- Preserve every required placeholder exactly once and in the same global order.
- Never alter, translate, duplicate, omit, or invent a placeholder.
- For exact-line-count blocks, keep each source line's placeholders on its matching
  output line.
- Only placeholders listed in line_leading_speaker_placeholders must begin a line.
- Character-name placeholders not listed there are inline names/vocatives. Place them
  naturally in English and preserve surrounding punctuation; never produce artifacts
  such as "<Kyle> This is bad, !" or "<Loni> Let's go, !".
- Japanese source determines required placeholders; old English does not.

LOCALIZATION RULES
- Do not add information absent from Japanese.
- Do not sanitize characterization, jokes, threats, affection, grief, or intensity.
- Use ASCII apostrophes, quotes, hyphens, and three periods (...) unless an immutable
  placeholder contains another character.
- Use glossary terms exactly.
- Use arte, not art, for battle abilities.
- Do not confuse Tales of Destiny 2 with Tales of Destiny II / Tales of Eternia.
- Command-only blocks are read-only context and must never be returned.

SILENT FINAL CHECK
- Correct IDs and order; valid JSON only
- Complete meaning and natural character voice
- No Japanese, blank strings, divider lines, or leading # markers
- Correct placeholder counts, order, exact-block line assignment, and natural name placement
- All line-count and width limits obeyed
- Output encodable in CP932

<PROJECT_GLOSSARY file="glossary.txt">
{refs.glossary}
</PROJECT_GLOSSARY>

<CODE_GLOSSARY file="code_glossary.txt">
{refs.code_glossary}
</CODE_GLOSSARY>

<CHARACTER_VOICE_GUIDE file="character_voice_guide.txt">
{refs.voice_guide}
</CHARACTER_VOICE_GUIDE>
"""
def prepare_block(block: Block) -> PreparedBlock:
    protector = BlockProtector(block.index)
    protected_source = protector.protect_source(block.japanese_lines)
    protected_draft = protector.protect_draft(block.english_lines)
    return PreparedBlock(block, protector, protected_source, protected_draft)


def context_entry(
    block: Block,
    editable: bool,
    prepared: PreparedBlock | None = None,
) -> dict[str, Any]:
    if prepared is not None:
        jp = prepared.protected_source
        en = prepared.protected_draft
    else:
        jp = block.japanese_lines
        en = block.english_lines
    return {
        "id": block.index,
        "editable": editable,
        "kind": block.kind,
        "preceding_marker": block.preceding_marker,
        "speaker": block.speaker,
        "command_lines": block.lines if block.kind == "command" else [],
        "japanese": jp,
        "current_english": en,
    }

def build_batch_prompt(
    filename: str,
    blocks: list[Block],
    prepared: list[PreparedBlock],
    file_context: str,
    context_blocks: int,
    args: argparse.Namespace,
    feedback: str | None = None,
    include_full_file_context: bool = True,
) -> str:
    prepared_by_id = {item.id: item for item in prepared}
    editable_ids = set(prepared_by_id)
    first = max(0, min(editable_ids) - context_blocks)
    last = min(len(blocks) - 1, max(editable_ids) + context_blocks)

    local_sequence: list[dict[str, Any]] = []
    for block in blocks[first:last + 1]:
        local_sequence.append(
            context_entry(block, block.index in editable_ids, prepared_by_id.get(block.index))
        )

    editable: list[dict[str, Any]] = []
    for item in prepared:
        block = item.block
        limits = effective_limits(block, filename, args)
        editable.append(
            {
                "id": block.index,
                "kind": block.kind,
                "speaker": block.speaker,
                "preceding_marker": block.preceding_marker,
                "exact_line_count": block.exact_line_count,
                "strict_scene": limits.strict,
                "strict_scene_label": limits.label,
                "source_line_count": len(block.japanese_indices),
                "current_english_line_count": len(block.english_indices),
                "max_output_lines": limits.max_lines,
                "max_visible_width": limits.max_width,
                "required_placeholders": item.protector.required_tokens,
                "required_placeholders_by_source_line": item.protector.source_line_tokens,
                "source_initial_name_placeholders": item.protector.speaker_tokens(),
                "runtime_render_break_placeholders": item.protector.runtime_break_tokens,
                "exact_source_lines_indexed": [
                    {
                        "line": index + 1,
                        "japanese": jp,
                        "current_english": (
                            item.protected_draft[index]
                            if index < len(item.protected_draft)
                            else ""
                        ),
                        "required_placeholders": item.protector.source_line_tokens[index],
                        "runtime_render_break_placeholders": (
                            item.protector.runtime_break_tokens_for_source_line(index)
                        ),
                    }
                    for index, jp in enumerate(item.protected_source)
                ] if block.exact_line_count else [],
                "japanese": item.protected_source,
                "current_english": item.protected_draft,
            }
        )

    request: dict[str, Any] = {
        "task": (
            "Revise every editable block for localization quality using Japanese and scene context. "
            "Return only the required JSON object."
            if args.mode == "quality"
            else
            "Compress/reflow every editable block to console-safe layout while preserving the "
            "quality-pass translation. Return only the required JSON object."
        ),
        "file": filename,
        "editable_block_ids_in_required_order": [item.id for item in prepared],
        "context_scope": (
            "complete-file plus local sequence"
            if include_full_file_context
            else "compact structural retry using local sequence only"
        ),
        "local_exact_sequence_context": local_sequence,
        "editable_blocks": editable,
    }
    if include_full_file_context:
        request["complete_file_scene_context_read_only"] = json.loads(file_context)
    if feedback:
        request["previous_attempt_validation_error"] = feedback
        exact_requirements = [
            f"block {item.id}: exactly {len(item.block.japanese_indices)} translation strings, "
            "one for each indexed Japanese source line; do not merge or omit lines"
            for item in prepared
            if item.block.exact_line_count
        ]
        request["retry_instruction"] = (
            (
                "Regenerate only the requested blocks and correct the structural error without "
                "weakening translation quality."
                if args.mode == "quality"
                else
                "Regenerate only the requested blocks, preserve every Japanese and quality-draft "
                "meaning point, and satisfy every console-safe layout constraint. Shorten "
                "wording; do not delete information."
            )
        )
        if exact_requirements:
            request["exact_block_retry_requirements"] = exact_requirements
    return json.dumps(request, ensure_ascii=False, separators=(",", ":"))

def response_schema(batch_size: int, max_lines: int) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "tod2_second_pass_batch",
            "description": "Revised English lines for every requested Tales of Destiny 2 script block.",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "blocks": {
                        "type": "array",
                        "minItems": batch_size,
                        "maxItems": batch_size,
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer"},
                                "translations": {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": max(1, max_lines),
                                    "items": {"type": "string", "minLength": 1},
                                },
                            },
                            "required": ["id", "translations"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["blocks"],
                "additionalProperties": False,
            },
        },
    }

def normalize_endpoint(endpoint: str) -> str:
    value = endpoint.strip().rstrip("/")
    # The Vercel dashboard URL is not an API endpoint. Accept it defensively and
    # redirect to the official AI Gateway endpoint.
    if "vercel.com/" in value and "ai-gateway" in value and "ai-gateway.vercel.sh" not in value:
        value = VERCEL_BASE_URL
    if value.endswith("/chat/completions"):
        return value
    if value.endswith("/v1"):
        return value + "/chat/completions"
    return value + "/v1/chat/completions"

def strip_reasoning(text: str) -> str:
    cleaned = text.lstrip("\ufeff")
    while True:
        updated, count = LEADING_REASONING_BLOCK_RE.subn("", cleaned, count=1)
        if not count:
            break
        cleaned = updated
    cleaned = re.sub(
        r"\A\s*<(?:think|analysis|reasoning)>\s*",
        "",
        cleaned,
        count=1,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


def extract_response_text(result: dict[str, Any]) -> tuple[str, str, str]:
    try:
        choice = result["choices"][0]
        message = choice.get("message") or {}
        content_value = message.get("content")
        if isinstance(content_value, list):
            parts: list[str] = []
            for item in content_value:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item, str):
                    parts.append(item)
            content = "".join(parts)
        else:
            content = str(content_value or "")
        reasoning = str(
            message.get("reasoning_content")
            or message.get("reasoning")
            or ""
        )
        return content, reasoning, str(choice.get("finish_reason") or "")
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ValueError(f"Unexpected AI Gateway response: {list(result)[:10]}") from exc

def parse_json_response(text: str) -> dict[str, Any]:
    cleaned = strip_reasoning(text)
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[^\n]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()
    candidates = [cleaned]
    first = cleaned.find("{")
    last = cleaned.rfind("}")
    if first >= 0 and last > first:
        candidates.append(cleaned[first:last + 1])
    for candidate in dict.fromkeys(candidates):
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"Could not parse model JSON: {cleaned[:600]!r}")


def nested_int(mapping: Any, *path: str) -> int:
    value = mapping
    for key in path:
        if not isinstance(value, dict):
            return 0
        value = value.get(key)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def extract_usage_record(
    result: dict[str, Any],
    budget: BudgetTracker,
    fallback_prompt_tokens: int,
    fallback_completion_tokens: int,
) -> UsageRecord:
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    prompt_tokens = nested_int(usage, "prompt_tokens") or nested_int(usage, "input_tokens")
    completion_tokens = nested_int(usage, "completion_tokens") or nested_int(usage, "output_tokens")
    cached_tokens = (
        nested_int(usage, "prompt_tokens_details", "cached_tokens")
        or nested_int(usage, "input_tokens_details", "cached_tokens")
        or nested_int(usage, "cached_tokens")
    )
    if prompt_tokens <= 0:
        prompt_tokens = fallback_prompt_tokens
    if completion_tokens <= 0:
        completion_tokens = fallback_completion_tokens

    provider = None
    metadata = result.get("providerMetadata") or result.get("provider_metadata")
    if isinstance(metadata, dict):
        gateway = metadata.get("gateway")
        if isinstance(gateway, dict):
            provider = gateway.get("provider") or gateway.get("providerName")
        if provider is None:
            provider = metadata.get("provider")

    cost = budget.estimate_cost(prompt_tokens, completion_tokens, cached_tokens)
    return UsageRecord(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        estimated_cost_usd=cost,
        provider=str(provider) if provider else None,
        model=str(result.get("model") or "") or None,
    )



def gateway_error_message(body: str) -> str:
    """Extract the useful message from an AI Gateway error response."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()[:1200]

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
            param = error.get("param")
            if isinstance(param, dict):
                nested = param.get("message") or param.get("error")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
    return body.strip()[:1200]


def model_access_hint(status: int, body: str) -> str:
    message = gateway_error_message(body)
    lower = message.lower()
    if status == 403 and (
        "free tier users do not have access" in lower
        or "restrictedmodelserror" in body.lower()
    ):
        return (
            "Kimi K2.6 is not available to this Vercel AI Gateway free-tier account. "
            "Purchase AI Gateway credits (which switches the account to paid access), "
            "configure a provider BYOK key, or select a model marked for free-tier access. "
            f"Gateway message: {message}"
        )
    if status in {402, 403}:
        return f"AI Gateway billing/access error HTTP {status}: {message}"
    if status == 401:
        return "AI Gateway rejected the API key (HTTP 401). Check AI_GATEWAY_API_KEY."
    return f"AI Gateway HTTP {status}: {message}"

def call_server(
    system_prompt: str,
    user_prompt: str,
    batch_size: int,
    max_schema_lines: int,
    budget: BudgetTracker,
    args: argparse.Namespace,
) -> dict[str, Any]:
    endpoint = normalize_endpoint(args.endpoint)
    # Reserve enough output for both the requested JSON and optional Kimi thinking.
    # Version 3.2 used 48 * 192 = 9,216 tokens, which Kimi could consume entirely
    # in reasoning before emitting message.content.
    thinking_reserve = (
        args.thinking_budget_tokens if args.thinking == "enabled" else 0
    )
    effective_max_tokens = min(
        args.max_tokens,
        max(4096, batch_size * args.tokens_per_block + thinking_reserve),
    )

    gateway_options: dict[str, Any] = {}
    if args.gateway_sort != "none":
        gateway_options["sort"] = args.gateway_sort
    if not args.no_gateway_cache:
        gateway_options["caching"] = "auto"
    if args.providers:
        gateway_options["only"] = [
            value.strip() for value in args.providers.split(",") if value.strip()
        ]

    payload: dict[str, Any] = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": args.temperature,
        "top_p": args.top_p,
        "max_tokens": effective_max_tokens,
        "stream": False,
    }
    provider_options: dict[str, Any] = {}
    if gateway_options:
        provider_options["gateway"] = gateway_options

    # Kimi K2.6 is reasoning-capable. For this constrained localization task the
    # default is disabled thinking so the completion budget is used for the JSON
    # translation rather than a long hidden chain of thought. Users may explicitly
    # enable bounded thinking with --thinking enabled.
    if args.thinking != "auto":
        thinking: dict[str, Any] = {"type": args.thinking}
        if args.thinking == "enabled":
            thinking["budgetTokens"] = args.thinking_budget_tokens
        provider_options["moonshotai"] = {
            "thinking": thinking,
            "reasoningHistory": "disabled",
        }

    if provider_options:
        payload["providerOptions"] = provider_options
    if not args.no_json_schema:
        payload["response_format"] = response_schema(batch_size, max_schema_lines)

    api_key = args.api_key or os.getenv("AI_GATEWAY_API_KEY", "") or os.getenv("VERCEL_AI_GATEWAY_API_KEY", "")
    if not api_key:
        raise FatalGatewayError(
            "AI Gateway key not found. Set AI_GATEWAY_API_KEY in PowerShell before running."
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "TOD2-Kimi-Two-Stage/4.5",
    }

    fallback_prompt_tokens = max(1, (len(system_prompt) + len(user_prompt) + 2) // 3)
    expected_completion_tokens = min(
        effective_max_tokens,
        max(256, batch_size * args.estimated_output_tokens_per_block),
    )
    preflight_cost = budget.estimate_cost(
        fallback_prompt_tokens,
        expected_completion_tokens,
        0,
    )
    budget.ensure_room(preflight_cost)

    response_modes = ["json_schema", "json_object", "plain"]
    mode_index = 0 if "response_format" in payload else 2
    last_error: Exception | None = None

    for attempt in range(1, args.network_retries + 1):
        if mode_index == 1:
            payload["response_format"] = {"type": "json_object"}
        elif mode_index >= 2:
            payload.pop("response_format", None)

        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
        started = time.monotonic()
        print(
            f"    AI Gateway attempt {attempt}/{args.network_retries}; "
            f"mode={response_modes[mode_index]}; blocks={batch_size}; "
            f"max_tokens={effective_max_tokens}; tracked=${budget.estimated_cost_usd:.4f}",
            flush=True,
        )
        try:
            with urllib.request.urlopen(request, timeout=args.timeout) as response:
                raw_bytes = response.read()
            raw = raw_bytes.decode("utf-8")
            result = json.loads(raw)
            if isinstance(result.get("error"), dict):
                error_text = json.dumps(result["error"], ensure_ascii=False)
                lower = error_text.lower()
                if any(marker in lower for marker in (
                    "restrictedmodelserror",
                    "billing",
                    "insufficient",
                    "invalid api key",
                    "unauthorized",
                )):
                    raise FatalGatewayError(f"AI Gateway error: {error_text}")
                raise GatewayError(f"AI Gateway error: {error_text}")
            content, reasoning, finish_reason = extract_response_text(result)
            if args.debug_response:
                print(json.dumps(result, ensure_ascii=False, indent=2)[:20000], file=sys.stderr)

            # HTTP 200 responses can still be billable even when the model exhausts
            # its output budget before producing usable JSON. Track usage before any
            # content/validation checks so retries and splits cannot bypass the local
            # spend guard.
            fallback_completion_tokens = max(
                1,
                (len(content) + len(reasoning) + 2) // 3,
            )
            usage = extract_usage_record(
                result,
                budget,
                fallback_prompt_tokens,
                fallback_completion_tokens,
            )
            budget.add(usage)

            hit_limit = finish_reason.lower() in {"length", "limit", "max_tokens"}
            if not content.strip() and hit_limit:
                raise OutputTokenLimitError(
                    "Kimi exhausted the completion budget before emitting JSON; "
                    f"max_tokens={effective_max_tokens}, reasoning={len(reasoning)} chars, "
                    f"thinking={args.thinking!r}. The batch will be split without "
                    "repeating the same full-size request."
                )
            if not content.strip():
                raise ValidationError(
                    f"Empty message.content; finish_reason={finish_reason!r}; "
                    f"reasoning={len(reasoning)} chars"
                )
            if hit_limit:
                raise OutputTokenLimitError(
                    "Kimi returned partial content at the output-token limit; "
                    f"max_tokens={effective_max_tokens}, reasoning={len(reasoning)} chars."
                )

            parsed = parse_json_response(content)
            provider_text = f" via {usage.provider}" if usage.provider else ""
            print(
                f"    completed in {time.monotonic() - started:.1f}s{provider_text}; "
                f"tokens in={usage.prompt_tokens:,} out={usage.completion_tokens:,} "
                f"cached={usage.cached_tokens:,}; est=${usage.estimated_cost_usd:.4f}; "
                f"total=${budget.estimated_cost_usd:.4f}",
                flush=True,
            )
            return parsed

        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:4000]
            if exc.code in {400, 422} and mode_index < 2 and "response_format" in payload:
                print(
                    f"    structured-output mode rejected (HTTP {exc.code}); "
                    f"falling back from {response_modes[mode_index]}",
                    file=sys.stderr,
                )
                mode_index += 1
                continue
            if exc.code in {401, 402, 403}:
                raise FatalGatewayError(model_access_hint(exc.code, body)) from exc
            last_error = RuntimeError(f"HTTP {exc.code} {exc.reason}: {body}")
            retryable = exc.code in {408, 409, 429} or exc.code >= 500
        except OutputTokenLimitError:
            # This is a completed, billed model response, not a transport failure.
            # Do not repeat the identical request in the network retry loop.
            raise
        except ValidationError:
            raise
        except (urllib.error.URLError, TimeoutError, socket.timeout, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            retryable = True

        if not retryable or attempt >= args.network_retries:
            break
        delay = args.retry_delay * (2 ** (attempt - 1))
        print(f"    request error: {last_error}; retrying in {delay:.1f}s", file=sys.stderr)
        time.sleep(delay)

    if isinstance(last_error, (ValueError, json.JSONDecodeError)):
        raise ValidationError(f"AI response could not be parsed or validated: {last_error}")
    raise GatewayError(f"AI Gateway request failed after retries: {last_error}")

def visible_width(text: str) -> int:
    text = TOKEN_RE.sub("", text)

    def angle_visible(match: re.Match[str]) -> str:
        token = match.group(0)
        inner = token[1:-1]
        # Bare name variables such as <Kyle> render as visible text. Colon
        # controls such as <button:...> and <item:...> remain dynamic-width and
        # are handled by the control-sensitive policy.
        if ":" not in inner and re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_-]*",
            inner,
        ):
            return inner
        return ""

    text = ANGLE_TAG_RE.sub(angle_visible, text)
    text = CURLY_CODE_RE.sub("", text)
    width = 0
    for char in text:
        if char == "\t":
            width += 4
        elif unicodedata.east_asian_width(char) in {"W", "F"}:
            width += 2
        else:
            width += 1
    return width


def raw_render_segments(text: str) -> list[str]:
    """Split an unprotected .sced English line at renderer-controlled breaks."""
    return RAW_RENDER_BREAK_SPLIT_RE.split(text)


def raw_render_segment_widths(text: str) -> list[int]:
    return [visible_width(segment) for segment in raw_render_segments(text)]


def protected_render_segment_widths(
    text: str,
    protector: "BlockProtector",
) -> list[int]:
    return [
        visible_width(segment)
        for segment in protector.split_render_segments(text)
    ]


def max_raw_render_width(text: str) -> int:
    widths = raw_render_segment_widths(text)
    return max(widths, default=0)


def ordinary_page_visible_totals(
    lines: Iterable[str],
    page_lines: int = 4,
) -> list[int]:
    """Return visible-character totals for successive ordinary-textbox pages."""
    if page_lines < 1:
        raise ValueError("page_lines must be at least 1")
    values = list(lines)
    return [
        sum(max_raw_render_width(line) for line in values[start:start + page_lines])
        for start in range(0, len(values), page_lines)
    ]


def ordinary_page_budget_ok(
    lines: Iterable[str],
    page_lines: int,
    page_visible_budget: int,
) -> bool:
    return all(
        total <= page_visible_budget
        for total in ordinary_page_visible_totals(lines, page_lines)
    )


def balanced_page_aware_wrap(
    text: str,
    max_width: int,
    max_lines: int,
    page_lines: int,
    page_visible_budget: int,
) -> list[str]:
    """Wrap text under line, line-count, and displayed-page constraints."""
    from functools import lru_cache

    words = text.split()
    if not words:
        return []
    if max_lines < 1 or page_lines < 1 or page_visible_budget < 1:
        raise ValidationError("Invalid page-aware wrapping limits")
    for word in words:
        if visible_width(word) > max_width:
            raise ValidationError(f"Cannot wrap overlong word/token safely: {word!r}")

    word_count = len(words)
    total_visible = sum(visible_width(word) for word in words)

    for line_count in range(1, max_lines + 1):
        target_width = (total_visible + max(0, word_count - line_count)) / line_count

        @lru_cache(None)
        def solve(word_index: int, line_index: int, page_total: int):
            if word_index == word_count:
                return (0.0, ()) if line_index == line_count else None
            if line_index >= line_count:
                return None
            remaining_words = word_count - word_index
            remaining_lines = line_count - line_index
            if remaining_words < remaining_lines:
                return None

            current = ""
            best = None
            page_position = line_index % page_lines
            active_page_total = 0 if page_position == 0 else page_total

            for end in range(word_index, word_count):
                current = words[end] if end == word_index else f"{current} {words[end]}"
                width = visible_width(current)
                if width > max_width:
                    break
                new_page_total = active_page_total + width
                if new_page_total > page_visible_budget:
                    continue
                words_left = word_count - (end + 1)
                lines_left = line_count - (line_index + 1)
                if words_left < lines_left:
                    break
                next_page_total = 0 if (line_index + 1) % page_lines == 0 else new_page_total
                tail = solve(end + 1, line_index + 1, next_page_total)
                if tail is None:
                    continue
                cost = (width - target_width) ** 2 + tail[0]
                if line_index + 1 < line_count and width < target_width * 0.55:
                    cost += 80.0
                candidate = (cost, (current,) + tail[1])
                if best is None or candidate[0] < best[0]:
                    best = candidate
            return best

        solved = solve(0, 0, 0)
        if solved is not None:
            return list(solved[1])

    raise ValidationError(
        "Cannot fit ordinary dialogue within "
        f"{max_lines} lines, {max_width} columns, and "
        f"{page_visible_budget} visible characters per {page_lines}-row page"
    )


def token_spans(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in TOKEN_RE.finditer(text)]


def inside_span(position: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < position < end for start, end in spans)


def smart_wrap_line(text: str, max_width: int) -> list[str]:
    """Wrap a protected ordinary-dialogue line without splitting placeholder tokens."""
    remaining = text.strip()
    output: list[str] = []
    while visible_width(remaining) > max_width:
        spans = token_spans(remaining)
        candidates: list[tuple[int, int, int]] = []
        for match in re.finditer(r"\s+", remaining):
            position = match.start()
            if inside_span(position, spans):
                continue
            width = visible_width(remaining[:position].rstrip())
            if 1 <= width <= max_width:
                left = remaining[:position].rstrip()
                punctuation_bonus = 2 if left.endswith((",", ";", ":", ".", "?", "!")) else 0
                balance = -abs(max_width - width)
                candidates.append((punctuation_bonus, balance, position))
        if candidates:
            total_width = visible_width(remaining)
            expected_parts = max(2, (total_width + max_width - 1) // max_width)
            target_width = (total_width + expected_parts - 1) // expected_parts
            scored = []
            for punctuation_bonus, _old_balance, position in candidates:
                candidate_width = visible_width(remaining[:position].rstrip())
                score = -abs(candidate_width - target_width) + punctuation_bonus * 2
                scored.append((score, candidate_width, position))
            _, _, split_at = max(scored)
        else:
            split_at = 0
            for position in range(1, len(remaining) + 1):
                if inside_span(position, spans):
                    continue
                if visible_width(remaining[:position]) <= max_width:
                    split_at = position
                else:
                    break
            if split_at <= 0:
                raise ValidationError(f"Cannot wrap line safely: {remaining!r}")
        left = remaining[:split_at].strip()
        remaining = remaining[split_at:].strip()
        if not left or not remaining:
            raise ValidationError(f"Failed to split long line safely: {text!r}")
        output.append(left)
    if remaining:
        output.append(remaining)
    return output


def auto_wrap_ordinary(lines: list[str], max_width: int) -> list[str]:
    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(smart_wrap_line(line, max_width))
    return wrapped


def auto_reflow_ordinary(
    lines: list[str],
    max_width: int,
    max_lines: int,
    page_lines: int | None = None,
    page_visible_budget: int | None = None,
) -> list[str]:
    """Reflow ordinary dialogue without changing wording or placeholders."""
    cleaned = [" ".join(line.strip().split()) for line in lines if line.strip()]
    if not cleaned:
        return cleaned

    line_ok = (
        len(cleaned) <= max_lines
        and all(visible_width(line) <= max_width for line in cleaned)
    )
    page_ok = (
        True
        if page_lines is None or page_visible_budget is None
        else ordinary_page_budget_ok(cleaned, page_lines, page_visible_budget)
    )
    if line_ok and page_ok:
        return cleaned

    joined = " ".join(cleaned)
    if page_lines is not None and page_visible_budget is not None:
        try:
            return balanced_page_aware_wrap(
                joined,
                max_width,
                max_lines,
                page_lines,
                page_visible_budget,
            )
        except ValidationError:
            return cleaned

    wrapped = smart_wrap_line(joined, max_width)
    if len(wrapped) <= max_lines:
        return wrapped
    return cleaned


def validate_cp932(lines: Iterable[str]) -> None:
    for line in lines:
        try:
            line.encode("cp932")
        except UnicodeEncodeError as exc:
            raise ValidationError(
                f"Output contains a character not encodable as CP932: {line!r}"
            ) from exc


def normalize_cp932_safe_punctuation(text: str) -> str:
    """Normalize common model punctuation that Python's CP932 codec rejects."""
    replacements = {
        "\u2014": "--",  # em dash
        "\u2013": "-",   # en dash
        "\u2212": "-",   # mathematical minus
        "\u00A0": " ",   # non-breaking space
        "\u202F": " ",   # narrow non-breaking space
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def response_lines_by_id(
    parsed: dict[str, Any],
    prepared: list[PreparedBlock],
) -> dict[int, list[str]]:
    """Validate the response envelope and normalize each block's strings."""
    raw_blocks = parsed.get("blocks")
    if not isinstance(raw_blocks, list):
        raise ValidationError("Top-level 'blocks' must be an array")

    expected_ids = [item.id for item in prepared]
    actual_ids: list[int] = []
    by_id: dict[int, list[str]] = {}
    for entry in raw_blocks:
        if not isinstance(entry, dict):
            raise ValidationError("Every response block must be an object")
        block_id = entry.get("id")
        translations = entry.get("translations")
        if not isinstance(block_id, int):
            raise ValidationError("Every response block requires an integer id")
        if not isinstance(translations, list) or not all(isinstance(x, str) for x in translations):
            raise ValidationError(f"Block {block_id}: translations must be an array of strings")
        if block_id in by_id:
            raise ValidationError(f"Duplicate response block id {block_id}")
        cleaned: list[str] = []
        for line in translations:
            # Some providers return an escaped newline inside one JSON string even
            # though the semantic result is multiple translation lines. Split it
            # deterministically before structural validation instead of paying for
            # another generation.
            parts = re.split(r"\r\n|\r|\n", line)
            for part in parts:
                value = normalize_cp932_safe_punctuation(
                    " ".join(part.strip().split())
                )
                if not value:
                    raise ValidationError(f"Block {block_id}: empty output line")
                cleaned.append(value)
        actual_ids.append(block_id)
        by_id[block_id] = cleaned

    if actual_ids != expected_ids:
        raise ValidationError(
            f"Response IDs/order {actual_ids} do not match requested {expected_ids}"
        )
    return by_id


def normalize_speaker_token_positions(
    lines: list[str],
    item: PreparedBlock,
) -> list[str]:
    """Return name placeholders unchanged.

    Tags such as <Kyle> and <Loni> are textual name variables, not structural
    speaker-control commands. Their required sequence is validated separately,
    but English grammar may place them anywhere in the sentence.
    """
    return list(lines)

def validate_one_block_response(
    lines: list[str],
    filename: str,
    item: PreparedBlock,
    args: argparse.Namespace,
) -> RevisionResult:
    """Validate one model result, reflowing only structurally safe dialogue."""
    block = item.block
    limits = effective_limits(block, filename, args)
    lines = normalize_speaker_token_positions(list(lines), item)

    if block.exact_line_count:
        expected_count = len(block.japanese_indices)
        if len(lines) != expected_count:
            raise ValidationError(
                f"Block {item.id}: exact block returned {len(lines)} lines; "
                f"expected {expected_count}"
            )
    else:
        # Never reflow across an embedded {02} renderer break. The physical record
        # line may contain several independently displayed segments.
        if not item.protector.runtime_break_tokens:
            lines = auto_reflow_ordinary(
                lines,
                limits.max_width,
                limits.max_lines,
                args.safe_page_lines if args.mode == "safe" else None,
                args.safe_page_visible_budget if args.mode == "safe" else None,
            )
        if len(lines) > limits.max_lines:
            raise ValidationError(
                f"Block {item.id}: returned {len(lines)} lines; maximum is "
                f"{limits.max_lines} ({limits.label or 'current tested layout'})"
            )

    required_set = set(item.protector.required_tokens)
    unknown = [
        token
        for line in lines
        for token in TOKEN_RE.findall(line)
        if token not in required_set
    ]
    if unknown:
        raise ValidationError(f"Block {item.id}: unknown placeholders {unknown}")

    if block.exact_line_count:
        for index, (line, expected_tokens) in enumerate(
            zip(lines, item.protector.source_line_tokens, strict=True), start=1
        ):
            actual_tokens = TOKEN_RE.findall(line)
            if actual_tokens != expected_tokens:
                raise ValidationError(
                    f"Block {item.id} line {index}: placeholders {actual_tokens} "
                    f"do not match source {expected_tokens}"
                )
    else:
        actual_tokens = [token for line in lines for token in TOKEN_RE.findall(line)]
        if actual_tokens != item.protector.required_tokens:
            raise ValidationError(
                f"Block {item.id}: placeholder sequence {actual_tokens} does not "
                f"match source {item.protector.required_tokens}"
            )

    for index, line in enumerate(lines, start=1):
        if contains_japanese(TOKEN_RE.sub("", line)):
            raise ValidationError(f"Block {item.id} line {index}: Japanese leaked into output")
        if line.lstrip().startswith("#"):
            raise ValidationError(f"Block {item.id} line {index}: leading source marker #")
        if DIVIDER in line:
            raise ValidationError(f"Block {item.id} line {index}: divider emitted")
        segment_widths = protected_render_segment_widths(line, item.protector)
        overlong_segments = [
            (segment_index, width)
            for segment_index, width in enumerate(segment_widths, start=1)
            if width > limits.max_width
        ]
        if overlong_segments:
            segment_index, width = overlong_segments[0]
            suffix = (
                f" rendered segment {segment_index}"
                if len(segment_widths) > 1
                else ""
            )
            raise ValidationError(
                f"Block {item.id} line {index}{suffix}: visible width {width} exceeds "
                f"limit {limits.max_width}; segment_widths={segment_widths}: {line!r}"
            )

    if (
        args.mode == "safe"
        and not block.exact_line_count
        and not item.protector.runtime_break_tokens
        and not block_has_sensitive_runtime_codes(block)
    ):
        page_totals = ordinary_page_visible_totals(lines, args.safe_page_lines)
        overfull_pages = [
            (index + 1, total)
            for index, total in enumerate(page_totals)
            if total > args.safe_page_visible_budget
        ]
        if overfull_pages:
            page_no, total = overfull_pages[0]
            raise ValidationError(
                f"Block {item.id}: ordinary page {page_no} uses {total} visible "
                f"characters; maximum is {args.safe_page_visible_budget} across "
                f"{args.safe_page_lines} displayed rows"
            )

    restored = item.protector.restore(lines)
    validate_cp932(restored)
    return RevisionResult(item.id, lines, restored)


def validate_batch_response(
    parsed: dict[str, Any],
    filename: str,
    prepared: list[PreparedBlock],
    args: argparse.Namespace,
) -> list[RevisionResult]:
    by_id = response_lines_by_id(parsed, prepared)
    return [
        validate_one_block_response(by_id[item.id], filename, item, args)
        for item in prepared
    ]

def revise_batch_once(
    filename: str,
    all_blocks: list[Block],
    prepared: list[PreparedBlock],
    file_context: str,
    system_prompt: str,
    budget: BudgetTracker,
    args: argparse.Namespace,
    allow_full_file_context: bool = True,
) -> list[RevisionResult]:
    """Revise a batch while retaining every block that already validates.

    The validator retains every good block. Structural retries use compact local context so a single failed block does not resend a 100k-character scene map. Older versions discarded an otherwise good 48-block response when one line was
    too wide, then paid to regenerate all 48 blocks. Version 5.0 validates blocks
    independently and asks the model to regenerate only the failing subset.
    """
    feedback: str | None = None
    last_error: Exception | None = None
    pending = list(prepared)
    accepted: dict[int, RevisionResult] = {}

    for generation_attempt in range(1, args.generation_retries + 1):
        max_schema_lines = max(
            effective_limits(item.block, filename, args).max_lines
            for item in pending
        )
        include_full_context = allow_full_file_context and generation_attempt == 1
        prompt = build_batch_prompt(
            filename,
            all_blocks,
            pending,
            file_context,
            args.context_blocks,
            args,
            feedback,
            include_full_file_context=include_full_context,
        )
        if not include_full_context:
            print(
                "    compact retry context: omitted complete-file scene map; "
                "kept local sequence and reference guides",
                flush=True,
            )
        print(
            f"  revising blocks {pending[0].id}-{pending[-1].id} "
            f"({len(pending)} editable blocks), generation "
            f"{generation_attempt}/{args.generation_retries}",
            flush=True,
        )
        try:
            parsed = call_server(
                system_prompt,
                prompt,
                len(pending),
                max_schema_lines,
                budget,
                args,
            )
            by_id = response_lines_by_id(parsed, pending)
        except GatewayError:
            # Access, billing, rate-limit, provider, and transport failures are
            # independent of translation quality. Do not regenerate or split.
            raise
        except OutputTokenLimitError:
            # A second identical full-size generation would only repeat the cost.
            # Let revise_batch_recursive split the batch immediately.
            raise
        except ValidationError as exc:
            last_error = exc
            feedback = str(exc)[:1800]
            print(f"    batch validation failed: {feedback}", file=sys.stderr)
            continue

        next_pending: list[PreparedBlock] = []
        errors: list[str] = []
        accepted_this_round = 0
        for item in pending:
            try:
                result = validate_one_block_response(by_id[item.id], filename, item, args)
            except ValidationError as exc:
                next_pending.append(item)
                errors.append(str(exc))
            else:
                accepted[item.id] = result
                accepted_this_round += 1

        if not next_pending:
            return [accepted[item.id] for item in prepared]

        last_error = ValidationError("; ".join(errors))
        feedback = (
            "Only the following returned blocks failed validation. Regenerate only "
            "these requested IDs and obey every supplied line and width limit: "
            + "; ".join(errors)
        )[:1800]
        print(
            f"    accepted {accepted_this_round}/{len(pending)} blocks; "
            f"retrying only {len(next_pending)} invalid block(s): "
            + ", ".join(str(item.id) for item in next_pending),
            file=sys.stderr,
        )
        pending = next_pending

    accepted_results = [
        accepted[item.id] for item in prepared if item.id in accepted
    ]
    if accepted_results:
        raise PartialBatchValidationError(
            accepted_results,
            pending,
            f"Remaining blocks failed after regeneration attempts: {last_error}",
        )
    raise RuntimeError(f"Batch failed after regeneration attempts: {last_error}")


def revise_batch_recursive(
    filename: str,
    all_blocks: list[Block],
    prepared: list[PreparedBlock],
    file_context: str,
    system_prompt: str,
    budget: BudgetTracker,
    args: argparse.Namespace,
    allow_full_file_context: bool = True,
) -> tuple[list[RevisionResult], list[tuple[int, str]]]:
    try:
        return revise_batch_once(
            filename,
            all_blocks,
            prepared,
            file_context,
            system_prompt,
            budget,
            args,
            allow_full_file_context=allow_full_file_context,
        ), []
    except (GatewayError, KeyboardInterrupt):
        raise
    except PartialBatchValidationError as exc:
        accepted = list(exc.accepted_results)
        remaining = list(exc.pending)
        if len(remaining) == 1:
            return accepted, [(remaining[0].id, str(exc))]
        midpoint = len(remaining) // 2
        print(
            f"  splitting only the {len(remaining)} still-invalid blocks into "
            f"{midpoint} + {len(remaining) - midpoint}; "
            f"retaining {len(accepted)} accepted block(s)",
            file=sys.stderr,
        )
        left_results, left_failures = revise_batch_recursive(
            filename,
            all_blocks,
            remaining[:midpoint],
            file_context,
            system_prompt,
            budget,
            args,
            allow_full_file_context=False,
        )
        right_results, right_failures = revise_batch_recursive(
            filename,
            all_blocks,
            remaining[midpoint:],
            file_context,
            system_prompt,
            budget,
            args,
            allow_full_file_context=False,
        )
        order = {item.id: index for index, item in enumerate(prepared)}
        combined = accepted + left_results + right_results
        combined.sort(key=lambda result: order[result.block_id])
        return combined, left_failures + right_failures
    except Exception as exc:
        if len(prepared) == 1:
            return [], [(prepared[0].id, str(exc))]
        midpoint = len(prepared) // 2
        print(
            f"  splitting failed batch of {len(prepared)} blocks into "
            f"{midpoint} + {len(prepared) - midpoint}",
            file=sys.stderr,
        )
        left_results, left_failures = revise_batch_recursive(
            filename,
            all_blocks,
            prepared[:midpoint],
            file_context,
            system_prompt,
            budget,
            args,
            allow_full_file_context=False,
        )
        right_results, right_failures = revise_batch_recursive(
            filename,
            all_blocks,
            prepared[midpoint:],
            file_context,
            system_prompt,
            budget,
            args,
            allow_full_file_context=False,
        )
        return left_results + right_results, left_failures + right_failures

def runtime_code_sequence(lines: Iterable[str]) -> list[str]:
    """Return immutable runtime codes in true left-to-right order."""
    return [
        match.group(0)
        for line in lines
        for match in IMMUTABLE_CODE_RE.finditer(line)
    ]



def block_has_runtime_codes(block: Block) -> bool:
    """Return whether the target English contains immutable runtime codes."""
    return bool(runtime_code_sequence(block.english_lines))


def bare_name_runtime_code(token: str) -> bool:
    """Return whether a runtime token is a visible textual name variable."""
    return bool(
        re.fullmatch(
            r"<[A-Za-z][A-Za-z0-9_-]*>",
            token,
        )
    )


def block_has_sensitive_runtime_codes(block: Block) -> bool:
    """Return whether target codes require control-sensitive handling.

    Bare name variables are safe for deterministic line-break-only reflow.
    """
    return any(
        not bare_name_runtime_code(token)
        for token in runtime_code_sequence(
            block.english_lines
        )
    )


def normalized_reflow_words(lines: Iterable[str]) -> tuple[str, ...]:
    """Normalize only whitespace so deterministic line-break changes compare exactly."""
    return tuple(
        " ".join(
            line.strip()
            for line in lines
            if line.strip()
        ).split()
    )


def deterministic_safe_reflow(
    block: Block,
    filename: str,
    args: argparse.Namespace,
) -> list[str] | None:
    """Return a local lossless safe-layout repair, or None when AI/review is needed.

    This is deliberately limited to ordinary control-free dialogue with a valid
    runtime-code sequence. It changes whitespace/line breaks only.
    """
    if args.mode != "safe":
        return None
    if args.no_safe_local_reflow:
        return None
    if block.exact_line_count:
        return None
    if known_good_rule_for(filename, block) is not None:
        return None
    if block_has_sensitive_runtime_codes(block):
        return None
    if current_block_has_runtime_violation(block):
        return None

    limits = effective_limits(block, filename, args)
    current = list(block.english_lines)

    if not current_block_has_layout_violation(block, filename, args):
        return None

    proposed = auto_reflow_ordinary(
        current,
        limits.max_width,
        limits.max_lines,
        args.safe_page_lines,
        args.safe_page_visible_budget,
    )

    if normalized_reflow_words(current) != normalized_reflow_words(proposed):
        return None
    if len(proposed) > limits.max_lines:
        return None
    if any(
        max_raw_render_width(line) > limits.max_width
        for line in proposed
    ):
        return None
    if not ordinary_page_budget_ok(
        proposed,
        args.safe_page_lines,
        args.safe_page_visible_budget,
    ):
        return None
    if runtime_code_sequence(current) != runtime_code_sequence(proposed):
        return None

    validate_cp932(proposed)

    if proposed == current:
        return None
    return proposed


def current_block_has_runtime_violation(block: Block) -> bool:
    if not block.translated:
        return False
    return runtime_code_sequence(block.japanese_lines) != runtime_code_sequence(
        block.english_lines
    )


def current_block_has_long_line(
    block: Block,
    filename: str,
    args: argparse.Namespace,
) -> bool:
    limit = effective_limits(block, filename, args).max_width
    return any(max_raw_render_width(line) > limit for line in block.english_lines)


def current_block_has_layout_violation(
    block: Block,
    filename: str,
    args: argparse.Namespace,
) -> bool:
    """Return whether the current English violates the active mode's hard layout."""
    limits = effective_limits(block, filename, args)
    if block.exact_line_count:
        if len(block.english_lines) != len(block.japanese_indices):
            return True
    elif len(block.english_lines) > limits.max_lines:
        return True

    if any(
        max_raw_render_width(line) > limits.max_width
        for line in block.english_lines
    ):
        return True

    if (
        args.mode == "safe"
        and not block.exact_line_count
        and not block_has_sensitive_runtime_codes(block)
        and not ordinary_page_budget_ok(
            block.english_lines,
            args.safe_page_lines,
            args.safe_page_visible_budget,
        )
    ):
        return True

    return False

def make_batches(prepared: list[PreparedBlock], args: argparse.Namespace) -> list[list[PreparedBlock]]:
    batches: list[list[PreparedBlock]] = []
    current: list[PreparedBlock] = []
    current_chars = 0
    for item in prepared:
        block_chars = sum(map(len, item.protected_source + item.protected_draft))
        would_overflow = (
            current
            and (
                len(current) >= args.batch_blocks
                or current_chars + block_chars > args.batch_max_chars
            )
        )
        if would_overflow:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += block_chars
    if current:
        batches.append(current)
    return batches


def output_path_for(input_path: Path, input_root: Path, args: argparse.Namespace) -> Path:
    if args.in_place:
        return input_path
    try:
        relative = input_path.relative_to(input_root)
    except ValueError:
        relative = Path(input_path.name)
    return args.output_dir / relative


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"files": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"files": {}}
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return {"files": {}}
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def append_report(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def structural_signature(blocks: list[Block]) -> list[dict[str, Any]]:
    signature: list[dict[str, Any]] = []
    for block in blocks:
        signature.append(
            {
                "id": block.index,
                "kind": block.kind,
                "japanese": list(block.japanese_lines),
                "command": list(block.lines) if block.kind == "command" else [],
                "preceding_marker": block.preceding_marker,
            }
        )
    return signature


def verify_structure_and_locks(
    blocks: list[Block],
    baseline_signature: list[dict[str, Any]],
    locked_lines: dict[int, list[str]],
) -> None:
    if structural_signature(blocks) != baseline_signature:
        raise RuntimeError(
            "Internal safety check failed: Japanese source, command blocks, or block order changed."
        )
    for block_id, expected in locked_lines.items():
        if block_id >= len(blocks) or blocks[block_id].lines != expected:
            raise RuntimeError(
                f"Internal safety check failed: known-good locked block {block_id} changed."
            )


def write_checkpoint(path: Path, blocks: list[Block], trailing_newline: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(render_blocks(blocks, trailing_newline), encoding="utf-8", newline="\n")
    os.replace(temp, path)


def audit_files(files: list[Path], input_root: Path, args: argparse.Namespace) -> int:
    report_path = args.output_dir / f"{args.mode}_pass_layout_audit.csv"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    for path in files:
        blocks, _ = split_blocks(path.read_text(encoding="utf-8-sig"))
        for block in blocks:
            if not block.translated:
                continue

            limits = effective_limits(block, path.name, args)
            if block.exact_line_count:
                line_count_issue = (
                    len(block.english_lines)
                    != len(block.japanese_indices)
                )
            else:
                line_count_issue = (
                    len(block.english_lines)
                    > limits.max_lines
                )

            source_codes = runtime_code_sequence(block.japanese_lines)
            english_codes = runtime_code_sequence(block.english_lines)
            runtime_issue = source_codes != english_codes
            target_has_codes = block_has_runtime_codes(block)
            page_totals = ordinary_page_visible_totals(
                block.english_lines,
                args.safe_page_lines,
            )
            page_budget_issue = (
                args.mode == "safe"
                and not block.exact_line_count
                and not block_has_sensitive_runtime_codes(block)
                and any(
                    total > args.safe_page_visible_budget
                    for total in page_totals
                )
            )
            local_proposal = deterministic_safe_reflow(
                block,
                path.name,
                args,
            )

            deferred_reason = ""
            if limits.locked:
                deferred_reason = "locked_known_good"
            elif local_proposal is not None:
                deferred_reason = "deterministic_lossless_reflow"
            elif (
                args.mode == "safe"
                and target_has_codes
                and not args.safe_revise_runtime_code_blocks
                and (
                    line_count_issue
                    or page_budget_issue
                    or runtime_issue
                    or any(
                        max_raw_render_width(line)
                        > limits.max_width
                        for line in block.english_lines
                    )
                )
            ):
                deferred_reason = "target_runtime_codes_preserved"
            elif (
                args.mode == "safe"
                and (
                    line_count_issue
                    or page_budget_issue
                    or runtime_issue
                    or any(
                        max_raw_render_width(line)
                        > limits.max_width
                        for line in block.english_lines
                    )
                )
            ):
                deferred_reason = (
                    "unresolved_for_review"
                    if args.safe_deterministic_only
                    else "kimi_condensation_or_runtime_repair"
                )

            for line_no, line in enumerate(
                block.english_lines,
                start=1,
            ):
                segment_widths = raw_render_segment_widths(line)
                width = max(segment_widths, default=0)
                include_runtime = runtime_issue and line_no == 1

                if (
                    width > limits.max_width
                    or line_count_issue
                    or page_budget_issue
                    or limits.locked
                    or include_runtime
                ):
                    rows.append(
                        {
                            "file": str(path),
                            "block": block.index,
                            "line": line_no,
                            "width": width,
                            "width_limit": limits.max_width,
                            "render_segment_count":
                                len(segment_widths),
                            "render_segment_widths":
                                json.dumps(segment_widths),
                            "english_lines":
                                len(block.english_lines),
                            "line_limit":
                                limits.max_lines,
                            "page_visible_totals":
                                json.dumps(page_totals),
                            "page_visible_budget":
                                (
                                    args.safe_page_visible_budget
                                    if args.mode == "safe"
                                    else ""
                                ),
                            "page_budget_issue":
                                page_budget_issue,
                            "exact_line_count":
                                block.exact_line_count,
                            "known_good_locked":
                                limits.locked,
                            "strict_scene":
                                limits.strict,
                            "scene_label":
                                limits.label or "",
                            "target_has_runtime_codes":
                                target_has_codes,
                            "deterministic_reflow_possible":
                                local_proposal is not None,
                            "deterministic_reflow_lines":
                                json.dumps(
                                    local_proposal or [],
                                    ensure_ascii=False,
                                ),
                            "deterministic_reflow_widths":
                                json.dumps(
                                    [
                                        max_raw_render_width(value)
                                        for value in (
                                            local_proposal or []
                                        )
                                    ]
                                ),
                            "deterministic_reflow_page_totals":
                                json.dumps(
                                    ordinary_page_visible_totals(
                                        local_proposal or [],
                                        args.safe_page_lines,
                                    )
                                ),
                            "deferred_reason":
                                deferred_reason,
                            "source_runtime_sequence":
                                json.dumps(
                                    source_codes,
                                    ensure_ascii=False,
                                ),
                            "english_runtime_sequence":
                                json.dumps(
                                    english_codes,
                                    ensure_ascii=False,
                                ),
                            "issue": "; ".join(
                                value
                                for value in (
                                    (
                                        "overlong"
                                        if width
                                        > limits.max_width
                                        else ""
                                    ),
                                    (
                                        "wrong_line_count"
                                        if line_count_issue
                                        else ""
                                    ),
                                    (
                                        "overfull_page"
                                        if page_budget_issue
                                        else ""
                                    ),
                                    (
                                        "runtime_code_order"
                                        if include_runtime
                                        else ""
                                    ),
                                    (
                                        "locked_known_good"
                                        if limits.locked
                                        else ""
                                    ),
                                    (
                                        "target_runtime_codes"
                                        if target_has_codes
                                        else ""
                                    ),
                                    (
                                        "deterministic_fixable"
                                        if local_proposal
                                        is not None
                                        else ""
                                    ),
                                )
                                if value
                            ),
                            "text": line,
                        }
                    )

    fieldnames = [
        "file",
        "block",
        "line",
        "width",
        "width_limit",
        "render_segment_count",
        "render_segment_widths",
        "english_lines",
        "line_limit",
        "page_visible_totals",
        "page_visible_budget",
        "page_budget_issue",
        "exact_line_count",
        "known_good_locked",
        "strict_scene",
        "scene_label",
        "target_has_runtime_codes",
        "deterministic_reflow_possible",
        "deterministic_reflow_lines",
        "deterministic_reflow_widths",
        "deterministic_reflow_page_totals",
        "deferred_reason",
        "source_runtime_sequence",
        "english_runtime_sequence",
        "issue",
        "text",
    ]

    with report_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        writer.writerows(rows)

    deterministic_rows = sum(
        bool(row["deterministic_reflow_possible"])
        for row in rows
    )
    print(
        f"Audit wrote {len(rows)} rows to {report_path}; "
        f"deterministic-fixable rows={deterministic_rows}"
    )
    return 0


def process_file(
    input_path: Path,
    input_root: Path,
    refs: ReferenceBundle,
    system_prompt: str,
    state: dict[str, Any],
    state_path: Path,
    report_path: Path,
    budget: BudgetTracker,
    args: argparse.Namespace,
) -> dict[str, int]:
    output_path = output_path_for(
        input_path,
        input_root,
        args,
    )
    state_key = str(input_path.resolve())
    file_state = state["files"].setdefault(
        state_key,
        {
            "processed": [],
            "failed": {},
        },
    )
    processed = {
        int(value)
        for value in file_state.get(
            "processed",
            [],
        )
    }

    source_path = input_path

    if args.resume and output_path.exists():
        source_path = output_path
        print(f"  resuming from {output_path}")
    elif not args.resume:
        processed.clear()
        file_state["processed"] = []
        file_state["failed"] = {}

    if args.in_place and not args.resume:
        backup = input_path.with_suffix(
            input_path.suffix
            + ".before_kimi_two_stage.bak"
        )
        if not backup.exists():
            shutil.copy2(
                input_path,
                backup,
            )
            print(f"  backup: {backup}")

    content = source_path.read_text(
        encoding="utf-8-sig"
    )
    blocks, trailing_newline = split_blocks(content)
    baseline_signature = structural_signature(blocks)
    locked_lines = {
        block.index: list(block.lines)
        for block in blocks
        if known_good_rule_for(
            input_path.name,
            block,
        )
        is not None
        and not args.revise_known_good_scenes
    }

    candidates: list[Block] = []
    locked_count = 0
    translated_count = 0
    local_reflowed = 0
    runtime_locked = 0
    deferred = 0
    local_changed = False

    for block in blocks:
        if not block.translated:
            continue

        translated_count += 1

        if block.index in processed:
            continue
        if (
            args.block is not None
            and block.index != args.block
        ):
            continue
        if (
            args.start_block is not None
            and block.index < args.start_block
        ):
            continue
        if (
            args.end_block is not None
            and block.index > args.end_block
        ):
            continue

        limits = effective_limits(
            block,
            input_path.name,
            args,
        )

        if limits.locked:
            locked_count += 1
            continue

        if (
            args.only_long_lines
            and not current_block_has_long_line(
                block,
                input_path.name,
                args,
            )
        ):
            continue

        if args.mode == "safe":
            layout_issue = (
                current_block_has_layout_violation(
                    block,
                    input_path.name,
                    args,
                )
            )
            runtime_issue = (
                current_block_has_runtime_violation(
                    block
                )
            )

            if not args.safe_all_blocks:
                if not (
                    layout_issue
                    or runtime_issue
                ):
                    continue

                if (
                    layout_issue
                    and not runtime_issue
                ):
                    local_proposal = (
                        deterministic_safe_reflow(
                            block,
                            input_path.name,
                            args,
                        )
                    )

                    if local_proposal is not None:
                        old_lines = list(
                            block.english_lines
                        )
                        block.replace_english(
                            local_proposal
                        )
                        processed.add(block.index)
                        file_state.setdefault(
                            "failed",
                            {},
                        ).pop(
                            str(block.index),
                            None,
                        )
                        local_reflowed += 1
                        local_changed = True

                        append_report(
                            report_path,
                            {
                                "file": str(input_path),
                                "block": block.index,
                                "speaker": block.speaker,
                                "method":
                                    "deterministic_lossless_reflow",
                                "exact_line_count":
                                    block.exact_line_count,
                                "strict_scene":
                                    limits.strict,
                                "scene_label":
                                    limits.label,
                                "max_lines":
                                    limits.max_lines,
                                "max_width":
                                    limits.max_width,
                                "old":
                                    old_lines,
                                "new":
                                    local_proposal,
                                "old_widths": [
                                    max_raw_render_width(line)
                                    for line in old_lines
                                ],
                                "new_widths": [
                                    max_raw_render_width(line)
                                    for line in local_proposal
                                ],
                                "changed": True,
                            },
                        )
                        continue

                if (
                    block_has_runtime_codes(block)
                    and not args.safe_revise_runtime_code_blocks
                ):
                    runtime_locked += 1
                    print(
                        f"  block {block.index} deferred: "
                        "target contains runtime codes",
                        file=sys.stderr,
                    )
                    continue

                if args.safe_deterministic_only:
                    deferred += 1
                    continue

            elif (
                block_has_runtime_codes(block)
                and not args.safe_revise_runtime_code_blocks
            ):
                runtime_locked += 1
                print(
                    f"  block {block.index} deferred: "
                    "target contains runtime codes",
                    file=sys.stderr,
                )
                continue

        candidates.append(block)

    # Kimi sees the deterministic safe repairs in its read-only scene map.
    file_context = build_file_context(
        blocks,
        args.file_context_max_chars,
    )
    prepared = [
        prepare_block(block)
        for block in candidates
    ]
    batches = make_batches(
        prepared,
        args,
    )

    stats = {
        "revised": 0,
        "local_reflowed": local_reflowed,
        "failed": 0,
        "locked": locked_count,
        "runtime_locked": runtime_locked,
        "deferred": deferred,
        "skipped": max(
            0,
            translated_count
            - len(candidates)
            - locked_count
            - local_reflowed
            - runtime_locked
            - deferred,
        ),
    }

    def update_state_metadata() -> None:
        file_state["processed"] = sorted(processed)
        file_state["reference_hashes"] = refs.hashes
        file_state["model"] = args.model
        file_state["mode"] = args.mode
        file_state["pipeline_version"] = "5.0"
        file_state["input_sha256"] = hashlib.sha256(
            input_path.read_bytes()
        ).hexdigest()

    # Preserve deterministic progress even when the first API request later fails.
    if local_changed:
        update_state_metadata()
        verify_structure_and_locks(
            blocks,
            baseline_signature,
            locked_lines,
        )
        write_checkpoint(
            output_path,
            blocks,
            trailing_newline,
        )
        save_state(
            state_path,
            state,
        )
        print(
            f"  deterministic checkpoint: "
            f"{output_path}"
        )

    if not candidates:
        update_state_metadata()
        verify_structure_and_locks(
            blocks,
            baseline_signature,
            locked_lines,
        )

        if (
            local_changed
            or not output_path.exists()
            or args.in_place
        ):
            write_checkpoint(
                output_path,
                blocks,
                trailing_newline,
            )

        save_state(
            state_path,
            state,
        )
        print(
            "  no API-eligible blocks; "
            f"local reflows={local_reflowed}; "
            f"runtime-code blocks preserved={runtime_locked}; "
            f"deferred={deferred}; "
            f"known-good locked={locked_count}"
        )
        return stats

    print(
        f"  API-eligible blocks ({args.mode}): "
        f"{len(candidates)}; "
        f"batches: {len(batches)}; "
        f"local reflows: {local_reflowed}; "
        f"runtime-code blocks preserved: "
        f"{runtime_locked}; "
        f"known-good blocks preserved: "
        f"{locked_count}; "
        f"file-context chars: "
        f"{len(file_context):,}"
    )

    for batch_no, batch in enumerate(
        batches,
        start=1,
    ):
        print(
            f"  batch {batch_no}/{len(batches)}"
        )
        old_by_id = {
            item.id: list(
                item.block.english_lines
            )
            for item in batch
        }
        results, failures = revise_batch_recursive(
            input_path.name,
            blocks,
            batch,
            file_context,
            system_prompt,
            budget,
            args,
        )

        for result in results:
            block = blocks[result.block_id]
            limits = effective_limits(
                block,
                input_path.name,
                args,
            )
            old_lines = old_by_id[
                result.block_id
            ]
            block.replace_english(
                result.restored_lines
            )
            processed.add(
                result.block_id
            )
            file_state.setdefault(
                "failed",
                {},
            ).pop(
                str(result.block_id),
                None,
            )
            stats["revised"] += 1

            append_report(
                report_path,
                {
                    "file": str(input_path),
                    "block": result.block_id,
                    "speaker": block.speaker,
                    "method": "kimi_revision",
                    "exact_line_count":
                        block.exact_line_count,
                    "strict_scene":
                        limits.strict,
                    "scene_label":
                        limits.label,
                    "max_lines":
                        limits.max_lines,
                    "max_width":
                        limits.max_width,
                    "old":
                        old_lines,
                    "new":
                        result.restored_lines,
                    "old_widths": [
                        max_raw_render_width(line)
                        for line in old_lines
                    ],
                    "new_widths": [
                        max_raw_render_width(line)
                        for line in (
                            result.restored_lines
                        )
                    ],
                    "old_render_segment_widths": [
                        raw_render_segment_widths(line)
                        for line in old_lines
                    ],
                    "new_render_segment_widths": [
                        raw_render_segment_widths(line)
                        for line in (
                            result.restored_lines
                        )
                    ],
                    "old_page_visible_totals":
                        ordinary_page_visible_totals(
                            old_lines,
                            args.safe_page_lines,
                        ),
                    "new_page_visible_totals":
                        ordinary_page_visible_totals(
                            result.restored_lines,
                            args.safe_page_lines,
                        ),
                    "page_visible_budget":
                        (
                            args.safe_page_visible_budget
                            if args.mode == "safe"
                            else None
                        ),
                    "changed":
                        old_lines
                        != result.restored_lines,
                },
            )

        for block_id, error in failures:
            file_state.setdefault(
                "failed",
                {},
            )[str(block_id)] = error
            stats["failed"] += 1
            print(
                f"  block {block_id} FAILED "
                f"and was left unchanged: "
                f"{error}",
                file=sys.stderr,
            )

        update_state_metadata()
        verify_structure_and_locks(
            blocks,
            baseline_signature,
            locked_lines,
        )
        write_checkpoint(
            output_path,
            blocks,
            trailing_newline,
        )
        save_state(
            state_path,
            state,
        )
        print(
            f"  checkpoint: {output_path}"
        )

        if failures and args.fail_fast:
            raise RuntimeError(
                f"Batch contained "
                f"{len(failures)} failed block(s)"
            )

    return stats


def discover_files(args: argparse.Namespace) -> tuple[list[Path], Path]:
    if args.file:
        path = args.file.expanduser().resolve()
        return [path], path.parent

    if args.input_dir is not None:
        input_root = args.input_dir.expanduser().resolve()
        roots = [input_root]
    elif args.mode == "safe":
        input_root = args.root / "second_pass_quality_output"
        roots = [input_root]
    else:
        input_root = args.root
        scenario_txt_en = args.root / "ps2" / "PyTOD2" / "TXT_EN"
        skit_txt_en = args.root / "ps2" / "PyTOD2" / "FILE" / "pak1" / "TXT_EN"
        translated = args.root / "translated_output"

        if args.scenarios_only:
            roots = [scenario_txt_en] if scenario_txt_en.is_dir() else [translated / "ps2" / "scenarios"]
        elif args.skits_only:
            roots = [skit_txt_en] if skit_txt_en.is_dir() else [translated / "ps2" / "skits"]
        elif scenario_txt_en.is_dir() or skit_txt_en.is_dir():
            roots = [root for root in (scenario_txt_en, skit_txt_en) if root.is_dir()]
        elif translated.is_dir():
            roots = [translated / "ps2" / "scenarios", translated / "ps2" / "skits"]
        else:
            roots = [args.root]

    files = sorted(
        path
        for root in roots
        if root.exists()
        for path in root.rglob("*.sced.txt")
        if path.is_file()
    )
    if args.max_files is not None:
        files = files[:args.max_files]
    return files, input_root

def estimate_files(
    files: list[Path],
    refs: ReferenceBundle,
    system_prompt: str,
    args: argparse.Namespace,
) -> int:
    dummy_budget = BudgetTracker(
        path=(
            args.output_dir
            / ".unused_estimate.json"
        ),
        max_cost_usd=Decimal("0"),
        input_price_per_million=
            args.input_price,
        output_price_per_million=
            args.output_price,
        cache_read_price_per_million=
            args.cache_read_price,
    )
    total_prompt = 0
    total_output = 0
    total_batches = 0
    total_blocks = 0
    locked = 0
    deterministic_fixable = 0
    runtime_locked = 0
    deferred = 0

    for path in files:
        blocks, _ = split_blocks(
            path.read_text(
                encoding="utf-8-sig"
            )
        )
        file_context = build_file_context(
            blocks,
            args.file_context_max_chars,
        )
        candidates: list[Block] = []

        for block in blocks:
            if not block.translated:
                continue

            limits = effective_limits(
                block,
                path.name,
                args,
            )

            if limits.locked:
                locked += 1
                continue
            if (
                args.block is not None
                and block.index != args.block
            ):
                continue
            if (
                args.start_block is not None
                and block.index < args.start_block
            ):
                continue
            if (
                args.end_block is not None
                and block.index > args.end_block
            ):
                continue
            if (
                args.only_long_lines
                and not current_block_has_long_line(
                    block,
                    path.name,
                    args,
                )
            ):
                continue

            if args.mode == "safe":
                layout_issue = (
                    current_block_has_layout_violation(
                        block,
                        path.name,
                        args,
                    )
                )
                runtime_issue = (
                    current_block_has_runtime_violation(
                        block
                    )
                )

                if not args.safe_all_blocks:
                    if not (
                        layout_issue
                        or runtime_issue
                    ):
                        continue

                    if (
                        layout_issue
                        and not runtime_issue
                        and deterministic_safe_reflow(
                            block,
                            path.name,
                            args,
                        )
                        is not None
                    ):
                        deterministic_fixable += 1
                        continue

                    if (
                        block_has_runtime_codes(block)
                        and not args.safe_revise_runtime_code_blocks
                    ):
                        runtime_locked += 1
                        continue

                    if args.safe_deterministic_only:
                        deferred += 1
                        continue

                elif (
                    block_has_runtime_codes(block)
                    and not args.safe_revise_runtime_code_blocks
                ):
                    runtime_locked += 1
                    continue

            candidates.append(block)

        prepared = [
            prepare_block(block)
            for block in candidates
        ]

        for batch in make_batches(
            prepared,
            args,
        ):
            prompt = build_batch_prompt(
                path.name,
                blocks,
                batch,
                file_context,
                args.context_blocks,
                args,
            )
            total_prompt += max(
                1,
                (
                    len(system_prompt)
                    + len(prompt)
                    + 2
                )
                // 3,
            )
            total_output += max(
                256,
                len(batch)
                * args.estimated_output_tokens_per_block,
            )
            total_batches += 1
            total_blocks += len(batch)

    estimated = dummy_budget.estimate_cost(
        total_prompt,
        total_output,
        0,
    )

    print(f"Files: {len(files):,}")
    print(
        f"Deterministic lossless reflows: "
        f"{deterministic_fixable:,}"
    )
    print(
        f"Runtime-code target blocks preserved: "
        f"{runtime_locked:,}"
    )
    print(
        f"Unresolved blocks deferred: "
        f"{deferred:,}"
    )
    print(
        f"API-editable blocks: "
        f"{total_blocks:,}"
    )
    print(
        f"Known-good blocks preserved: "
        f"{locked:,}"
    )
    print(
        f"Estimated API requests: "
        f"{total_batches:,}"
    )
    print(
        "Estimated input tokens "
        f"(uncached): {total_prompt:,}"
    )
    print(
        f"Estimated output tokens: "
        f"{total_output:,}"
    )
    print(
        "Conservative estimated cost "
        f"before caching: ${estimated:.2f}"
    )

    if args.safe_deterministic_only:
        print(
            "Deterministic-only mode makes no "
            "API requests."
        )
    else:
        print(
            "Actual cost may be lower when the "
            "repeated prompt prefix is served "
            "from cache."
        )

    return 0


def test_api(args: argparse.Namespace) -> int:
    """Verify authentication, catalog visibility, and actual generation access."""
    api_key = args.api_key or os.getenv("AI_GATEWAY_API_KEY", "") or os.getenv("VERCEL_AI_GATEWAY_API_KEY", "")
    if not api_key:
        print("AI_GATEWAY_API_KEY is not set.", file=sys.stderr)
        return 2

    endpoint = normalize_endpoint(args.endpoint)
    models_url = endpoint.rsplit("/chat/completions", 1)[0] + "/models"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "TOD2-Kimi-Two-Stage/4.5",
    }

    request = urllib.request.Request(models_url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=min(args.timeout, 120)) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:4000]
        print(model_access_hint(exc.code, body), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"API catalog test failed: {exc}", file=sys.stderr)
        return 1

    models = result.get("data") if isinstance(result, dict) else None
    ids = {
        str(item.get("id"))
        for item in models or []
        if isinstance(item, dict) and item.get("id")
    }
    print(f"AI Gateway authentication succeeded; models returned: {len(ids):,}")
    if args.model not in ids:
        print(f"Model not found in returned catalog: {args.model}", file=sys.stderr)
        return 1
    print(f"Model listed in catalog: {args.model}")

    # Catalog visibility does not guarantee that the current account tier can invoke
    # the model. Make a tiny real request so --test-api catches RestrictedModelsError.
    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": "Reply with exactly OK."}],
        "temperature": 0,
        "max_tokens": 256,
        "stream": False,
    }
    probe_provider_options: dict[str, Any] = {}
    if args.providers:
        probe_provider_options["gateway"] = {
            "only": [value.strip() for value in args.providers.split(",") if value.strip()]
        }
    if args.thinking != "auto":
        probe_thinking: dict[str, Any] = {"type": args.thinking}
        if args.thinking == "enabled":
            probe_thinking["budgetTokens"] = args.thinking_budget_tokens
        probe_provider_options["moonshotai"] = {
            "thinking": probe_thinking,
            "reasoningHistory": "disabled",
        }
    if probe_provider_options:
        payload["providerOptions"] = probe_provider_options
    generation_request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            generation_request,
            timeout=min(args.timeout, 180),
        ) as response:
            generation_result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:4000]
        print(model_access_hint(exc.code, body), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Model generation test failed: {exc}", file=sys.stderr)
        return 1

    try:
        content, _reasoning, finish_reason = extract_response_text(generation_result)
    except Exception as exc:
        print(f"Model returned an unexpected test response: {exc}", file=sys.stderr)
        return 1
    if not content.strip():
        # A valid HTTP 200 Chat Completions response already proves generation access.
        # Reasoning models may spend a small probe budget on internal reasoning and
        # reach finish_reason='length' before emitting visible message.content.
        print(f"Model generation access succeeded: {args.model}")
        if _reasoning.strip():
            print(
                "Test request returned reasoning but no visible answer; "
                f"finish_reason={finish_reason!r}. Access is confirmed."
            )
        else:
            print(
                "Test request returned no visible answer; "
                f"finish_reason={finish_reason!r}. Access is confirmed by the valid response."
            )
        print("Run the one-file translation test to verify full structured-output behavior.")
        return 0

    print(f"Model generation access succeeded: {args.model}")
    print("Test response: " + content.strip()[:80])
    return 0


def metadata_paths_for(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    if args.mode == "quality":
        return (
            args.output_dir / ".second_pass_quality_progress.json",
            args.output_dir / "second_pass_quality_changes.jsonl",
            args.output_dir / "second_pass_quality_usage.json",
        )
    return (
        args.output_dir / ".third_pass_safe_progress.json",
        args.output_dir / "third_pass_safe_changes.jsonl",
        args.output_dir / "third_pass_safe_usage.json",
    )


def backup_metadata_files(
    paths: Iterable[Path],
    output_dir: Path,
    label: str,
) -> Path | None:
    existing = [path for path in paths if path.is_file()]
    if not existing:
        return None
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = output_dir / "_progress_backups" / f"{stamp}_{label}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for path in existing:
        shutil.copy2(path, backup_dir / path.name)
    return backup_dir


def existing_output_paths(
    files: list[Path],
    input_root: Path,
    args: argparse.Namespace,
) -> list[Path]:
    return [
        output_path
        for input_path in files
        if (output_path := output_path_for(input_path, input_root, args)).is_file()
    ]


def recover_progress_from_outputs(
    files: list[Path],
    input_root: Path,
    refs: ReferenceBundle,
    state: dict[str, Any],
    state_path: Path,
    args: argparse.Namespace,
    *,
    reason: str,
) -> dict[str, Any]:
    """Conservatively reconstruct processed IDs by comparing output to input.

    A block is marked processed only when its current output English differs from
    the original input English. Accepted-but-unchanged blocks and previously
    failed blocks are intentionally left eligible, because they cannot be
    distinguished after the old progress/change log has been lost.
    """
    if args.in_place:
        raise RuntimeError(
            "Progress recovery requires separate input and output trees; "
            "--in-place cannot be recovered by comparison."
        )

    state.setdefault("files", {})
    totals = {
        "reason": reason,
        "files_considered": len(files),
        "outputs_found": 0,
        "files_recovered": 0,
        "files_structurally_mismatched": 0,
        "blocks_marked_processed": 0,
        "blocks_already_processed": 0,
        "unchanged_blocks_left_eligible": 0,
        "unreadable_files": 0,
        "details": [],
    }

    for input_path in files:
        output_path = output_path_for(input_path, input_root, args)
        if not output_path.is_file():
            continue
        totals["outputs_found"] += 1

        detail: dict[str, Any] = {
            "input": str(input_path),
            "output": str(output_path),
            "marked_processed": [],
            "already_processed": [],
            "left_eligible": [],
            "status": "ok",
        }

        try:
            input_blocks, _ = split_blocks(
                input_path.read_text(encoding="utf-8-sig")
            )
            output_blocks, _ = split_blocks(
                output_path.read_text(encoding="utf-8-sig")
            )
        except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
            detail["status"] = "unreadable"
            detail["error"] = str(exc)
            totals["unreadable_files"] += 1
            totals["details"].append(detail)
            continue

        if structural_signature(input_blocks) != structural_signature(output_blocks):
            detail["status"] = "structural_mismatch"
            totals["files_structurally_mismatched"] += 1
            totals["details"].append(detail)
            continue

        state_key = str(input_path.resolve())
        file_state = state["files"].setdefault(
            state_key,
            {"processed": [], "failed": {}},
        )
        processed = {int(value) for value in file_state.get("processed", [])}
        failed = file_state.setdefault("failed", {})

        for input_block, output_block in zip(input_blocks, output_blocks):
            if not input_block.translated:
                continue
            limits = effective_limits(input_block, input_path.name, args)
            if limits.locked:
                continue

            block_id = input_block.index
            if block_id in processed:
                detail["already_processed"].append(block_id)
                totals["blocks_already_processed"] += 1
                continue

            # A structurally intact translated output with different English is
            # strong evidence that this block was successfully checkpointed.
            if (
                output_block.translated
                and output_block.english_lines != input_block.english_lines
            ):
                processed.add(block_id)
                failed.pop(str(block_id), None)
                detail["marked_processed"].append(block_id)
                totals["blocks_marked_processed"] += 1
            else:
                detail["left_eligible"].append(block_id)
                totals["unchanged_blocks_left_eligible"] += 1

        file_state["processed"] = sorted(processed)
        file_state["reference_hashes"] = refs.hashes
        file_state["model"] = args.model
        file_state["mode"] = args.mode
        file_state["input_sha256"] = hashlib.sha256(
            input_path.read_bytes()
        ).hexdigest()
        file_state["recovered_from_output"] = True
        totals["files_recovered"] += 1
        totals["details"].append(detail)

    state["last_progress_recovery"] = {
        key: value for key, value in totals.items() if key != "details"
    }
    save_state(state_path, state)

    report_path = args.output_dir / f"{args.mode}_progress_recovery_report.json"
    temp = report_path.with_suffix(report_path.suffix + ".tmp")
    temp.write_text(
        json.dumps(totals, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temp, report_path)

    print("Progress recovery complete:")
    print(f"  outputs found: {totals['outputs_found']}")
    print(f"  files recovered: {totals['files_recovered']}")
    print(
        "  changed blocks marked processed: "
        f"{totals['blocks_marked_processed']}"
    )
    print(
        "  unchanged blocks left eligible for conservative retry: "
        f"{totals['unchanged_blocks_left_eligible']}"
    )
    if totals["files_structurally_mismatched"]:
        print(
            "  WARNING: structurally mismatched files skipped: "
            f"{totals['files_structurally_mismatched']}",
            file=sys.stderr,
        )
    if totals["unreadable_files"]:
        print(
            "  WARNING: unreadable files skipped: "
            f"{totals['unreadable_files']}",
            file=sys.stderr,
        )
    print(f"  state: {state_path}")
    print(f"  report: {report_path}")
    return totals


def build_parser() -> argparse.ArgumentParser:
    script_root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--file", type=Path, help="process one .sced.txt file")
    scope.add_argument("--scenarios-only", action="store_true")
    scope.add_argument("--skits-only", action="store_true")

    parser.add_argument(
        "--mode",
        choices=("quality", "safe"),
        default="quality",
        help=(
            "quality = unrestricted second-pass localization; "
            "safe = targeted third-pass PS2 layout/runtime repair"
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=script_root,
        help="project root containing glossary.txt, code_glossary.txt, and character_voice_guide.txt",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        help="input tree; for the tested current build use ps2/PyTOD2/TXT_EN",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="output tree; defaults to ROOT/second_pass_quality_output or ROOT/third_pass_safe_output",
    )
    parser.add_argument("--in-place", action="store_true", help="overwrite inputs after creating a backup")
    run_control = parser.add_mutually_exclusive_group()
    run_control.add_argument(
        "--resume",
        action="store_true",
        help=(
            "force resume mode; Version 5.0 also auto-resumes whenever existing "
            "progress or output files are detected"
        ),
    )
    run_control.add_argument(
        "--restart",
        action="store_true",
        help=(
            "explicitly reset progress/change/usage metadata and restart from the "
            "input tree; existing metadata is backed up first"
        ),
    )
    parser.add_argument(
        "--recover-progress",
        action="store_true",
        help=(
            "rebuild conservative progress from existing output files without API "
            "calls; changed blocks are marked processed and unchanged blocks remain "
            "eligible for safe retry"
        ),
    )
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--audit-only", action="store_true", help="write visual-layout and protected-scene audit CSV without API calls")
    parser.add_argument("--estimate-only", action="store_true", help="estimate token use and cost without API calls")
    parser.add_argument("--dry-run", action="store_true", help="alias for --estimate-only")
    parser.add_argument("--test-api", action="store_true", help="verify the key and model catalog, then exit")
    parser.add_argument("--only-long-lines", action="store_true", help="legacy filter: revise only blocks over the active width limit")
    parser.add_argument("--block", type=int, help="process only one divider-block index")
    parser.add_argument("--start-block", type=int)
    parser.add_argument("--end-block", type=int)
    parser.add_argument("--max-files", type=int)

    parser.add_argument(
        "--revise-known-good-scenes",
        action="store_true",
        help="allow revision of fixed crash/layout ranges; each record's tested per-rule limits remain enforced",
    )
    parser.add_argument(
        "--allow-line-expansion",
        action="store_true",
        help=(
            "deprecated compatibility option; safe ordinary dialogue already "
            "reflows up to the verified five-line limit"
        ),
    )
    parser.add_argument(
        "--line-expansion",
        type=int,
        default=1,
        help="deprecated compatibility option; retained so older commands still run",
    )

    parser.add_argument("--batch-blocks", type=int, default=48, help="maximum editable blocks per Kimi request")
    parser.add_argument("--batch-max-chars", type=int, default=60000, help="maximum JP+draft characters per request")
    parser.add_argument("--context-blocks", type=int, default=8, help="exact neighboring blocks supplied around each batch")
    parser.add_argument(
        "--file-context-max-chars",
        type=int,
        default=120000,
        help="maximum complete-file scene-context characters per request",
    )
    parser.add_argument(
        "--quality-max-line-width",
        type=int,
        default=80,
        help="quality-mode sanity ceiling per visible line; default 80",
    )
    parser.add_argument(
        "--quality-max-lines",
        type=int,
        default=4,
        help="quality-mode maximum English lines for ordinary dialogue; default 4",
    )
    parser.add_argument(
        "--safe-max-line-width",
        type=int,
        default=36,
        help="safe-mode visible width; values above 36 require --allow-unsafe-width",
    )
    parser.add_argument(
        "--safe-max-lines",
        type=int,
        default=5,
        help="safe-mode ordinary line limit; default 5 (verified ordinary textbox paging)",
    )
    parser.add_argument(
        "--safe-page-lines",
        type=int,
        default=4,
        help="ordinary rows displayed before advancing; default 4",
    )
    parser.add_argument(
        "--safe-page-visible-budget",
        type=int,
        default=126,
        help=(
            "maximum combined visible characters across one ordinary four-row "
            "page; default 126 from PCSX2 evidence"
        ),
    )
    parser.add_argument(
        "--safe-all-blocks",
        action="store_true",
        help="in safe mode, revise all unlocked blocks instead of only unresolved layout/runtime violations",
    )
    parser.add_argument(
        "--no-safe-local-reflow",
        action="store_true",
        help="disable deterministic control-free lossless reflow before Kimi",
    )
    parser.add_argument(
        "--safe-deterministic-only",
        action="store_true",
        help=(
            "safe mode only: apply deterministic lossless reflow, write/audit the "
            "remaining unresolved blocks, and make no API requests"
        ),
    )
    parser.add_argument(
        "--safe-revise-runtime-code-blocks",
        action="store_true",
        help=(
            "allow Kimi to revise target blocks containing runtime codes; disabled "
            "by default because these blocks require separate control-sensitive audit"
        ),
    )
    parser.add_argument(
        "--allow-unsafe-lines",
        action="store_true",
        help="allow safe mode to exceed the verified five-line ordinary-dialogue limit",
    )
    parser.add_argument(
        "--max-line-width",
        type=int,
        default=None,
        help="legacy override for the active mode's width",
    )
    parser.add_argument(
        "--allow-unsafe-width",
        action="store_true",
        help="allow safe mode to exceed the recommended 36-column limit",
    )

    parser.add_argument(
        "--endpoint",
        default=os.getenv("AI_GATEWAY_ENDPOINT", VERCEL_BASE_URL),
        help="Vercel AI Gateway API base URL, not the dashboard URL",
    )
    parser.add_argument("--model", default=os.getenv("AI_GATEWAY_MODEL", DEFAULT_MODEL))
    parser.add_argument(
        "--api-key",
        default="",
        help="optional; prefer the AI_GATEWAY_API_KEY environment variable",
    )
    parser.add_argument("--timeout", type=int, default=int(os.getenv("AI_GATEWAY_TIMEOUT", "900")))
    parser.add_argument("--network-retries", type=int, default=int(os.getenv("AI_GATEWAY_NETWORK_RETRIES", "5")))
    parser.add_argument("--generation-retries", type=int, default=int(os.getenv("AI_GATEWAY_GENERATION_RETRIES", "3")))
    parser.add_argument("--retry-delay", type=float, default=float(os.getenv("AI_GATEWAY_RETRY_DELAY", "5")))
    parser.add_argument("--max-tokens", type=int, default=int(os.getenv("AI_GATEWAY_MAX_TOKENS", "32768")))
    parser.add_argument("--tokens-per-block", type=int, default=int(os.getenv("AI_GATEWAY_TOKENS_PER_BLOCK", "256")))
    parser.add_argument(
        "--thinking",
        choices=("disabled", "enabled", "auto"),
        default=os.getenv("AI_GATEWAY_THINKING", "disabled"),
        help=(
            "Kimi reasoning mode. Default disabled is recommended for structured "
            "translation; enabled uses --thinking-budget-tokens; auto leaves the "
            "provider default unchanged."
        ),
    )
    parser.add_argument(
        "--thinking-budget-tokens",
        type=int,
        default=int(os.getenv("AI_GATEWAY_THINKING_BUDGET_TOKENS", "4096")),
        help="reasoning-token cap when --thinking enabled; Moonshot minimum is 1024",
    )
    parser.add_argument(
        "--estimated-output-tokens-per-block",
        type=int,
        default=int(os.getenv("AI_GATEWAY_EST_OUTPUT_TOKENS_PER_BLOCK", "96")),
        help="used only by the pre-request spend guard and estimate mode",
    )
    parser.add_argument("--temperature", type=float, default=float(os.getenv("AI_GATEWAY_TEMPERATURE", "0.15")))
    parser.add_argument("--top-p", type=float, default=float(os.getenv("AI_GATEWAY_TOP_P", "0.90")))
    parser.add_argument(
        "--gateway-sort",
        choices=("cost", "latency", "throughput", "none"),
        default=os.getenv("AI_GATEWAY_SORT", "cost"),
        help="provider ranking behind Kimi K2.6",
    )
    parser.add_argument(
        "--providers",
        default=os.getenv("AI_GATEWAY_PROVIDERS", ""),
        help="optional comma-separated provider allowlist, e.g. baseten,fireworks,moonshotai,novita",
    )
    parser.add_argument("--no-gateway-cache", action="store_true", help="disable gateway automatic caching")
    parser.add_argument("--no-json-schema", action="store_true")
    parser.add_argument("--debug-response", action="store_true")

    parser.add_argument(
        "--max-cost-usd",
        type=Decimal,
        default=Decimal(os.getenv("AI_GATEWAY_MAX_COST_USD", "18.00")),
        help="local tracked-cost stop; 0 disables it",
    )
    parser.add_argument(
        "--input-price",
        type=Decimal,
        default=Decimal(os.getenv("AI_GATEWAY_INPUT_PRICE", "0.95")),
        help="USD per million uncached input tokens",
    )
    parser.add_argument(
        "--output-price",
        type=Decimal,
        default=Decimal(os.getenv("AI_GATEWAY_OUTPUT_PRICE", "4.00")),
        help="USD per million output tokens",
    )
    parser.add_argument(
        "--cache-read-price",
        type=Decimal,
        default=Decimal(os.getenv("AI_GATEWAY_CACHE_READ_PRICE", "0.16")),
        help="USD per million cached input tokens",
    )
    return parser

def main() -> int:
    args = build_parser().parse_args()
    args.root = args.root.expanduser().resolve()
    default_output_name = (
        "second_pass_quality_output"
        if args.mode == "quality"
        else "third_pass_safe_output"
    )
    args.output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir is not None
        else args.root / default_output_name
    )

    args.active_max_line_width = (
        args.max_line_width
        if args.max_line_width is not None
        else (
            args.quality_max_line_width
            if args.mode == "quality"
            else args.safe_max_line_width
        )
    )

    if args.batch_blocks < 1 or args.batch_max_chars < 1000:
        print("Batch settings are invalid.", file=sys.stderr)
        return 2
    if args.quality_max_lines < 1 or args.safe_max_lines < 1:
        print("Line-count limits must be at least 1.", file=sys.stderr)
        return 2
    if args.safe_page_lines < 1:
        print("--safe-page-lines must be at least 1.", file=sys.stderr)
        return 2
    if args.safe_page_visible_budget < 40:
        print("--safe-page-visible-budget is unrealistically small.", file=sys.stderr)
        return 2
    if args.active_max_line_width < 20:
        print("The active line-width limit is unrealistically small.", file=sys.stderr)
        return 2
    if (
        args.mode == "safe"
        and args.active_max_line_width > 36
        and not args.allow_unsafe_width
    ):
        print(
            f"Safe mode requested width {args.active_max_line_width}, above the "
            "recommended PS2 limit. Capping it to 36. Use --allow-unsafe-width "
            "only for controlled experiments.",
            file=sys.stderr,
        )
        args.active_max_line_width = 36
    if args.mode != "safe" and (
        args.safe_deterministic_only
        or args.safe_revise_runtime_code_blocks
        or args.no_safe_local_reflow
        or args.allow_unsafe_lines
    ):
        print(
            "Safe-only options require --mode safe.",
            file=sys.stderr,
        )
        return 2
    if args.safe_deterministic_only and args.safe_all_blocks:
        print(
            "--safe-deterministic-only cannot be combined with --safe-all-blocks.",
            file=sys.stderr,
        )
        return 2
    if (
        args.mode == "safe"
        and args.safe_max_lines > 5
        and not args.allow_unsafe_lines
    ):
        print(
            f"Safe mode requested {args.safe_max_lines} ordinary lines, above the "
            "verified limit. Capping it to 5. Use --allow-unsafe-lines only for "
            "controlled experiments.",
            file=sys.stderr,
        )
        args.safe_max_lines = 5
    if args.max_cost_usd < 0:
        print("--max-cost-usd cannot be negative.", file=sys.stderr)
        return 2
    if args.thinking == "enabled" and args.thinking_budget_tokens < 1024:
        print("--thinking-budget-tokens must be at least 1024.", file=sys.stderr)
        return 2
    if args.max_tokens < 1024:
        print("--max-tokens must be at least 1024.", file=sys.stderr)
        return 2

    if args.test_api:
        return test_api(args)

    files, input_root = discover_files(args)
    if not files:
        print("No .sced.txt files found.", file=sys.stderr)
        return 2

    if args.audit_only:
        return audit_files(files, input_root, args)

    refs = read_references(args.root)
    system_prompt = build_system_prompt(refs, args)

    if args.estimate_only or args.dry_run:
        return estimate_files(files, refs, system_prompt, args)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    state_path, report_path, usage_path = metadata_paths_for(args)
    output_files = existing_output_paths(files, input_root, args)
    metadata_exists = any(
        path.is_file() for path in (state_path, report_path, usage_path)
    )

    if args.restart:
        backup_dir = backup_metadata_files(
            (state_path, report_path, usage_path),
            args.output_dir,
            "before_explicit_restart",
        )
        if backup_dir is not None:
            print(f"Metadata backup before restart: {backup_dir}")
        for path in (state_path, report_path, usage_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        args.resume = False
        print(
            "Explicit restart requested: progress metadata was reset. "
            "Existing .sced output files remain until overwritten."
        )
    else:
        auto_resume = bool(args.resume or metadata_exists or output_files)
        if auto_resume and not args.resume:
            print(
                "Auto-resume enabled: existing progress or output files were "
                "detected. Use --restart for an intentional reset."
            )
        args.resume = auto_resume

    state = load_state(state_path) if args.resume else {"files": {}}

    # Recover missing progress metadata conservatively. This catches the exact
    # failure mode where an older version was run without --resume and deleted
    # its JSON/JSONL metadata while leaving the checkpointed output files intact.
    state_file_keys = set(state.get("files", {}))
    output_input_keys = {
        str(input_path.resolve())
        for input_path in files
        if output_path_for(input_path, input_root, args).is_file()
    }
    incomplete_state = bool(output_input_keys - state_file_keys)
    if args.recover_progress or (args.resume and output_files and incomplete_state):
        backup_dir = backup_metadata_files(
            (state_path, report_path, usage_path),
            args.output_dir,
            "before_progress_recovery",
        )
        if backup_dir is not None:
            print(f"Metadata backup before recovery: {backup_dir}")
        reason = (
            "explicit --recover-progress"
            if args.recover_progress
            else "automatic recovery of incomplete progress metadata"
        )
        recover_progress_from_outputs(
            files,
            input_root,
            refs,
            state,
            state_path,
            args,
            reason=reason,
        )
        if args.recover_progress:
            print("No API requests were made.")
            return 0

    budget = BudgetTracker.load(
        usage_path,
        args.max_cost_usd,
        args.input_price,
        args.output_price,
        args.cache_read_price,
        args.resume,
    )

    print(f"Endpoint: {normalize_endpoint(args.endpoint)}")
    print(f"Mode: {args.mode}")
    print(f"Model: {args.model}")
    print(f"Project root: {args.root}")
    print(f"Input root: {input_root}")
    print(f"Output: {args.output_dir}")
    print(
        "Progress policy: "
        + (
            "explicit restart"
            if args.restart
            else ("resume/auto-resume" if args.resume else "new output")
        )
    )
    print(
        f"Files: {len(files)}; batch blocks: {args.batch_blocks}; "
        f"batch chars: {args.batch_max_chars:,}; file context: {args.file_context_max_chars:,}"
    )
    print(
        f"Spend guard: ${args.max_cost_usd:.2f}; tracked: ${budget.estimated_cost_usd:.4f}; "
        f"provider sort: {args.gateway_sort}; cache: {'off' if args.no_gateway_cache else 'auto'}"
    )
    thinking_text = args.thinking
    if args.thinking == "enabled":
        thinking_text += f" ({args.thinking_budget_tokens:,}-token budget)"
    print(
        f"Kimi thinking: {thinking_text}; max completion: {args.max_tokens:,}; "
        f"tokens per block: {args.tokens_per_block}"
    )
    if args.mode == "quality":
        print(
            f"Quality limits: {args.active_max_line_width} columns per rendered segment, "
            f"{args.quality_max_lines} ordinary English lines. "
            "This output is experimental and not guaranteed console-safe."
        )
    else:
        selection = (
            "all unlocked blocks"
            if args.safe_all_blocks
            else (
                "deterministic lossless reflow only"
                if args.safe_deterministic_only
                else "local lossless reflow, then unresolved layout/runtime cases"
            )
        )
        print(
            f"Safe limits: {args.active_max_line_width} columns per rendered segment, at most "
            f"{args.safe_max_lines} ordinary English lines independent of Japanese "
            f"source-line count, and {args.safe_page_visible_budget} visible characters "
            f"per {args.safe_page_lines}-row page; selection: {selection}."
        )
        print(
            "Target blocks containing runtime codes are "
            + (
                "editable by explicit opt-in."
                if args.safe_revise_runtime_code_blocks
                else "preserved for separate control-sensitive audit."
            )
        )
    print(
        "Known-good tested ranges and source-signature records are preserved. "
        "Use --revise-known-good-scenes only for intentional retesting."
        if not args.revise_known_good_scenes
        else "Known-good tested ranges are editable only within their stored per-rule limits."
    )
    print("Loaded reference files:")
    for filename, digest in refs.hashes.items():
        print(f"  {filename}: {digest[:16]}...")

    totals = {
        "revised": 0,
        "local_reflowed": 0,
        "failed": 0,
        "locked": 0,
        "runtime_locked": 0,
        "deferred": 0,
        "skipped": 0,
    }
    try:
        for file_no, path in enumerate(files, start=1):
            print(f"\n[{file_no}/{len(files)}] Processing {path}")
            result = process_file(
                path,
                input_root,
                refs,
                system_prompt,
                state,
                state_path,
                report_path,
                budget,
                args,
            )
            for key in totals:
                totals[key] += result[key]
    except FatalGatewayError as exc:
        print(f"\nFATAL AI GATEWAY ERROR: {exc}", file=sys.stderr)
        print("No further batches were attempted.", file=sys.stderr)
        return 3
    except GatewayError as exc:
        print(f"\nAI GATEWAY ERROR: {exc}", file=sys.stderr)
        print(
            "The run stopped without splitting the batch. Retry later with --resume "
            "after the gateway/provider issue is resolved.",
            file=sys.stderr,
        )
        return 4
    except KeyboardInterrupt:
        print(
            "\nInterrupted by user. Completed checkpoints remain available; use "
            "--resume to continue.",
            file=sys.stderr,
        )
        return 130

    print("\nSummary: " + ", ".join(f"{key}={value}" for key, value in totals.items()))
    print(f"Change log: {report_path}")
    print(f"Progress state: {state_path}")
    print(f"Usage: {usage_path}")
    print(
        f"Tracked usage: requests={budget.requests:,}; input={budget.prompt_tokens:,}; "
        f"output={budget.completion_tokens:,}; cached={budget.cached_tokens:,}; "
        f"estimated cost=${budget.estimated_cost_usd:.4f}; "
        f"remaining local allowance=${budget.remaining:.4f}"
    )
    return 1 if totals["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

