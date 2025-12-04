import os
import json
from typing import Dict, Any

# Base directory for saving annotations
# We can use a 'data' folder in the project root or backend root
BASE_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data"))

if not os.path.exists(BASE_DATA_DIR):
    os.makedirs(BASE_DATA_DIR)

def get_annotation_file_path(project_id: int) -> str:
    # Naming convention: project_{id}_annotations.jsonl
    filename = f"project_{project_id}_annotations.jsonl"
    return os.path.join(BASE_DATA_DIR, filename)

def append_jsonl(project_id: int, data: Dict[str, Any]) -> bool:
    """
    Appends a single record to the project's JSONL file.
    Ensures atomic-like write (though OS level appending is generally safe for text).
    """
    file_path = get_annotation_file_path(project_id)
    
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
