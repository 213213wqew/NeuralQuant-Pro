import json
import re

log_path = r"C:\Users\Administrator\.gemini\antigravity\brain\67e1fe5d-c985-4ae7-9537-e11757774f71\.system_generated\logs\transcript.jsonl"

print("Searching transcript.jsonl for app.py code versions...")
matches = []

with open(log_path, 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        if "app.py" in line:
            # We want to find writes or edits that contain UI components
            # Let's see if it contains keywords like "AI 决策" or "Agent Live" or "健康度"
            has_ai_decision = "AI决策" in line or "AI 决策" in line or "Agent Live" in line
            print(f"Line {i}: length {len(line)}, has_ai_decision: {has_ai_decision}")
            if has_ai_decision:
                matches.append((i, len(line)))

# Let's inspect the latest match containing the beautiful UI
if matches:
    print(f"Found matches at lines: {matches}")
    # Let's print details of the last match
    last_line_idx = matches[-1][0]
    print(f"Reading details for line {last_line_idx}...")
else:
    print("No matches with AI决策 found, let's do a broader search for any app.py write/replace.")
    # Broader search: find lines with tool_calls and "write_to_file" or "replace_file_content" or "multi_replace_file_content" and "app.py"
    with open(log_path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            if "app.py" in line and ("CodeContent" in line or "ReplacementContent" in line):
                print(f"Broad Line {i}: length {len(line)}")
