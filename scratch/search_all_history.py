import subprocess

def main():
    # We want to search git log of quant_app/ui/app.py for any commit diff containing the Chinese word "方格" or "网格" or similar.
    # We can also search for code that generated strategy buttons or cards.
    cmd = ["git", "log", "-p", "quant_app/ui/app.py"]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    
    keywords = ["方格", "网格", "strategy_cards", "PresetGrid", "StrategyGrid", "GridView", "strategy_card", "preset_grid"]
    lines = res.stdout.split("\n")
    found_commits = {}
    current_commit = None
    
    for line in lines:
        if line.startswith("commit "):
            current_commit = line.strip()
        for kw in keywords:
            if kw in line:
                if current_commit not in found_commits:
                    found_commits[current_commit] = []
                found_commits[current_commit].append(line)
                
    for commit, matches in found_commits.items():
        print(f"Commit: {commit}")
        for match in matches[:5]:
            print(f"  Match: {match}")
            
if __name__ == "__main__":
    main()
