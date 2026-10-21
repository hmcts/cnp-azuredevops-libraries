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
SECTION_END = re.compile(r'^(?:Plan:|Changes to Outputs:|Warnings?:|Error:|Note:|\u2577)')
OUTPUT_SECTION_END = re.compile(r'^(?:Warnings?:|Error:|Note:|\u2577)')


def heredoc_closes(line: str, ident: str) -> bool:
    stripped = line.strip()
    # A removed string closes as 'EOT -> null'.
    return stripped == ident or stripped.startswith(ident + ' -> ')


def is_tag_only_update(summary: Dict[str, Any]) -> bool:
    # Default behaviour: only hide resources whose ENTIRE diff is tags. Data reads and
    return not summary.get('data_read') and bool(summary.get('tags_only')) and summary.get('change_type') == 'update'


def filter_console(text: str, by_address: Dict[str, List[Dict[str, Any]]]) -> str:
    raw = text.split('\n')
    plain = [ANSI.sub('', line) for line in raw]
    output_start = next((i for i, line in enumerate(plain) if line.startswith('Changes to Outputs:')), None)
    output_section = ''
    if output_start is not None:
        output_end = next(
            (i for i in range(output_start + 1, len(plain)) if OUTPUT_SECTION_END.match(plain[i])),
            len(plain),
        )
        output_section = '\n'.join(raw[output_start:output_end]).strip()

    start = next((i for i, p in enumerate(plain) if p.startswith('Terraform used the selected providers')), None)
    if start is None:
        start = next((i for i, p in enumerate(plain) if p.startswith('Terraform will perform')), None)
    if start is None:
        result = '  No planned resource changes.'
        return f'{result}\n\n{output_section}' if output_section else result

    end = next((i for i in range(start, len(plain)) if SECTION_END.match(plain[i])), len(plain))
    headers = [i for i in range(start, end) if TEXT_HEADER.match(plain[i])]
    if not headers:
        result = '  No planned resource changes.'
        return f'{result}\n\n{output_section}' if output_section else result

    out = raw[start:headers[0]]
    shown = hidden_tags = data_reads = 0

    for n, first in enumerate(headers):
        last = (headers + [end])[n + 1]
        header_match = TEXT_HEADER.match(plain[first])
        address = header_match.group(1).strip()
        summaries = by_address.get(address) or []
        is_data_read = header_match.group(3).startswith('be read') or (
            bool(summaries) and all(summary.get('data_read') for summary in summaries)
        )

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

        if is_data_read:
            data_reads += 1
        else:
            shown += 1
        out.extend(raw[k] for k in kept)

    displayed = shown + data_reads
    total = displayed + hidden_tags
    body = '\n'.join(out).rstrip() if shown or data_reads else '  No changes outside tags.'
    trailer = f'  {displayed} of {total} resource change(s) shown; {hidden_tags} tag-only change(s) hidden'
    if data_reads:
        read_label = 'read' if data_reads == 1 else 'reads'
        trailer += f'; {data_reads} data {read_label} shown'
    trailer += '.'
    result = f'{body}\n\n{trailer}'
    return f'{result}\n\n{output_section}' if output_section else result
