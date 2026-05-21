import json

file_path = r"e:\python\lh01\gold-quantification\scratch\app_py_versions\step_1802_tc_0_multi_replace_file_content.json"
try:
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print("Keys in JSON:", data.keys())
    print("Instruction:", data.get("Instruction"))
    print("Description:", data.get("Description"))
    chunks = data.get("ReplacementChunks", [])
    print(f"Total chunks: {len(chunks)}")
    for idx, c in enumerate(chunks):
        print(f"\n--- Chunk {idx+1} (Lines {c.get('StartLine')} - {c.get('EndLine')}) ---")
        target = c.get("TargetContent", "")
        replacement = c.get("ReplacementContent", "")
        print(f"Target length: {len(target)} chars, Replacement length: {len(replacement)} chars")
        # Print first and last 3 lines of target and replacement to understand
        t_lines = target.splitlines()
        r_lines = replacement.splitlines()
        print("Target (first 5 lines):")
        for line in t_lines[:5]:
            print("  ", line)
        print("Replacement (first 5 lines):")
        for line in r_lines[:5]:
            print("  ", line)
except Exception as e:
    print("Error reading file:", e)
