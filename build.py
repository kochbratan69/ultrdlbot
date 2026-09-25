import subprocess
import sys

def build_exe(target: str, name: str):
    print(f"🚀 Собираем {name}.exe...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", name,
        target
    ]
    res = subprocess.run(cmd)
    if res.returncode == 0:
        print(f"🎉 {name}.exe успешно собран! (⁠≧⁠◡⁠≦⁠) ♡\n")
    else:
        print(f"❌ Ошибка сборки {name}.exe TwT\n")

def main():
    build_exe("bot.py", "SuicidalBot")
    build_exe("worker.py", "SuicidalWorker")

if __name__ == "__main__":
    main()