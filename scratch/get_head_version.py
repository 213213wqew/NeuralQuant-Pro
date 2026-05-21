import subprocess

try:
    # Run git show HEAD:quant_app/ui/app.py
    result = subprocess.run(
        ["git", "show", "HEAD:quant_app/ui/app.py"],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='ignore'
    )
    if result.returncode == 0:
        content = result.stdout
        print("Successfully read HEAD:quant_app/ui/app.py!")
        print("Length:", len(content))
        print("Keywords search:")
        keywords = ["AI 决策", "AI决策", "Agent Live", "脑电波", "智能对冲", "一键锁仓"]
        for kw in keywords:
            print(f"  '{kw}': {kw in content}")
        
        # Save to a scratch file to inspect
        with open(r"e:\python\lh01\gold-quantification\scratch\app_py_head.py", 'w', encoding='utf-8') as f:
            f.write(content)
        print("Saved HEAD version to scratch/app_py_head.py")
    else:
        print("Error running git show:", result.stderr)
except Exception as e:
    print("Exception occurred:", e)
