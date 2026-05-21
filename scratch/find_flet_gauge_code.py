import json
import os

log_path = r"C:\Users\Administrator\.gemini\antigravity\brain\67e1fe5d-c985-4ae7-9537-e11757774f71\.system_generated\logs\transcript.jsonl"
out_dir = r"e:\python\lh01\gold-quantification\scratch\gauge_code_extracts"
os.makedirs(out_dir, exist_ok=True)

print("Scanning all log entries for 'ProgressRing' to find the gauges code...")
with open(log_path, 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        if "ProgressRing" in line:
            try:
                data = json.loads(line)
            except Exception:
                continue
                
            step = data.get("step_index")
            tool_calls = data.get("tool_calls", [])
            for tc_idx, tc in enumerate(tool_calls):
                name = tc.get("name")
                args = tc.get("args", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        pass
                
                if isinstance(args, dict):
                    target = args.get("TargetFile", "")
                    print(f"Line {i}, Step {step}: tool={name}, TargetFile={target}")
                    code = args.get("CodeContent", "")
                    if code:
                        out_path = os.path.join(out_dir, f"step_{step}_tc_{tc_idx}_code.py")
                        with open(out_path, 'w', encoding='utf-8') as out_f:
                            out_f.write(code)
                        print(f"  -> Extracted code to {out_path} ({len(code)} chars)")
                    
                    # If it's a replacement, let's extract the replacement chunks
                    chunks = args.get("ReplacementChunks", [])
                    if chunks:
                        out_path = os.path.join(out_dir, f"step_{step}_tc_{tc_idx}_chunks.json")
                        with open(out_path, 'w', encoding='utf-8') as out_f:
                            json.dump(args, out_f, indent=2, ensure_ascii=False)
                        print(f"  -> Extracted replacement chunks to {out_path}")
                        
                    # Also look at simple replacement
                    if name == "replace_file_content":
                        out_path = os.path.join(out_dir, f"step_{step}_tc_{tc_idx}_replace.json")
                        with open(out_path, 'w', encoding='utf-8') as out_f:
                            json.dump(args, out_f, indent=2, ensure_ascii=False)
                        print(f"  -> Extracted replace content to {out_path}")
print("Scan complete.")
