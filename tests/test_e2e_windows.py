'''本物の Win32 を使う E2E テスト。

GitHub-hosted の Windows runner 上で INPUTGHOST_E2E=1 のときだけ動く。
入力先は repo 内の使い捨て window (e2e_target.py) だけ。それ以外の環境では skip する。'''

import os
import subprocess
import sys
import time

import pyperclip
import pytest

from e2e_support import (
    LAUNCHER_SCRIPT, PYTHONW, SLEEPER_SCRIPT, Target, clipboardSequence,
    e2e_enabled, killPid, putNonTextClipboard, readClipboard, startInputGhost,
    wait_until)

HOSTED = {
    'INPUTGHOST_E2E': '1',
    'GITHUB_ACTIONS': 'true',
    'RUNNER_ENVIRONMENT': 'github-hosted',
}


@pytest.mark.parametrize('platform, environ, expected', [
    ('win32', HOSTED, True),
    ('win32', {**HOSTED, 'INPUTGHOST_E2E': '0'}, False),
    ('win32', {**HOSTED, 'RUNNER_ENVIRONMENT': 'self-hosted'}, False),
    ('win32', {'INPUTGHOST_E2E': '1'}, False),
    ('darwin', HOSTED, False),
])
def test_e2e_runs_only_on_github_hosted_windows_with_opt_in(
        platform, environ, expected):
    assert e2e_enabled(platform, environ) is expected


def test_requested_e2e_is_not_silently_skipped():
    # INPUTGHOST_E2E=1 なのに動かせない環境なら、skip で緑にせず失敗させる (本物の key は送らない)。
    if os.environ.get('INPUTGHOST_E2E') == '1':
        assert e2e_enabled(sys.platform, os.environ), (
            'INPUTGHOST_E2E=1 but this is not a GitHub-hosted Windows runner')


needs_hosted_windows = pytest.mark.skipif(
    not e2e_enabled(sys.platform, os.environ),
    reason='GitHub-hosted Windows runner で INPUTGHOST_E2E=1 のときだけ動く')

# command として実行されないよう、# で始まるテスト用の文章だけを打つ。
ROWS = ['# ghost e2e 1', '# ghost e2e 2', '# ghost e2e 3']
# 入力先は Ctrl+V を受けてから 0.2 秒遅れて clipboard を読む。
# Ctrl+V 直後に次の行をコピーすると、前の行の代わりに次の行が貼られてしまう。
# 既定の PASTE_SETTLE_TIME (0.5 秒) なら、runner 自体の遅れを足しても間に合う。
PASTE_DELAY_MS = 200
# 実行前に runner の clipboard に入れておく合成テキスト。終わったら戻っているはず。
ORIGINAL_CLIPBOARD = '# e2e original clipboard'
# 文字列ではない独自の形式に入れる合成の byte。
NON_TEXT_PAYLOAD = b'InputGhost E2E synthetic non-text payload \x00\x01\x02\xfe\xff'


@pytest.fixture
def desktop(tmp_path):
    '''起動元の代わりの window (decoy) と入力先 (target) を用意し、decoy を前面にする。'''

    textFile = tmp_path / 'rows.txt'
    processes = []

    def start(rows, keyOrder, waitTime, launch=None, clipboardText=ORIGINAL_CLIPBOARD):
        textFile.write_text('\n'.join(rows) + '\n', encoding='cp932')
        if clipboardText is not None:
            pyperclip.copy(clipboardText)
        processes.append(startInputGhost(textFile, keyOrder, waitTime, launch))
        return processes[-1]

    with Target(tmp_path, 'decoy') as decoy, \
            Target(tmp_path, 'target', PASTE_DELAY_MS) as target:
        if not decoy.bringToFront():
            pytest.fail('No interactive foreground on this runner; nothing was sent.')
        try:
            yield start, decoy, target
        finally:
            for process in processes:
                process.kill()


def assertRefusal(err):
    '''安全のために止まったときの stderr は「InputGhost: 理由」の 1 行だけ。'''

    assert 'Traceback' not in err, err
    lines = err.splitlines()
    assert len(lines) == 1 and lines[0].startswith('InputGhost: '), err


def switchDuringCountdown(process, target):
    '''カウントダウン中に入力先を前面にする。できなければ InputGhost を kill する。'''

    if not target.bringToFront():
        process.kill()
        pytest.fail('Could not bring the E2E target to front; InputGhost was killed.')


@needs_hosted_windows
def test_real_rows_reach_only_the_chosen_slow_target_in_order(desktop):
    start, decoy, target = desktop
    process = start(ROWS, ['copypaste', 'return'], 0.5)
    switchDuringCountdown(process, target)

    out, err = process.communicate(timeout=60)

    assert process.returncode == 0, err
    # 最後の行も遅れて読まれるので、clipboard を戻すのが早すぎると元の文字列が貼られる。
    assert target.text() == ''.join(row + '\n' for row in ROWS)
    assert decoy.text() == ''
    assert pyperclip.paste() == ORIGINAL_CLIPBOARD


@needs_hosted_windows
def test_real_focus_change_stops_before_next_paste(desktop):
    start, decoy, target = desktop
    process = start(ROWS[:2], ['return', 'copypaste'], 3)
    switchDuringCountdown(process, target)

    # 最初の Enter が届いたら前面を decoy に戻す。Ctrl+V の前 (3 秒待ちの間) に止まるはず。
    if not wait_until(lambda: target.textFile.read_text('utf-8') == '\n', 15):
        process.kill()
        pytest.fail('First key never reached the E2E target; InputGhost was killed.')
    if not decoy.bringToFront():
        process.kill()
        pytest.fail('Could not move focus away; InputGhost was killed.')

    out, err = process.communicate(timeout=60)

    assert process.returncode == 1, err
    assertRefusal(err)
    assert 'Foreground window changed' in err
    assert 'before action 2/4' in err
    assert target.text() == '\n'
    assert decoy.text() == ''
    assert pyperclip.paste() == ORIGINAL_CLIPBOARD


@needs_hosted_windows
def test_real_launched_target_is_waited_for_and_used(desktop, tmp_path):
    start, decoy, target = desktop
    launched = Target(tmp_path, 'launched', launch=False)
    # 文字列のコマンドラインは、古い版 (shell の call) でも新しい版でも同じように使える。
    process = start(ROWS[:2], ['copypaste', 'return'], 0.5, (launched.commandLine(), 10))

    try:
        with launched:
            # 前の固定 1 秒より遅れて前面にする (自分で前面に来ていてもかまわない)。
            time.sleep(1.5)
            if not launched.bringToFront():
                process.kill()
                pytest.fail('Could not bring the launched target to front; InputGhost was killed.')
            out, err = process.communicate(timeout=60)
            assert process.returncode == 0, err
            assert launched.text() == '# ghost e2e 1\n# ghost e2e 2\n'
    except RuntimeError as error:
        process.kill()
        pytest.fail(f'{error} InputGhost was killed.')

    assert target.text() == ''
    assert decoy.text() == ''
    assert pyperclip.paste() == ORIGINAL_CLIPBOARD


@needs_hosted_windows
def test_real_window_handed_off_to_a_new_process_is_used(desktop, tmp_path):
    start, decoy, target = desktop
    handed = Target(tmp_path, 'handed', launch=False)
    # launcher が入力先を別の process で起動してすぐ終わる。window の持ち主は起動した
    # process ではないので、「起動後に始まった同じ実行ファイル」として見つかるはず。
    command = subprocess.list2cmdline(
        [str(PYTHONW), str(LAUNCHER_SCRIPT), *handed.command()[1:]])
    process = start(ROWS[:2], ['copypaste', 'return'], 0.5, (command, 10))

    try:
        with handed:
            if not handed.bringToFront():
                process.kill()
                pytest.fail('Could not bring the handed-off target to front; InputGhost was killed.')
            out, err = process.communicate(timeout=60)
            assert process.returncode == 0, err
            assert handed.text() == '# ghost e2e 1\n# ghost e2e 2\n'
    except RuntimeError as error:
        process.kill()
        pytest.fail(f'{error} InputGhost was killed.')

    assert target.text() == ''
    assert decoy.text() == ''
    assert pyperclip.paste() == ORIGINAL_CLIPBOARD


@needs_hosted_windows
def test_real_launch_does_not_type_into_an_older_window(desktop, tmp_path):
    start, decoy, target = desktop
    pidFile = tmp_path / 'sleeper.pid'
    # window を作らない process を起動させる。前面には、起動前からある同じ pythonw の window を出す。
    command = subprocess.list2cmdline([str(PYTHONW), str(SLEEPER_SCRIPT), str(pidFile)])
    process = start(ROWS[:1], ['copypaste', 'return'], 0.5, (command, 3))

    try:
        if not wait_until(pidFile.exists, 20):
            process.kill()
            pytest.fail('The launched process never started; InputGhost was killed.')
        if not target.bringToFront():
            process.kill()
            pytest.fail('Could not bring the older window to front; InputGhost was killed.')
        out, err = process.communicate(timeout=60)
    finally:
        if pidFile.exists():
            killPid(int(pidFile.read_text()))

    assert process.returncode == 1, err
    assertRefusal(err)
    assert 'did not come to the front' in err
    assert 'Nothing was sent' in err
    assert target.text() == ''
    assert decoy.text() == ''
    assert pyperclip.paste() == ORIGINAL_CLIPBOARD


@needs_hosted_windows
def test_real_non_text_clipboard_is_refused_and_left_untouched(desktop):
    start, decoy, target = desktop
    # 画像やファイルの代わりに、文字列のない独自の形式 1 つだけを clipboard に置く。
    clipboardFormat = putNonTextClipboard(NON_TEXT_PAYLOAD)
    sequence = clipboardSequence()
    process = start(ROWS[:1], ['copypaste', 'return'], 0.5, clipboardText=None)
    switchDuringCountdown(process, target)

    out, err = process.communicate(timeout=60)

    assert process.returncode == 1, err
    assertRefusal(err)
    assert 'non-text' in err
    assert 'Nothing was sent' in err
    assert target.text() == ''
    assert decoy.text() == ''
    # 形式もその中身も残っていて、clipboard は一度も書き換えられていない。
    # (GlobalSize は確保した大きさなので、頼んだ大きさより長いことがある)
    formats, data = readClipboard(clipboardFormat)
    assert formats == [clipboardFormat]
    assert data[:len(NON_TEXT_PAYLOAD)] == NON_TEXT_PAYLOAD
    assert clipboardSequence() == sequence

    # 対照: 本当に書き換えれば、同じ確かめ方で分かる。
    pyperclip.copy(ORIGINAL_CLIPBOARD)
    assert readClipboard(clipboardFormat)[0] != [clipboardFormat]
    assert clipboardSequence() != sequence
