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
args = parser.parse_args()

# Read all Terraform plans in the 'plans' folder and concatenate them
plans_dir = args.plansDir
plan_files = [os.path.join(plans_dir, f) for f in os.listdir(plans_dir) if os.path.isfile(os.path.join(plans_dir, f))]
all_plans = []
for plan_file in plan_files:
    with open(plan_file) as f:
        all_plans.append(f"--- {os.path.basename(plan_file)} ---\n" + f.read())
tf_plan = "\n\n".join(all_plans)
print(f"The tfplan looks like this: {tf_plan}")

# Compose your prompt for ONLY table rows matching the new template's column order (Plan File column removed).
# Columns (in order now): Stage Name | Environment | Location | Resource Name | Change Type | Tags Only | Details
# Requirements:
#  - Change Type: create | update in-place | delete (or destroy) derived from plan symbols (+, ~, -) or wording.
#  - Tags Only: 'Yes' ONLY if the ONLY change for that resource is tags/labels metadata; else 'No'.
#  - Location: if absent in plan, default to 'uksouth'.
#  - Ignore/exclude any drift sections or changes reported as "changed outside of Terraform" OR sections under notes like:
#       "Terraform detected the following changes made outside of Terraform" / "objects have changed outside of Terraform".
#    Do NOT emit rows for resources that are only mentioned in those drift sections. If a resource was deleted manually and will
#    be recreated, output only the creation (do not output a separate delete). If plan shows a replace ("-/+"), treat as update in-place
#    unless it is a full destroy without recreation.
#  - Ignore any import suggestions or lines starting with "# (import" or "# (known after apply)" that don't constitute actual change actions.
#  - Escape HTML entities (&, <, >) in names or details.
#  - DO NOT wrap the output in <table>, <tbody>, <html>, or markdown fences. Return ONLY <tr> rows.
#  - Each <td> must be in the exact 7-column order above; no extra columns.
#  - List each resource occurrence separately; do not aggregate.

prompt = f"""
You are given concatenated terraform plan outputs. Produce one HTML <tr> row per actual Terraform managed change (excluding drift-only changes) with exactly 7 <td> cells in this order:
1) Stage Name (derived from the plan file name by stripping leading pattern tfplan-<env>- and the file extension; examples: tfplan-aat-network.txt -> network; tfplan-preview-platform.txt -> platform; tfplan-sbox-storage.txt -> storage. If pattern not found, use filename without extension.)
2) Environment (infer from plan file marker name if present: e.g. tfplan-aat-network.txt -> aat, tfplan-preview- -> preview, tfplan-sbox- or ptlsbox -> sandbox, perftest -> testing; keep lowercase; if not inferable derive from resource naming.)
3) Location (default 'uksouth' if unspecified)
4) Resource Name
5) Change Type (create | update in-place | delete). Treat replacements ("-/+") as update in-place unless it's a pure destroy.
6) Tags Only ('Yes' only if ONLY tag metadata differs; else 'No').
7) If a resource is being created and that resource has tags then the Change Type should be 'create' and the Tags Only value should be 'No'
8) Details (succinct attribute/tag change notes, e.g. 'tags added', 'Kubernetes version change', 'max_count: 3 → 5').

Ignore and DO NOT output rows for drift sections (changes outside of Terraform) or manual deletions where the plan simply recreates the resource; in those cases output only the resulting create action.
Exclude any lines that are commentary, import suggestions, or purely informational (# (known after apply), # (import ...)).

Input plans are delimited by lines: --- <planfile> --- (planfile names are for deriving Stage Name & Environment only; DO NOT output the raw filename directly unless processed into Stage Name as specified).

Terraform Plans:
{tf_plan}

Return ONLY <tr> rows, no code fences or additional commentary.
"""

OPEN_AI_ENDPOINT = args.endpoint
OPEN_AI_DEPLOYMENT = args.deployment
AZURE_OPENAI_API_KEY = args.apiKey
  
# Azure OpenAI API details (replace with your endpoint/key/deployment)  
api_url = f"{OPEN_AI_ENDPOINT}/openai/deployments/{OPEN_AI_DEPLOYMENT}/chat/completions?api-version=2023-03-15-preview"
print(api_url)
headers = {
    "api-key": f"{AZURE_OPENAI_API_KEY}",
    "Content-Type": "application/json"  
}  
payload = {  
    "messages": [  
        {"role": "system", "content": "You are an expert in HTML and Terraform."},  
        {"role": "user", "content": prompt}  
    ],  
    "temperature": 0.2,  
    "max_tokens": 8192  
}  
  
response = requests.post(api_url, headers=headers, json=payload)
resp_json = response.json()
print(resp_json)  # basic debug

try:
    ai_rows = resp_json["choices"][0]["message"]["content"]
except (KeyError, IndexError) as e:
    raise RuntimeError(f"Unexpected response format from Azure OpenAI: {resp_json}") from e

# Strip code fences if present
fenced_match = re.match(r"```(?:html|HTML)?\n([\s\S]*?)```", ai_rows.strip())
if fenced_match:
    ai_rows = fenced_match.group(1).strip()

# Remove any accidental outer <table> or <tbody> wrappers to keep only <tr>
ai_rows = re.sub(r"</?(?:table|tbody)[^>]*>", "", ai_rows, flags=re.IGNORECASE)

# Basic sanity: keep only lines containing <tr>
if '<tr' not in ai_rows.lower():
    print("[WARN] AI output did not contain <tr>; writing raw output for inspection.")

# --- Post-process to correct 'Tags Only' column heuristically if AI misclassified ---
def _is_tag_only_details(text: str) -> bool:
    tl = text.lower().strip()
    if 'tag' not in tl:
        return False
    # Positive indicative patterns
    positive_patterns = [
        'tags added', 'tags removed', 'tags changed', 'tag added', 'tag removed', 'tag changed',
        'builtfrom tag changed', 'environment tag changed', 'criticality tag changed'
    ]
    if any(p in tl for p in positive_patterns):
        # Exclude if other non-tag keywords suggesting broader changes
        forbidden = ['version', 'count', 'size', 'sku', 'role', 'orchestrator', 'max_', 'capacity', 'image', 'policy', 'network', 'subnet']
        if not any(f in tl for f in forbidden):
            # Also exclude if arrow changes present for non-tag attributes (colon or arrow patterns without 'tag')
            structural_change = ('→' in tl or '->' in tl or ':' in tl)
            # If structural change exists but every segment with arrow/colon also contains 'tag', still ok
            if structural_change:
                # Split on commas or semicolons; if any segment with arrow/colon lacks 'tag', treat as not tag-only
                segments = re.split(r'[;,]', tl)
                for seg in segments:
                    if ('→' in seg or '->' in seg or ':' in seg) and 'tag' not in seg:
                        return False
            return True
    return False

def _fix_tag_only(ai_html: str) -> str:
    row_re = re.compile(r'(<tr[^>]*>)([\s\S]*?)(</tr>)', re.IGNORECASE)
    td_re = re.compile(r'<td[^>]*>([\s\S]*?)</td>', re.IGNORECASE)
    out = []
    modified = 0
    pos = 0
    for m in row_re.finditer(ai_html):
        out.append(ai_html[pos:m.start()])
        row_html = m.group(0)
        tds = td_re.findall(row_html)
        # Expect 7 columns now: Stage Name, Environment, Location, Resource Name, Change Type, Tags Only, Details
        if len(tds) == 7:
            tags_only_val = tds[5].strip().lower()
            details_val = re.sub(r'<[^>]+>', '', tds[6])  # strip inner HTML if any
            if tags_only_val in ('no', 'n', 'false') and _is_tag_only_details(details_val):
                # Replace the 6th td content with 'Yes'
                # Reconstruct row by substituting only that td
                def replace_td(match):
                    nonlocal modified
                    inner = match.group(1)
                    idx = replace_td.idx
                    replace_td.idx += 1
                    if idx == 5:
                        modified += 1
                        return match.group(0).replace(inner, 'Yes')
                    return match.group(0)
                replace_td.idx = 0
                row_html = td_re.sub(replace_td, row_html)
        out.append(row_html)
        pos = m.end()
    out.append(ai_html[pos:])
    if modified:
        print(f"[INFO] Corrected Tags Only classification for {modified} row(s)")
    return ''.join(out)

ai_rows = _fix_tag_only(ai_rows)

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
