import subprocess
import re

def search():
    print("Searching git log for strategy-related UI changes in app.py...")
    # Run git log -p on app.py and search for strategy list/selection changes
    res = subprocess.run(["git", "log", "-p", "-G", "strategy", "quant_app/ui/app.py"], capture_output=True, text=True, encoding="utf-8", errors="ignore")
    lines = res.stdout.split("\n")
    print(f"Total lines of log: {len(lines)}")
    
    # We want to find any mentions of grid, card, dropdown, GridMartingale, buttons, etc. in the diffs
    current_commit = None
    commit_lines = []
    
    for line in lines:
        if line.startswith("commit "):
            if current_commit:
                process_commit(current_commit, commit_lines)
            current_commit = line
            commit_lines = [line]
        elif current_commit:
            commit_lines.append(line)
            
    if current_commit:
        process_commit(current_commit, commit_lines)

def process_commit(commit_id, lines):
    # Check if lines contain terms like "grid", "方格", "Dropdown", "Option", "GridMartingale"
    text = "\n".join(lines)
    if "方格" in text or "网格" in text or "grid" in text.lower():
        # Print commit header
        print("="*60)
        for line in lines[:10]:
            print(line)
        print("...")
        # Print matching context
        for line in lines:
            if any(term in line.lower() for term in ["方格", "网格", "dropdown", "option", "grid_view", "gridview", "card"]):
                if line.startswith("+") or line.startswith("-"):
                    print(line[:120])

if __name__ == "__main__":
    search()
