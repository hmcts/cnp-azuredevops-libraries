import os
import re
import json
import argparse
import requests
from typing import List, Dict, Any, Iterable


script_dir = os.path.dirname(os.path.abspath(__file__))
default_template = os.path.join(script_dir, 'plan.html')

parser = argparse.ArgumentParser(description="Analyse terraform plans using AI and inject results into HTML template")
parser.add_argument("--plansDir", type=str, required=True, help="Path to the directory containing terraform plan text files")
parser.add_argument("--outputDir", type=str, required=True, help="Directory to write generated plan.html")
parser.add_argument("--endpoint", type=str, required=True, help="Azure OpenAI endpoint base URL (e.g. https://my-resource.openai.azure.com)")
parser.add_argument("--deployment", type=str, required=True, help="Azure OpenAI model deployment name")
parser.add_argument("--apiKey", type=str, required=True, help="Azure OpenAI API key")
parser.add_argument("--templateFile", type=str, default=default_template, help=f"Path to HTML template (default: {default_template})")
parser.add_argument("--chunkChars", type=int, default=12000, help="Approximate maximum characters of plan text per AI request (large plans are split)")
parser.add_argument("--assumeJson", action="store_true", help="Treat all plan files as JSON (terraform show -json or concatenated resource change objects)")
parser.add_argument("--noAI", action="store_true", help="If set, skip AI calls and emit rows generated locally from JSON (only for JSON plans)")
args = parser.parse_args()

plans_dir = args.plansDir
plan_files = [os.path.join(plans_dir, f) for f in os.listdir(plans_dir) if os.path.isfile(os.path.join(plans_dir, f))]

def read_file_text(p):
    with open(p, 'r', encoding='utf-8', errors='replace') as fh:
        return fh.read()

# ---- Chunking helpers ----
def estimate_tokens(text: str) -> int:
    # Rough heuristic: 1 token ~ 4 chars
    return max(1, len(text)//4)

def chunk_plan(plan_text: str, max_chars: int):
    if len(plan_text) <= max_chars:
        return [plan_text]
    lines = plan_text.splitlines()
    chunks = []
    cur = []
    cur_len = 0
    safe_boundary_patterns = re.compile(r'^(# |Terraform will perform the following actions|Plan: |\s*$)')
    for line in lines:
        # Always append first; we'll decide split after potential boundary
        cur.append(line)
        cur_len += len(line) + 1
        if cur_len >= max_chars and safe_boundary_patterns.match(line):
            chunks.append('\n'.join(cur))
            cur = []
            cur_len = 0
    if cur:
        chunks.append('\n'.join(cur))
    # Fallback: ensure no empty
    return [c for c in chunks if c.strip()]

# We'll process each plan file separately, chunking as necessary

# Collect rows from all AI calls
all_ai_rows = []
seen_resources = set()  # key: (stage_name, environment, resource_name)

def build_file_prompt(file_name: str, chunk_text: str, stage_name: str, environment: str, chunk_idx: int, total_chunks: int, seen_resource_names: set, is_json_summary: bool=False):
    seen_list = ', '.join(sorted(seen_resource_names)) if seen_resource_names else 'None'
    source_desc = "JSON summary of resource changes" if is_json_summary else "fragment of a terraform plan"
    base_instructions = f"""
You are given a fragment ({chunk_idx}/{total_chunks}) consisting of a {source_desc} for file {file_name}.
Only output rows for resources present in THIS fragment. Do NOT repeat resources already emitted in previous fragments (Previously emitted resource names: {seen_list}).
Produce one <tr> per actual managed change with exactly 7 <td> cells in this order:
1) Stage Name (already provided below)
2) Environment (already provided below)
3) Location (default 'uksouth' if unknown or not given)
4) Resource Name (derive from the resource address: use last segment after last '.' or bracket)
5) Change Type (create | update | delete). Treat replacements (delete+create) as update unless it is a pure destroy.
6) Tags Only ('Yes' only if and only if every reported change ONLY alters tags; otherwise 'No'). Creations are always 'No'.
7) Details (succinct attribute/tag change notes, e.g. 'tags added', 'sku.capacity: 1001 → 250'). Use 'tags updated' if exclusively tag modifications.

IMPORTANT:
- Do NOT hallucinate resources not present in the fragment.
- Omit unchanged or purely informational items.
- Use lowercase for change type values.
- Never include commentary outside <tr> elements.

Context:
Stage Name: {stage_name}
Environment: {environment}

Fragment Content Start >>>\n{chunk_text}\n<<< Fragment Content End
"""
    return base_instructions

def derive_stage_and_env(file_name: str):
    base = re.sub(r'\.txt$', '', file_name)
    # Expect patterns like tfplan-<env>-<stage>
    m = re.match(r'^tfplan-([a-z0-9]+?)-(.+)$', base)
    environment = 'unknown'
    stage = base
    if m:
        environment = m.group(1)
        stage = m.group(2)
    stage = stage.replace('tfplan-', '')
    return stage, environment

def call_openai(prompt_text: str):
    api_url = f"{args.endpoint}/openai/deployments/{args.deployment}/chat/completions?api-version=2023-03-15-preview"
    headers = {"api-key": args.apiKey, "Content-Type": "application/json"}
    payload = {"messages": [
        {"role": "system", "content": "You convert structured Terraform plan change summaries into minimal HTML <tr> rows with exactly 7 <td> cells as specified."},
        {"role": "user", "content": prompt_text}
    ], "temperature": 0.2, "max_completion_tokens": 2048}
    resp = requests.post(api_url, headers=headers, json=payload, timeout=120)
    rj = resp.json()
    try:
        content = rj['choices'][0]['message']['content']
    except Exception:
        raise RuntimeError(f"Unexpected Azure OpenAI response: {rj}")
    # Strip code fences and extraneous wrappers
    fm = re.match(r"```(?:html|HTML)?\n([\s\S]*?)```", content.strip())
    if fm:
        content = fm.group(1).strip()
    content = re.sub(r"</?(?:table|tbody)[^>]*>", "", content, flags=re.IGNORECASE)
    return content

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

# ---------------- JSON PLAN SUPPORT -----------------

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
    details = 'tags updated' if (summary['tags_only'] and summary['change_type'] == 'update') else (summary['diffs'][0] if summary['diffs'] else summary['change_type'])
    details = details.replace('<', '&lt;').replace('>', '&gt;')
    return f"<tr><td>{stage}</td><td>{env}</td><td>{location}</td><td>{res_name}</td><td>{summary['change_type']}</td><td>{tags_only}</td><td>{details}</td></tr>"

for pf in plan_files:
    file_name = os.path.basename(pf)
    raw = read_file_text(pf)
    stage_name, environment = derive_stage_and_env(file_name)
    is_json = args.assumeJson or file_name.lower().endswith('.json')
    if is_json:
        plan_obj = load_json_plan_variants(raw)
        rc_list = plan_obj.get('resource_changes', []) or []
        summaries = [summarize_resource_change(rc) for rc in rc_list]
        if args.noAI:
            # Direct row generation
            for s in summaries:
                rn = resource_name_from_address(s['address'])
                key = (stage_name, environment, rn)
                if key in seen_resources:
                    continue
                seen_resources.add(key)
                all_ai_rows.append(make_row_from_summary(stage_name, environment, 'uksouth', s))
            print(f"Processed {file_name} (JSON) locally: {len(summaries)} summaries -> {len(all_ai_rows)} total rows")
            continue
        summary_text = build_json_summary_text(summaries)
        chunks = chunk_plan(summary_text, args.chunkChars)
        print(f"Processing {file_name} (JSON): {len(summary_text)} chars summary -> {len(chunks)} chunk(s)")
        file_seen_names = set([n for (s,e,n) in seen_resources if s == stage_name and e == environment])
        for idx, chunk_text in enumerate(chunks, start=1):
            prompt_text = build_file_prompt(file_name, chunk_text, stage_name, environment, idx, len(chunks), {n for n in file_seen_names}, is_json_summary=True)
            ai_out = call_openai(prompt_text)
            if '<tr' not in ai_out.lower():
                print(f"[WARN] No <tr> rows returned for {file_name} chunk {idx}")
            else:
                added_rows = []
                row_blocks = re.findall(r'<tr[\s\S]*?</tr>', ai_out, flags=re.IGNORECASE)
                for rb in row_blocks:
                    cells = re.findall(r'<td[^>]*>([\s\S]*?)</td>', rb, flags=re.IGNORECASE)
                    if len(cells) >= 4:
                        rn = re.sub(r'<[^>]+>', '', cells[3]).strip()
                        key = (stage_name, environment, rn)
                        if key in seen_resources:
                            continue
                        seen_resources.add(key)
                        file_seen_names.add(rn)
                        added_rows.append(rb)
                if added_rows:
                    all_ai_rows.append('\n'.join(added_rows))
    else:
        chunks = chunk_plan(raw, args.chunkChars)
        print(f"Processing {file_name}: {len(raw)} chars -> {len(chunks)} chunk(s)")
        file_seen_names = set([n for (s,e,n) in seen_resources if s == stage_name and e == environment])
        for idx, chunk_text in enumerate(chunks, start=1):
            prompt_text = build_file_prompt(file_name, chunk_text, stage_name, environment, idx, len(chunks), {n for n in file_seen_names})
            ai_out = call_openai(prompt_text)
            if '<tr' not in ai_out.lower():
                print(f"[WARN] No <tr> rows returned for {file_name} chunk {idx}")
            else:
                added_rows = []
                row_blocks = re.findall(r'<tr[\s\S]*?</tr>', ai_out, flags=re.IGNORECASE)
                for rb in row_blocks:
                    cells = re.findall(r'<td[^>]*>([\s\S]*?)</td>', rb, flags=re.IGNORECASE)
                    if len(cells) >= 4:
                        rn = re.sub(r'<[^>]+>', '', cells[3]).strip()
                        key = (stage_name, environment, rn)
                        if key in seen_resources:
                            continue
                        seen_resources.add(key)
                        file_seen_names.add(rn)
                        added_rows.append(rb)
                if added_rows:
                    all_ai_rows.append('\n'.join(added_rows))

tf_plan = ''  # No longer using concatenated big prompt; variable kept for backward compatibility logging

ai_rows = '\n'.join(all_ai_rows)
if not ai_rows.strip():
    print("[WARN] No AI rows produced.")

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
