import json
import os

log_path = r"C:\Users\Administrator\.gemini\antigravity\brain\67e1fe5d-c985-4ae7-9537-e11757774f71\.system_generated\logs\transcript.jsonl"
out_dir = r"e:\python\lh01\gold-quantification\scratch\step_1762_extract"
os.makedirs(out_dir, exist_ok=True)

print("Extracting Step 1762 from logs...")

with open(log_path, 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        if "1762" in line and "multi_replace_file_content" in line:
            try:
                data = json.loads(line)
            except Exception:
                continue
                
            step = data.get("step_index")
            if step == 1762:
                print(f"Line {i}: Found Step 1762!")
                tool_calls = data.get("tool_calls", [])
                for tc_idx, tc in enumerate(tool_calls):
                    args = tc.get("args", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            pass
                    
                    if isinstance(args, dict):
                        out_path = os.path.join(out_dir, f"step_1762_tc_{tc_idx}_details.json")
                        with open(out_path, 'w', encoding='utf-8') as out_f:
                            json.dump(args, out_f, indent=2, ensure_ascii=False)
                        print(f"  -> Extracted to {out_path}")
                        
                        # Print some metadata
                        print("Instruction:", args.get("Instruction"))
                        print("Description:", args.get("Description"))
                        chunks = args.get("ReplacementChunks", [])
                        print(f"Total chunks: {len(chunks)}")
                        for idx, c in enumerate(chunks):
                            print(f"  Chunk {idx+1}: lines {c.get('StartLine')} - {c.get('EndLine')}")
                            # Write target and replacement to files
                            with open(os.path.join(out_dir, f"chunk_{idx+1}_target.txt"), 'w', encoding='utf-8') as target_f:
                                target_f.write(c.get("TargetContent", ""))
                            with open(os.path.join(out_dir, f"chunk_{idx+1}_replacement.txt"), 'w', encoding='utf-8') as replacement_f:
                                replacement_f.write(c.get("ReplacementContent", ""))
                            print(f"    -> Extracted Chunk {idx+1} to txt files.")
