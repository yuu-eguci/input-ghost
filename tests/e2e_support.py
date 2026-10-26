'''E2E テストの道具。本物の Win32 を触るのは GitHub-hosted の Windows runner の中だけ。'''

import ctypes
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
TARGET_SCRIPT = pathlib.Path(__file__).resolve().parent / 'e2e_target.py'

# InputGhost を別 process で動かす。止められなかったら kill できるように。
DRIVER = '''
import sys
import InputGhost
ghost = InputGhost.InputGhost
ghost._TEXT_FILE_NAME = sys.argv[1]
ghost._KEY_ORDER = tuple(sys.argv[2].split(','))
ghost._WAIT_TIME = float(sys.argv[3])
ghost._READY_TIME = 3
InputGhost.main([])
'''


def e2e_enabled(platform, environ):
    '''GitHub-hosted の Windows runner で INPUTGHOST_E2E=1 のときだけ True。'''

    return (platform == 'win32'
            and environ.get('INPUTGHOST_E2E') == '1'
            and environ.get('GITHUB_ACTIONS') == 'true'
            and environ.get('RUNNER_ENVIRONMENT') == 'github-hosted')


def wait_until(condition, seconds):
    deadline = time.monotonic() + seconds
    while not condition():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


class Target:
    '''使い捨ての入力先 window。with を抜けたら必ず終了させる。'''

    def __init__(self, directory, name):
        self.infoFile = directory / f'{name}.json'
        self.textFile = directory / f'{name}.txt'
        self.process = None
        self.hwnd = None
        self.pid = None

    def __enter__(self):
        self.process = subprocess.Popen(
            [sys.executable, str(TARGET_SCRIPT),
             str(self.infoFile), str(self.textFile)])
        try:
            return self._identify()
        except BaseException:
            self.__exit__()
            raise

    def _identify(self):
        if not wait_until(self.infoFile.exists, 20):
            raise RuntimeError('E2E target did not start; nothing was sent.')
        info = json.loads(self.infoFile.read_text(encoding='utf-8'))
        self.hwnd, self.pid = info['hwnd'], info['pid']

        # handle が本当にこの target の window か、title ではなく PID で確かめる。
        owner = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(
            self.hwnd, ctypes.byref(owner))
        if owner.value != self.pid:
            raise RuntimeError('E2E target window could not be identified.')
        return self

    def __exit__(self, *exc):
        # 自分で 60 秒後に終了もするけど、ここで必ず止める。
        if self.pid is not None:
            try:
                os.kill(self.pid, signal.SIGTERM)
            except OSError:
                pass
        self.process.kill()
        self.process.wait(timeout=10)

    def text(self):
        # target は 100ms ごとに保存するので、少し待ってから読む。
        time.sleep(0.5)
        return self.textFile.read_text(encoding='utf-8')

    def bringToFront(self):
        '''1 秒以内に前面にできなければ False。そのときは何も入力させないこと。'''

        user32 = ctypes.windll.user32
        user32.SetForegroundWindow(self.hwnd)
        return wait_until(lambda: user32.GetForegroundWindow() == self.hwnd, 1)


def startInputGhost(textFile, keyOrder, waitTime):
    '''InputGhost を READY_TIME=3 で起動し、起動元 window を記録した後 (最初の表示) まで待つ。'''

    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    process = subprocess.Popen(
        [sys.executable, '-u', '-c', DRIVER,
         str(textFile), ','.join(keyOrder), str(waitTime)],
        cwd=REPO, env=env, text=True, encoding='utf-8',
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # 最初のカウントダウン表示は、起動元 window を記録した 1 秒後に出る。
    if process.stdout.readline().strip() != '3':
        process.kill()
        raise RuntimeError('InputGhost did not start its countdown.')
    return process
