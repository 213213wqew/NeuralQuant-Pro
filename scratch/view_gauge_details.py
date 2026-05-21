import json
import os

folder = r"e:\python\lh01\gold-quantification\scratch\gauge_code_extracts"

files = [
    "step_932_tc_0_replace.json",
    "step_938_tc_0_replace.json",
    "step_950_tc_0_chunks.json"
]

for f in files:
    path = os.path.join(folder, f)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as file_obj:
            data = json.load(file_obj)
        print(f"\n======================================")
        print(f"File: {f}")
        print(f"Instruction: {data.get('Instruction')}")
        print(f"Description: {data.get('Description')}")
        
        if "ReplacementChunks" in data:
            chunks = data.get("ReplacementChunks", [])
            print(f"Total chunks: {len(chunks)}")
            for idx, c in enumerate(chunks):
                print(f"\n--- Chunk {idx+1} (Lines {c.get('StartLine')} - {c.get('EndLine')}) ---")
                print("Target:")
                print(c.get("TargetContent", "")[:500])
                print("\nReplacement:")
                print(c.get("ReplacementContent", "")[:800])
        else:
            print("\nReplacement content:")
            print(data.get("ReplacementContent", "")[:800])
    else:
        print(f"File not found: {path}")
