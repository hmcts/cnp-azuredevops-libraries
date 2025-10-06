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

# Compose your prompt for ONLY table rows matching the new template's column order.
# Columns (in order): Plan File | Resource Type | Resource Name | Environment | Location | Change Type | Tags Only | Details
# Requirements:
#  - Change Type: use concise verbs: create | update in-place | delete (or destroy) as per plan semantics
#  - Tags Only: 'Yes' ONLY if the ONLY detected changes for that resource are tag additions/removals/modifications; otherwise 'No'.
#  - Location: if absent in plan, use 'uksouth'.
#  - Plan File: must be the originating plan file name (e.g. tfplan-aat-network.txt) exactly as provided between --- markers.
#  - Escape HTML entities in names or details (&, <, >).
#  - DO NOT wrap the output in <table>, <tbody>, <html>, or markdown fences. Return ONLY one or more <tr>...</tr> rows.
#  - Each <td> must be in the exact column order; do not add extra columns.
#  - Avoid summarising across environments; list each resource occurrence separately.

prompt = f"""
You are given concatenated terraform plan outputs. For EACH resource change produce one HTML table row (<tr>...</tr>) with exactly 8 <td> cells in this order:
1) Plan File
2) Resource Type
3) Resource Name
4) Environment (infer from filename if embedded e.g. tfplan-aat-network.txt -> aat, tfplan-preview-aks.txt -> preview, tfplan-sbox- -> sandbox, ptlsbox -> sandbox, perftest -> testing, if ambiguous leave as given or derive from resource naming). Keep original environment token (lowercase).
5) Location (default 'uksouth' if not present)
6) Change Type (create | update in-place | delete) matching plan semantics (+ create, ~ update, - delete)
7) Tags Only (Yes if ONLY tag changes else No)
8) Details (concise: list key attribute changes or 'tags added', 'tags removed', 'tags changed', 'Kubernetes version change', etc.)

Input plans below delimited by lines beginning with '--- <planfile> ---'. Use the planfile for column 1.

Terraform Plans:
{tf_plan}

Return ONLY <tr> rows, no surrounding code fences or commentary.
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
