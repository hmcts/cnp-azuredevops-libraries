import os
import re
import json
import argparse
from typing import List, Dict, Any


script_dir = os.path.dirname(os.path.abspath(__file__))
default_template = os.path.join(script_dir, 'plan.html')

parser = argparse.ArgumentParser(description="Convert Terraform JSON plan(s) to HTML table rows (local only, no AI)")
parser.add_argument("--plansDir", type=str, required=True, help="Directory containing terraform plan JSON files (terraform show -json or concatenated resource change objects)")
parser.add_argument("--outputDir", type=str, required=True, help="Directory to write generated plan.html")
parser.add_argument("--templateFile", type=str, default=default_template, help=f"Path to HTML template (default: {default_template})")
args = parser.parse_args()

plans_dir = args.plansDir
plan_files = [os.path.join(plans_dir, f) for f in os.listdir(plans_dir) if os.path.isfile(os.path.join(plans_dir, f))]

def read_file_text(p):
    with open(p, 'r', encoding='utf-8', errors='replace') as fh:
        return fh.read()


# Collect rows
html_rows: List[str] = []
seen_resources = set()  # (stage, env, resource_name)

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

def diff_before_after(before: Any, after: Any) -> List[str]:
    if before is None and after is None:
        return []
    fb = flatten_dict(before) if isinstance(before, (dict, list)) else {"value": before}
    fa = flatten_dict(after) if isinstance(after, (dict, list)) else {"value": after}
    changes = []
    keys = set(fb.keys()) | set(fa.keys())
    for k in sorted(keys):
        vb = fb.get(k, '<absent>')
        va = fa.get(k, '<absent>')
        if vb == va:
            continue
        # Shorten long values
        def shorten(v):
            s = str(v)
            return (s[:60] + '…') if len(s) > 60 else s
        changes.append(f"{k}: {shorten(vb)} -> {shorten(va)}")
    return changes

def summarize_resource_change(rc: Dict[str, Any]) -> Dict[str, Any]:
    addr = rc.get('address') or rc.get('name')
    change = rc.get('change') or {}
    actions = change.get('actions') or []
    before = change.get('before')
    after = change.get('after')
    diffs = diff_before_after(before, after)
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
        change_type = 'update'
    elif actions == ['no-op']:
        change_type = 'no changes'
    summary_lines = diffs[:25]  # cap to avoid huge prompts
    return {
        'address': addr,
        'actions': actions,
        'change_type': change_type,
        'diffs': summary_lines,
        'tags_only': tags_only
    }

def build_json_summary_text(summaries: List[Dict[str, Any]]) -> str:
    parts = []
    for s in summaries:
        parts.append(f"ADDRESS: {s['address']}\nCHANGE: {s['change_type']} TAGS_ONLY: {str(s['tags_only']).lower()}\nDIFFS:\n" + ("\n".join(s['diffs']) if s['diffs'] else "<no scalar diff details>"))
        parts.append("---")
    return '\n'.join(parts)

def resource_name_from_address(address: str) -> str:
    if not address:
        return ''
    # remove module prefixes
    parts = address.split('.')
    last = parts[-1]
    # handle index or key
    last = re.sub(r'\["?([^\]]+)"?\]$', r'\1', last)
    last = last.replace('"', '')
    return last

def make_row_from_summary(stage: str, env: str, location: str, summary: Dict[str, Any]) -> str:
    res_name = resource_name_from_address(summary['address'])
    tags_only = 'Yes' if (summary['tags_only'] and summary['change_type'] == 'update') else 'No'
    # Combine up to first 3 diff lines for richer context
    if summary['tags_only'] and summary['change_type'] == 'update':
        details = 'tags updated'
    elif summary['diffs']:
        details = '; '.join(summary['diffs'][:3])
    else:
        details = summary['change_type']
    details = details.replace('<', '&lt;').replace('>', '&gt;')
    return f"<tr><td>{stage}</td><td>{env}</td><td>{location}</td><td>{res_name}</td><td>{summary['change_type']}</td><td>{tags_only}</td><td>{details}</td></tr>"

for pf in plan_files:
    file_name = os.path.basename(pf)
    raw = read_file_text(pf)
    stage_name, environment = derive_stage_and_env(file_name)
    plan_obj = load_json_plan_variants(raw)
    rc_list = plan_obj.get('resource_changes', []) or []
    summaries = [summarize_resource_change(rc) for rc in rc_list]
    print(f"Processing {file_name}: {len(rc_list)} resource change(s)")
    for s in summaries:
        rn = resource_name_from_address(s['address'])
        key = (stage_name, environment, rn)
        if key in seen_resources:
            continue
        seen_resources.add(key)
        html_rows.append(make_row_from_summary(stage_name, environment, 'uksouth', s))

ai_rows = '\n'.join(html_rows)
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
