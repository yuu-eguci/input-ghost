'''InputGhost のテスト。

Windows の入力(SendInput)・前面 window・クリップボード・アプリ起動はすべて偽物に差し替える。
本物のキー入力は絶対に送らない。'''

import ctypes

import pytest

import InputGhost as ig

KEYUP = 0x2
CF_UNICODETEXT = 13
# 偽の window handle。起動元の console・入力先・別の window。
CONSOLE, TARGET, OTHER = 100, 200, 300
# 実行前にユーザーが clipboard に入れていた (ことにする) 合成テキスト。
USER_CLIPBOARD = 'ユーザーの clipboard'


class FakeUser32:
    '''SendInput を記録し、前面の window と clipboard を偽装する偽 user32。

    foregrounds の先頭から順に返し、最後の 1 つは返し続ける。
    既定は「起動時は console、カウントダウン後は入力先」。
    SendInput は 1 回ごとの key を batches に、受け付けた key を events に残す。
    accept(key の一覧) が受け付ける数を決める (既定は全部)。
    clipboard は文字列 (clipboardText) と、文字列以外の形式の数 (otherFormats)。'''

    def __init__(self, clock):
        self.clock = clock
        self.batches = []
        self.events = []
        self.accept = len
        self.pasteTimes = []
        self.copies = []
        self.foregrounds = [CONSOLE, TARGET]
        self.clipboardText = USER_CLIPBOARD
        self.otherFormats = 0

    def GetForegroundWindow(self):
        if len(self.foregrounds) > 1:
            return self.foregrounds.pop(0)
        return self.foregrounds[0]

    def SendInput(self, count, inputs, size):
        assert size == ctypes.sizeof(ig.INPUT)
        assert all(inputs[i].type == ig.INPUT_KEYBOARD for i in range(count))
        keys = [(inputs[i].u.ki.wVk, inputs[i].u.ki.dwFlags) for i in range(count)]
        self.batches.append(keys)
        accepted = min(count, self.accept(keys))
        for key in keys[:accepted]:
            self.events.append(key)
            if key == (86, 0):
                self.pasteTimes.append(self.clock.now)
        return accepted

    def CountClipboardFormats(self):
        return bool(self.clipboardText) + self.otherFormats

    def IsClipboardFormatAvailable(self, clipboardFormat):
        return clipboardFormat == CF_UNICODETEXT and bool(self.clipboardText)

    def copy(self, text):
        # pyperclip.copy と同じく、clipboard を空にしてから文字列だけ入れる。
        self.copies.append((text, self.clock.now))
        self.clipboardText = text
        self.otherFormats = 0


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
        self.onSleep = None

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps += 1
        if self.sleeps > 10000:
            raise AssertionError('待ちループが止まらない')
        self.now += seconds
        if self.onSleep:
            self.onSleep()


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

    user32 = FakeUser32(ig.time)
    monkeypatch.setattr(ig.pyperclip, 'copy', user32.copy)
    monkeypatch.setattr(ig.pyperclip, 'paste', lambda: user32.clipboardText)
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


def test_each_action_is_one_send_input_batch(ghost):
    ig.InputGhost.run()

    one_row = [
        [(48, 0), (48, KEYUP)],
        [(13, 0), (13, KEYUP)],
        [(17, 0), (86, 0), (17, KEYUP), (86, KEYUP)],
        [(13, 0), (13, KEYUP)],
    ]
    assert ghost.batches == one_row * 3


def test_input_struct_matches_win32_layout():
    # union に MOUSEINPUT (いちばん大きい) を入れないと、SendInput が全部断る大きさになる。
    pointer = ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(ig.INPUT) == {8: 40, 4: 28}[pointer]
    assert ctypes.sizeof(ig.KEYBDINPUT) == {8: 24, 4: 16}[pointer]


def accept_for_paste(count):
    # Ctrl+V の 4 つのときだけ count 個まで受け付け、ほかは全部受け付ける。
    return lambda keys: count if (86, 0) in keys else len(keys)


def test_rejected_key_batch_stops_and_restores_clipboard(ghost):
    ghost.accept = accept_for_paste(0)

    with pytest.raises(
            ig.GreenException,
            match=r'accepted only 0/4 key events.*action 3/12 \(copypaste\)'
                  r'.*2 actions already sent.*no key is left pressed'):
        ig.InputGhost.run()

    # 受け付けられなかった batch のあとは、何も送らない。
    assert ghost.batches[-1] == [(17, 0), (86, 0), (17, KEYUP), (86, KEYUP)]
    assert ghost.events == [(48, 0), (48, KEYUP), (13, 0), (13, KEYUP)]
    assert ghost.clipboardText == USER_CLIPBOARD


def test_partly_accepted_batch_releases_pressed_keys(ghost, monkeypatch):
    monkeypatch.setattr(ig.InputGhost, '_PASTE_SETTLE_TIME', 0.5)
    ghost.accept = accept_for_paste(2)

    with pytest.raises(
            ig.GreenException,
            match='accepted only 2/4 key events.*no key is left pressed'):
        ig.InputGhost.run()

    # Ctrl と V が押されたままにならないよう、離す分だけを送る。
    assert ghost.batches[-1] == [(17, KEYUP), (86, KEYUP)]
    assert ghost.events[-4:] == [(17, 0), (86, 0), (17, KEYUP), (86, KEYUP)]
    # V が押されたので貼られたかもしれない。clipboard は待ってから戻す。
    assert ghost.clipboardText == USER_CLIPBOARD
    assert ghost.copies[-1][1] - ghost.pasteTimes[-1] >= 0.5


def test_failed_key_release_is_reported(ghost):
    # Ctrl+V は 2 つまで、そのあと key を離す分は 1 つも受け付けない。
    release = [(17, KEYUP), (86, KEYUP)]
    ghost.accept = lambda keys: 2 if (86, 0) in keys else 0 if keys == release else len(keys)

    with pytest.raises(ig.GreenException, match='some keys may still be pressed'):
        ig.InputGhost.run()


def test_clipboard_that_updates_late_is_still_pasted(ghost, monkeypatch):
    synced_paste = ig.pyperclip.paste
    calls = []

    def late_paste():
        calls.append(None)
        return 'stale' if len(calls) <= 3 else synced_paste()

    monkeypatch.setattr(ig.pyperclip, 'paste', late_paste)

    ig.InputGhost.run()

    assert ghost.events.count((86, 0)) == 3


def test_clipboard_changes_only_after_paste_settles(ghost, monkeypatch):
    monkeypatch.setattr(ig.InputGhost, '_PASTE_SETTLE_TIME', 0.5)

    ig.InputGhost.run()

    # 3 行のコピーのあと、最後に元の clipboard へ戻す。
    assert [text for text, _ in ghost.copies] == [
        'あいうえお', 'かき', 'さし す', USER_CLIPBOARD]
    # どの貼り付けのあとも、次に clipboard を書き換えるまで 0.5 秒以上あく。
    for pasted, (_, copied) in zip(ghost.pasteTimes, ghost.copies[1:]):
        assert copied - pasted >= 0.5
    assert ghost.clipboardText == USER_CLIPBOARD


def steal_focus_right_after_first_paste(ghost, monkeypatch):
    # Ctrl+V を送り終えた直後に前面を奪う。次の操作 ('return') の前で止まる。
    send = ghost.SendInput

    def SendInput(count, inputs, size):
        accepted = send(count, inputs, size)
        if (86, KEYUP) in ghost.events:
            ghost.foregrounds = [OTHER]
        return accepted

    monkeypatch.setattr(ghost, 'SendInput', SendInput)
    return ig.GreenException, 'before action 4/12'


def keep_clipboard_stale(ghost, monkeypatch):
    # clipboard が行の文字列にならないまま CLIPBOARD_TIMEOUT 秒たつ。
    monkeypatch.setattr(ig.pyperclip, 'paste', lambda: USER_CLIPBOARD)
    return ig.GreenException, 'within 5s'


def fail_to_copy_rows(ghost, monkeypatch):
    # 行のコピーだけ失敗する (元に戻すコピーは成功する)。
    def copy(text):
        if text != USER_CLIPBOARD:
            raise ig.pyperclip.PyperclipException('clipboard is locked')
        ghost.copy(text)

    monkeypatch.setattr(ig.pyperclip, 'copy', copy)
    return ig.pyperclip.PyperclipException, 'clipboard is locked'


@pytest.mark.parametrize('stop', [
    steal_focus_right_after_first_paste, keep_clipboard_stale, fail_to_copy_rows])
def test_stopped_run_keeps_its_error_and_restores_clipboard_after_settle(
        ghost, monkeypatch, stop):
    monkeypatch.setattr(ig.InputGhost, '_PASTE_SETTLE_TIME', 0.5)
    error, message = stop(ghost, monkeypatch)

    with pytest.raises(error, match=message):
        ig.InputGhost.run()

    assert ghost.clipboardText == USER_CLIPBOARD
    restored = ghost.copies[-1][1]
    for pasted in ghost.pasteTimes:
        assert restored - pasted >= 0.5


def test_failed_restore_after_a_stop_keeps_the_original_error(
        ghost, monkeypatch, capsys):
    steal_focus_right_after_first_paste(ghost, monkeypatch)

    def copy(text):
        if text == USER_CLIPBOARD:
            raise ig.pyperclip.PyperclipException('restore failed')
        ghost.copy(text)

    monkeypatch.setattr(ig.pyperclip, 'copy', copy)

    with pytest.raises(ig.GreenException, match='Foreground window changed'):
        ig.InputGhost.run()

    assert 'could not restore the clipboard' in capsys.readouterr().err


def test_failed_restore_after_a_normal_run_is_an_error(ghost, monkeypatch):
    def copy(text):
        if text == USER_CLIPBOARD:
            raise ig.pyperclip.PyperclipException('restore failed')
        ghost.copy(text)

    monkeypatch.setattr(ig.pyperclip, 'copy', copy)

    with pytest.raises(ig.pyperclip.PyperclipException, match='restore failed'):
        ig.InputGhost.run()

    # 入力自体は最後まで送られている。
    assert ghost.events.count((86, 0)) == 3


def test_empty_clipboard_is_left_empty(ghost):
    ghost.clipboardText = ''

    ig.InputGhost.run()

    assert ghost.copies[-1][0] == ''
    assert ghost.CountClipboardFormats() == 0


def test_non_text_clipboard_is_refused_before_any_input(ghost):
    # 画像やファイルなど、文字列のない clipboard は戻せないので触らない。
    ghost.clipboardText = ''
    ghost.otherFormats = 2

    with pytest.raises(ig.GreenException, match='non-text.*Nothing was sent'):
        ig.InputGhost.run()

    assert ghost.events == []
    assert ghost.copies == []
    assert ghost.otherFormats == 2


def test_clipboard_is_untouched_when_nothing_is_copied(ghost, monkeypatch):
    monkeypatch.setattr(ig.InputGhost, '_KEY_ORDER', ('0', 'return'))

    ig.InputGhost.run()

    assert ghost.events
    assert ghost.copies == []


def test_focus_change_during_paste_settle_stops_before_next_paste(ghost, monkeypatch):
    monkeypatch.setattr(ig.InputGhost, '_PASTE_SETTLE_TIME', 0.5)

    def steal_focus_while_settling():
        # 1 行目を貼ったあとの待ち (カウントダウンの 1 秒より先に進んだ sleep) で前面を奪う。
        if (86, 0) in ghost.events and ig.time.now > 1.0:
            ghost.foregrounds = [OTHER]

    ig.time.onSleep = steal_focus_while_settling

    with pytest.raises(ig.GreenException, match=r'before action 7/12'):
        ig.InputGhost.run()

    # 2 行目は '0' と 'return' までで、2 回目の Ctrl+V は送られない。
    assert ghost.events.count((86, 0)) == 1
    assert ghost.events[-1] == (13, KEYUP)


def test_stale_clipboard_stops_before_paste(ghost, monkeypatch):
    monkeypatch.setattr(ig.InputGhost, '_CLIPBOARD_TIMEOUT', 2)
    monkeypatch.setattr(ig.InputGhost, '_READY_TIME', 0)
    monkeypatch.setattr(ig.pyperclip, 'paste', lambda: 'stale')

    with pytest.raises(ig.GreenException, match="'あいうえお'.* within 2s"):
        ig.InputGhost.run()

    # 1 行目の '0' と 'return' だけ送られて、Ctrl+V は送られない。
    assert ghost.events == [(48, 0), (48, KEYUP), (13, 0), (13, KEYUP)]
    assert 2 <= ig.time.now < 2.2


@pytest.mark.parametrize('foregrounds', [[CONSOLE], [CONSOLE, 0]])
@pytest.mark.parametrize('ready_time', [1, False])
def test_no_new_target_window_sends_nothing(
        ghost, monkeypatch, ready_time, foregrounds):
    monkeypatch.setattr(ig.InputGhost, '_READY_TIME', ready_time)
    monkeypatch.setattr(ig.subprocess, 'Popen', lambda *args, **kwargs: None)
    ghost.foregrounds = foregrounds

    with pytest.raises(ig.GreenException, match='Nothing was sent'):
        ig.InputGhost.run()

    assert ghost.events == []
    assert ghost.copies == []


def test_focus_change_stops_before_next_key(ghost):
    def steal_focus():
        # カウントダウン中ではなく、入力が始まってからの sleep で前面を奪う。
        if ghost.events:
            ghost.foregrounds = [OTHER]

    ig.time.onSleep = steal_focus

    with pytest.raises(ig.GreenException, match=r'before action 3/12'):
        ig.InputGhost.run()

    # 1 行目の '0' と 'return' だけ送られて、Ctrl+V は送られない。
    assert ghost.events == [(48, 0), (48, KEYUP), (13, 0), (13, KEYUP)]


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
