import subprocess

def main():
    cmd = ["git", "show", "a3ed9938634f3b360dbaefc3e8c2579be34baf56", "--", "quant_app/ui/app.py"]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    
    lines = res.stdout.split("\n")
    start = -1
    for idx, line in enumerate(lines):
        if "_strategy_card" in line:
            start = idx
            break
            
    with open("scratch/extracted_diff.txt", "w", encoding="utf-8") as f:
        if start != -1:
            f.write("\n".join(lines[max(0, start - 30): start + 250]))
        else:
            f.write(res.stdout)
    print("Done! Extracted diff written to scratch/extracted_diff.txt")

if __name__ == "__main__":
    main()
