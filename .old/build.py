import subprocess
import sys

def main():
    print("🚀 Собираем легкий SuicidalBot.exe...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "SuicidalBot",
        "main.py"
    ]
    res = subprocess.run(cmd)
    if res.returncode == 0:
        print("\n🎉 УРА-А! Маленький dist/SuicidalBot.exe готов! (⁠≧⁠◡⁠≦⁠) ♡")
    else:
        print("\n❌ Упс! Ошибка сборки TwT")

if __name__ == "__main__":
    main()