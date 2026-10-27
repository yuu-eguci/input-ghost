'''E2E テスト専用。渡されたものを別の process で起動して、自分はすぐ終わる。

Windows 11 の Notepad のように、起動した process とは別の process が window を出すアプリのまね。
python e2e_launcher.py <script> [args...]'''

import subprocess
import sys

subprocess.Popen([sys.executable, *sys.argv[1:]])
