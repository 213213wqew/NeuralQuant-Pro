import json

with open(r"e:\python\lh01\gold-quantification\scratch\gauge_code_extracts\step_932_tc_0_replace.json", 'r', encoding='utf-8') as f:
    data = json.load(f)

print("--- STEP 932 REPLACE CONTENT ---")
print(data.get("ReplacementContent"))

with open(r"e:\python\lh01\gold-quantification\scratch\gauge_code_extracts\step_938_tc_0_replace.json", 'r', encoding='utf-8') as f:
    data2 = json.load(f)

print("\n--- STEP 938 REPLACE CONTENT ---")
print(data2.get("ReplacementContent"))
