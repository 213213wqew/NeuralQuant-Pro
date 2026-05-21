import json
import os

log_path = r"C:\Users\Administrator\.gemini\antigravity\brain\67e1fe5d-c985-4ae7-9537-e11757774f71\.system_generated\logs\transcript.jsonl"
output_dir = r"e:\python\lh01\gold-quantification\scratch\app_py_versions"
os.makedirs(output_dir, exist_ok=True)

print("Parsing transcript.jsonl to extract app.py code edits...")

with open(log_path, 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        try:
            data = json.loads(line)
        except Exception as e:
            continue
        
        # Check if this is a model step with tool calls
        tool_calls = data.get("tool_calls", [])
        if not tool_calls and "content" in data:
            # Check if it contains tools in json structure inside content
            pass
            
        for tc_idx, tc in enumerate(tool_calls):
            name = tc.get("name")
            args = tc.get("args", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    pass
            
            # Check if it targets app.py
            target_file = args.get("TargetFile", "") if isinstance(args, dict) else ""
            if "app.py" in target_file or "app.py" in str(args):
                # Write-to-file
                if name == "write_to_file":
                    code = args.get("CodeContent", "")
                    if code:
                        out_path = os.path.join(output_dir, f"step_{data.get('step_index')}_tc_{tc_idx}_write.py")
                        with open(out_path, 'w', encoding='utf-8') as out_f:
                            out_f.write(code)
                        print(f"Extracted write to {out_path} (length {len(code)})")
                
                # Replace file content
                elif name in ("replace_file_content", "multi_replace_file_content"):
                    chunks = []
                    if name == "replace_file_content":
                        chunks = [args]
                    else:
                        chunks = args.get("ReplacementChunks", [])
                    
                    out_path = os.path.join(output_dir, f"step_{data.get('step_index')}_tc_{tc_idx}_{name}.json")
                    with open(out_path, 'w', encoding='utf-8') as out_f:
                        json.dump(args, out_f, indent=2, ensure_ascii=False)
                    print(f"Extracted replacement details to {out_path}")
                    
print("Extraction complete. Check scratch/app_py_versions/")
