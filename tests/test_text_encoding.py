'''入力ファイルの文字コードの決め方のテスト。ファイルを読むだけで、Windows には触らない。'''

import codecs

import pytest

import InputGhost as ig


@pytest.fixture
def write(tmp_path, monkeypatch):
    '''合成テキストの byte をファイルに書き、TEXT_ENCODING を設定する。'''

    path = tmp_path / 'input.txt'
    monkeypatch.setattr(ig.InputGhost, '_TEXT_FILE_NAME', str(path))

    def write(data, encoding='auto'):
        path.write_bytes(data)
        monkeypatch.setattr(ig.InputGhost, '_TEXT_ENCODING', encoding)

    return write


@pytest.mark.parametrize('data, text, label', [
    ('あいうえお\r\n'.encode('cp932'), 'あいうえお\r\n', 'cp932'),
    ('あいうえお\r\n'.encode('utf-8'), 'あいうえお\r\n', 'utf-8'),
    (codecs.BOM_UTF8 + 'こんにちは世界'.encode('utf-8'), 'こんにちは世界', 'utf-8 (BOM)'),
    ('ｶﾀｶﾅ'.encode('utf-16'), 'ｶﾀｶﾅ', 'utf-16 (BOM)'),
    (b'plain ascii\r\n', 'plain ascii\r\n', 'ascii'),
])
def test_auto_reads_files_with_only_one_meaning(write, data, text, label):
    write(data)

    assert ig.InputGhost.readInputText() == (text, label)


@pytest.mark.parametrize('data', [
    # UTF-8 の日本語が cp932 としても読めてしまう (「縺薙ｓ縺ｫ…」)。
    'こんにちは世界'.encode('utf-8'),
    # cp932 の半角カナが UTF-8 としても読めてしまう (「é」)。
    'ﾃｩ'.encode('cp932'),
])
def test_auto_refuses_files_that_read_differently_as_utf8_and_cp932(write, data):
    write(data)

    with pytest.raises(
            ig.GreenException,
            match='both as UTF-8 and as cp932.*Nothing was sent.*TEXT_ENCODING'):
        ig.InputGhost.readInputText()


def test_auto_refuses_files_that_are_neither_utf8_nor_cp932(write):
    # 最後の 0x82 は cp932 の 2 byte 文字の 1 byte 目だけで、続きがない。
    write('あ'.encode('cp932') + b'\x82')

    with pytest.raises(
            ig.GreenException,
            match=r'as UTF-8 \(byte 0x82 at position 0\) or cp932 '
                  r'\(byte 0x82 at position 2\).*Nothing was sent'):
        ig.InputGhost.readInputText()


@pytest.mark.parametrize('data, encoding, text', [
    ('こんにちは世界'.encode('utf-8'), 'utf-8', 'こんにちは世界'),
    ('ﾃｩ'.encode('cp932'), 'cp932', 'ﾃｩ'),
    # UTF-8 を指定したら BOM は外す (見えない文字を打たない)。
    (codecs.BOM_UTF8 + b'abc', 'utf-8', 'abc'),
])
def test_explicit_encoding_settles_what_auto_refuses(write, data, encoding, text):
    write(data, encoding)

    assert ig.InputGhost.readInputText() == (text, f'{encoding} (TEXT_ENCODING)')


def test_explicit_encoding_is_strict(write):
    write('あ'.encode('cp932'), 'utf-8')

    with pytest.raises(
            ig.GreenException,
            match=r'as utf-8 \(TEXT_ENCODING\): byte 0x82 at position 0.*Nothing was sent'):
        ig.InputGhost.readInputText()


@pytest.mark.parametrize('encoding', ['no-such-encoding', 'base64'])
def test_unknown_or_non_text_encoding_is_refused(write, encoding):
    # base64 は codec としてはあるが、文字コードではない。
    write(b'abc', encoding)

    with pytest.raises(ig.GreenException, match=f"Unknown TEXT_ENCODING '{encoding}'"):
        ig.InputGhost.readInputText()


def test_bom_that_disagrees_with_the_setting_is_refused(write):
    # cp932 として読むと、UTF-8 の BOM が「・ｿ」のような文字になって打たれてしまう。
    write(codecs.BOM_UTF8 + b'abc', 'cp932')

    with pytest.raises(ig.GreenException, match='UTF-8 BOM.*cp932.*Nothing was sent'):
        ig.InputGhost.readInputText()


def test_nul_characters_are_refused(write):
    # BOM のない UTF-16 は ASCII として読めてしまうが、NUL が入る。
    write('abc'.encode('utf-16-le'))

    with pytest.raises(ig.GreenException, match='NUL.*Nothing was sent'):
        ig.InputGhost.readInputText()
