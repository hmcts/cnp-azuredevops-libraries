import os
import re
import json
import sys
import html
import argparse
from typing import List, Dict, Any, Set

from console_filter import filter_console

script_dir = os.path.dirname(os.path.abspath(__file__))
default_template = os.path.join(script_dir, 'plan.html')

parser = argparse.ArgumentParser(description="Convert Terraform JSON plan(s) to an HTML report, or filter the rendered text plan for console output (local only, no AI)")
parser.add_argument("--plansDir", type=str, required=True, help="Directory containing terraform plan JSON files (terraform show -json or concatenated resource change objects)")
parser.add_argument("--outputDir", type=str, default='', help="Directory to write generated plan.html (required unless --consoleFrom is used)")
parser.add_argument("--templateFile", type=str, default=default_template, help=f"Path to HTML template (default: {default_template})")
parser.add_argument("--consoleFrom", type=str, default='', help="Path to 'terraform show' text output; filters and prints it instead of writing HTML")
args = parser.parse_args()
if not args.consoleFrom and not args.outputDir:
    parser.error("--outputDir is required unless --consoleFrom is used")

plans_dir = args.plansDir
plan_files = [os.path.join(plans_dir, f) for f in os.listdir(plans_dir) if os.path.isfile(os.path.join(plans_dir, f))]

def read_file_text(p):
    with open(p, 'r', encoding='utf-8', errors='replace') as fh:
        return fh.read()


# Collect rows
html_rows: List[str] = []
seen_resources = set()  # (stage, env, resource_name)
summaries_by_address: Dict[str, List[Dict[str, Any]]] = {}

def derive_stage_and_env(file_name: str):
    base = re.sub(r'\.json$', '', file_name)
    # Expect patterns like tfplan-<env>-<stage>
    m = re.match(r'^tfplan-([a-z0-9]+?)-(.+)$', base)
    environment = 'unknown'
    stage = base
    if m:
        environment = m.group(1)
        stage = m.group(2)
    stage = stage.replace('tfplan-', '')
    return stage, environment


def extract_resource_names(tr_html: str):
    names = []
    # Each row: <tr>...<td>Stage</td><td>Env</td><td>Loc</td><td>Resource Name</td>...
    row_re = re.compile(r'<tr[\s\S]*?</tr>', re.IGNORECASE)
    cell_re = re.compile(r'<td[^>]*>([\s\S]*?)</td>', re.IGNORECASE)
    for row in row_re.findall(tr_html):
        cells = cell_re.findall(row)
        if len(cells) >= 4:
            stage = re.sub(r'<[^>]+>', '', cells[0]).strip()
            env = re.sub(r'<[^>]+>', '', cells[1]).strip()
            res_name = re.sub(r'<[^>]+>', '', cells[3]).strip()
            if res_name:
                names.append((stage, env, res_name))
    return names

def load_json_plan_variants(raw: str) -> Dict[str, Any]:
    """Attempt to parse raw JSON which can be:
    1. A full terraform show -json output (has resource_changes array)
    2. Concatenated pretty-printed resource change JSON objects (we'll split by top-level object)
    Returns dict with key 'resource_changes' (list).
    """
    raw_strip = raw.strip()
    if not raw_strip:
        return {"resource_changes": []}
    # Fast path full plan
    try:
        doc = json.loads(raw_strip)
        if isinstance(doc, dict) and 'resource_changes' in doc:
            return {"resource_changes": doc.get('resource_changes') or []}
        # Single resource change object
        if isinstance(doc, dict) and 'address' in doc and 'change' in doc:
            return {"resource_changes": [doc]}
    except Exception:
        pass
    # Fallback: extract multiple JSON objects by brace balance
    objs = []
    buf = []
    depth = 0
    in_obj = False
    for ch in raw:
        if ch == '{':
            depth += 1
            in_obj = True
        if in_obj:
            buf.append(ch)
        if ch == '}':
            depth -= 1
            if depth == 0 and in_obj:
                # end object
                candidate = ''.join(buf)
                try:
                    obj = json.loads(candidate)
                    if isinstance(obj, dict):
                        objs.append(obj)
                except Exception:
                    pass
                buf = []
                in_obj = False
    return {"resource_changes": objs}

def flatten_dict(d: Any, prefix: str = '') -> Dict[str, Any]:
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            new_p = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                out.update(flatten_dict(v, new_p))
            else:
                out[new_p] = v
    elif isinstance(d, list):
        for i, v in enumerate(d):
            new_p = f"{prefix}[{i}]" if prefix else f"[{i}]"
            if isinstance(v, (dict, list)):
                out.update(flatten_dict(v, new_p))
            else:
                out[new_p] = v
    return out

SENSITIVE_KEYWORDS = (
    'password', 
    'secret', 
    'key', 
    'token',
    'private_key',
    'client_secret',
    'access_key',
    'connection_string'
)

def collect_sensitive_paths(change: Dict[str, Any]) -> Set[str]:
    paths: Set[str] = set()
    for field in ('before_sensitive', 'after_sensitive'):
        sens = change.get(field)
        flat = flatten_dict(sens) if isinstance(sens, (dict, list)) else ({'value': sens} if sens is not None else {})
        for key, value in flat.items():
            if value is True:
                paths.add(key)
    return paths

def is_sensitive_key_path(path: str, sensitive_paths: Set[str]) -> bool:
    path_1 = path.lower()
    if path_1 == 'value' or path_1.endswith('value'):
        return True
    if any(k in path_1 for k in SENSITIVE_KEYWORDS):
        return True
    for sp in sensitive_paths:
        if path_1 == sp or path_1.startswith(sp + '.') or path_1.startswith(sp + '['):
            return True
    return False

def mask_value(value: Any) -> str:
    if value =='<absent>':
        return '<absent>'
    return '*******'

def diff_before_after(before: Any, after: Any, sensitive_paths: Set[str], unknown_paths: Set[str] = frozenset()) -> List[str]:
    if before is None and after is None and not unknown_paths:
        return []
    fb = flatten_dict(before) if isinstance(before, (dict, list)) else {"value": before}
    fa = flatten_dict(after) if isinstance(after, (dict, list)) else {"value": after}
    changes = []
    keys = set(fb.keys()) | set(fa.keys()) | set(unknown_paths)
    for k in sorted(keys):
        vb = fb.get(k, '<absent>')
        va = fa.get(k, '<absent>')
        is_unknown = k in unknown_paths
        if vb == va and not is_unknown:
            continue
        if is_sensitive_key_path(k, sensitive_paths):
            changes.append(f"{k}: {mask_value(vb)} -> {mask_value(va)}")
            continue
        # Shorten long values
        def shorten(v):
            s = str(v)
            return (s[:60] + '…') if len(s) > 60 else s
        if is_unknown and vb == va:
            # before/after look identical but the value won't be known until apply - a real change.
            changes.append(f"{k}: {shorten(vb)} -> (known after apply)")
            continue
        changes.append(f"{k}: {shorten(vb)} -> {shorten(va)}")
    return changes

# Skips module.<name>[<key>]. prefixes and an optional data. prefix, leaving the resource type segment.
ADDRESS_TYPE = re.compile(r'^(?:module\.[^.\[]+(?:\[[^\]]*\])?\.)*(?:data\.)?([^.\[]+)\.')


def collect_unknown_paths(change: Dict[str, Any]) -> Set[str]:
    # 'after_unknown' marks attributes with no real value until apply, even when before/after look identical.
    unknown = change.get('after_unknown')
    flat = flatten_dict(unknown) if isinstance(unknown, (dict, list)) else {}
    return {k for k, v in flat.items() if v is True}


def resource_type(rc: Dict[str, Any], addr: str) -> str:
    explicit = rc.get('type')
    if explicit:
        return explicit
    match = ADDRESS_TYPE.match(addr or '')
    return match.group(1) if match else ''

def summarize_resource_change(rc: Dict[str, Any]) -> Dict[str, Any]:
    addr = rc.get('address') or rc.get('name')
    change = rc.get('change') or {}
    actions = change.get('actions') or []
    before = change.get('before')
    after = change.get('after')
    sensitive_paths = collect_sensitive_paths(change)
    unknown_paths = collect_unknown_paths(change)
    diffs = diff_before_after(before, after, sensitive_paths, unknown_paths)
    # Determine tags-only: all diffs start with 'tags' key path
    tags_only = bool(diffs) and all(d.startswith('tags') or '.tags.' in d for d in diffs)
    # Determine change type
    change_type = 'update'
    if actions == ['create']:
        change_type = 'create'
    elif actions == ['delete']:
        change_type = 'delete'
    elif actions == ['update']:
        change_type = 'update'
    elif actions == ['delete', 'create'] or actions == ['create', 'delete']:
        change_type = 'replace'
    elif actions == ['no-op']:
        change_type = 'no changes'
    elif actions == ['read']:
        change_type = 'read'
    data_reads = rc.get('mode') == 'data' or actions == ['read']
    null_resource = resource_type(rc, addr) == 'null_resource'
    summary_lines = diffs[:25]  # cap to avoid huge prompts
    return {
        'address': addr,
        'actions': actions,
        'change_type': change_type,
        'diffs': summary_lines,
        'tags_only': tags_only,
        'data_read': data_reads,
        'null_resource': null_resource
    }

def build_json_summary_text(summaries: List[Dict[str, Any]]) -> str:
    parts = []
    for s in summaries:
        parts.append(f"ADDRESS: {s['address']}\nCHANGE: {s['change_type']} TAGS_ONLY: {str(s['tags_only']).lower()}\nDIFFS:\n" + ("\n".join(s['diffs']) if s['diffs'] else "<no scalar diff details>"))
        parts.append("---")
    return '\n'.join(parts)

## Resource name now uses full address unchanged.

def make_row_from_summary(stage: str, env: str, location: str, summary: Dict[str, Any]) -> str:
    res_name = summary.get('address', '') or ''
    # A replacement is never tags-only, however the diff reads: destroying the resource is never cosmetic.
    tags_only = 'Yes' if (summary['tags_only'] and summary['change_type'] == 'update') else 'No'
    data_read = 'Yes' if summary['data_read'] else 'No'
    null_resource = 'Yes' if summary['null_resource'] else 'No'
    # Combine up to first 3 diff lines for richer context
    if summary['tags_only'] and summary['change_type'] == 'update':
        details = 'tags updated'
    elif summary['diffs']:
        details = '; '.join(summary['diffs'][:3])
    else:
        details = summary['change_type']
    # Stage/env come from the filename and the rest from the plan, so every cell is escaped.
    cells = [stage, env, location, res_name, summary['change_type'], tags_only, data_read, null_resource, details]
    return '<tr>' + ''.join(f'<td>{html.escape(str(c), quote=True)}</td>' for c in cells) + '</tr>'

for pf in plan_files:
    file_name = os.path.basename(pf)
    raw = read_file_text(pf)
    stage_name, environment = derive_stage_and_env(file_name)
    plan_obj = load_json_plan_variants(raw)
    rc_list = plan_obj.get('resource_changes', []) or []
    summaries = [summarize_resource_change(rc) for rc in rc_list]
    print(f"Processing {file_name}: {len(rc_list)} resource change(s)", file=sys.stderr if args.consoleFrom else sys.stdout)
    for s in summaries:
        rn = s.get('address', '') or ''
        summaries_by_address.setdefault(rn, []).append(s)
        key = (stage_name, environment, rn)
        if key in seen_resources:
            continue
        seen_resources.add(key)
        html_rows.append(make_row_from_summary(stage_name, environment, 'uksouth', s))

ai_rows = '\n'.join(html_rows)

if args.consoleFrom:
    sys.stdout.reconfigure(encoding='utf-8')
    print(filter_console(read_file_text(args.consoleFrom), summaries_by_address))
    sys.exit(0)

if not ai_rows.strip():
    print("[WARN] No rows produced from JSON plans.")

# Load template
template_path = args.templateFile
if not os.path.isfile(template_path):
    raise FileNotFoundError(f"Template file not found: {template_path}")

with open(template_path, 'r', encoding='utf-8') as tf:
    template_html = tf.read()

# Locate tbody region
tbody_pattern = re.compile(r"(<tbody[^>]*>)([\s\S]*?)(</tbody>)", re.IGNORECASE)
m = tbody_pattern.search(template_html)
if not m:
    raise RuntimeError("Could not locate <tbody>...</tbody> section in template")

existing_rows = m.group(2)  # not used now, but kept for potential logging/debug
replacement_rows = '\n      <!-- Generated rows -->\n' + ai_rows + '\n    '

new_html = template_html[:m.start(2)] + replacement_rows + template_html[m.end(2):]

os.makedirs(args.outputDir, exist_ok=True)
output_path = os.path.join(args.outputDir, 'plan.html')
with open(output_path, 'w', encoding='utf-8') as outf:
    outf.write(new_html)

print(f"Generated plan HTML written to {output_path}")
