"""Block extraction, which decides what the documentation contributes."""

from paRY.corpus.collect import extract_blocks


def test_tagged_block_keeps_its_language_and_line():
    text = "intro\n\n```etamil\nஅச்சு \"hi\";\n```\n\ntrailing\n"
    blocks = extract_blocks(text)
    assert len(blocks) == 1
    assert blocks[0]["lang"] == "etamil"
    assert blocks[0]["line"] == 3
    assert blocks[0]["text"] == 'அச்சு "hi";\n'


def test_untagged_block_is_kept_untagged():
    blocks = extract_blocks("```\nplain\n```\n")
    assert [block["lang"] for block in blocks] == [""]


def test_indented_block_loses_its_indent_not_its_body():
    text = "1. run it:\n\n    ```bash\n    etamil a.qmz\n    ```\n"
    blocks = extract_blocks(text)
    assert blocks[0]["text"] == "etamil a.qmz\n"


def test_unclosed_fence_is_not_a_block():
    assert extract_blocks("```etamil\nஅச்சு 1;\n") == []


def test_empty_fence_is_not_a_block():
    assert extract_blocks("```etamil\n```\n") == []
