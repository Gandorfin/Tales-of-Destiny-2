#!/usr/bin/env python3
"""Tales of Destiny 2 PS2 skit JP->EN translator for llama.cpp llama-server.

Standard-library only. This is the skit-specific branch of translate_fixed_v10:
it keeps the proven divider parser, control-code protection, checkpointing, resume,
and JSON fallback behavior, but uses source-length-aware token and character limits
so legitimate long skit monologues are translated completely instead of rejected as
runaway output. It processes ps2/skits by default and writes Japanese-plus-English
blocks under translated_output/ps2/skits.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DIVIDER = "-----------------------"
JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff01-\uff65]")
SPEAKER_RE = re.compile(r"^#?\s*<([A-Za-z][A-Za-z0-9_-]*)>")
ANGLE_TAG_RE = re.compile(r"<[^>\r\n]+>")
CURLY_CODE_RE = re.compile(r"(?:\{[0-9A-Fa-f]{2,8}\})+")
PRINTF_RE = re.compile(r"%(?:\d+\$)?[-+ #0]*(?:\d+|\*)?(?:\.\d+|\.\*)?[hlLzjt]*[diuoxXfFeEgGaAcspn%]")
FORMAT_RE = re.compile(r"\{\d+(?::[^{}]+)?\}")
LITERAL_NEWLINE_RE = re.compile(r"\\n")
RUNAWAY_CHAR_RE = re.compile(r"([^\s])\1{47,}", re.DOTALL)
# Confirmed paired wrapper from code_glossary. Preserve the entire wrapped value.
PAIRED_0B_RE = re.compile(r"<0B:00000001>.*?<0B:00000000>")

COMMAND_PREFIXES = (
    "select", "exit-party", "notice", "wait_map", "effect", "effect_off",
    "set_parameter", "set_condition", "call_script", "wait", "select_party",
    "end", "change_scene", "show_title", "fade", "cutscene", "scene_start",
    "scene_end", "background", "music", "play_movie",
)

VOICE_ALIASES = {
    "Kyle": "Kyle Dunamis",
    "Loni": "Loni Dunamis",
    "Reala": "Reala",
    "Judas": "Judas",
    "Nanaly": "Nanaly Fletcher",
    "Harold": "Harold Berselius",
    "Barbatos": "Barbatos Goetia",
    "Elraine": "Elraine",
}


@dataclass
class Block:
    lines: list[str] = field(default_factory=list)
    kind: str = "command"
    japanese_indices: list[int] = field(default_factory=list)
    english_indices: list[int] = field(default_factory=list)
    speaker: str | None = None

    @property
    def needs_translation(self) -> bool:
        return bool(self.japanese_indices) and not self.english_indices

    @property
    def already_translated(self) -> bool:
        return bool(self.japanese_indices) and len(self.english_indices) >= len(self.japanese_indices)


class PlaceholderProtector:
    """Replace immutable script codes with unique placeholders for one source line.

    Leading and trailing codes can be restored deterministically even when a model
    omits them. Inline codes must still be returned by the model because their
    semantic position inside the translated sentence matters.
    """

    TOKEN_RE = re.compile(r"\[\[L\d+C\d+\]\]")

    def __init__(self, line_number: int) -> None:
        self.line_number = line_number
        self.saved: list[tuple[str, str]] = []
        self.protected_source = ""

    def _new_token(self, original: str) -> str:
        token = f"[[L{self.line_number}C{len(self.saved) + 1}]]"
        self.saved.append((token, original))
        return token

    def _replace_pattern(self, text: str, pattern: re.Pattern[str]) -> str:
        return pattern.sub(lambda m: self._new_token(m.group(0)), text)

    def _protect_non_japanese_0b_spans(self, text: str) -> str:
        """Protect a complete 0B span only when its body has no Japanese text.

        Some real choice lines wrap translatable Japanese inside the 0B pair.
        Hiding the entire span would reduce that source line to a bare placeholder
        and make the model return an empty translation. In that case the generic
        angle/curly-code passes protect only the immutable codes while leaving the
        Japanese visible for translation.
        """
        def repl(match: re.Match[str]) -> str:
            whole = match.group(0)
            inner = whole[len("<0B:00000001>"):-len("<0B:00000000>")]
            return whole if contains_japanese(inner) else self._new_token(whole)
        return PAIRED_0B_RE.sub(repl, text)

    def protect(self, text: str) -> str:
        text = self._protect_non_japanese_0b_spans(text)
        for pattern in (ANGLE_TAG_RE, CURLY_CODE_RE, LITERAL_NEWLINE_RE,
                        PRINTF_RE, FORMAT_RE):
            text = self._replace_pattern(text, pattern)
        self.protected_source = text
        return text

    def required_tokens(self) -> list[str]:
        return [token for token, _ in self.saved]

    def _edge_token_groups(self) -> tuple[list[str], list[str]]:
        """Return source-order leading and trailing placeholder groups."""
        leading: list[str] = []
        trailing: list[str] = []

        left = self.protected_source.lstrip()
        while True:
            match = self.TOKEN_RE.match(left)
            if not match:
                break
            leading.append(match.group(0))
            left = left[match.end():].lstrip()

        right = self.protected_source.rstrip()
        while True:
            matches = list(self.TOKEN_RE.finditer(right))
            if not matches or matches[-1].end() != len(right):
                break
            token = matches[-1].group(0)
            trailing.insert(0, token)
            right = right[:matches[-1].start()].rstrip()

        # A code-only line may classify the same token as both edges. Treat it as
        # leading so it is emitted exactly once.
        trailing = [token for token in trailing if token not in leading]
        return leading, trailing

    def _insert_missing_inline_tokens(self, text: str, missing: list[str]) -> str:
        """Reinsert omitted inline placeholders at source-relative positions.

        This is a last-resort structural repair after a targeted line retry has
        also omitted the code. It preserves token order and chooses the nearest
        whitespace/punctuation boundary in the English line instead of failing
        the entire scenario file.
        """
        source = self.protected_source
        visible_source = self.TOKEN_RE.sub("", source)
        denominator = max(1, len(visible_source))
        repairs: list[tuple[float, int, str]] = []

        for source_order, (token, _original) in enumerate(self.saved):
            if token not in missing:
                continue
            token_index = source.find(token)
            visible_before = self.TOKEN_RE.sub("", source[:token_index])
            ratio = len(visible_before) / denominator
            repairs.append((ratio, source_order, token))

        def boundary_positions(value: str) -> list[int]:
            positions = {0, len(value)}
            for match in re.finditer(r"\s+|[,.!?;:…—-]+", value):
                positions.add(match.start())
                positions.add(match.end())
            return sorted(positions)

        # Insert from right to left so earlier offsets remain valid. Source order
        # breaks ties and keeps adjacent codes in their original order.
        for ratio, source_order, token in sorted(
            repairs, key=lambda item: (item[0], item[1]), reverse=True
        ):
            target = round(len(text) * ratio)
            candidates = boundary_positions(text)
            position = min(candidates, key=lambda value: (abs(value - target), value))
            text = text[:position] + token + text[position:]
        return text

    def restore(self, text: str, *, repair_missing_inline: bool = False) -> str:
        leading, trailing = self._edge_token_groups()
        edge_tokens = set(leading + trailing)

        # Remove any edge tokens the model did return; rebuild those groups in
        # their exact source order. This also repairs omitted/moved choice and
        # speaker tags without guessing an inline semantic position.
        for token in edge_tokens:
            text = text.replace(token, "")
        text = text.strip()

        known_tokens = {saved for saved, _ in self.saved}
        unknown = [
            token for token in self.TOKEN_RE.findall(text)
            if token not in known_tokens
        ]
        if unknown:
            raise ValueError(f"unknown placeholders returned: {unknown}")

        # Collapse accidental duplicate inline placeholders to one occurrence.
        for token, _original in self.saved:
            if token in edge_tokens:
                continue
            count = text.count(token)
            if count > 1:
                first = text.find(token)
                text = text.replace(token, "")
                text = text[:first] + token + text[first:]

        missing_inline = [
            token for token, _ in self.saved
            if token not in edge_tokens and token not in text
        ]
        if missing_inline and repair_missing_inline:
            text = self._insert_missing_inline_tokens(text, missing_inline)
            missing_inline = [token for token in missing_inline if token not in text]
        if missing_inline:
            raise ValueError(
                "model dropped required inline placeholder(s) "
                + ", ".join(missing_inline)
            )

        originals = dict(self.saved)
        for token, original in self.saved:
            if token in text:
                text = text.replace(token, original)

        prefix = "".join(originals[token] for token in leading)
        suffix = "".join(originals[token] for token in trailing)
        return prefix + text + suffix


def contains_japanese(text: str) -> bool:
    return bool(JP_RE.search(text))


def is_command_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    return any(lowered.startswith(prefix) for prefix in COMMAND_PREFIXES)


def should_tag(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped == DIVIDER or stripped.startswith("#"):
        return False
    if is_command_line(stripped):
        return False
    # A standalone speaker/control tag is not dialogue, but a tag plus Japanese is.
    without_tags = ANGLE_TAG_RE.sub("", stripped)
    without_codes = CURLY_CODE_RE.sub("", without_tags)
    return contains_japanese(without_codes)


def tag_lines(lines: list[str]) -> list[str]:
    return [("#" + line if should_tag(line) else line) for line in lines]


def parse_voice_guide(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    voices: dict[str, str] = {}
    current_name: str | None = None
    note: list[str] = []

    def flush() -> None:
        nonlocal current_name, note
        if current_name:
            voices[current_name] = " ".join(x.strip() for x in note if x.strip())
        current_name, note = None, []

    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        # Voice guide headers are bare names, optionally followed by parenthetical text.
        if not line.startswith(("=", "#", "-")) and not line.endswith((".", ",", ";")):
            candidate = re.sub(r"\s*\(.*\)\s*$", "", line).strip()
            if candidate in set(VOICE_ALIASES.values()) or candidate in {"Reala", "Elraine"}:
                flush()
                current_name = candidate
                continue
        if current_name:
            note.append(raw)
    flush()
    return voices


def parse_glossary(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    glossary: dict[str, str] = {}
    # Accept entries like "JP (reading) -> EN" and ignore prose notes.
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if "->" not in line or line.startswith(("#", "-", "|")):
            continue
        left, right = line.split("->", 1)
        jp = re.sub(r"\s*\([^)]*\)\s*$", "", left).strip()
        en = right.strip()
        if jp and en and contains_japanese(jp):
            glossary[jp] = en
    return glossary


def classify_block(lines: list[str]) -> Block:
    lines = tag_lines(lines)
    jp_indices = [i for i, line in enumerate(lines) if line.lstrip().startswith("#") and contains_japanese(line)]
    if not jp_indices:
        return Block(lines=lines, kind="command")

    last_jp = max(jp_indices)
    # Existing translations are nonempty, non-Japanese lines after all JP source lines.
    en_indices = [
        i for i in range(last_jp + 1, len(lines))
        if lines[i].strip() and not contains_japanese(lines[i]) and not is_command_line(lines[i])
    ]
    kind = "choice" if any("<03:" in lines[i] for i in jp_indices) else "dialogue"
    speaker = None
    for i in jp_indices:
        match = SPEAKER_RE.match(lines[i].strip())
        if match:
            speaker = match.group(1)
            break
    return Block(lines=lines, kind=kind, japanese_indices=jp_indices,
                 english_indices=en_indices, speaker=speaker)


def trim_block_boundary_blanks(lines: list[str]) -> list[str]:
    """Remove separator-adjacent blank lines while preserving internal blanks."""
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def split_blocks(content: str) -> tuple[list[Block], bool]:
    trailing_newline = content.endswith(("\n", "\r"))
    chunks = re.split(r"^\s*" + re.escape(DIVIDER) + r"\s*$", content, flags=re.MULTILINE)
    blocks = [
        classify_block(trim_block_boundary_blanks(chunk.splitlines()))
        for chunk in chunks
    ]
    return blocks, trailing_newline


def visible_source_length(text: str) -> int:
    """Return a practical source-length estimate after immutable codes are hidden."""
    visible = PlaceholderProtector.TOKEN_RE.sub("", text)
    return max(1, len(re.sub(r"\s+", "", visible)))


def skit_line_token_budget(source: str, args: argparse.Namespace) -> int:
    """Scale output tokens for short banter through long skit monologues.

    Japanese character count is a useful conservative proxy for eventual English
    token count. Budgets are rounded to 64-token steps to keep llama.cpp requests
    predictable, with args.max_tokens remaining the hard ceiling.
    """
    source_chars = visible_source_length(source)
    estimated = math.ceil(source_chars * args.skit_tokens_per_jp_char)
    rounded = int(math.ceil(max(args.line_min_tokens, estimated) / 64.0) * 64)
    return min(args.max_tokens, max(64, rounded))


def skit_line_char_limit(source: str, args: argparse.Namespace) -> int:
    """Allow complete long translations while retaining a runaway-output guard."""
    source_chars = visible_source_length(source)
    dynamic = math.ceil(source_chars * args.skit_chars_per_jp_char)
    return min(args.skit_max_line_chars, max(args.max_line_chars, dynamic))


def build_prompt(jp_lines: list[str], voice_note: str | None, glossary_rows: list[str],
                 required_placeholders: list[list[str]],
                 target_index: int | None = None) -> str:
    """Build a compact prompt with explicit numbered source-line boundaries."""
    voice = voice_note or "(none matched; narration or unknown speaker)"
    glossary = "\n".join(glossary_rows) if glossary_rows else "(none)"
    numbered = "\n".join(f"{i + 1}: {line}" for i, line in enumerate(jp_lines))
    placeholder_rows = "\n".join(
        f"{i + 1}: {', '.join(tokens) if tokens else '(none)'}"
        for i, tokens in enumerate(required_placeholders)
    )

    if target_index is None:
        task = (
            f"Translate all {len(jp_lines)} numbered source lines. Return one translation "
            "for every source number. Never merge adjacent lines, even when they form one sentence."
        )
        expected = len(jp_lines)
    else:
        task = (
            f"Use all source lines as context, but translate ONLY source line {target_index + 1}. "
            "Do not translate any other source line."
        )
        expected = 1

    return f"""You are translating Japanese JRPG dialogue into natural English for a fan translation of Tales of Destiny 2.

Speaker voice: {voice}
Glossary terms for this block:
{glossary}

Task:
{task}

Rules:
- Write lively, natural skit dialogue that preserves banter, comedy, character chemistry, and emotional timing.
- Use natural, idiomatic English rather than rigid literal wording.
- Drop Japanese honorifics by default; convey relationships through phrasing.
- Preserve every placeholder exactly. Each output string must contain the exact placeholders listed for its source line.
- Use glossary translations exactly when applicable and keep terminology consistent within the skit.
- Preserve tone; do not censor, summarize, omit, or invent content.
- Translate long speeches completely. Do not shorten normal dialogue merely to be concise.
- Each returned string must be a single non-empty English line.
- Only shorten prolonged cries, groans, laughs, and repeated punctuation. Never repeat one character more than 8 times; use forms like "Mmm..." or "Aaaah!" instead of a long character run.
- Return JSON only, with this shape: {{"translations":["line 1", "line 2"]}}.
- The translations array must contain exactly {expected} string(s).
- Do not output explanations, Markdown, numbering, quotes outside JSON, or Japanese.

Required placeholders by source line:
{placeholder_rows}

Numbered source lines:
{numbered}"""


def translation_response_format(expected_lines: int) -> dict[str, Any]:
    """llama.cpp schema-constrained response with an exact array length."""
    return {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": {
                "translations": {
                    "type": "array",
                    "minItems": expected_lines,
                    "maxItems": expected_lines,
                    "items": {"type": "string", "minLength": 1},
                }
            },
            "required": ["translations"],
            "additionalProperties": False,
        },
    }


def normalize_endpoint(endpoint: str) -> str:
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/v1/chat/completions"):
        return endpoint
    if endpoint.endswith("/v1"):
        return endpoint + "/chat/completions"
    return endpoint + "/v1/chat/completions"


def extract_response_text(result: dict[str, Any]) -> tuple[str, str, str]:
    """Return (answer, reasoning, finish_reason) from llama-server JSON."""
    try:
        choice = result["choices"][0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        finish_reason = str(choice.get("finish_reason") or "")
        return str(content), str(reasoning), finish_reason
    except (KeyError, IndexError, TypeError, AttributeError):
        # Helpful fallback for llama.cpp's legacy /completion shape.
        if "content" in result:
            return str(result.get("content") or ""), "", str(result.get("stop_type") or "")
        raise ValueError(f"unexpected llama-server JSON response keys: {list(result)[:10]}")


LEADING_REASONING_BLOCK_RE = re.compile(
    r"\A\s*<(think|analysis|reasoning)>.*?</\1>\s*",
    re.IGNORECASE | re.DOTALL,
)


def strip_leading_reasoning_blocks(text: str) -> str:
    """Remove llama.cpp/Qwen reasoning wrappers preceding the final answer.

    Some chat templates emit an empty or populated <think>...</think> block in
    message.content even when request-side thinking is disabled. Only leading
    reasoning blocks are removed so game tags inside the actual translation are
    never touched.
    """
    cleaned = text.lstrip("\ufeff")
    while True:
        updated, count = LEADING_REASONING_BLOCK_RE.subn("", cleaned, count=1)
        if count == 0:
            break
        cleaned = updated

    # Defensive handling for a malformed/unclosed leading reasoning tag.
    # Do not remove anything unless the tag begins the response.
    cleaned = re.sub(
        r"\A\s*<(?:think|analysis|reasoning)>\s*",
        "",
        cleaned,
        count=1,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


def runaway_output_reason(text: str, finish_reason: str, max_line_chars: int,
                         expected_lines: int) -> str | None:
    """Return a reason when generation is clearly truncated or degenerate."""
    cleaned = strip_leading_reasoning_blocks(text)
    run = RUNAWAY_CHAR_RE.search(cleaned)
    if run:
        return (
            f"runaway repetition of {run.group(1)!r} "
            f"({len(run.group(0))} consecutive characters)"
        )
    if finish_reason.lower() in {"length", "limit"}:
        return f"generation stopped at token limit (finish_reason={finish_reason!r})"
    hard_limit = max_line_chars * max(1, expected_lines) * 3
    if len(cleaned) > hard_limit:
        return f"response is implausibly long ({len(cleaned)} characters)"
    return None


def clamp_excessive_runs(text: str, max_run: int) -> tuple[str, bool]:
    """Clamp pathological repeated non-whitespace characters in accepted output."""
    changed = False

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        return match.group(1) * max_run

    pattern = re.compile(rf"([^\s])\1{{{max_run},}}", re.DOTALL)
    return pattern.sub(repl, text), changed


def repair_common_json_errors(text: str) -> str:
    """Repair only conservative, common local-model JSON mistakes.

    This intentionally does not attempt broad heuristic reconstruction. It only
    removes trailing commas before a closing array/object delimiter.
    """
    return re.sub(r",\s*([}\]])", r"\1", text)


def parse_model_translations(text: str, expected: int) -> list[str]:
    """Parse schema JSON, with conservative repair and a plain-line fallback."""
    text = strip_leading_reasoning_blocks(text)
    if text.startswith("```") and text.endswith("```"):
        text = re.sub(r"^```[^\n]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()

    candidates = [text]
    first_brace, last_brace = text.find("{"), text.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        candidates.append(text[first_brace:last_brace + 1])

    # Preserve order while adding conservative trailing-comma repairs.
    candidates = list(dict.fromkeys(
        candidates + [repair_common_json_errors(candidate) for candidate in candidates]
    ))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            values = parsed.get("translations")
        elif isinstance(parsed, list):
            values = parsed
        else:
            values = None
        if isinstance(values, list) and all(isinstance(x, str) for x in values):
            lines = [" ".join(x.strip().splitlines()).strip() for x in values]
            if len(lines) == expected and all(lines):
                return lines

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) == expected and all(re.match(r"^\d+[.)]\s+", x) for x in lines):
        lines = [re.sub(r"^\d+[.)]\s+", "", x) for x in lines]
    if len(lines) != expected:
        raise ValueError(
            f"model returned {len(lines)} plain lines; expected {expected}; "
            f"could not parse exact-length translation JSON: {text[:400]!r}"
        )
    return lines


def call_llama_server(
    prompt: str,
    expected_lines: int,
    args: argparse.Namespace,
    *,
    max_tokens_override: int | None = None,
    line_char_limits: list[int] | None = None,
    rescue_mode: bool = False,
) -> list[str]:
    endpoint = normalize_endpoint(args.endpoint)
    automatic_cap = max(args.line_min_tokens, expected_lines * args.tokens_per_line)
    if line_char_limits is None:
        line_char_limits = [args.max_line_chars] * expected_lines
    if len(line_char_limits) != expected_lines:
        raise ValueError("line_char_limits length must match expected_lines")
    effective_max_tokens = min(
        args.max_tokens,
        max_tokens_override if max_tokens_override is not None else automatic_cap,
    )
    effective_max_tokens = max(32, effective_max_tokens)

    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    "Return the translation now. Be concise. Do not stretch or repeat "
                    "letters. Return only the required JSON object."
                    if rescue_mode else
                    "Perform the task now. Return only the required JSON object."
                ),
            },
        ],
        "temperature": min(args.temperature, 0.1) if rescue_mode else args.temperature,
        "top_p": min(args.top_p, 0.8) if rescue_mode else args.top_p,
        "max_tokens": effective_max_tokens,
        "stream": False,
        "repeat_penalty": max(args.repeat_penalty, 1.18) if rescue_mode else args.repeat_penalty,
        "repeat_last_n": args.repeat_last_n,
        "reasoning_format": "none",
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if rescue_mode:
        payload.update({
            "dry_multiplier": args.rescue_dry_multiplier,
            "dry_base": 1.75,
            "dry_allowed_length": 3,
            "dry_penalty_last_n": max(args.repeat_last_n, 256),
        })
    if not args.no_json_schema:
        payload["response_format"] = translation_response_format(expected_lines)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"

    last_error: Exception | None = None
    attempts_made = 0
    for attempt in range(1, args.retries + 1):
        attempts_made = attempt
        request = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
        started = time.monotonic()
        mode = " rescue" if rescue_mode else ""
        print(
            f"    llama-server{mode} attempt {attempt}/{args.retries}; "
            f"timeout={args.timeout}s; max_tokens={effective_max_tokens}",
            flush=True,
        )
        try:
            with urllib.request.urlopen(request, timeout=args.timeout) as response:
                raw = response.read().decode("utf-8")
            result = json.loads(raw)
            content, reasoning, finish_reason = extract_response_text(result)
            if args.debug_response:
                print("    raw llama-server response:", file=sys.stderr)
                print(json.dumps(result, ensure_ascii=False, indent=2)[:12000], file=sys.stderr)
            if not content.strip():
                usage = result.get("usage", {}) if isinstance(result, dict) else {}
                timings = result.get("timings", {}) if isinstance(result, dict) else {}
                reason_note = f"; reasoning_content={len(reasoning)} chars" if reasoning else ""
                raise ValueError(
                    f"empty message.content; finish_reason={finish_reason!r}{reason_note}; "
                    f"usage={usage!r}; timings={timings!r}"
                )

            runaway = runaway_output_reason(
                content, finish_reason, max(line_char_limits), expected_lines
            )
            if runaway:
                raise ValueError(runaway)

            lines = parse_model_translations(content, expected_lines)
            normalized: list[str] = []
            for line_number, (line, line_limit) in enumerate(
                zip(lines, line_char_limits, strict=True), start=1
            ):
                if len(line) > line_limit:
                    raise ValueError(
                        f"translation line {line_number} is too long "
                        f"({len(line)} characters; dynamic limit {line_limit})"
                    )
                clamped, changed = clamp_excessive_runs(line, args.max_char_run)
                if changed:
                    print(
                        f"    warning: clamped excessive repeated characters to "
                        f"{args.max_char_run}",
                        file=sys.stderr,
                    )
                normalized.append(clamped)
            print(f"    completed in {time.monotonic() - started:.1f}s", flush=True)
            return normalized
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:1000]
            last_error = RuntimeError(f"HTTP {exc.code} {exc.reason}: {body}")

            # Some llama.cpp/Qwen chat templates emit an automatic <think> token
            # before the assistant's answer. A strict JSON grammar cannot accept
            # that token and llama-server returns HTTP 400 before generation. In
            # that specific case, transparently retry without response_format;
            # the prompt and parser still enforce/validate JSON afterward.
            grammar_think_conflict = (
                exc.code == 400
                and "response_format" in payload
                and (
                    "Unexpected empty grammar stack" in body
                    or "Failed to initialize samplers" in body
                )
                and "<think>" in body
            )
            if grammar_think_conflict:
                payload.pop("response_format", None)
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                print(
                    "    llama.cpp grammar conflicts with the model's <think> token; "
                    "retrying this request without schema grammar",
                    file=sys.stderr,
                )
                continue

            retryable = exc.code in (408, 409, 429) or exc.code >= 500
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            last_error = exc
            retryable = True
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            # Formatting/repetition failures need a different rescue prompt, not
            # three identical generations. Network failures still retry normally.
            retryable = args.no_json_schema and attempt < args.retries
        if not retryable or attempt == args.retries:
            break
        delay = args.retry_delay * (2 ** (attempt - 1))
        print(f"    error: {last_error}; retrying in {delay:.1f}s", file=sys.stderr)
        time.sleep(delay)
    raise RuntimeError(
        f"llama-server request failed after {attempts_made} attempt(s): {last_error}"
    )


def translate_block(block: Block, glossary: dict[str, str], voices: dict[str, str],
                    args: argparse.Namespace) -> list[str]:
    protected_lines: list[str] = []
    protectors: list[PlaceholderProtector] = []
    raw_jp: list[str] = []
    for line_number, index in enumerate(block.japanese_indices, start=1):
        source = block.lines[index].lstrip()
        source = source[1:] if source.startswith("#") else source
        raw_jp.append(source)
        protector = PlaceholderProtector(line_number)
        protected_lines.append(protector.protect(source))
        protectors.append(protector)

    matched = [f"{jp} -> {en}" for jp, en in glossary.items() if any(jp in line for line in raw_jp)]
    voice_key = VOICE_ALIASES.get(block.speaker or "", block.speaker or "")
    voice_note = voices.get(voice_key)
    required_placeholders = [protector.required_tokens() for protector in protectors]
    line_token_budgets = [skit_line_token_budget(line, args) for line in protected_lines]
    line_char_limits = [skit_line_char_limit(line, args) for line in protected_lines]
    block_token_budget = min(args.max_tokens, sum(line_token_budgets))
    prompt = build_prompt(protected_lines, voice_note, matched, required_placeholders)

    if args.dry_run:
        for number, (tokens, chars) in enumerate(
            zip(line_token_budgets, line_char_limits, strict=True), start=1
        ):
            print(f"[skit budget line {number}: max_tokens={tokens}, max_chars={chars}]")
        print(prompt)
        return []

    def translate_one(target_index: int, retry_reason: Exception | None = None) -> str:
        # A failed block call is retried with only the target source line. Earlier
        # versions showed the whole block and asked the model to translate one line;
        # some local models translated the context too, making one-line recovery
        # impossible. The original block call already supplied full context.
        line_prompt = build_prompt(
            [protected_lines[target_index]],
            voice_note,
            matched,
            [required_placeholders[target_index]],
        )
        if retry_reason is not None:
            print(
                f"    line {target_index + 1} retry requested "
                f"({retry_reason}); translating that line separately",
                file=sys.stderr,
            )
        line_token_budget = line_token_budgets[target_index]
        line_char_limit = line_char_limits[target_index]
        try:
            return call_llama_server(
                line_prompt,
                1,
                args,
                max_tokens_override=line_token_budget,
                line_char_limits=[line_char_limit],
            )[0]
        except RuntimeError as normal_error:
            print(
                f"    line {target_index + 1} separate generation failed "
                f"({normal_error}); using anti-repetition rescue",
                file=sys.stderr,
            )
            rescue_prompt = line_prompt + """

Emergency output rule:
- Translate the complete target line faithfully; do not summarize or omit any normal dialogue.
- If the source is a prolonged sound or vocalization, shorten only that sound naturally, for example "Mmm...", "Aaaah!", or "Grrr...".
- Never repeat any one character more than 8 times.
- Return exactly one non-empty translation string in the required JSON object.
"""
            rescue_budget = min(
                args.max_tokens,
                max(line_token_budget, args.rescue_max_tokens),
            )
            return call_llama_server(
                rescue_prompt,
                1,
                args,
                max_tokens_override=rescue_budget,
                line_char_limits=[line_char_limit],
                rescue_mode=True,
            )[0]

    try:
        translated = call_llama_server(
            prompt,
            len(protected_lines),
            args,
            max_tokens_override=block_token_budget,
            line_char_limits=line_char_limits,
        )
    except RuntimeError as block_error:
        if args.no_line_fallback:
            raise
        if len(protected_lines) == 1:
            translated = [translate_one(0, block_error)]
        else:
            print(
                f"    block output invalid ({block_error}); translating "
                f"{len(protected_lines)} lines separately with target-only prompts",
                file=sys.stderr,
            )
            translated = [translate_one(i) for i in range(len(protected_lines))]

    restored: list[str] = []
    for target_index, (line, protector) in enumerate(
        zip(translated, protectors, strict=True)
    ):
        try:
            restored.append(protector.restore(line))
        except ValueError as restore_error:
            if args.no_line_fallback:
                raise
            print(
                f"    line {target_index + 1} placeholder validation failed "
                f"({restore_error}); retrying that line with a target-only prompt",
                file=sys.stderr,
            )
            retried = translate_one(target_index, restore_error)
            try:
                restored.append(protector.restore(retried))
            except ValueError as retry_restore_error:
                if args.no_placeholder_auto_repair:
                    raise
                print(
                    f"    line {target_index + 1} still omitted inline code "
                    f"({retry_restore_error}); restoring it at the nearest "
                    "source-relative boundary",
                    file=sys.stderr,
                )
                restored.append(
                    protector.restore(retried, repair_missing_inline=True)
                )
    return restored


def output_path_for(path: Path, args: argparse.Namespace) -> Path:
    if args.in_place:
        return path
    try:
        relative = path.relative_to(args.root)
    except ValueError:
        relative = Path(path.name)
    return args.output_dir / relative


def render_blocks(blocks: list[Block], trailing_newline: bool) -> str:
    # Canonical file layout: no empty line immediately before or after a divider.
    rendered = [
        "\n".join(trim_block_boundary_blanks(block.lines))
        for block in blocks
    ]
    output = ("\n" + DIVIDER + "\n").join(rendered)
    if trailing_newline:
        output += "\n"
    return output


def write_checkpoint(output_path: Path, blocks: list[Block],
                     trailing_newline: bool) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_blocks(blocks, trailing_newline),
        encoding="utf-8",
        newline="\n",
    )


def process_file(path: Path, glossary: dict[str, str], voices: dict[str, str],
                 args: argparse.Namespace) -> dict[str, int]:
    output_path = output_path_for(path, args)
    input_path = path
    if args.resume and not args.in_place and output_path.exists():
        input_path = output_path
        print(f"  resuming from {output_path}")

    content = input_path.read_text(encoding="utf-8-sig")
    blocks, trailing_newline = split_blocks(content)
    translated_count = skipped_count = command_count = failed_count = 0

    selected_block = args.block
    for block_no, block in enumerate(blocks):
        if block.kind == "command":
            command_count += 1
            continue
        if selected_block is not None and block_no != selected_block:
            continue
        if block.already_translated and not args.force:
            skipped_count += 1
            continue
        try:
            english = translate_block(block, glossary, voices, args)
            if not args.dry_run:
                # Remove incomplete pre-existing target lines only when --force is used.
                if block.english_indices:
                    existing = set(block.english_indices)
                    block.lines = [
                        line for i, line in enumerate(block.lines)
                        if i not in existing
                    ]
                block.lines.extend(english)
                translated_count += 1
                # Checkpoint every completed block. Skit batches contain hundreds of
                # files, so a late failure must not discard earlier work.
                write_checkpoint(output_path, blocks, trailing_newline)
        except Exception as exc:
            failed_count += 1
            print(f"  block {block_no} FAILED: {exc}", file=sys.stderr)
            if not args.dry_run:
                write_checkpoint(output_path, blocks, trailing_newline)
                print(f"  partial checkpoint written to {output_path}", file=sys.stderr)
            if args.fail_fast:
                raise

    if not args.dry_run:
        write_checkpoint(output_path, blocks, trailing_newline)
        print(f"  wrote {output_path}")

    return {"translated": translated_count, "skipped": skipped_count,
            "commands": command_count, "failed": failed_count}


def build_parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--file", type=Path, help="translate one skit .sced.txt file")
    scope.add_argument(
        "--skits-only",
        action="store_true",
        help="translate all ps2/skits files (default when --file is omitted)",
    )
    parser.add_argument("--root", type=Path, default=root, help="project root")
    parser.add_argument("--block", type=int, help="process only this divider-block index")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="replace existing translations")
    parser.add_argument("--resume", action="store_true", help="resume from an existing translated_output file")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--in-place", action="store_true", help="overwrite source files (make a backup first)")
    parser.add_argument("--output-dir", type=Path, default=root / "translated_output")
    parser.add_argument("--endpoint", default=os.getenv("LLM_ENDPOINT", "http://127.0.0.1:8080"))
    parser.add_argument("--model", default=os.getenv("LLM_MODEL", "local-model"))
    parser.add_argument("--api-key", default=os.getenv("LLM_API_KEY", ""))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("LLM_TIMEOUT", "1800")),
                        help="seconds per request; default 1800 for slow local models")
    parser.add_argument("--retries", type=int, default=int(os.getenv("LLM_MAX_RETRIES", "3")))
    parser.add_argument("--retry-delay", type=float, default=float(os.getenv("LLM_RETRY_BASE_DELAY", "5")))
    parser.add_argument("--max-tokens", type=int, default=int(os.getenv("LLM_MAX_TOKENS", "512")),
                        help="hard output-token ceiling for a block; requests are capped dynamically")
    parser.add_argument("--tokens-per-line", type=int, default=int(os.getenv("LLM_TOKENS_PER_LINE", "128")),
                        help="fallback dynamic block budget per source line")
    parser.add_argument(
        "--line-min-tokens", "--line-max-tokens", dest="line_min_tokens", type=int,
        default=int(os.getenv("LLM_LINE_MIN_TOKENS", os.getenv("LLM_LINE_MAX_TOKENS", "128"))),
        help="minimum one-line budget before skit source-length scaling",
    )
    parser.add_argument(
        "--skit-tokens-per-jp-char", type=float,
        default=float(os.getenv("LLM_SKIT_TOKENS_PER_JP_CHAR", "2.25")),
        help="dynamic output-token estimate per visible Japanese source character",
    )
    parser.add_argument("--rescue-max-tokens", type=int, default=int(os.getenv("LLM_RESCUE_MAX_TOKENS", "128")),
                        help="minimum rescue budget; long lines retain their larger normal budget")
    parser.add_argument("--temperature", type=float, default=float(os.getenv("LLM_TEMPERATURE", "0.2")))
    parser.add_argument("--top-p", type=float, default=float(os.getenv("LLM_TOP_P", "0.9")))
    parser.add_argument("--repeat-penalty", type=float, default=float(os.getenv("LLM_REPEAT_PENALTY", "1.10")))
    parser.add_argument("--repeat-last-n", type=int, default=int(os.getenv("LLM_REPEAT_LAST_N", "256")))
    parser.add_argument("--rescue-dry-multiplier", type=float,
                        default=float(os.getenv("LLM_RESCUE_DRY_MULTIPLIER", "0.8")))
    parser.add_argument("--max-char-run", type=int, default=int(os.getenv("LLM_MAX_CHAR_RUN", "12")),
                        help="clamp accepted output containing pathological repeated characters")
    parser.add_argument("--max-line-chars", type=int, default=int(os.getenv("LLM_MAX_LINE_CHARS", "300")),
                        help="minimum per-line character allowance")
    parser.add_argument(
        "--skit-chars-per-jp-char", type=float,
        default=float(os.getenv("LLM_SKIT_CHARS_PER_JP_CHAR", "5.0")),
        help="dynamic English character allowance per visible Japanese source character",
    )
    parser.add_argument(
        "--skit-max-line-chars", type=int,
        default=int(os.getenv("LLM_SKIT_MAX_LINE_CHARS", "1000")),
        help="hard ceiling for a legitimate long skit translation line",
    )
    parser.add_argument("--debug-response", action="store_true", help="print raw llama-server JSON response")
    parser.add_argument(
        "--no-json-schema", action="store_true",
        help="disable llama.cpp schema-constrained JSON; prompt/parser validation remains active",
    )
    parser.add_argument(
        "--no-line-fallback", action="store_true",
        help="disable one-request-per-line fallback for merged block output",
    )
    parser.add_argument(
        "--no-placeholder-auto-repair", action="store_true",
        help=(
            "fail instead of source-relative reinsertion when a targeted retry "
            "still drops an inline control-code placeholder"
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.root = args.root.resolve()
    args.output_dir = args.output_dir.resolve()
    glossary = parse_glossary(args.root / "glossary.txt")
    voices = parse_voice_guide(args.root / "character_voice_guide.txt")

    if args.file:
        files = [args.file.resolve()]
    else:
        skit_dir = args.root / "ps2" / "skits"
        files = sorted(skit_dir.rglob("*.sced.txt")) if skit_dir.exists() else []

    if not files:
        print("No .sced.txt files found.", file=sys.stderr)
        return 2

    print(f"Endpoint: {normalize_endpoint(args.endpoint)}")
    print(f"Model: {args.model}; timeout: {args.timeout}s; files: {len(files)}")
    totals = {"translated": 0, "skipped": 0, "commands": 0, "failed": 0}
    for path in files:
        print(f"Processing {path}")
        result = process_file(path, glossary, voices, args)
        for key in totals:
            totals[key] += result[key]

    print("Summary: " + ", ".join(f"{k}={v}" for k, v in totals.items()))
    return 1 if totals["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
