import json

log_path = r"C:\Users\Administrator\.gemini\antigravity\brain\67e1fe5d-c985-4ae7-9537-e11757774f71\.system_generated\logs\transcript.jsonl"

print("Checking first few lines in logs containing app.py...")
count = 0
with open(log_path, 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        if "app.py" in line:
            try:
                data = json.loads(line)
            except Exception:
                continue
            
            tool_calls = data.get("tool_calls", [])
            if tool_calls:
                print(f"\nLine {i}, Step {data.get('step_index')}:")
                for tc_idx, tc in enumerate(tool_calls):
                    name = tc.get("name")
                    args = tc.get("args", {})
                    print(f"  Tool name: {name}")
                    print(f"  Args type: {type(args)}")
                    if isinstance(args, dict):
                        print(f"  Args keys: {list(args.keys())}")
                        print(f"  TargetFile in args: {args.get('TargetFile')}")
                    else:
                        print(f"  Args (truncated): {str(args)[:200]}")
                count += 1
                if count >= 10:
                    break
