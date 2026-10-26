'''InputGhost のテスト。

Windows の入力(keybd_event)・クリップボード・アプリ起動はすべて偽物に差し替える。
本物のキー入力は絶対に送らない。'''

import pytest

import InputGhost as ig

KEYUP = 0x2


class FakeUser32:
    '''keybd_event の呼び出しを記録するだけの偽 user32。'''

    def __init__(self):
        self.events = []

    def keybd_event(self, keycode, scan, flags, extra):
        self.events.append((keycode, flags))


class Forbidden:
    '''触られたら失敗する偽物。dry-run で副作用がないことの確認用。'''

    def __getattr__(self, name):
        raise AssertionError(f'dry-run で {name} が使われた')

    def __call__(self, *args, **kwargs):
        raise AssertionError('dry-run で副作用のある関数が呼ばれた')


class FakeClock:
    '''sleep した分だけ monotonic が進む偽の time。本当には待たない。'''

    def __init__(self):
        self.now = 0.0
        self.sleeps = 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps += 1
        if self.sleeps > 10000:
            raise AssertionError('待ちループが止まらない')
        self.now += seconds


@pytest.fixture
def ghost(tmp_path, monkeypatch):
    '''合成テキストと偽の Windows 環境を用意する。'''

    text_file = tmp_path / 'synthetic.txt'
    text_file.write_text('あいうえおかき\r\nさし　す\r\n', encoding='cp932')
    monkeypatch.setattr(ig.InputGhost, '_TEXT_FILE_NAME', str(text_file))
    monkeypatch.setattr(ig.InputGhost, '_NUM_CHARA_IN_ROW', 5)
    monkeypatch.setattr(
        ig.InputGhost, '_KEY_ORDER', ('0', 'return', 'copypaste', 'return'))
    monkeypatch.setattr(ig.InputGhost, '_WAIT_TIME', 0)
    monkeypatch.setattr(ig.InputGhost, '_READY_TIME', 1)
    monkeypatch.setattr(ig.begin_set, 'exec_all', lambda file_name: None)
    monkeypatch.setattr(ig, 'time', FakeClock())

    clipboard = {'text': ''}
    monkeypatch.setattr(
        ig.pyperclip, 'copy', lambda text: clipboard.update(text=text))
    monkeypatch.setattr(ig.pyperclip, 'paste', lambda: clipboard['text'])
    user32 = FakeUser32()
    monkeypatch.setattr(
        ig.ctypes, 'windll', type('windll', (), {'user32': user32}),
        raising=False)
    monkeypatch.setattr(ig.subprocess, 'Popen', Forbidden())
    return user32


def test_text_is_split_into_chunks(ghost):
    assert ig.InputGhost.getInputTextList() == ['あいうえお', 'かき', 'さし す']


def test_real_run_sends_key_order_for_each_chunk(ghost):
    ig.InputGhost.run()

    one_row = [
        (48, 0), (48, KEYUP),
        (13, 0), (13, KEYUP),
        (17, 0), (86, 0), (17, KEYUP), (86, KEYUP),
        (13, 0), (13, KEYUP),
    ]
    assert ghost.events == one_row * 3


def test_clipboard_that_updates_late_is_still_pasted(ghost, monkeypatch):
    synced_paste = ig.pyperclip.paste
    calls = []

    def late_paste():
        calls.append(None)
        return 'stale' if len(calls) <= 3 else synced_paste()

    monkeypatch.setattr(ig.pyperclip, 'paste', late_paste)

    ig.InputGhost.run()

    assert ghost.events.count((86, 0)) == 3


def test_stale_clipboard_stops_before_paste(ghost, monkeypatch):
    monkeypatch.setattr(ig.InputGhost, '_CLIPBOARD_TIMEOUT', 2)
    monkeypatch.setattr(ig.InputGhost, '_READY_TIME', 0)
    monkeypatch.setattr(ig.pyperclip, 'paste', lambda: 'stale')

    with pytest.raises(ig.GreenException, match="'あいうえお'.* within 2s"):
        ig.InputGhost.run()

    # 1 行目の '0' と 'return' だけ送られて、Ctrl+V は送られない。
    assert ghost.events == [(48, 0), (48, KEYUP), (13, 0), (13, KEYUP)]
    assert 2 <= ig.time.now < 2.2


def test_invalid_key_order_is_rejected_before_any_input(ghost, monkeypatch):
    monkeypatch.setattr(ig.InputGhost, '_KEY_ORDER', ('0', 'typo'))

    with pytest.raises(ig.GreenException, match='typo'):
        ig.InputGhost.run()

    assert ghost.events == []


def test_dry_run_prints_plan_and_sends_nothing(ghost, monkeypatch, capsys):
    monkeypatch.setattr(ig.ctypes, 'windll', Forbidden(), raising=False)
    monkeypatch.setattr(ig.pyperclip, 'copy', Forbidden())
    monkeypatch.setattr(ig.pyperclip, 'paste', Forbidden())
    monkeypatch.setattr(ig.time, 'sleep', Forbidden())
    monkeypatch.setattr(ig.InputGhost, '_READY_TIME', False)

    ig.main(['--dry-run'])

    out = capsys.readouterr().out
    assert 'paste あいうえお' in out
    assert 'paste さし す' in out
    assert out.count('key return') == 6
    assert 'no input was sent' in out
