import subprocess

def find_details():
    # Search for commits containing _strategy_card
    res = subprocess.run(["git", "log", "-S", "_strategy_card", "--oneline"], capture_output=True, text=True, encoding="utf-8")
    print("Commits touching _strategy_card:")
    print(res.stdout)
    
    commits = [line.split()[0] for line in res.stdout.strip().split("\n") if line.strip()]
    for commit in commits:
        print(f"\n--- COMMIT {commit} ---")
        show_res = subprocess.run(["git", "show", commit, "--", "quant_app/ui/app.py"], capture_output=True, text=True, encoding="utf-8", errors="ignore")
        lines = show_res.stdout.split("\n")
        
        # Look for _strategy_card definition or usage
        print_lines = False
        count = 0
        for i, line in enumerate(lines):
            if "_strategy_card" in line:
                print_lines = True
                count = 0
            if print_lines:
                print(line)
                count += 1
                if count > 80: # Print up to 80 lines after match
                    print_lines = False

if __name__ == "__main__":
    find_details()
