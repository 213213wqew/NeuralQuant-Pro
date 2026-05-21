import os
import sys

def analyze_dir(path):
    if not os.path.exists(path):
        print(f"[ERROR] Path does not exist: {path}")
        return
        
    print(f"=== Analyzing Directory Size: {path} ===")
    total_size = 0
    file_list = []
    
    for root, dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                sz = os.path.getsize(fp)
                total_size += sz
                file_list.append((fp, sz))
            except Exception:
                pass
                
    print(f"Total Size: {total_size / (1024*1024):.2f} MB")
    
    # Sort files by size
    file_list.sort(key=lambda x: x[1], reverse=True)
    
    print("\n--- Top 30 Largest Files ---")
    for fp, sz in file_list[:30]:
        rel = os.path.relpath(fp, path)
        print(f"  {sz / (1024*1024):>7.2f} MB | {rel}")
        
    # Analyze by folder
    print("\n--- Folder Breakdown (Direct Children) ---")
    folder_sizes = {}
    for fp, sz in file_list:
        rel = os.path.relpath(fp, path)
        parts = rel.split(os.sep)
        if len(parts) > 1:
            child = parts[0]
        else:
            child = "[root files]"
        folder_sizes[child] = folder_sizes.get(child, 0) + sz
        
    sorted_folders = sorted(folder_sizes.items(), key=lambda x: x[1], reverse=True)
    for folder, sz in sorted_folders:
        print(f"  {sz / (1024*1024):>7.2f} MB | {folder}")

if __name__ == "__main__":
    # Check staging or dist
    paths_to_check = ["dist/AQuantPro", "dist_staging/AQuantPro"]
    found = False
    for p in paths_to_check:
        if os.path.exists(p):
            analyze_dir(p)
            found = True
            break
    if not found:
        print("[ERROR] Neither dist/AQuantPro nor dist_staging/AQuantPro exists. Please build the project first.")
