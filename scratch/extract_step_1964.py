import json

log_path = r"C:\Users\Administrator\.gemini\antigravity\brain\67e1fe5d-c985-4ae7-9537-e11757774f71\.system_generated\logs\transcript.jsonl"

with open(log_path, 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        if i == 2316:
            data = json.loads(line)
            tool_calls = data.get("tool_calls", [])
            for tc_idx, tc in enumerate(tool_calls):
                args = tc.get("args", {})
                if isinstance(args, str):
                    args = json.loads(args)
                print("TargetFile:", args.get("TargetFile"))
                print("Description:", args.get("Description"))
                code = args.get("CodeContent", "")
                print(f"Code length: {len(code)}")
                with open(r"e:\python\lh01\gold-quantification\scratch\step_1964_extracted.py", 'w', encoding='utf-8') as out:
                    out.write(code)
                print("Extracted to scratch/step_1964_extracted.py")
