"""The invariants the tokenizer has to hold, whatever it was trained on."""

import pytest
from tokenizers import Tokenizer

from paRY import config, lexicon
from paRY.tokenizer.train import SPECIAL_TOKENS, build_tokenizer

TOKENIZER_PATH = config.TOKENIZER_DIR / "paRY-16k.json"

needs_tokenizer = pytest.mark.skipif(
    not TOKENIZER_PATH.exists(), reason="run python -m paRY.tokenizer.train first"
)


@pytest.fixture(scope="module")
def tokenizer() -> Tokenizer:
    return Tokenizer.from_file(str(TOKENIZER_PATH))


def test_a_tamil_word_is_one_pre_token():
    """The bug that cost the first tokenizer every keyword it had.

    Tamil vowel signs are combining marks, and a splitter that only knows
    `\\p{L}` cuts a word into pieces BPE can never merge back together. This
    holds on an untrained tokenizer because it is a property of the splitter.
    """
    pieces = build_tokenizer().pre_tokenizer.pre_tokenize_str("செயல் வருவாய்")
    assert len(pieces) == 2


def test_an_underscore_may_start_a_word():
    """`_fn` and `_GST` are spellings the lexer accepts."""
    pieces = build_tokenizer().pre_tokenizer.pre_tokenize_str("_fn")
    assert len(pieces) == 1


@needs_tokenizer
def test_every_special_token_survived_training(tokenizer):
    for token in SPECIAL_TOKENS:
        assert tokenizer.token_to_id(token) is not None


@needs_tokenizer
@pytest.mark.parametrize(
    "text",
    [
        'செயல் கூட்டு(எண் a, எண் b) { திரும்பு a + b; }\n',
        "eN varuvAy = 100000;\n",
        "// ஒரு குறிப்பு — em dash, quotes “ ” and a tab\there\n",
        "\r\n\r\n",
        "🪘 பறை\n",
    ],
)
def test_text_survives_a_round_trip(tokenizer, text):
    encoded = tokenizer.encode(text, add_special_tokens=False)
    assert tokenizer.decode(encoded.ids) == text


@needs_tokenizer
def test_every_accepted_name_is_a_single_token(tokenizer):
    """A keyword that costs four tokens is four chances to invent a keyword.

    Except where the name carries a digit, and then it cannot be one token by
    this tokenizer's own design: digits are split individually because this is
    a language for money, and `18` reaching the model as one symbol it has seen
    and `180` as one it has not is how an amount comes back wrong. That rule is
    worth more than one-token names for the two identifiers it costs.

    Those two are `முறை_0_100` and `முறை_50_50` — 0/100 and 50/50 are the
    standard names of the earned-value conventions they implement, so the
    digits are the domain's and not a naming slip to tidy away.

    The assertion is therefore that a name splits *only* because of a digit. A
    name without one that splits is a real regression and still fails here.
    """
    names = lexicon.load().vocabulary
    split = [
        name
        for name in names
        if len(tokenizer.encode(" " + name, add_special_tokens=False).ids) != 1
    ]
    assert [name for name in split if not any(c.isdigit() for c in name)] == []


@needs_tokenizer
def test_digits_are_separate_tokens(tokenizer):
    """Money. `18` and `180` must not share a token."""
    assert tokenizer.encode("800000", add_special_tokens=False).tokens == ["8", "0", "0", "0", "0", "0"]
