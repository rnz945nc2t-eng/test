import os
import json

def generate_index(root_dir):
    index = {
        "Applications": [],
        "Core Assets": [],
        "Vault": []
    }

    # Categorization logic
    apps_keywords = ['html', 'app', 'ui', 'controller', 'service']
    core_keywords = ['pdf', 'doc', 'md', 'vision', 'article', 'report', 'audit']

    # Sensitive files to exclude
    exclude_files = ['SECRETS.pdf', 'file-index.json', 'server.log', '.git']
    exclude_dirs = ['.git', '__pycache__', 'node_modules']

    for root, dirs, files in os.walk(root_dir):
        # Filter directories in-place
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        rel_path = os.path.relpath(root, root_dir)
        if rel_path == '.':
            rel_path = ''

        for file in files:
            if file in exclude_files:
                continue
            file_path = os.path.join(rel_path, file)
            ext = file.split('.')[-1].lower() if '.' in file else ''

            entry = {
                "name": file,
                "path": file_path,
                "size": os.path.getsize(os.path.join(root, file))
            }

            # Categorize
            if 'GIGA' in root:
                index["Vault"].append(entry)
            elif ext == 'html' or any(k in file.lower() for k in apps_keywords):
                index["Applications"].append(entry)
            elif ext in ['pdf', 'md'] or any(k in file.lower() for k in core_keywords):
                index["Core Assets"].append(entry)
            else:
                index["Vault"].append(entry)

    return index

if __name__ == "__main__":
    public_dir = "public"
    if os.path.exists(public_dir):
        index_data = generate_index(public_dir)
        with open(os.path.join(public_dir, "file-index.json"), "w") as f:
            json.dump(index_data, f, indent=2)
        print("Generated public/file-index.json")
    else:
        print("public/ directory not found")
