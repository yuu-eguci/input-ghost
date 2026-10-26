'''本物の Win32 を使う E2E テスト。

GitHub-hosted の Windows runner 上で INPUTGHOST_E2E=1 のときだけ動く。
入力先は repo 内の使い捨て window (e2e_target.py) だけ。それ以外の環境では skip する。'''

import os
import sys

import pytest

from e2e_support import Target, e2e_enabled, startInputGhost, wait_until

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
ROWS = ['# ghost e2e 1', '# ghost e2e 2']


@pytest.fixture
def desktop(tmp_path):
    '''起動元の代わりの window (decoy) と入力先 (target) を用意し、decoy を前面にする。'''

    textFile = tmp_path / 'rows.txt'
    textFile.write_text('\n'.join(ROWS) + '\n', encoding='cp932')
    processes = []

    def start(keyOrder, waitTime):
        processes.append(startInputGhost(textFile, keyOrder, waitTime))
        return processes[-1]

    with Target(tmp_path, 'decoy') as decoy, Target(tmp_path, 'target') as target:
        if not decoy.bringToFront():
            pytest.fail('No interactive foreground on this runner; nothing was sent.')
        try:
            yield start, decoy, target
        finally:
            for process in processes:
                process.kill()


def switchDuringCountdown(process, target):
    '''カウントダウン中に入力先を前面にする。できなければ InputGhost を kill する。'''

    if not target.bringToFront():
        process.kill()
        pytest.fail('Could not bring the E2E target to front; InputGhost was killed.')


@needs_hosted_windows
def test_real_input_goes_only_to_the_window_chosen_during_countdown(desktop):
    start, decoy, target = desktop
    process = start(['copypaste', 'return'], 0.5)
    switchDuringCountdown(process, target)

    out, err = process.communicate(timeout=60)

    assert process.returncode == 0, err
    assert target.text() == '# ghost e2e 1\n# ghost e2e 2\n'
    assert decoy.text() == ''


@needs_hosted_windows
def test_real_focus_change_stops_before_next_paste(desktop):
    start, decoy, target = desktop
    process = start(['copypaste'], 3)
    switchDuringCountdown(process, target)

    # 1 行目が届いたら前面を decoy に戻す。2 行目の Ctrl+V の前 (3 秒待ちの間) に止まるはず。
    if not wait_until(lambda: ROWS[0] in target.textFile.read_text('utf-8'), 15):
        process.kill()
        pytest.fail('First row never reached the E2E target; InputGhost was killed.')
    if not decoy.bringToFront():
        process.kill()
        pytest.fail('Could not move focus away; InputGhost was killed.')

    out, err = process.communicate(timeout=60)

    assert process.returncode != 0
    assert 'Foreground window changed' in err
    assert 'before action 2/2' in err
    assert target.text() == ROWS[0]
    assert decoy.text() == ''
