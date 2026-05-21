import json

file_path = r"e:\python\lh01\gold-quantification\scratch\app_py_versions\step_1802_tc_0_multi_replace_file_content.json"
try:
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print("Keys in JSON:", data.keys())
    print("Instruction:", data.get("Instruction"))
    
    chunks = data.get("ReplacementChunks", [])
    if isinstance(chunks, str):
        chunks = json.loads(chunks)
        
    print(f"Total chunks: {len(chunks)}")
    for idx, c in enumerate(chunks):
        if not isinstance(c, dict):
            print(f"Chunk {idx+1} is not a dict: {type(c)}")
            continue
        print(f"\n--- Chunk {idx+1} (Lines {c.get('StartLine')} - {c.get('EndLine')}) ---")
        target = c.get("TargetContent", "")
        replacement = c.get("ReplacementContent", "")
        print(f"Target length: {len(target)} chars, Replacement length: {len(replacement)} chars")
        
        t_lines = target.splitlines()
        r_lines = replacement.splitlines()
        print("Target (first 5 lines):")
        for line in t_lines[:5]:
            print("  ", line)
        print("Replacement (first 5 lines):")
        for line in r_lines[:5]:
            print("  ", line)
except Exception as e:
    import traceback
    traceback.print_exc()
