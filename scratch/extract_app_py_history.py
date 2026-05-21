import json
import os

log_path = r"C:\Users\Administrator\.gemini\antigravity\brain\67e1fe5d-c985-4ae7-9537-e11757774f71\.system_generated\logs\transcript.jsonl"
out_dir = r"e:\python\lh01\gold-quantification\scratch\extracted_app_py"
os.makedirs(out_dir, exist_ok=True)

print("Searching transcript.jsonl for direct writes to app.py...")

with open(log_path, 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        try:
            data = json.loads(line)
        except Exception:
            continue
            
        tool_calls = data.get("tool_calls", [])
        for tc_idx, tc in enumerate(tool_calls):
            name = tc.get("name")
            args = tc.get("args", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    pass
            
            if not isinstance(args, dict):
                continue
                
            target_file = args.get("TargetFile", "")
            if target_file and target_file.endswith("app.py"):
                print(f"Line {i}: Found tool call '{name}' targeting '{target_file}' in step {data.get('step_index')}")
                if name == "write_to_file":
                    code = args.get("CodeContent", "")
                    if code:
                        out_path = os.path.join(out_dir, f"step_{data.get('step_index')}_full.py")
                        with open(out_path, 'w', encoding='utf-8') as out_f:
                            out_f.write(code)
                        print(f"  -> Extracted full file to {out_path} ({len(code)} chars)")
                elif name in ("replace_file_content", "multi_replace_file_content"):
                    out_path = os.path.join(out_dir, f"step_{data.get('step_index')}_{name}.json")
                    with open(out_path, 'w', encoding='utf-8') as out_f:
                        json.dump(args, out_f, indent=2, ensure_ascii=False)
                    print(f"  -> Extracted edit chunk to {out_path}")
