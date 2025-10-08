import os
import re
import requests
import argparse


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

def build_file_prompt(file_name: str, chunk_text: str, stage_name: str, environment: str, chunk_idx: int, total_chunks: int, seen_resource_names: set):
    seen_list = ', '.join(sorted(seen_resource_names)) if seen_resource_names else 'None'
    base_instructions = f"""
You are given a fragment ({chunk_idx}/{total_chunks}) of a terraform plan for file {file_name}.
Only output rows for resources present in THIS fragment. Do NOT repeat resources already emitted in previous fragments (Previously emitted resource names: {seen_list}).
Produce one <tr> per actual managed change with exactly 7 <td> cells in this order:
1) Stage Name (derived from the plan file name by stripping leading pattern tfplan-<env>- and the file extension; examples: tfplan-aat-network.txt -> network; tfplan-preview-platform.txt -> platform; tfplan-sbox-storage.txt -> storage. If pattern not found, use filename without extension.)
2) Environment (infer from plan file marker name if present: e.g. tfplan-aat-network.txt -> aat, tfplan-preview- -> preview, tfplan-sbox- or ptlsbox -> sandbox, perftest -> testing; keep lowercase; if not inferable derive from resource naming.)
3) Location (default 'uksouth' if unspecified)
4) Resource Name
5) Change Type (create | update | delete). Treat replacements ("-/+") as update unless it's a pure destroy.
6) Tags Only ('Yes' only if the Change Type is 'update' and the update being made is to change the values of Azure resource tags; else 'No').
7) If a resource is being created and that resource has tags then the Change Type should be 'create' and the Tags Only value should be 'No'
8) Details (succinct attribute/tag change notes, e.g. 'tags added', 'Kubernetes version change', 'max_count: 3 → 5').

Input plans are delimited by lines: --- <planfile> --- (planfile names are for deriving Stage Name & Environment only; DO NOT output the raw filename directly unless processed into Stage Name as specified).

Stage Name (already determined): {stage_name}
Environment (already determined): {environment}

If something is being updated, use 'update'.
If something is being destroyed or deleted, use 'delete'
If nothing is being changed, use 'no changes'
Ignore and DO NOT output rows for drift sections (changes outside of Terraform) or manual deletions where the plan simply recreates the resource; in those cases output only the resulting create action.
Exclude any lines that are commentary, import suggestions, or purely informational (# (known after apply), # (import ...)).
Return ONLY <tr> rows, no surrounding commentary.
Fragment Plan Content:\n\n{chunk_text}\n\n"""
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
        {"role": "system", "content": "You are an expert in Terraform plan interpretation and concise HTML row generation."},
        {"role": "user", "content": prompt_text}
    ], "temperature": 0.1, "max_tokens": 4096}
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

for pf in plan_files:
    file_name = os.path.basename(pf)
    raw = read_file_text(pf)
    stage_name, environment = derive_stage_and_env(file_name)
    chunks = chunk_plan(raw, args.chunkChars)
    print(f"Processing {file_name}: {len(raw)} chars -> {len(chunks)} chunk(s)")
    file_seen_names = set([n for (s,e,n) in seen_resources if s == stage_name and e == environment])
    for idx, chunk_text in enumerate(chunks, start=1):
        prompt_text = build_file_prompt(file_name, chunk_text, stage_name, environment, idx, len(chunks), {n for n in file_seen_names})
        ai_out = call_openai(prompt_text)
        if '<tr' not in ai_out.lower():
            print(f"[WARN] No <tr> rows returned for {file_name} chunk {idx}")
        else:
            # Deduplicate rows that contain already seen resource names
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

# Compose your prompt for ONLY table rows matching the new template's column order (Plan File column removed).
# Columns (in order now): Stage Name | Environment | Location | Resource Name | Change Type | Tags Only | Details
# Requirements:
#  - Change Type: create | update | delete (or destroy) derived from plan symbols (+, ~, -) or wording.
#  - Tags Only: 'Yes' ONLY if the ONLY change for that resource is tags/labels metadata; else 'No'.
#  - Location: if absent in plan, default to 'uksouth'.
#  - Ignore/exclude any drift sections or changes reported as "changed outside of Terraform" OR sections under notes like:
#       "Terraform detected the following changes made outside of Terraform" / "objects have changed outside of Terraform".
#    Do NOT emit rows for resources that are only mentioned in those drift sections. If a resource was deleted manually and will
#    be recreated, output only the creation (do not output a separate delete). If plan shows a replace ("-/+"), treat as update
#    unless it is a full destroy without recreation.
#  - Ignore any import suggestions or lines starting with "# (import" or "# (known after apply)" that don't constitute actual change actions.
#  - Escape HTML entities (&, <, >) in names or details.
#  - DO NOT wrap the output in <table>, <tbody>, <html>, or markdown fences. Return ONLY <tr> rows.
#  - Each <td> must be in the exact 7-column order above; no extra columns.
#  - List each resource occurrence separately; do not aggregate.

## Original single large prompt removed in favor of per-chunk prompts when needed.

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
