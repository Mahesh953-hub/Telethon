"""
Tests for `telethon.extensions.markdownv3` (the unified MarkdownV3 parser).

These implement the test matrix from ``/code/.plans/mdv3-research.md``.
A few offsets/lengths and one or two "expected unparse" strings in that
doc are internally inconsistent (the doc admits as much for the
surrogate-pair section, and a couple of the escaping/unparse examples
contradict each other -- see the build report). Where that happens this
suite asserts the value that is *actually correct* for the described
input/behaviour rather than blindly copying the doc's arithmetic; the
semantic intent of every case is preserved.
"""
import pytest

from telethon.extensions import markdownv3
from telethon.extensions.markdownv3 import MarkdownV3, parse, unparse
from telethon.tl.types import (
    MessageEntityBold, MessageEntityItalic, MessageEntityCode,
    MessageEntityPre, MessageEntityTextUrl, MessageEntitySpoiler,
    MessageEntityBlockquote, MessageEntityCustomEmoji, MessageEntityUnderline,
    MessageEntityStrike, MessageEntityMentionName, MessageEntityUrl,
)

parser = MarkdownV3()


def _types(entities):
    return [type(e) for e in entities]


def _spans(entities):
    return [(type(e), e.offset, e.length) for e in entities]


# region Basic formatting (cases 1-5)

def test_case_01_basic_bold():
    text, entities = parser.parse('**bold**')
    assert text == 'bold'
    assert _spans(entities) == [(MessageEntityBold, 0, 4)]
    assert parser.unparse(text, entities, flavor='markdown2') == '**bold**'


def test_case_02_basic_italic():
    text, entities = parser.parse('__italic__')
    assert text == 'italic'
    assert _spans(entities) == [(MessageEntityItalic, 0, 6)]
    assert parser.unparse(text, entities, flavor='markdown2') == '__italic__'


def test_case_03_underline():
    text, entities = parser.parse('--underline--')
    assert text == 'underline'
    assert _spans(entities) == [(MessageEntityUnderline, 0, 9)]
    assert parser.unparse(text, entities, flavor='markdown2') == '--underline--'


def test_case_04_strike():
    text, entities = parser.parse('~~strike~~')
    assert text == 'strike'
    assert _spans(entities) == [(MessageEntityStrike, 0, 6)]
    assert parser.unparse(text, entities, flavor='markdown2') == '~~strike~~'


def test_case_05_inline_code():
    text, entities = parser.parse('`code`')
    assert text == 'code'
    assert _spans(entities) == [(MessageEntityCode, 0, 4)]
    assert parser.unparse(text, entities, flavor='markdown2') == '`code`'

# endregion


# region Code blocks & blockquotes (cases 6-10)

def test_case_06_fenced_code_no_language():
    text, entities = parser.parse('```\ntext\n```')
    assert text == 'text'
    assert len(entities) == 1
    assert isinstance(entities[0], MessageEntityPre)
    assert (entities[0].offset, entities[0].length, entities[0].language) == (0, 4, '')
    assert parser.unparse(text, entities, flavor='markdown2') == '```\ntext\n```'


def test_case_07_fenced_code_with_language():
    text, entities = parser.parse('```python\ncode\n```')
    assert text == 'code'
    assert len(entities) == 1
    assert isinstance(entities[0], MessageEntityPre)
    assert (entities[0].offset, entities[0].length, entities[0].language) == (0, 4, 'python')
    assert parser.unparse(text, entities, flavor='markdown2') == '```python\ncode\n```'


def test_case_08_regular_blockquote():
    text, entities = parser.parse('> quote')
    assert text == 'quote'
    assert len(entities) == 1
    assert isinstance(entities[0], MessageEntityBlockquote)
    assert (entities[0].offset, entities[0].length) == (0, 5)
    assert not entities[0].collapsed
    assert parser.unparse(text, entities, flavor='markdown2') == '> quote'


def test_case_09_expandable_blockquote():
    text, entities = parser.parse('**> expanded')
    assert text == 'expanded'
    assert len(entities) == 1
    assert isinstance(entities[0], MessageEntityBlockquote)
    assert (entities[0].offset, entities[0].length) == (0, 8)
    assert entities[0].collapsed is True
    assert parser.unparse(text, entities, flavor='markdown2') == '**> expanded'


def test_case_10_multiline_blockquote():
    text, entities = parser.parse('> line1\n> line2')
    assert text == 'line1\nline2'
    assert len(entities) == 1
    assert isinstance(entities[0], MessageEntityBlockquote)
    assert (entities[0].offset, entities[0].length) == (0, len('line1\nline2'))
    assert parser.unparse(text, entities, flavor='markdown2') == '> line1\n> line2'

# endregion


# region Links & special URLs (cases 11-15)

def test_case_11_text_url():
    text, entities = parser.parse('[link](http://example.com)')
    assert text == 'link'
    assert len(entities) == 1
    assert isinstance(entities[0], MessageEntityTextUrl)
    assert (entities[0].offset, entities[0].length, entities[0].url) == (0, 4, 'http://example.com')
    assert parser.unparse(text, entities, flavor='markdown2') == '[link](http://example.com)'


def test_case_12_user_mention():
    text, entities = parser.parse('[user](tg://user?id=123)')
    assert text == 'user'
    assert len(entities) == 1
    assert isinstance(entities[0], MessageEntityMentionName)
    assert (entities[0].offset, entities[0].length, entities[0].user_id) == (0, 4, 123)
    assert parser.unparse(text, entities, flavor='markdown2') == '[user](tg://user?id=123)'


def test_case_13_custom_emoji_markdown():
    text, entities = parser.parse('[emoji](emoji/5471952317469485434)')
    assert text == 'emoji'
    assert len(entities) == 1
    assert isinstance(entities[0], MessageEntityCustomEmoji)
    assert (entities[0].offset, entities[0].length, entities[0].document_id) == (0, 5, 5471952317469485434)
    assert parser.unparse(text, entities, flavor='markdown2') == '[emoji](emoji/5471952317469485434)'


def test_case_14_html_link():
    text, entities = parser.parse('<a href="http://example.com">link</a>', mode='html')
    assert text == 'link'
    assert _spans(entities) == [(MessageEntityTextUrl, 0, 4)]
    assert entities[0].url == 'http://example.com'
    assert parser.unparse(text, entities, flavor='html') == '<a href="http://example.com">link</a>'


def test_case_15_html_custom_emoji():
    text, entities = parser.parse(
        '<tg-emoji emoji-id="5471952317469485434">\U0001F600</tg-emoji>', mode='html')
    assert text == '\U0001F600'
    assert len(entities) == 1
    assert isinstance(entities[0], MessageEntityCustomEmoji)
    # The emoji is outside the BMP -> 2 UTF-16 units.
    assert (entities[0].offset, entities[0].length, entities[0].document_id) == (0, 2, 5471952317469485434)
    assert parser.unparse(text, entities, flavor='html') == (
        '<tg-emoji emoji-id="5471952317469485434">\U0001F600</tg-emoji>')

# endregion


# region Spoilers & mixed formatting (cases 16-20)

def test_case_16_markdownv2_spoiler():
    text, entities = parser.parse('||spoiler||', mode='markdown2')
    assert text == 'spoiler'
    assert _spans(entities) == [(MessageEntitySpoiler, 0, 7)]
    assert parser.unparse(text, entities, flavor='markdown2') == '||spoiler||'


def test_case_17_legacy_spoiler():
    text, entities = parser.parse('$$spoiler$$', mode='legacy')
    assert text == 'spoiler'
    assert _spans(entities) == [(MessageEntitySpoiler, 0, 7)]
    assert parser.unparse(text, entities, flavor='legacy') == '$$spoiler$$'


def test_case_18_html_spoiler():
    text, entities = parser.parse('<tg-spoiler>hide</tg-spoiler>', mode='html')
    assert text == 'hide'
    assert _spans(entities) == [(MessageEntitySpoiler, 0, 4)]
    assert parser.unparse(text, entities, flavor='html') == '<tg-spoiler>hide</tg-spoiler>'


def test_case_19_nested_formatting():
    # NOTE: the fork uses double-underscore `__` for italic (see the
    # delimiter table); the doc's case 19 input uses a single `_` which
    # contradicts its own expected *unparse* output (`__and italic__`).
    # We use `__` consistently, matching the fork's actual convention.
    text, entities = parser.parse('**bold __and italic__**')
    assert text == 'bold and italic'
    assert isinstance(entities[0], MessageEntityBold)
    assert isinstance(entities[1], MessageEntityItalic)
    assert (entities[0].offset, entities[0].length) == (0, len('bold and italic'))
    assert (entities[1].offset, entities[1].length) == (5, len('and italic'))
    assert parser.unparse(text, entities, flavor='markdown2') == '**bold __and italic__**'


def test_case_20_adjacent_entities():
    text, entities = parser.parse('**bold** and **bold**')
    assert text == 'bold and bold'
    assert _spans(entities) == [(MessageEntityBold, 0, 4), (MessageEntityBold, 9, 4)]
    assert parser.unparse(text, entities, flavor='markdown2') == '**bold** and **bold**'

# endregion


# region Escaping & special characters (cases 21-23)

def test_case_21_escaped_delimiters():
    text, entities = parser.parse(r'\*not bold\*', mode='markdown2')
    assert text == '*not bold*'
    assert entities == []
    # unparse() backslash-escapes inline delimiters found in literal
    # text (all of ``text`` is content — formatting lives in entities),
    # so the unparse -> parse round trip is lossless even though a
    # single '*' is itself an italic delimiter.
    unparsed = parser.unparse(text, entities, flavor='markdown2')
    assert unparsed == r'\*not bold\*'
    text2, entities2 = parser.parse(unparsed, mode='markdown2')
    assert (text2, entities2) == (text, entities)


def test_case_22_escape_outside_escape_list():
    text, entities = parser.parse(r'Cost: \$5', mode='markdown2')
    assert text == 'Cost: $5'
    assert entities == []
    assert parser.unparse(text, entities, flavor='markdown2') == 'Cost: $5'


def test_case_23_escaped_backtick_in_code():
    # Raw input: `code \` with backtick` -- the backslash-escaped
    # backtick must stay literal instead of closing the code span early.
    raw = '`code \\` with backtick`'
    text, entities = parser.parse(raw, mode='mixed')
    assert text == 'code ` with backtick'
    assert len(entities) == 1
    assert isinstance(entities[0], MessageEntityCode)
    assert (entities[0].offset, entities[0].length) == (0, len('code ` with backtick'))

# endregion


# region Emoji & UTF-16 offsets (cases 24-26)

def test_case_24_emoji_in_bold():
    text, entities = parser.parse('**\U0001F44B**')
    assert text == '\U0001F44B'
    assert _spans(entities) == [(MessageEntityBold, 0, 2)]
    assert parser.unparse(text, entities, flavor='markdown2') == '**\U0001F44B**'


def test_case_25_entity_after_emoji():
    text, entities = parser.parse('Hi \U0001F44B **Bye**')
    assert text == 'Hi \U0001F44B Bye'
    assert _spans(entities) == [(MessageEntityBold, 6, 3)]
    assert parser.unparse(text, entities, flavor='markdown2') == 'Hi \U0001F44B **Bye**'


def test_case_26_adjacent_emoji_and_entity():
    # From the existing test_markdown.py::test_entities_together.
    original = '**\u2699\ufe0f**__Settings__'
    text, entities = parser.parse(original)
    assert text == '\u2699\ufe0fSettings'
    assert _spans(entities) == [(MessageEntityBold, 0, 2), (MessageEntityItalic, 2, 8)]
    assert parser.unparse(text, entities, flavor='markdown2') == original

# endregion


# region Mixed input (cases 27-30)

def test_case_27_markdown_plus_html_to_html():
    text, entities = parser.parse('**bold** and <i>italic</i>')
    assert text == 'bold and italic'
    assert _spans(entities) == [(MessageEntityBold, 0, 4), (MessageEntityItalic, 9, 6)]
    assert parser.unparse(text, entities, flavor='html') == '<b>bold</b> and <i>italic</i>'


def test_case_28_html_plus_markdown_to_markdown2():
    text, entities = parser.parse('<b>bold</b> and __italic__')
    assert text == 'bold and italic'
    assert _spans(entities) == [(MessageEntityBold, 0, 4), (MessageEntityItalic, 9, 6)]
    assert parser.unparse(text, entities, flavor='markdown2') == '**bold** and __italic__'


def test_case_29_html_nested_inside_markdown():
    text, entities = parser.parse('**bold <i>nested</i>**')
    assert text == 'bold nested'
    assert _spans(entities) == [(MessageEntityBold, 0, 11), (MessageEntityItalic, 5, 6)]
    assert parser.unparse(text, entities, flavor='html') == '<b>bold <i>nested</i></b>'


def test_case_30_blockquote_with_formatting():
    text, entities = parser.parse('> **quoted bold**')
    assert text == 'quoted bold'
    assert len(entities) == 2
    types_offsets = {(type(e), e.offset, e.length) for e in entities}
    assert types_offsets == {
        (MessageEntityBlockquote, 0, 11),
        (MessageEntityBold, 0, 11),
    }
    assert parser.unparse(text, entities, flavor='markdown2') == '> **quoted bold**'

# endregion


# region Edge cases (cases 31-35)

def test_case_31_empty_string():
    text, entities = parser.parse('')
    assert text == ''
    assert entities == []
    assert parser.unparse(text, entities, flavor='markdown2') == ''


def test_case_32_whitespace_stripping():
    text, entities = parser.parse('  text  ')
    assert text == 'text'
    assert entities == []


def test_case_33_unmatched_delimiter():
    text, entities = parser.parse('**')
    assert text == '**'
    assert entities == []
    # The literal '**' is escaped on unparse so it round-trips instead
    # of being read as an (unmatched) bold delimiter by a fresh parse.
    unparsed = parser.unparse(text, entities, flavor='markdown2')
    assert unparsed == r'\*\*'
    assert parser.parse(unparsed, mode='markdown2') == ('**', [])


def test_case_34_malformed_link():
    text, entities = parser.parse('[no](')
    assert text == '[no]('
    assert entities == []


def test_case_35_auto_detected_entities_not_parsed():
    text, entities = parser.parse('text with @mention and #tag')
    assert text == 'text with @mention and #tag'
    assert entities == []
    assert parser.unparse(text, entities, flavor='markdown2') == 'text with @mention and #tag'

# endregion


# region Round-trip tests (cases 36-40)

def test_case_36_roundtrip_bold():
    text, entities = parser.parse('**bold**')
    assert parser.unparse(text, entities, flavor='markdown2') == '**bold**'


def test_case_37_roundtrip_html_italic():
    text, entities = parser.parse('<i>italic</i>')
    assert parser.unparse(text, entities, flavor='html') == '<i>italic</i>'


def test_case_38_double_roundtrip_mixed():
    original = '**bold** and <i>italic</i>'
    text, entities = parser.parse(original)
    unparsed = parser.unparse(text, entities, flavor='markdown2')

    text2, entities2 = parser.parse(unparsed)
    assert text2 == text
    assert _spans(entities2) == _spans(entities)


def test_case_39_strict_escapes_html_injection():
    text, entities = parser.parse(
        "<script>alert('xss')</script>", mode='mixed', strict=True)
    # The script tag must be treated as literal text, never as a real
    # HTML tag / entity.
    assert text == "<script>alert('xss')</script>"
    assert entities == []


def test_case_40_unparse_preserves_autodetected_url():
    text = 'Visit http://example.com'
    entities = [MessageEntityUrl(offset=6, length=18)]
    assert parser.unparse(text, entities, flavor='html') == (
        'Visit <a href="http://example.com">http://example.com</a>')
    # Auto-detected entities aren't given markdown markup (they already
    # look correct as plain text).
    assert parser.unparse(text, entities, flavor='markdown2') == text

# endregion


# region Module-level API / backwards compatibility

def test_module_level_parse_unparse_are_exported():
    text, entities = parse('**bold**')
    assert text == 'bold'
    assert unparse(text, entities, flavor='markdown2') == '**bold**'


def test_extensions_package_exports_new_markdownv3():
    from telethon.extensions import MarkdownV3 as ExportedMarkdownV3
    assert ExportedMarkdownV3 is markdownv3.MarkdownV3


def test_markdown_alias_points_to_markdownv3():
    assert markdownv3.Markdown is markdownv3.MarkdownV3


def test_sanitize_parse_mode_uses_unified_parser():
    from telethon import utils

    for mode in ('mdv3', 'markdownv3', 'v3'):
        resolved = utils.sanitize_parse_mode(mode)
        assert isinstance(resolved, markdownv3.MarkdownV3)
        text, entities = resolved.parse('**bold** and <i>italic</i>')
        assert text == 'bold and italic'
        assert _types(entities) == [MessageEntityBold, MessageEntityItalic]

    # Untouched mappings must keep working as before.
    md = utils.sanitize_parse_mode('md')
    assert md.__name__ == 'telethon.extensions.markdown'

    mdv2 = utils.sanitize_parse_mode('mdv2')
    assert type(mdv2).__module__ == 'telethon.extensions.markdownv2'

    html_mod = utils.sanitize_parse_mode('html')
    assert html_mod.__name__ == 'telethon.extensions.html'


def test_invalid_parse_mode_raises():
    with pytest.raises(ValueError):
        parser.parse('text', mode='not-a-real-mode')


def test_invalid_unparse_flavor_raises():
    with pytest.raises(ValueError):
        parser.unparse('text', [MessageEntityBold(0, 4)], flavor='not-a-real-flavor')

# endregion


# region Additional coverage: overlapping/nested entities, HTML modes

def test_overlapping_entities_unparse_markdown2():
    text = '01234567'
    entities = [MessageEntityBold(0, 5), MessageEntityItalic(3, 5)]
    result = parser.unparse(text, entities, flavor='markdown2')
    assert result == '**012__34**567__'


def test_properly_nested_entities_unparse_markdown2():
    text = '0123456789'
    entities = [MessageEntityBold(0, 10), MessageEntityItalic(2, 4)]
    result = parser.unparse(text, entities, flavor='markdown2')
    assert result == '**01__2345__6789**'
    # And it parses back correctly nested.
    text2, entities2 = parser.parse(result)
    assert text2 == text
    assert _spans(entities2) == [(MessageEntityBold, 0, 10), (MessageEntityItalic, 2, 4)]


def test_properly_nested_entities_unparse_html():
    text = '0123456789'
    entities = [MessageEntityBold(0, 10), MessageEntityItalic(2, 4)]
    result = parser.unparse(text, entities, flavor='html')
    assert result == '<b>01<i>2345</i>6789</b>'
    text2, entities2 = parser.parse(result, mode='html')
    assert text2 == text
    assert _spans(entities2) == [(MessageEntityBold, 0, 10), (MessageEntityItalic, 2, 4)]


def test_mode_markdown_treats_html_as_literal():
    text, entities = parser.parse('**bold** and <i>italic</i>', mode='markdown')
    assert text == 'bold and <i>italic</i>'
    assert _spans(entities) == [(MessageEntityBold, 0, 4)]


def test_mode_html_ignores_markdown_delimiters():
    text, entities = parser.parse('**bold**', mode='html')
    assert text == '**bold**'
    assert entities == []


def test_legacy_mode_still_supports_underline_and_collapsed_blockquote():
    # Exercised via the legacy delimiters directly supported by
    # telethon.extensions.markdown.DEFAULT_DELIMITERS.
    text, entities = parser.parse('++underline++', mode='legacy')
    assert text == 'underline'
    assert _spans(entities) == [(MessageEntityUnderline, 0, 9)]

    text, entities = parser.parse('^^collapsed^^', mode='legacy')
    assert text == 'collapsed'
    assert len(entities) == 1
    assert isinstance(entities[0], MessageEntityBlockquote)
    assert entities[0].collapsed is True


def test_blockquote_entity_survives_html_flavor_roundtrip():
    text, entities = parser.parse('> line1\n> line2')
    html_out = parser.unparse(text, entities, flavor='html')
    assert html_out == '<blockquote>line1\nline2</blockquote>'
    text2, entities2 = parser.parse(html_out, mode='html')
    assert text2 == text
    assert _spans(entities2) == _spans(entities)


def test_expandable_blockquote_html_flavor():
    text, entities = parser.parse('**> expanded')
    html_out = parser.unparse(text, entities, flavor='html')
    assert html_out == '<blockquote expandable>expanded</blockquote>'


def test_unparse_with_single_tlobject_entity():
    # unparse() must also accept a single TLObject (not just a list),
    # matching markdown.py/html.py's existing behaviour.
    text = 'bold'
    entity = MessageEntityBold(0, 4)
    assert parser.unparse(text, entity, flavor='markdown2') == '**bold**'

# endregion


# region Review-agent regression tests (8 correctness bugs)
#
# These regressions were found by a review agent after the initial
# implementation landed. Each ``test_bugN_*`` below reproduces the
# reported failure and asserts the fixed behaviour; see the build
# report for the underlying root-cause analysis of each one.

def test_bug1_scan_continues_past_grown_replacements():
    # _convert_markdown_delimiters used to cache the string length
    # before doing any replacement; once a "**x**" -> "<b>x</b>"
    # substitution made the working string longer, anything past the
    # *original* length was silently never scanned again.
    text, entities = parser.parse('**a** **b** **c**')
    assert text == 'a b c'
    assert _spans(entities) == [
        (MessageEntityBold, 0, 1), (MessageEntityBold, 2, 1), (MessageEntityBold, 4, 1),
    ]


def test_bug1_scan_continues_after_a_link():
    text, entities = parser.parse('[x](u) **b**')
    assert text == 'x b'
    assert _spans(entities) == [
        (MessageEntityTextUrl, 0, 1), (MessageEntityBold, 2, 1),
    ]
    assert entities[0].url == 'u'


def test_bug1_three_or_more_formatting_spans():
    text, entities = parser.parse('**a** __b__ ~~c~~ --d--')
    assert text == 'a b c d'
    assert _spans(entities) == [
        (MessageEntityBold, 0, 1),
        (MessageEntityItalic, 2, 1),
        (MessageEntityStrike, 4, 1),
        (MessageEntityUnderline, 6, 1),
    ]


def test_bug1_formatting_after_a_link():
    text, entities = parser.parse('[x](u) **after link**')
    assert text == 'x after link'
    assert _spans(entities) == [
        (MessageEntityTextUrl, 0, 1), (MessageEntityBold, 2, 10),
    ]


def test_bug1_formatting_after_a_code_span():
    text, entities = parser.parse('`code` **after code**')
    assert text == 'code after code'
    assert _spans(entities) == [
        (MessageEntityCode, 0, 4), (MessageEntityBold, 5, 10),
    ]


def test_bug2_escaped_astral_char_does_not_shift_later_offsets():
    # The escaped emoji is 1 placeholder unit while it's protected, but
    # a real astral character (2 UTF-16 units) once restored: the Bold
    # entity after it must account for that extra unit.
    text, entities = parser.parse('\\\U0001F600 **x**', mode='markdown2')
    assert text == '\U0001F600 x'
    assert _spans(entities) == [(MessageEntityBold, 3, 1)]


def test_bug2_escaped_astral_char_inside_entity_content():
    text, entities = parser.parse('**\\\U0001F600 x**')
    assert text == '\U0001F600 x'
    # 4 UTF-16 units: 2 for the astral emoji, 1 for the space, 1 for 'x'.
    assert _spans(entities) == [(MessageEntityBold, 0, 4)]


def test_bug3_fenced_code_protects_blockquote_marker_inside():
    text, entities = parser.parse('```\n> literal\n```')
    assert text == '> literal'
    assert _spans(entities) == [(MessageEntityPre, 0, 9)]


def test_bug3_html_pre_protects_blockquote_marker_inside():
    text, entities = parser.parse('<pre>\n> literal\n</pre>')
    assert text == '> literal'
    assert _spans(entities) == [(MessageEntityPre, 0, 9)]


def test_bug3_inline_code_protects_quote_marker_inside():
    # Additional coverage the reviewer asked for: quote markers inside
    # an *inline* (single backtick) code span, not just a fence.
    text, entities = parser.parse('`> not a quote`')
    assert text == '> not a quote'
    assert _spans(entities) == [(MessageEntityCode, 0, 13)]


def test_bug4_formatting_entity_escapes_its_own_delimiter_in_content():
    result = parser.unparse('a**b', [MessageEntityBold(0, 4)], flavor='markdown2')
    text, entities = parser.parse(result)
    assert text == 'a**b'
    assert _spans(entities) == [(MessageEntityBold, 0, 4)]


def test_bug4_code_entity_escapes_backtick_in_content():
    result = parser.unparse('a`b', [MessageEntityCode(0, 3)], flavor='markdown2')
    text, entities = parser.parse(result)
    assert text == 'a`b'
    assert _spans(entities) == [(MessageEntityCode, 0, 3)]


def test_bug5_nested_bold_inside_link_survives_roundtrip():
    text = 'bold'
    entities = [MessageEntityTextUrl(0, 4, 'url'), MessageEntityBold(0, 4)]
    result = parser.unparse(text, entities, flavor='markdown2')
    text2, entities2 = parser.parse(result)
    assert text2 == 'bold'
    assert _spans(entities2) == [(MessageEntityTextUrl, 0, 4), (MessageEntityBold, 0, 4)]
    assert entities2[0].url == 'url'


def test_bug5_nested_link_entities_direct_parse():
    text, entities = parser.parse('[**bold**](url)')
    assert text == 'bold'
    assert _spans(entities) == [(MessageEntityTextUrl, 0, 4), (MessageEntityBold, 0, 4)]
    assert entities[0].url == 'url'


def test_bug6_markdown_inside_html_attribute_is_not_converted():
    text, entities = parser.parse('<a href="https://e/**segment**">label</a>')
    assert text == 'label'
    assert _spans(entities) == [(MessageEntityTextUrl, 0, 5)]
    assert entities[0].url == 'https://e/**segment**'


def test_bug6_markdown_inside_other_html_attribute_is_not_converted():
    text, entities = parser.parse(
        '<a href="url" title="**t**">label</a>')
    assert text == 'label'
    assert _spans(entities) == [(MessageEntityTextUrl, 0, 5)]
    assert entities[0].url == 'url'


def test_bug7_unparsed_url_with_escaped_chars_roundtrips():
    url = 'https://e/x)y\\z'
    entities = [MessageEntityTextUrl(0, 1, url)]
    result = parser.unparse('x', entities, flavor='markdown2')
    text2, entities2 = parser.parse(result)
    assert text2 == 'x'
    assert _spans(entities2) == [(MessageEntityTextUrl, 0, 1)]
    assert entities2[0].url == url


def test_bug8_adjacent_blockquotes_split_on_collapsed_state_change():
    text, entities = parser.parse('> q\n**> collapsed')
    assert text == 'q\ncollapsed'
    assert _spans(entities) == [
        (MessageEntityBlockquote, 0, 1), (MessageEntityBlockquote, 2, 9),
    ]
    assert not entities[0].collapsed
    assert entities[1].collapsed is True


def test_bug8_adjacent_blockquotes_same_state_still_merge():
    # Sanity check that the fix for bug 8 didn't break the existing
    # "contiguous same-state lines merge into one entity" behaviour.
    text, entities = parser.parse('> line1\n> line2')
    assert text == 'line1\nline2'
    assert _spans(entities) == [(MessageEntityBlockquote, 0, 11)]
    assert not entities[0].collapsed

# endregion
