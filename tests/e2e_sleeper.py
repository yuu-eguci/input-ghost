'''E2E テスト専用。window を作らずに自分の PID を書いて、30 秒寝るだけの process。

python e2e_sleeper.py <pid_file>'''

import os
import sys
import time

with open(sys.argv[1] + '.tmp', 'w') as f:
    f.write(str(os.getpid()))
os.replace(sys.argv[1] + '.tmp', sys.argv[1])
time.sleep(30)
