"""
Tests for the full MarkdownV3 block-level support added on top of the
unified parser in ``telethon/extensions/markdownv3.py``: headings,
lists (unordered/ordered/task), images, GFM tables, GitHub-style
callouts, ``:::`` admonitions, ``<kbd>``, ``~~strike~~``, LaTeX math and
horizontal rules. See ``/code/.plans/mdv3-blocks-spec.md`` for the
normative mapping this test matrix implements (mappings #1-#15).
"""
import re

import pytest

from telethon.extensions.markdownv3 import MarkdownV3
from telethon.helpers import add_surrogate
from telethon.tl.types import (
    MessageEntityBold, MessageEntityItalic, MessageEntityCode,
    MessageEntityPre, MessageEntityTextUrl, MessageEntitySpoiler,
    MessageEntityBlockquote, MessageEntityUnderline, MessageEntityStrike,
)

parser = MarkdownV3()


def _spans(entities):
    return [(type(e), e.offset, e.length) for e in entities]


def _utf16_len(s):
    # Entity lengths are counted in UTF-16 code units; some of the
    # emoji used in callout/admonition labels (e.g. tip/danger/caution)
    # are outside the BMP and take 2 units each as a Python `str` char.
    return len(add_surrogate(s))


# region 1. Headings

def test_heading_h1_bold_underline():
    text, entities = parser.parse('# Heading 1')
    assert text == 'Heading 1'
    assert set(_spans(entities)) == {
        (MessageEntityBold, 0, 9), (MessageEntityUnderline, 0, 9),
    }


def test_heading_h2_bold_only():
    text, entities = parser.parse('## Heading 2')
    assert text == 'Heading 2'
    assert _spans(entities) == [(MessageEntityBold, 0, 9)]


@pytest.mark.parametrize('level', [3, 4, 5, 6])
def test_heading_h3_to_h6_bold_italic(level):
    text, entities = parser.parse('{} Heading'.format('#' * level))
    assert text == 'Heading'
    assert set(_spans(entities)) == {
        (MessageEntityBold, 0, 7), (MessageEntityItalic, 0, 7),
    }


def test_heading_hash_markers_removed():
    text, _ = parser.parse('# Heading 1')
    assert '#' not in text


def test_heading_seven_hashes_is_not_a_heading():
    text, entities = parser.parse('####### not a heading')
    assert text == '####### not a heading'
    assert entities == []


def test_heading_nested_bold_is_deduped_not_doubled():
    # `# **x**` must not produce two identical, overlapping Bold
    # entities: the heading-level Bold and the inline `**x**` Bold
    # cover the exact same range and must merge into one.
    text, entities = parser.parse('# **x**')
    assert text == 'x'
    bolds = [e for e in entities if isinstance(e, MessageEntityBold)]
    assert len(bolds) == 1
    assert (bolds[0].offset, bolds[0].length) == (0, 1)
    assert any(isinstance(e, MessageEntityUnderline) for e in entities)


def test_heading_partial_nested_bold_is_absorbed():
    # Only *part* of the heading is bold, but it's still the *same*
    # entity type (Bold) as the heading itself and fully contained
    # within its range, so it must be absorbed into the single
    # whole-heading Bold entity rather than kept as a separate,
    # fully-redundant nested entity (bug #7 in the review of commit
    # 03eb2525) -- this is what makes unparse/parse round-trip
    # cleanly instead of re-emitting a spurious nested ``**x**``.
    text, entities = parser.parse('## a **x** b')
    assert text == 'a x b'
    bolds = sorted(
        (e.offset, e.length) for e in entities if isinstance(e, MessageEntityBold))
    assert bolds == [(0, 5)]


def test_heading_content_still_inline_parsed():
    text, entities = parser.parse('## __italic__ heading')
    assert text == 'italic heading'
    assert any(isinstance(e, MessageEntityItalic) and e.offset == 0 and e.length == 6
               for e in entities)
    assert any(isinstance(e, MessageEntityBold) and e.offset == 0 and e.length == 14
               for e in entities)


def test_heading_roundtrip_through_unparse():
    text, entities = parser.parse('# Heading 1')
    unparsed = parser.unparse(text, entities, flavor='markdown2')
    text2, entities2 = parser.parse(unparsed)
    assert text2 == text
    assert set(_spans(entities2)) == set(_spans(entities))

# endregion


# region 2 & 3. Unordered / ordered lists (incl. nesting)

def test_unordered_list_bullets_by_depth():
    text, _ = parser.parse('- item 1\n- item 2\n  - nested item\n  - nested item')
    assert text == '\u2022 item 1\n\u2022 item 2\n  \u25e6 nested item\n  \u25e6 nested item'


def test_unordered_list_depth_two_plus_uses_triangle():
    text, _ = parser.parse('- a\n  - b\n    - c')
    assert text == '\u2022 a\n  \u25e6 b\n    \u25aa c'


def test_unordered_list_accepts_star_and_plus_markers():
    text, _ = parser.parse('* a\n+ b')
    assert text == '\u2022 a\n\u2022 b'


def test_unordered_list_item_text_is_inline_parsed():
    text, entities = parser.parse('- **bold** item')
    assert text == '\u2022 bold item'
    assert _spans(entities) == [(MessageEntityBold, 2, 4)]


def test_ordered_list_sequential_numbering():
    text, _ = parser.parse('1. first\n2. second\n3. third')
    assert text == '1. first\n2. second\n3. third'


def test_ordered_list_renumbers_regardless_of_source_numbers():
    text, _ = parser.parse('5. first\n5. second\n5. third')
    assert text == '1. first\n2. second\n3. third'


def test_ordered_list_nested_restarts_and_resumes_parent_count():
    text, _ = parser.parse('1. a\n  1. nested1\n  2. nested2\n2. b')
    assert text == '1. a\n  1. nested1\n  2. nested2\n2. b'


def test_ordered_list_breaks_reset_numbering():
    text, _ = parser.parse('1. a\n2. b\n\nsomething else\n\n1. c\n2. d')
    assert text == '1. a\n2. b\n\nsomething else\n\n1. c\n2. d'

# endregion


# region 4. Task lists

def test_task_list_checked_and_unchecked():
    text, _ = parser.parse('- [x] done\n- [ ] todo')
    assert text == '\u2611 done\n\u2610 todo'


def test_task_list_uppercase_x_checked():
    text, _ = parser.parse('- [X] done')
    assert text == '\u2611 done'


def test_task_list_no_bullet_before_box():
    text, _ = parser.parse('- [ ] todo')
    assert not text.startswith('\u2022')
    assert text == '\u2610 todo'

# endregion


# region 5. Images

def test_image_becomes_text_url_over_alt_text():
    text, entities = parser.parse('![Alt text](image-url.png)')
    assert text == 'Alt text'
    assert _spans(entities) == [(MessageEntityTextUrl, 0, 8)]
    assert entities[0].url == 'image-url.png'


def test_image_empty_alt_falls_back_to_image_word():
    text, entities = parser.parse('![](pic.png)')
    assert text == 'image'
    assert _spans(entities) == [(MessageEntityTextUrl, 0, 5)]
    assert entities[0].url == 'pic.png'


def test_image_and_link_both_in_same_line():
    text, entities = parser.parse('![alt](img.png) and [link](http://x.com)')
    assert text == 'alt and link'
    assert _spans(entities) == [
        (MessageEntityTextUrl, 0, 3), (MessageEntityTextUrl, 8, 4),
    ]
    assert entities[0].url == 'img.png'
    assert entities[1].url == 'http://x.com'

# endregion


# region 7. Callouts (GitHub alert syntax)

@pytest.mark.parametrize('kind,label', [
    ('note', '\u2139\ufe0f Note'),
    ('warning', '\u26a0\ufe0f Warning'),
    ('tip', '\U0001f4a1 Tip'),
    ('important', '\u2757 Important'),
    ('caution', '\U0001f6ab Caution'),
])
def test_callout_known_types(kind, label):
    text, entities = parser.parse('> [!{}]\n> body text'.format(kind))
    assert text == '{}\nbody text'.format(label)
    assert any(isinstance(e, MessageEntityBlockquote) for e in entities)
    bolds = [e for e in entities if isinstance(e, MessageEntityBold)]
    assert len(bolds) == 1
    assert (bolds[0].offset, bolds[0].length) == (0, _utf16_len(label))


def test_callout_unknown_type_capitalized():
    text, _ = parser.parse('> [!xyz]\n> body')
    assert text == '\u2139\ufe0f Xyz\nbody'


def test_callout_case_insensitive():
    text, _ = parser.parse('> [!NOTE]\n> body')
    assert text == '\u2139\ufe0f Note\nbody'

# endregion


# region 9. Tables

def test_table_renders_as_monospace_pre():
    text, entities = parser.parse(
        '| Feature | Supported |\n|---|---|\n| Bold | Yes |\n| Lists | Yes |')
    assert len(entities) == 1
    assert isinstance(entities[0], MessageEntityPre)
    assert entities[0].language == ''
    lines = text.split('\n')
    assert lines[0] == 'Feature | Supported'
    assert set(lines[1]) == {'-'}
    assert lines[2].startswith('Bold')
    assert lines[3].startswith('Lists')


def test_table_columns_aligned_to_max_width():
    text, _ = parser.parse('| a | bbbbb |\n|---|---|\n| x | y |\n\nafter')
    lines = text.split('\n')
    # "a" column widened to fit nothing longer than 1 char; "bbbbb"
    # column widened to fit the header itself (5 chars).
    assert lines[0] == 'a | bbbbb'
    assert lines[2] == 'x | y' + ' ' * 4


def test_table_tolerates_leading_trailing_pipes_and_alignment_colons():
    text, entities = parser.parse('|H1|H2|\n|:---|---:|\n|a|b|')
    assert isinstance(entities[0], MessageEntityPre)
    lines = text.split('\n')
    assert lines[0] == 'H1 | H2'
    assert lines[2] == 'a  | b'


def test_table_cell_content_not_inline_parsed():
    text, _ = parser.parse('| a |\n|---|\n| **not bold** |')
    assert '**not bold**' in text

# endregion


# region 10. Admonitions

@pytest.mark.parametrize('kind,label', [
    ('info', '\u2139\ufe0f Info'),
    ('note', '\u2139\ufe0f Note'),
    ('warning', '\u26a0\ufe0f Warning'),
    ('tip', '\U0001f4a1 Tip'),
    ('danger', '\U0001f6ab Caution'),
    ('caution', '\U0001f6ab Caution'),
])
def test_admonition_known_types(kind, label):
    text, entities = parser.parse(':::{}\nbody text\n:::'.format(kind))
    assert text == '{}\nbody text'.format(label)
    assert any(isinstance(e, MessageEntityBlockquote) for e in entities)
    bolds = [e for e in entities if isinstance(e, MessageEntityBold)]
    assert len(bolds) == 1
    assert (bolds[0].offset, bolds[0].length) == (0, _utf16_len(label))


def test_admonition_unknown_type_capitalized():
    text, _ = parser.parse(':::custom\nbody\n:::')
    assert text == '\u2139\ufe0f Custom\nbody'


def test_admonition_body_is_inline_parsed():
    text, entities = parser.parse(':::info\n**bold** body\n:::')
    assert 'bold body' in text
    assert any(isinstance(e, MessageEntityBold) and e.length == 4 for e in entities)


def test_admonition_no_leftover_fence_markers():
    text, _ = parser.parse(':::warning\nBe careful.\n:::')
    assert ':::' not in text

# endregion


# region 11. <kbd>

def test_kbd_in_mixed_mode_is_code_entity():
    text, entities = parser.parse('<kbd>Ctrl</kbd> + <kbd>K</kbd>')
    assert text == 'Ctrl + K'
    assert _spans(entities) == [(MessageEntityCode, 0, 4), (MessageEntityCode, 7, 1)]


def test_kbd_in_html_mode_is_code_entity():
    text, entities = parser.parse('<kbd>Ctrl</kbd>', mode='html')
    assert text == 'Ctrl'
    assert _spans(entities) == [(MessageEntityCode, 0, 4)]


def test_kbd_in_markdown_mode_is_left_literal():
    # 'markdown' mode treats all literal HTML (including <kbd>) as
    # plain text -- only 'mixed'/'html' recognise it.
    text, entities = parser.parse('<kbd>Ctrl</kbd>', mode='markdown')
    assert text == '<kbd>Ctrl</kbd>'
    assert entities == []

# endregion


# region 12. Strikethrough (both forms)

def test_strike_double_tilde():
    text, entities = parser.parse('~~strike~~')
    assert text == 'strike'
    assert _spans(entities) == [(MessageEntityStrike, 0, 6)]


def test_strike_single_tilde():
    text, entities = parser.parse('~strike~')
    assert text == 'strike'
    assert _spans(entities) == [(MessageEntityStrike, 0, 6)]


def test_strike_double_tilde_matched_before_single():
    text, entities = parser.parse('~~a~~ and ~b~')
    assert text == 'a and b'
    assert _spans(entities) == [(MessageEntityStrike, 0, 1), (MessageEntityStrike, 6, 1)]

# endregion


# region 13. Math

def test_math_inline_paren_is_code_entity():
    text, entities = parser.parse(r'\(a^2 + b^2 = c^2\)')
    assert text == 'a^2 + b^2 = c^2'
    assert _spans(entities) == [(MessageEntityCode, 0, len(text))]


def test_math_inline_keeps_backslashes_verbatim():
    text, entities = parser.parse(r'\(\frac{1}{n^2}\)')
    assert text == r'\frac{1}{n^2}'
    assert isinstance(entities[0], MessageEntityCode)


def test_math_display_block_is_latex_pre_entity():
    text, entities = parser.parse('$$\nE = mc^2\n$$')
    assert text == 'E = mc^2'
    assert len(entities) == 1
    assert isinstance(entities[0], MessageEntityPre)
    assert entities[0].language == 'latex'


def test_math_display_block_keeps_multiline_content_verbatim():
    text, entities = parser.parse('$$\n\\sum_{n=1}^{\\infty}\\frac{1}{n^2}\n$$')
    assert text == '\\sum_{n=1}^{\\infty}\\frac{1}{n^2}'
    assert isinstance(entities[0], MessageEntityPre)
    assert entities[0].language == 'latex'


def test_math_single_line_dollar_is_code_entity():
    text, entities = parser.parse('$$x^2$$')
    assert text == 'x^2'
    assert _spans(entities) == [(MessageEntityCode, 0, 3)]


def test_math_dollar_no_longer_means_spoiler_in_v3_modes():
    # Breaking change (mapping #13): in v3 modes $$ now means math, not
    # the legacy spoiler. Legacy spoiler stays available in 'legacy'
    # mode and via ||spoiler|| in v3 modes.
    text, entities = parser.parse('$$spoiler$$', mode='mixed')
    assert text == 'spoiler'
    assert entities != []
    assert not any(isinstance(e, MessageEntitySpoiler) for e in entities)
    assert isinstance(entities[0], MessageEntityCode)


def test_math_dollar_still_means_spoiler_in_legacy_mode():
    text, entities = parser.parse('$$spoiler$$', mode='legacy')
    assert text == 'spoiler'
    assert _spans(entities) == [(MessageEntitySpoiler, 0, 7)]

# endregion


# region 14. Spoilers still work in v3 modes

def test_pipe_spoiler_still_works_in_v3_modes():
    text, entities = parser.parse('||spoiler||', mode='mixed')
    assert text == 'spoiler'
    assert _spans(entities) == [(MessageEntitySpoiler, 0, 7)]

# endregion


# region 15. Horizontal rule

@pytest.mark.parametrize('rule', ['---', '***', '___', '-----', '*****'])
def test_horizontal_rule_becomes_em_dashes(rule):
    text, entities = parser.parse('above\n{}\nbelow'.format(rule))
    assert text == 'above\n\u2014\u2014\u2014\nbelow'
    assert entities == []


def test_horizontal_rule_does_not_break_table_separator():
    text, entities = parser.parse('| a |\n|---|\n| b |')
    assert '\u2014\u2014\u2014' not in text
    assert isinstance(entities[0], MessageEntityPre)

# endregion


# region Regression: fenced code / math blocks stay protected

def test_fenced_code_protects_hash_and_dash_and_pipe_lines():
    md = '```\n# not a heading\n- not a list\n| not | a table |\n---\n```'
    text, entities = parser.parse(md)
    assert text == '# not a heading\n- not a list\n| not | a table |\n---'
    assert len(entities) == 1
    assert isinstance(entities[0], MessageEntityPre)


def test_math_block_protects_backslashes_from_escape_processing():
    text, entities = parser.parse('$$\n\\begin{aligned}\na &= b \\\\\n\\end{aligned}\n$$')
    assert '\\begin{aligned}' in text
    assert '\\end{aligned}' in text
    assert isinstance(entities[0], MessageEntityPre)


def test_dollar_dollar_inside_fenced_code_is_not_math():
    md = '```\n$$ literal $$\n```'
    text, entities = parser.parse(md)
    assert text == '$$ literal $$'
    assert len(entities) == 1
    assert isinstance(entities[0], MessageEntityPre)

# endregion


# region End-to-end: the full reference document

def _load_reference_doc():
    raw = open('/code/.uploaded_artifacts/1.txt', encoding='utf-8').read()
    m = re.match(r'^```md\n(.*)\n```\s*$', raw, re.S)
    assert m, 'reference doc fixture is not fenced as expected'
    return m.group(1)


def test_reference_document_parses_without_raising():
    doc = _load_reference_doc()
    text, entities = parser.parse(doc, mode='mixed')
    assert text
    assert entities


def test_reference_document_has_no_leftover_raw_markers():
    doc = _load_reference_doc()
    text, _ = parser.parse(doc, mode='mixed')
    for marker in ('#', '|---|', '- [ ]', ':::', '![', '$$', '\\('):
        assert marker not in text, 'leftover raw marker {!r} in output'.format(marker)


def test_reference_document_produces_expected_entity_types():
    doc = _load_reference_doc()
    text, entities = parser.parse(doc, mode='mixed')
    kinds = {type(e) for e in entities}
    assert MessageEntityBold in kinds
    assert MessageEntityUnderline in kinds  # H1
    assert MessageEntityItalic in kinds  # H3
    assert MessageEntityStrike in kinds  # ~~strikethrough~~
    assert MessageEntityCode in kinds  # inline code / kbd / inline math
    assert MessageEntityPre in kinds  # fenced code / table / display math
    assert MessageEntityTextUrl in kinds  # link + image
    assert MessageEntityBlockquote in kinds  # quote + callouts + admonitions
    assert MessageEntitySpoiler in kinds  # ||Spoiler text||

    assert '\u2022 item 1' in text  # unordered list
    assert '1. first' in text  # ordered list
    assert '\u2611 done' in text and '\u2610 todo' in text  # task list
    assert '\u2139\ufe0f Note' in text  # callout
    assert '\u26a0\ufe0f Warning' in text  # callout / admonition
    assert '\u2139\ufe0f Info' in text  # admonition
    assert 'Ctrl' in text and 'K' in text  # kbd
    assert '\\sum' in text  # display math kept verbatim


def test_reference_document_double_parse_is_stable():
    # Parsing the reference doc twice must be deterministic.
    doc = _load_reference_doc()
    text1, entities1 = parser.parse(doc, mode='mixed')
    text2, entities2 = parser.parse(doc, mode='mixed')
    assert text1 == text2
    assert _spans(entities1) == _spans(entities2)

# endregion


# region Regression tests: review of commit 03eb2525 (7 correctness bugs)

def test_bugfix1_escaped_math_dollar_stays_literal_no_pua_leak():
    # `\$$x$$`: the first `$` is backslash-escaped, so it must never
    # be treated as the opening of a `$$...$$` math span. Before the
    # fix, the escape pass consumed the first char of the math
    # placeholder token, leaving unresolved Private-Use-Area
    # characters in the final text and no Code/Pre entity.
    text, entities = parser.parse(r'\$$x$$')
    assert not any(0xE000 <= ord(c) <= 0xF8FF for c in text), (
        'leaked private-use placeholder characters: {!r}'.format(text))
    assert not any(isinstance(e, (MessageEntityCode, MessageEntityPre)) for e in entities)
    assert text == '$$x$$'


def test_bugfix2_table_not_double_escaped_in_markdown_mode():
    text, entities = parser.parse(
        '| a | b |\n| - | - |\n| a & b | <x> |', mode='markdown')
    pre = next(e for e in entities if isinstance(e, MessageEntityPre))
    cell = text[pre.offset:pre.offset + pre.length]
    assert 'a & b' in cell
    assert '<x>' in cell
    assert 'amp;' not in cell
    assert '&lt;' not in cell and '&gt;' not in cell


def test_bugfix2_table_not_double_escaped_in_strict_mode():
    text, entities = parser.parse(
        '| a | b |\n| - | - |\n| a & b | <x> |', strict=True)
    pre = next(e for e in entities if isinstance(e, MessageEntityPre))
    cell = text[pre.offset:pre.offset + pre.length]
    assert 'a & b' in cell
    assert '<x>' in cell
    assert 'amp;' not in cell


def test_bugfix3_unclosed_dollar_math_does_not_cross_lines():
    # An unclosed `$$` opener must not pair up with an unrelated,
    # later `$$...$$` on a different line; the trailing `$$x$$` on
    # its own line must still become its own, separate math span.
    text, entities = parser.parse('$$\nunclosed\nthen $$x$$')
    assert '$$\nunclosed\nthen ' in text
    codes = [e for e in entities if isinstance(e, MessageEntityCode)]
    assert len(codes) == 1
    assert text[codes[0].offset:codes[0].offset + codes[0].length] == 'x'


def test_bugfix4_bodyless_callout_gets_label():
    # `> [!note]` alone (no quoted body lines after it) must still be
    # recognised as a callout and get its bold label -- not fall
    # through as literal `[!note]` text inside a plain blockquote.
    text, entities = parser.parse('> [!note]')
    assert '[!note]' not in text
    assert text == '\u2139\ufe0f Note'
    assert any(isinstance(e, MessageEntityBlockquote) for e in entities)
    assert any(isinstance(e, MessageEntityBold) for e in entities)


def test_bugfix5_ordered_list_resumes_after_nested_unordered_child():
    # A plain unordered/task child nested under an ordered item must
    # not reset the parent ordered list's numbering: the item after
    # the nested child must continue as "2." rather than restart at
    # "1.".
    text, _ = parser.parse('1. parent\n  - child\n2. next')
    lines = text.split('\n')
    assert lines[0] == '1. parent'
    assert lines[2] == '2. next'


def test_bugfix5_ordered_list_resumes_after_nested_task_child():
    text, _ = parser.parse('1. parent\n  - [ ] child\n2. next')
    lines = text.split('\n')
    assert lines[0] == '1. parent'
    assert lines[2] == '2. next'


def test_bugfix6_ragged_table_row_gets_padded_missing_columns():
    # A body row with fewer cells than the header must still emit
    # every computed column (as an empty, padded cell) rather than
    # silently dropping the missing trailing column(s).
    text, entities = parser.parse('| A | B |\n| - | - |\n| only |\n\nafter')
    pre = next(e for e in entities if isinstance(e, MessageEntityPre))
    cell = text[pre.offset:pre.offset + pre.length]
    body_line = cell.split('\n')[2]
    assert body_line.count('|') == 1
    left, right = body_line.split('|')
    assert left.strip() == 'only'
    assert right.strip() == ''


def test_bugfix7_heading_absorbs_fully_contained_same_type_entity():
    # A same-type (Bold) entity fully contained within the heading's
    # own Bold range must be absorbed into it rather than kept as a
    # separate, fully-redundant nested entity.
    text, entities = parser.parse('## a **x** b')
    assert text == 'a x b'
    bolds = [e for e in entities if isinstance(e, MessageEntityBold)]
    assert len(bolds) == 1
    assert (bolds[0].offset, bolds[0].length) == (0, 5)


def test_bugfix7_heading_roundtrip_with_partial_inner_bold():
    # The absorption must still round-trip cleanly through unparse().
    text, entities = parser.parse('## a **x** b')
    unparsed = parser.unparse(text, entities, flavor='markdown2')
    text2, entities2 = parser.parse(unparsed)
    assert text2 == text
    assert _spans(entities2) == _spans(entities)

# endregion


# region single-asterisk italic (reference "Basic formatting")

def test_single_asterisk_italic():
    text, entities = parser.parse('*italic*')
    assert text == 'italic'
    assert _spans(entities) == [(MessageEntityItalic, 0, 6)]


def test_single_asterisk_does_not_break_bold():
    text, entities = parser.parse('*a* **b** *c*')
    assert text == 'a b c'
    assert _spans(entities) == [
        (MessageEntityItalic, 0, 1),
        (MessageEntityBold, 2, 1),
        (MessageEntityItalic, 4, 1),
    ]


def test_lone_asterisks_left_alone():
    for s in ('2 * 3', 'a ** b'):
        text, entities = parser.parse(s)
        assert text == s
        assert entities == []


def test_asterisk_list_marker_not_italic():
    text, entities = parser.parse('* item 1\n* item 2')
    assert text == '\u2022 item 1\n\u2022 item 2'
    assert entities == []

# endregion

# region unparse escapes literal inline delimiters (round-trip stability)

@pytest.mark.parametrize('literal', [
    '*not italic*', '~tilde~', '**stars**', '~~waves~~', '||pipes||',
    'a `code` b', '__unders__', '--dashes--', 'a * b * c', '```fence```',
])
def test_unparse_escapes_literal_delimiters(literal):
    # Plain text containing delimiter-looking sequences must survive
    # unparse(flavor='markdown2') -> parse() unchanged.
    unparsed = parser.unparse(literal, [], flavor='markdown2')
    text2, entities2 = parser.parse(unparsed)
    assert text2 == literal
    assert entities2 == []


def test_unparse_escapes_foreign_delimiter_inside_entity():
    # A '*' inside a Bold entity's content is literal and must be
    # escaped so the round trip keeps one Bold over 'a*b'.
    text, entities = 'a*b', [MessageEntityBold(0, 3)]
    unparsed = parser.unparse(text, entities, flavor='markdown2')
    text2, entities2 = parser.parse(unparsed)
    assert text2 == text
    assert _spans(entities2) == _spans(entities)


def test_unparse_escapes_delimiter_inside_code_content():
    # Delimiters inside Code/Pre content are escaped too, and parse
    # honors escapes inside code spans, so this also round-trips.
    text, entities = 'a*b`c', [MessageEntityCode(0, 5)]
    unparsed = parser.unparse(text, entities, flavor='markdown2')
    text2, entities2 = parser.parse(unparsed)
    assert text2 == text
    assert _spans(entities2) == _spans(entities)

# endregion
