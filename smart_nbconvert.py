from openai import OpenAI
from pathlib import Path
import argparse
import json
import nbformat
import os
import re

from prompt import SYSTEM_PROMPT

def get_oai_client() -> OpenAI:
  key = os.getenv("OPENAI_API_KEY", None)
  if key is None:
    raise ValueError("OPENAI_API_KEY must be set")
  oai_client = OpenAI(api_key=key)
  return oai_client

def get_notebook_state(notebook: str) -> dict:
  with open(notebook, "r") as f:
    notebook = nbformat.read(f, as_version=4)
  print(f"Loaded notebook: {len(notebook.cells)} total cells")

  processed_cells = []
  images = []
  for c, cell in enumerate(notebook.cells):
    if cell['cell_type'] != 'code':
      processed_cells.append(cell)
    else:
      temp_cell = {k:v for k, v in cell.items() if k not in ['outputs']}
      temp_cell['outputs'] = []
      for output in cell['outputs']:
        temp_output = {p:q for p, q in output.items() if p not in ['data']}
        if 'data' in output:
          data_keys = list(output['data'].keys())
          if 'image/png' in data_keys:
            images.append({
              "type": "image_url",
              "image_url": {
                "url": f"data:image/jpeg;base64,{output['data']['image/png']}",
                "detail": "low"
              }
            })
            temp_output['data'] = {'image_idx': len(images)}
          else:
            temp_output['data'] = output['data']
        temp_cell['outputs'].append(temp_output)
      processed_cells.append(temp_cell)
  return {'cells': processed_cells, 'images': images}

def get_chat_messages(notebook_state: dict, instructions: str) -> list:
  content = []
  if instructions != '':
    content.append({"type": "text", "text": f"Goal for the report/project: {instructions}"})
  content.append({"type": "text", "text": f"<JupyterNotebookState>{json.dumps(notebook_state['cells'])}</JupyterNotebookState>"})
  content = content + notebook_state['images']
  messages=[
    {
      "role": "system",
      "content": SYSTEM_PROMPT
    },
    {
      "role": "user",
      "content": content
    }
  ]
  return messages

def replace_image_links(report_content: str, images: list) -> str:
  def replace_link(match):
    idx = int(match.group(1)) - 1
    return f'\n ![image_{idx+1}]({images[idx]["image_url"]["url"]}) \n'
  return re.sub(r'<image_idx>(\d+)</image_idx>', replace_link, report_content)


if "__main__" == __name__:
  parser = argparse.ArgumentParser()
  parser.add_argument("--notebook", "-n", type=str, required=True)
  parser.add_argument("--model", "-m", type=str, default="gpt-4o-mini")
  parser.add_argument("--instructions", "-i", type=str, default='')
  parser.add_argument("--output", "-o", type=str, default=None)
  args = parser.parse_args()

  oai_client = get_oai_client()
  notebook_state = get_notebook_state(args.notebook)
  messages = get_chat_messages(notebook_state, args.instructions)
  
  response = oai_client.chat.completions.create(
    model=args.model,
    messages=messages
  )

  summary_content = re.search(r'<summary>(.*?)</summary>', response.choices[0].message.content, re.DOTALL).group(1).strip()
  report_content = re.search(r'<report>(.*?)</report>', response.choices[0].message.content, re.DOTALL).group(1).strip()
  report_content = replace_image_links(report_content, notebook_state['images'])

  print(f"\n\nSummary: {summary_content}\n\n")

  if args.output is not None:
    filepath = Path(args.output)
  else:
    filepath = Path(args.notebook).parent / (Path(args.notebook).stem + "_report.md")
  with open(filepath, "w") as f:
    f.write(report_content)
  print(f"Report saved to {filepath}")
