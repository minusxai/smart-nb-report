from openai import OpenAI
from pathlib import Path
import argparse
import json
import nbformat
import os
import re


def get_oai_client():
  key = os.getenv("OPENAI_API_KEY", None)
  if key is None:
    raise ValueError("OPENAI_API_KEY must be set")
  oai_client = OpenAI(api_key=key)
  return oai_client

def get_notebook_state(notebook):
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

def get_chat_messages(notebook_state):
  messages=[
    {
      "role": "system",
      "content": '''You're an expert data scientist and proficient at communicating complex analysis. the goal is to take the user's jupyter notebook state and images and create a detailed report using markdown.
                    Routine to follow:
                    1. Think step by step about the point of the notebook and write a summary inside <summary> tags.
                        Think of information to add, and irrelevant information to skip. You do not need to include every single cell or image.
                        Also feel free to reorder content to make it most insightful and informative. Use the summary to outline the structure of the report.
                    2. Write a detailed markdown report inside <report> tags. The report needs to contain:
                      a. A title
                      b. A table of contents
                      c. Clear sections with headings
                      d. Wherever the plot or image needs to be inserted, use <image_idx> tag, where idx is the index of the image.
                      If needed, write a description of what the image contains, call out any interesting trends or patterns.
                      e. Write a nice conclusion and actionable insights at the end. the conclusions or the actionables should not be generic. It should be specific recommendations, and clear to dos, in simple words.

                  Important instructions:
                  - Do not write code in the report unless it is necessary to demonstrate something
                  - Spend time on the results, conclusions and actionable insights
                  - Do not include silly text or pedestrian sentences. This is a serious and important report.
      '''
    },
    {
      "role": "user",
      "content": [
        {"type": "text", "text": f"<JupyterNotebookState>{json.dumps(notebook_state['cells'])}</JupyterNotebookState>"},
      ] + notebook_state['images']
    }
  ]
  return messages

def replace_image_links(report_content, images):
  def replace_link(match):
    idx = int(match.group(1)) - 1
    return f'\n ![image_{idx+1}]({images[idx]["image_url"]["url"]}) \n'
  return re.sub(r'<image_idx>(\d+)</image_idx>', replace_link, report_content)


if "__main__" == __name__:
  parser = argparse.ArgumentParser()
  parser.add_argument("--notebook", type=str, required=True)
  parser.add_argument("--model", type=str, default="gpt-4o-mini")
  args = parser.parse_args()

  oai_client = get_oai_client()
  notebook_state = get_notebook_state(args.notebook)
  messages = get_chat_messages(notebook_state)
  
  response = oai_client.chat.completions.create(
    model=args.model,
    messages=messages
  )

  summary_content = re.search(r'<summary>(.*?)</summary>', response.choices[0].message.content, re.DOTALL).group(1).strip()
  report_content = re.search(r'<report>(.*?)</report>', response.choices[0].message.content, re.DOTALL).group(1).strip()
  report_content = replace_image_links(report_content, notebook_state['images'])

  print(f"\n\nSummary: {summary_content}\n\n")

  filepath = Path(args.notebook).parent / (Path(args.notebook).stem + "_report.md")
  with open(filepath, "w") as f:
    f.write(report_content)
  print(f"Report saved to {filepath}")
