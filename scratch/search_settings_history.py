import subprocess

def main():
    # Run git log -p -S "build_settings_view" on quant_app/ui/app.py
    cmd = ["git", "log", "-p", "-S", "build_settings_view", "quant_app/ui/app.py"]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    print(res.stdout[:5000])

if __name__ == "__main__":
    main()
