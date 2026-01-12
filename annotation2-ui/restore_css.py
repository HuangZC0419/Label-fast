
import os

# Use relative paths assuming cwd is annotation2-ui
dist_path = os.path.join("dist", "assets", "index-BabP2RLM.css")
src_path = os.path.join("src", "App.css")

if not os.path.exists(dist_path):
    print(f"Error: {dist_path} not found")
    exit(1)

with open(dist_path, "r", encoding="utf-8") as f:
    content = f.read()

# Simple formatting to make it readable (optional, but good for future edits)
# Replace '}' with '}\n'
# Replace '{' with ' {\n'
# Replace ';' with ';\n'
# Note: This is naive but works for standard CSS structure.
formatted = content.replace("}", "}\n").replace("{", " {\n").replace(";", ";\n")

with open(src_path, "w", encoding="utf-8") as f:
    f.write(formatted)

print(f"Restored {src_path} from {dist_path}")
