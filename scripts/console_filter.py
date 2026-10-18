"""Filters Terraform's rendered plan text for console output.

Classification (tag-only / data-read / change type) is computed elsewhere from the
JSON plan (tfplan-parser.py) and passed in as summary dicts; this module only decides which lines of the
human-readable `terraform show` output to keep, matching resources up by address.

!!! AZURERM-ONLY: tag-block removal below only tracks '{'/'}' depth, matching azurerm's
!!! map-style `tags = { ... }` rendering. Providers that render tags as a list/set
!!! (e.g. `tags = [ ... ]`, such as google_compute_instance.tags) are NOT handled -
!!! the block will not be fully dropped and will leave malformed, orphaned lines.
"""
import re
from typing import Any, Dict, List

ANSI = re.compile(r'\x1b\[[0-9;]*m')
STRING_LIT = re.compile(r'"(?:[^"\\]|\\.)*"')
CHANGE_MARK = r'(?:~|\+|-|-/\+|\+/-|<=)'
TEXT_HEADER = re.compile(r'^  # (.+?) (will |must |has )(.+)$')
TAG_LINE = re.compile(r'^\s*(?:' + CHANGE_MARK + r'\s+)?(?:tags|tags_all)\s*=\s*(.*)')
# Terraform renders multi-line strings as <<-EOT ... EOT; the opener may carry a trailing '# forces replacement'.
HEREDOC_START = re.compile(r'<<-?([A-Za-z_][A-Za-z0-9_]*)(?:\s+#.*)?\s*$')
SECTION_END = re.compile(r'^(?:Plan:|Changes to Outputs:|Warning:|Error:|Note:|\u2577)')


def heredoc_closes(line: str, ident: str) -> bool:
    stripped = line.strip()
    # A removed string closes as 'EOT -> null'.
    return stripped == ident or stripped.startswith(ident + ' -> ')


def is_tag_only_update(summary: Dict[str, Any]) -> bool:
    # Data reads are always kept; only tag-only *updates* are dropped - never replacements.
    return not summary.get('data_read') and bool(summary.get('tags_only')) and summary.get('change_type') == 'update'


def filter_console(text: str, by_address: Dict[str, List[Dict[str, Any]]]) -> str:
    raw = text.split('\n')
    plain = [ANSI.sub('', line) for line in raw]

    start = next((i for i, p in enumerate(plain) if p.startswith('Terraform used the selected providers')), None)
    if start is None:
        start = next((i for i, p in enumerate(plain) if p.startswith('Terraform will perform')), None)
    if start is None:
        return '  No planned resource changes.'

    end = next((i for i in range(start, len(plain)) if SECTION_END.match(plain[i])), len(plain))
    headers = [i for i in range(start, end) if TEXT_HEADER.match(plain[i])]
    if not headers:
        return '  No planned resource changes.'

    out = raw[start:headers[0]]
    shown = hidden_tags = 0

    for n, first in enumerate(headers):
        last = (headers + [end])[n + 1]
        address = TEXT_HEADER.match(plain[first]).group(1).strip()
        summaries = by_address.get(address) or []

        # The same address can appear in several plans, so hide it only if every one is tag-only.
        if summaries and all(is_tag_only_update(s) for s in summaries):
            hidden_tags += 1
            continue

        # Drop tag attribute lines (and any block they open) from the kept resource.
        # Heredoc bodies are string content: never matched as attributes, never brace-counted.
        kept = []
        depth = 0
        heredoc = None
        for k in range(first, last):
            line = plain[k]
            if heredoc:
                if heredoc_closes(line, heredoc):
                    heredoc = None
                if depth == 0:
                    kept.append(k)
                continue
            opener = HEREDOC_START.search(line)
            if depth > 0:
                flat = STRING_LIT.sub('""', line)
                depth += flat.count('{') - flat.count('}')
                if opener:
                    heredoc = opener.group(1)
                continue
            tag_match = TAG_LINE.match(line) if k > first else None
            if tag_match:
                flat = STRING_LIT.sub('""', tag_match.group(1))
                depth = max(flat.count('{') - flat.count('}'), 0)
                if opener:
                    heredoc = opener.group(1)
                continue
            if opener:
                heredoc = opener.group(1)
            kept.append(k)

        shown += 1
        out.extend(raw[k] for k in kept)

    total = shown + hidden_tags
    body = '\n'.join(out).rstrip() if shown else '  No changes outside tags.'
    trailer = f'  {shown} of {total} resource change(s) shown; {hidden_tags} tag-only change(s) hidden.'
    return f'{body}\n\n{trailer}'
