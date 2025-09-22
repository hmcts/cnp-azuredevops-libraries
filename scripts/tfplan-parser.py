import os  
import requests
import argparse


parser = argparse.ArgumentParser(description="Analyse terraform plans using AI")
parser.add_argument("--plans-dir", type=str, help="Specify the path to the plans directory")
parser.add_argument("--output-dir", type=str, help="Specify the path to the output directory")
args = parser.parse_args()

# Read all Terraform plans in the 'plans' folder and concatenate them
plans_dir = args.plans_dir
plan_files = [os.path.join(plans_dir, f) for f in os.listdir(plans_dir) if os.path.isfile(os.path.join(plans_dir, f))]
all_plans = []
for plan_file in plan_files:
    with open(plan_file) as f:
        all_plans.append(f"--- {os.path.basename(plan_file)} ---\n" + f.read())
tf_plan = "\n\n".join(all_plans)

# Compose your prompt
prompt = f"""
Parse these Terraform plan outputs and generate a single filterable HTML table.  
The filters should be based on resource type, environment, location, and whether the change is just to tags.  
If a resource does not have a location, assume it is uksouth.
Here are the plans:
{tf_plan}
Please only return the table in your response.
"""

OPEN_AI_ENDPOINT = os.environ["OPEN_AI_ENDPOINT"]
OPEN_AI_DEPLOYMENT = os.environ["OPEN_AI_DEPLOYMENT"]
  
# Azure OpenAI API details (replace with your endpoint/key/deployment)  
api_url = f"{OPEN_AI_ENDPOINT}/openai/deployments/{OPEN_AI_DEPLOYMENT}/chat/completions?api-version=2023-03-15-preview"
print(api_url)
headers = {  
    "api-key": os.environ["AZURE_OPENAI_API_KEY"],  
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
print(response.json())
html_output = response.json()["choices"][0]["message"]["content"]

# Remove leading ```html or ```HTML if present
if html_output.lstrip().lower().startswith('```html'):
    html_output = html_output.lstrip()[7:]
    # Remove a trailing triple backtick if present
    if html_output.rstrip().endswith('```'):
        html_output = html_output.rstrip()[:-3]

# Save the HTML file  
output_path = os.path.join(args.output_dir, "plan.html")
with open(output_path, "w") as f:
    f.write(html_output)
