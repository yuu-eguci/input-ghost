'''InputGhost.py をコマンドとして動かしたときの、止まり方のテスト。

本物の __main__ を別 process で動かすが、--dry-run だけなので key も clipboard も触らない。'''

import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

# InputGhostSetting の値を書き換えてから、InputGhost.py を __main__ として動かす。
DRIVER = '''
import ast, runpy, sys
import InputGhostSetting
setattr(InputGhostSetting, sys.argv[1], ast.literal_eval(sys.argv[2]))
sys.argv = ['InputGhost.py', '--dry-run']
runpy.run_path('InputGhost.py', run_name='__main__')
'''


def runScript(name, value):
    return subprocess.run(
        [sys.executable, '-c', DRIVER, name, repr(value)],
        cwd=REPO, capture_output=True, text=True, encoding='utf-8',
        env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
        timeout=60)


def test_refusal_is_one_line_with_exit_code_1():
    result = runScript('WAIT_TIME', -1)

    assert result.returncode == 1
    assert result.stderr == (
        'InputGhost: WAIT_TIME must be a number of seconds of 0 or more, '
        'but it is -1. Nothing was sent.\n')
    assert result.stdout == ''


def test_unexpected_error_keeps_its_traceback(tmp_path):
    # テキストファイルの代わりにフォルダを指定すると、open が OSError になる (InputGhost の想定外)。
    result = runScript('TEXT_FILE_NAME', str(tmp_path))

    assert result.returncode != 0
    assert 'Traceback (most recent call last)' in result.stderr
    assert 'Error' in result.stderr.splitlines()[-1]
    assert 'InputGhost: ' not in result.stderr
