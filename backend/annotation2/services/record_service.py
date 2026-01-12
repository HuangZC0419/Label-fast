import os
import json
from typing import Dict, Any

# Base directory for saving annotations
# We can use a 'data' folder in the project root or backend root
BASE_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data"))

if not os.path.exists(BASE_DATA_DIR):
    os.makedirs(BASE_DATA_DIR)

def get_annotation_file_path(project_id: int, project_name: str = None) -> str:
    # Naming convention: data/{project_name}/annotations.jsonl
    if project_name:
        # Sanitize project name to be safe for filenames
        safe_name = "".join([c for c in project_name if c.isalnum() or c in (' ', '-', '_')]).strip()
        project_dir = os.path.join(BASE_DATA_DIR, safe_name)
        if not os.path.exists(project_dir):
            os.makedirs(project_dir)
        return os.path.join(project_dir, "annotations.jsonl")
    
    # Fallback to old behavior if name not provided
    filename = f"project_{project_id}_annotations.jsonl"
    return os.path.join(BASE_DATA_DIR, filename)

def append_jsonl(project_id: int, data: Dict[str, Any]) -> bool:
    """
    Appends a single record to the project's JSONL file.
    Ensures atomic-like write (though OS level appending is generally safe for text).
    """
    project_name = data.get("meta", {}).get("project_name")
    file_path = get_annotation_file_path(project_id, project_name)
    
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # Prepare JSON string with newline
        json_line = json.dumps(data, ensure_ascii=False) + "\n"
        
        # Append mode 'a'
        with open(file_path, 'a', encoding='utf-8') as f:
            f.write(json_line)
            
        return True
    except Exception as e:
        print(f"Error appending to JSONL: {e}")
        raise e
