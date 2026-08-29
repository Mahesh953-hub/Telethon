"""
MarkdownV3: unified formatting parser for this Telethon fork.
---
Public API
----------

``MarkdownV3().parse(text, mode='mixed', strict=False)`` ->
``(clean_text, entities)``

``MarkdownV3().unparse(text, entities, flavor='markdown2')`` -> ``str``

Module-level ``parse``/``unparse`` are kept for backwards compatibility
(``from telethon.extensions.markdownv3 import parse, unparse``), and
delegate to a shared default instance.
"""
import bisect
import html as html_module
import re
from typing import Iterable, List, Tuple

from ..helpers import add_surrogate, del_surrogate, within_surrogate
from ..tl import TLObject
from ..tl import types
from . import html as htmlparser
from . import markdown as legacy_markdown

__all__ = [
    'MarkdownV3', 'Markdown', 'parse', 'unparse',
    'DEFAULT_URL_RE', 'DEFAULT_URL_FORMAT',
]

# Kept around for callers that still poke at these (mirrors markdown.py).
DEFAULT_URL_RE = re.compile(r'\[(.+?)\]\((.+?)\)')
DEFAULT_URL_FORMAT = '[{0}]({1})'

VALID_PARSE_MODES = ('mixed', 'markdown', 'html', 'markdown2', 'legacy')

BOLD_DELIM = '**'
ITALIC_DELIM = '__'
ITALIC_DELIM_SINGLE = '*'
UNDERLINE_DELIM = '--'
STRIKE_DELIM = '~~'
STRIKE_DELIM_SINGLE = '~'
SPOILER_DELIM = '||'
CODE_DELIM = '`'
PRE_DELIM = '```'
BLOCKQUOTE_DELIM = '>'
BLOCKQUOTE_EXPANDABLE_DELIM = '**>'

# reach this table.
_TAG_MAP = {
    PRE_DELIM: 'pre',
    CODE_DELIM: 'code',
    STRIKE_DELIM: 's',
    STRIKE_DELIM_SINGLE: 's',
    UNDERLINE_DELIM: 'u',
    ITALIC_DELIM: 'i',
    ITALIC_DELIM_SINGLE: 'i',
    BOLD_DELIM: 'b',
    SPOILER_DELIM: 'spoiler',
}

_DELIM_RE = re.compile(
    '|'.join(re.escape(d) for d in sorted(_TAG_MAP, key=len, reverse=True))
)

_LINK_RE = re.compile(r'\[(.*?)\]\(((?:\\.|[^\\)])*)\)')
_IMAGE_RE = re.compile(r'!\[(.*?)\]\(((?:\\.|[^\\)])*)\)')
_CODE_SPAN_RE = re.compile(r'<(code|pre)\b[^>]*>.*?</\1>', re.S)
_MD_CODE_SPAN_RE = re.compile(r'```.+?```|`[^`]+?`', re.S)
_HTML_TAG_RE = re.compile(r'<!--.*?-->|</?[a-zA-Z][^<>]*>', re.S)
_MENTION_URL_RE = re.compile(r'^tg://user\?id=(-?\d+)$')
_EMOJI_URL_RE = re.compile(r'^emoji/(\d+)$')

_ESCAPE_PLACEHOLDER_BASE = 0xE000
_ESCAPE_PLACEHOLDER_MAX = 0xF8FF
_ESCAPE_PLACEHOLDER_RE = re.compile(
    '[{}-{}]'.format(chr(_ESCAPE_PLACEHOLDER_BASE), chr(_ESCAPE_PLACEHOLDER_MAX))
)


_MATH_DISPLAY_RE = re.compile(r'^\$\$[ \t]*\n(.*?)\n\$\$[ \t]*$', re.M | re.S)
_MATH_INLINE_PAREN_RE = re.compile(r'\\\((.*?)\\\)', re.S)
_MATH_INLINE_DOLLAR_RE = re.compile(r'\$\$([^\n]+?)\$\$')
_ESCAPED_MATH_DELIM_RE = re.compile(r'\\\$')
_HEADING_RE = re.compile(r'^(#{1,6})(?!#)[ \t]+(.*)$')
_HEADING_SENTINEL_BEGIN = '\uEA10'
_HEADING_SENTINEL_END = '\uEA11'
_HEADING_SENTINEL_RE = re.compile('[{}{}]'.format(_HEADING_SENTINEL_BEGIN, _HEADING_SENTINEL_END))

_HEADING_ENTITY_TYPES = {
    1: (types.MessageEntityBold, types.MessageEntityUnderline),
    2: (types.MessageEntityBold,),
    3: (types.MessageEntityBold, types.MessageEntityItalic),
    4: (types.MessageEntityBold, types.MessageEntityItalic),
    5: (types.MessageEntityBold, types.MessageEntityItalic),
    6: (types.MessageEntityBold, types.MessageEntityItalic),
}

_SIMPLE_ENTITY_TYPES = (
    types.MessageEntityBold, types.MessageEntityItalic,
    types.MessageEntityUnderline, types.MessageEntityStrike,
    types.MessageEntitySpoiler, types.MessageEntityCode,
)

_TASK_LIST_RE = re.compile(r'^( *)[-*+] \[([ xX])\][ \t]+(.*)$')
_ORDERED_LIST_RE = re.compile(r'^( *)(\d+)\.[ \t]+(.*)$')
_UNORDERED_LIST_RE = re.compile(r'^( *)[-*+][ \t]+(.*)$')
_UNORDERED_BULLETS = ('\u2022', '\u25E6', '\u25AA')  # • ◦ ▪

_HR_RE = re.compile(r'^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$')

_TABLE_SEP_RE = re.compile(r'^[ \t]*\|?[ \t]*:?-+:?[ \t]*(\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$')

_ADMONITION_OPEN_RE = re.compile(r'^:::([A-Za-z][\w-]*)[ \t]*$')
_ADMONITION_CLOSE_RE = re.compile(r'^:::[ \t]*$')
_ADMONITION_LABELS = {
    'info': '\u2139\ufe0f Info',
    'note': '\u2139\ufe0f Note',
    'warning': '\u26a0\ufe0f Warning',
    'tip': '\U0001f4a1 Tip',
    'danger': '\U0001f6ab Caution',
    'caution': '\U0001f6ab Caution',
}

_CALLOUT_OPEN_RE = re.compile(r'^(<blockquote(?: expandable)?>)\[!([A-Za-z][\w-]*)\]$')

_CALLOUT_BODYLESS_RE = re.compile(
    r'^(<blockquote(?: expandable)?>)\[!([A-Za-z][\w-]*)\](</blockquote>)$')
_CALLOUT_LABELS = {
    'note': '\u2139\ufe0f Note',
    'warning': '\u26a0\ufe0f Warning',
    'tip': '\U0001f4a1 Tip',
    'important': '\u2757 Important',
    'caution': '\U0001f6ab Caution',
}


def _protect_escapes(text: str) -> Tuple[str, List[str]]:
    """
    Replaces every ``\\X`` (backslash followed by any character) with a
    single Private-Use-Area placeholder character standing in for the
    literal ``X``, so that later markdown/HTML parsing never treats an
    escaped delimiter as real syntax. Returns ``(new_text, table)`` where
    ``table[ord(placeholder) - BASE] == X``.
    """
    table = []

    def repl(m):
        table.append(m.group(1))
        idx = len(table) - 1
        if _ESCAPE_PLACEHOLDER_BASE + idx > _ESCAPE_PLACEHOLDER_MAX:
            # Pathological input with thousands of escapes; give up
            # protecting further occurrences rather than overflow.
            return m.group(0)
        return chr(_ESCAPE_PLACEHOLDER_BASE + idx)

    text = re.sub(r'\\(.)', repl, text, flags=re.S)
    return text, table


def _restore_escapes(text: str, table: List[str]) -> str:
    """
    Restores backslash-escaped characters right before the text is fed
    to :func:`telethon.extensions.html.parse`, HTML-escaping the
    restored character (``html.escape(..., quote=True)``) so it is
    never mistaken for real markup or for an attribute-value quote.

    This runs as a single blind substitution over the *entire* working
    string, tags and attribute values included, which is what lets an
    escaped character inside e.g. an ``href="..."`` attribute (see
    ``_escape_md2_url``) come back correctly too.

    Deliberately runs *before* ``html.parse`` rather than after: that
    way, if the restored character is astral (e.g. an emoji), the
    ``add_surrogate`` call ``html.parse`` performs internally still
    sees it and expands it to its true two-UTF-16-unit width, so
    entity offsets computed from the parse come out correct. Restoring
    afterwards (on already del-surrogated text) would leave later
    entities off by one per restored astral character.
    """
    if not table:
        return text

    def repl(m):
        idx = ord(m.group(0)) - _ESCAPE_PLACEHOLDER_BASE
        if 0 <= idx < len(table):
            return html_module.escape(table[idx], quote=True)
        return m.group(0)

    return _ESCAPE_PLACEHOLDER_RE.sub(repl, text)


def _protect_escaped_math_delims(text: str):
    """
    Hides backslash-escaped ``\\$`` behind an opaque placeholder
    *before* ``_protect_math_blocks`` runs, so a user-escaped dollar
    sign (meant to render as a literal character, per the normal
    backslash-escape convention handled later by ``_protect_escapes``)
    is never mistaken for the start/end of a math span -- e.g.
    ``\\$$x$$`` must stay literal
    """
    placeholders = {}

    def repl(m):
        placeholder = '\uE910{}\uE911'.format(len(placeholders))
        placeholders[placeholder] = m.group(0)
        return placeholder

    return _ESCAPED_MATH_DELIM_RE.sub(repl, text), placeholders


def _restore_escaped_math_delims(text: str, placeholders: dict) -> str:
    for placeholder, original in placeholders.items():
        text = text.replace(placeholder, original)
    return text


def _protect_math_blocks(text: str) -> Tuple[str, dict]:
    """
    Extracts MarkdownV3 math: multi-line display blocks
    (``$$\\n...\\n$$``), single-line display math (``$$expr$$``) and
    inline math (``\\(expr\\)``), replacing each with an opaque
    placeholder token that carries the verbatim expression alongside.

    Must run *before* ``_protect_escapes``: TeX backslashes (``\\frac``,
    ``\\(``, ``\\)``, ...) would otherwise be consumed by the escape
    pass as if they were markdown escape sequences, silently dropping
    the backslash. Callers should temporarily shield existing code
    spans first (see ``MarkdownV3.parse``) so a literal ``$$`` inside a
    fenced/backtick code span is never mistaken for math.
    """
    placeholders = {}

    def make_placeholder(kind, content):
        key = '\uE900{}\uE901'.format(len(placeholders))
        placeholders[key] = (kind, content)
        return key

    text = _MATH_DISPLAY_RE.sub(lambda m: make_placeholder('display', m.group(1)), text)
    text = _MATH_INLINE_PAREN_RE.sub(lambda m: make_placeholder('inline', m.group(1)), text)
    text = _MATH_INLINE_DOLLAR_RE.sub(lambda m: make_placeholder('inline', m.group(1)), text)

    return text, placeholders


def _restore_math_blocks(text: str, placeholders: dict) -> str:
    """
    Expands the placeholders left by ``_protect_math_blocks`` into their
    final, verbatim (HTML-escaped) ``<pre language="latex">``/``<code>``
    markup. Must run *before* ``_restore_escapes`` (its placeholder
    range overlaps this one) and after the delimiter/HTML-tag passes,
    the same spot ``_restore_code_spans`` runs in, so the generated
    ``<pre>``/``<code>`` text is never re-scanned for markdown/HTML
    syntax.
    """
    for placeholder, (kind, content) in placeholders.items():
        if kind == 'display':
            body = content[:-1] if content.endswith('\n') else content
            replacement = '<pre language="latex">{}</pre>'.format(
                html_module.escape(body, quote=False))
        else:
            replacement = '<code>{}</code>'.format(
                html_module.escape(content, quote=False))
        text = text.replace(placeholder, replacement)
    return text


def _protect_code_spans(text: str):
    """
    Protects literal ``<code>...</code>``/``<pre>...</pre>`` spans that
    were already present in the input (mixed markdown+HTML) from having
    markdown delimiters inside them re-interpreted.
    """
    placeholders = {}

    def repl(m):
        placeholder = '\uE100{}\uE101'.format(len(placeholders))
        placeholders[placeholder] = m.group(0)
        return placeholder

    return _CODE_SPAN_RE.sub(repl, text), placeholders


def _restore_code_spans(text: str, placeholders: dict) -> str:
    for placeholder, original in placeholders.items():
        text = text.replace(placeholder, original)
    return text


def _protect_markdown_code_spans(text: str):
    """
    Protects raw (still unconverted) markdown fenced-code/inline-code
    spans -- see ``_MD_CODE_SPAN_RE`` -- so a ``>`` inside one is never
    mistaken for a blockquote marker by ``_blockquote_parser``. Meant
    to be restored again immediately (``_restore_markdown_code_spans``)
    right after that, before ``_convert_markdown_delimiters`` runs, so
    the backticks are still there to be converted as normal.
    """
    placeholders = {}

    def repl(m):
        placeholder = '\uE200{}\uE201'.format(len(placeholders))
        placeholders[placeholder] = m.group(0)
        return placeholder

    return _MD_CODE_SPAN_RE.sub(repl, text), placeholders


def _restore_markdown_code_spans(text: str, placeholders: dict) -> str:
    for placeholder, original in placeholders.items():
        text = text.replace(placeholder, original)
    return text


def _protect_html_tags(text: str):
    """
    Protects every bare HTML tag (attributes and all) already present
    in the input from ``_convert_markdown_delimiters``, so e.g. ``**``
    inside an ``href="..."`` attribute value is never rewritten into a
    ``<b>`` tag. Only the tag syntax itself is protected; text between
    an opening and closing tag is left as-is and still gets its
    markdown delimiters converted normally.
    """
    placeholders = {}

    def repl(m):
        placeholder = '\uE300{}\uE301'.format(len(placeholders))
        placeholders[placeholder] = m.group(0)
        return placeholder

    return _HTML_TAG_RE.sub(repl, text), placeholders


def _restore_html_tags(text: str, placeholders: dict) -> str:
    for placeholder, original in placeholders.items():
        text = text.replace(placeholder, original)
    return text


def _blockquote_parser(text: str) -> str:
    """
    Converts ``> line`` / ``**> line`` markdown blockquote syntax into
    ``<blockquote>``/``<blockquote expandable>`` HTML, grouping
    contiguous quoted lines into a single tag pair. Must run before
    general delimiter parsing, since ``**>`` would otherwise look like
    the start of a bold delimiter.
    """
    if not text:
        return text

    # Strict/html-escaped input turns a leading '>' into '&gt;'; undo
    # that so blockquote markers written by the user are still detected.
    text = re.sub(r'\n&gt;', '\n>', re.sub(r'^&gt;', '>', text))

    lines = text.split('\n')
    result = []
    in_blockquote = False
    current_expandable = False

    for line in lines:
        if line.startswith(BLOCKQUOTE_EXPANDABLE_DELIM) or line.startswith(BLOCKQUOTE_DELIM):
            expandable = line.startswith(BLOCKQUOTE_EXPANDABLE_DELIM)
            prefix = BLOCKQUOTE_EXPANDABLE_DELIM if expandable else BLOCKQUOTE_DELIM
            content = line[len(prefix):]
            if content.startswith(' '):
                content = content[1:]

            if in_blockquote and expandable != current_expandable:
                # The collapsed/expandable state changed: close the
                # quote in progress instead of silently merging a
                # plain ``>`` line into an expandable ``**>`` one (or
                # vice versa), then start a fresh one below.
                result[-1] += '</blockquote>'
                in_blockquote = False

            if not in_blockquote:
                tag = 'blockquote expandable' if expandable else 'blockquote'
                result.append('<{}>{}'.format(tag, content))
                in_blockquote = True
                current_expandable = expandable
            else:
                result.append(content)
        else:
            if in_blockquote:
                result[-1] += '</blockquote>'
                in_blockquote = False
            result.append(line)

    if in_blockquote and result:
        result[-1] += '</blockquote>'

    return '\n'.join(result)


def _callout_label(kind: str) -> str:
    label = _CALLOUT_LABELS.get(kind.lower())
    if label:
        return label
    return '\u2139\ufe0f {}'.format(html_module.escape(kind.capitalize(), quote=False))


def _admonition_label(kind: str) -> str:
    label = _ADMONITION_LABELS.get(kind.lower())
    if label:
        return label
    return '\u2139\ufe0f {}'.format(html_module.escape(kind.capitalize(), quote=False))


def _format_table(rows: List[List[str]]) -> str:
    """
    Renders a GFM pipe table as a monospace-aligned block:
    columns padded to their max width, cells joined by ``' | '``, and a
    dashed rule under the header. Cell content is used verbatim (never
    inline-parsed).

    Ragged rows (fewer cells than the widest row, as GFM tolerates)
    still emit *every* computed column -- missing trailing cells are
    treated as empty rather than silently dropped
    """
    width = max((len(row) for row in rows), default=0)
    widths = [0] * width
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def render(row):
        padded = [
            (row[i] if i < len(row) else '').ljust(widths[i])
            for i in range(width)
        ]
        return ' | '.join(padded)

    header = render(rows[0])
    lines = [header, '-' * len(header)]
    lines.extend(render(row) for row in rows[1:])
    return '\n'.join(lines)


def _split_table_row(line: str) -> List[str]:
    cells = line.split('|')
    if cells and cells[0].strip() == '':
        cells = cells[1:]
    if cells and cells[-1].strip() == '':
        cells = cells[:-1]
    return [c.strip() for c in cells]


def _process_block_structure(text: str, already_escaped: bool = False) -> Tuple[str, List[int]]:
    """
    Line-based pass implementing headings, lists (unordered/ordered/
    task), tables, callouts and admonitions, and horizontal rules. Must run *after* fenced
    code/inline-code spans and ``> quote`` lines have already been
    protected/converted (see ``MarkdownV3.parse``), so their contents
    are never mistaken for block syntax.

    :param already_escaped:
        Set when the caller already ran the *entire* input through
        ``html.escape`` before this pass (``mode == 'markdown'`` and/or
        ``strict=True``). Table cell text is then already
        HTML-escaped, so the generated ``<pre>`` wrapper must not
        escape it a second time (bug #2 in the review of commit
        03eb2525) -- e.g. ``a & b`` must render as ``a &amp; b``, not
        ``a &amp;amp; b``.

    Returns ``(new_text, heading_levels)`` where ``heading_levels`` is
    the heading level (1-6) of each heading found, in the order its
    sentinel pair appears in ``new_text`` -- consumed later by
    ``_apply_heading_entities``.
    """
    lines = text.split('\n')
    result = []
    heading_levels = []
    ordered_counters = {}
    prev_ordered_depth = None
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # Admonitions: ``:::type`` ... ``:::``
        m = _ADMONITION_OPEN_RE.match(line)
        if m:
            kind = m.group(1)
            body = []
            j = i + 1
            while j < n and not _ADMONITION_CLOSE_RE.match(lines[j]):
                body.append(lines[j])
                j += 1
            block_lines = ['<blockquote><b>{}</b>'.format(_admonition_label(kind))]
            block_lines.extend(body)
            block_lines[-1] += '</blockquote>'
            result.append('\n'.join(block_lines))
            i = j + 1 if j < n else j
            ordered_counters = {}
            prev_ordered_depth = None
            continue

        # Callouts: already-merged ``<blockquote>[!type]`` line
        m = _CALLOUT_BODYLESS_RE.match(line)
        if m:
            result.append('{}<b>{}</b>{}'.format(
                m.group(1), _callout_label(m.group(2)), m.group(3)))
            i += 1
            ordered_counters = {}
            prev_ordered_depth = None
            continue

        m = _CALLOUT_OPEN_RE.match(line)
        if m:
            result.append('{}<b>{}</b>'.format(m.group(1), _callout_label(m.group(2))))
            i += 1
            ordered_counters = {}
            prev_ordered_depth = None
            continue

        # Tables: header row + separator row + body rows
        if '|' in line and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1]) and '-' in lines[i + 1]:
            header = _split_table_row(line)
            j = i + 2
            body_rows = []
            while j < n and '|' in lines[j] and lines[j].strip() != '':
                body_rows.append(_split_table_row(lines[j]))
                j += 1
            table_text = _format_table([header] + body_rows)
            rendered_table = table_text if already_escaped else html_module.escape(table_text, quote=False)
            result.append('<pre>{}</pre>'.format(rendered_table))
            i = j
            ordered_counters = {}
            prev_ordered_depth = None
            continue

        #Headings
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            heading_levels.append(level)
            result.append(
                _HEADING_SENTINEL_BEGIN + m.group(2) + _HEADING_SENTINEL_END)
            i += 1
            ordered_counters = {}
            prev_ordered_depth = None
            continue

        # Task lists (take precedence over plain unordered lists)
        m = _TASK_LIST_RE.match(line)
        if m:
            indent, box, rest = m.group(1), m.group(2), m.group(3)
            mark = '\u2611' if box.lower() == 'x' else '\u2610'
            result.append('{}{} {}'.format(indent, mark, rest))
            i += 1
            depth = len(indent) // 2
            # Only clear the in-progress ordered-list state if this
            # task item is *not* nested under it (same/shallower
            # indent breaks the list; deeper indent is just a child
            # of the current ordered item and must not reset its
            # parent's numbering
            if prev_ordered_depth is None or depth <= prev_ordered_depth:
                ordered_counters = {}
                prev_ordered_depth = None
            continue

        #Ordered lists
        m = _ORDERED_LIST_RE.match(line)
        if m:
            indent, rest = m.group(1), m.group(3)
            depth = len(indent) // 2
            if prev_ordered_depth is None or depth > prev_ordered_depth:
                ordered_counters[depth] = 1
            else:
                for d in list(ordered_counters):
                    if d > depth:
                        del ordered_counters[d]
                ordered_counters[depth] = ordered_counters.get(depth, 0) + 1
            result.append('{}{}. {}'.format(indent, ordered_counters[depth], rest))
            prev_ordered_depth = depth
            i += 1
            continue

        #Unordered lists 
        m = _UNORDERED_LIST_RE.match(line)
        if m:
            indent, rest = m.group(1), m.group(2)
            depth = len(indent) // 2
            bullet = _UNORDERED_BULLETS[min(depth, len(_UNORDERED_BULLETS) - 1)]
            result.append('{}{} {}'.format(indent, bullet, rest))
            i += 1
            # See the task-list branch above for why this is
            # depth-conditioned rather than unconditional.
            if prev_ordered_depth is None or depth <= prev_ordered_depth:
                ordered_counters = {}
                prev_ordered_depth = None
            continue

        #Anything else (including horizontal rules and plain text)
        #breaks any ordered list still in progress
        ordered_counters = {}
        prev_ordered_depth = None

        # Horizontal rule
        if _HR_RE.match(line):
            result.append('\u2014\u2014\u2014')
            i += 1
            continue

        result.append(line)
        i += 1

    return '\n'.join(result), heading_levels


def _dedupe_simple_entities(entities: list) -> list:
    """
    Collapses redundant entities among the "simple" entity types that
    carry no other data than offset/length: exact duplicates collapse
    into one, and any such entity that is fully contained within
    another of the *same* type is dropped, keeping only the outer/
    larger one. This is what makes ``# **x**`` produce a single
    ``Bold`` entity rather than two identical, overlapping ones, and
    ``## a **x** b`` produce a single whole-heading ``Bold`` rather
    than a whole-heading ``Bold`` *plus* a fully-redundant, contained
    inner ``Bold`` for "x"
    -- per mapping #1's "nested same-type entities must be merged or
    deduped" requirement.
    """
    simple = [e for e in entities if isinstance(e, _SIMPLE_ENTITY_TYPES)]
    other = [e for e in entities if not isinstance(e, _SIMPLE_ENTITY_TYPES)]

    dropped = set()
    for i, a in enumerate(simple):
        if i in dropped:
            continue
        a_start, a_end = a.offset, a.offset + a.length
        for j, b in enumerate(simple):
            if i == j or j in dropped:
                continue
            if type(a) is not type(b):
                continue
            b_start, b_end = b.offset, b.offset + b.length
            if (a_start, a_end) == (b_start, b_end):
                # Exact duplicate: keep only the first occurrence.
                if j > i:
                    dropped.add(j)
            elif a_start <= b_start and b_end <= a_end:
                # `b` is strictly contained within `a`: absorb it.
                dropped.add(j)

    result = [e for k, e in enumerate(simple) if k not in dropped]
    result.extend(other)
    return result


def _apply_heading_entities(text: str, entities: list, heading_levels: List[int]):
    """
    Consumes the sentinel pairs left in ``text`` by
    ``_process_block_structure`` for each heading, turning them into
    the heading's Bold/Underline/Italic entities (mapping #1) and
    stripping the (invisible, non-rendering) sentinel characters back
    out of ``text`` -- remapping every entity's offset/length to
    account for their removal.
    """
    if not heading_levels:
        return text, entities

    text = add_surrogate(text)
    positions = [m.start() for m in _HEADING_SENTINEL_RE.finditer(text)]
    # Headings never nest: sentinels appear as consecutive
    # (begin, end) pairs in the same left-to-right order as
    # ``heading_levels``.
    pairs = list(zip(positions[0::2], positions[1::2]))
    removed = sorted(positions)

    def map_offset(old_offset):
        return old_offset - bisect.bisect_left(removed, old_offset)

    new_entities = []
    for (begin, end), level in zip(pairs, heading_levels):
        start = map_offset(begin + 1)
        stop = map_offset(end)
        length = stop - start
        if length <= 0:
            continue
        for EntityType in _HEADING_ENTITY_TYPES.get(level, (types.MessageEntityBold,)):
            new_entities.append(EntityType(offset=start, length=length))

    for e in entities:
        s = map_offset(e.offset)
        en = map_offset(e.offset + e.length)
        e.offset = s
        e.length = en - s

    new_text = _HEADING_SENTINEL_RE.sub('', text)
    all_entities = _dedupe_simple_entities(list(entities) + new_entities)
    all_entities.sort(key=lambda e: e.offset)
    return del_surrogate(new_text), all_entities


def _convert_markdown_delimiters(text: str) -> str:
    """
    Forward scan converting MarkdownV2-style delimiters and
    ``[label](url)`` links into HTML tags. Unmatched delimiters are left
    untouched (as literal text). Code/pre spans are never re-scanned for
    nested delimiters. This function does not need to preserve UTF-16
    offsets: whatever it returns is fed through a fresh HTML->entity
    pass, which computes correct offsets from scratch.
    """
    i = 0
    while i < len(text):
        dm = _DELIM_RE.match(text, i)
        if dm:
            delim = dm.group(0)
            # +1 avoids matching an empty span right next to itself
            # (e.g. "****" is left untouched rather than empty-bold).
            end = text.find(delim, i + len(delim) + 1)
            if end != -1:
                inner = text[i + len(delim):end]
                if delim == PRE_DELIM:
                    nl = inner.find('\n')
                    if nl != -1:
                        lang = inner[:nl]
                        code = inner[nl + 1:]
                    else:
                        lang, code = '', inner
                    if code.endswith('\n'):
                        code = code[:-1]
                    code = html_module.escape(code, quote=False)
                    replacement = '<pre language="{}">{}</pre>'.format(
                        html_module.escape(lang, quote=True), code)
                    text = text[:i] + replacement + text[end + len(delim):]
                    i += len(replacement)
                    continue
                elif delim == CODE_DELIM:
                    replacement = '<code>{}</code>'.format(
                        html_module.escape(inner, quote=False))
                    text = text[:i] + replacement + text[end + len(delim):]
                    i += len(replacement)
                    continue
                else:
                    tag = _TAG_MAP[delim]
                    open_tag = '<{}>'.format(tag)
                    close_tag = '</{}>'.format(tag)
                    text = (text[:i] + open_tag + inner + close_tag
                            + text[end + len(delim):])
                    i += len(open_tag)
                    continue
            # No matching close found: fall through, leave delimiter as
            # literal text and keep scanning one character at a time.

        im = _IMAGE_RE.match(text, i)
        if im:
            # Images: Telegram entities can't inline an
            # actual image, so this renders exactly like a link, with
            # the alt text (or the literal word "image" when empty) as
            # the visible/clickable text.
            alt = im.group(1) or 'image'
            label = _convert_markdown_delimiters(alt)
            replacement = '<a href="{}">{}</a>'.format(
                html_module.escape(im.group(2).strip(), quote=True), label)
            text = text[:i] + replacement + text[im.end():]
            i += len(replacement)
            continue

        lm = _LINK_RE.match(text, i)
        if lm:
            # Recursively convert markdown delimiters inside the link
            # *label* (so e.g. ``[**bold**](url)`` keeps its Bold
            # entity on round-trip), while the URL itself is only ever
            # used verbatim as an attribute value -- never re-scanned
            # for markdown syntax.
            label = _convert_markdown_delimiters(lm.group(1))
            # tg://user?id=... and emoji/... URLs are emitted as plain
            # links too; post-processing after the HTML pass turns them
            # into MessageEntityMentionName/CustomEmoji.
            replacement = '<a href="{}">{}</a>'.format(
                html_module.escape(lm.group(2).strip(), quote=True), label)
            text = text[:i] + replacement + text[lm.end():]
            i += len(replacement)
            continue

        i += 1

    return text


def _postprocess_entities(entities: list) -> list:
    """
    Turns generic ``MessageEntityTextUrl`` entities produced for
    ``tg://user?id=<id>`` and ``emoji/<id>`` URLs into their proper
    ``MessageEntityMentionName``/``MessageEntityCustomEmoji`` forms.
    """
    for i, e in enumerate(entities):
        if isinstance(e, types.MessageEntityTextUrl):
            m = _MENTION_URL_RE.match(e.url)
            if m:
                entities[i] = types.MessageEntityMentionName(
                    e.offset, e.length, int(m.group(1)))
                continue
            m = _EMOJI_URL_RE.match(e.url)
            if m:
                entities[i] = types.MessageEntityCustomEmoji(
                    e.offset, e.length, int(m.group(1)))
    return entities


class MarkdownV3:
    """
    Unified formatting parser: markdown (legacy + MarkdownV2-style),
    inline HTML, and mixed markdown+HTML input; configurable unparse
    output flavor.
    """

    def parse(self, text: str, mode: str = 'mixed', strict: bool = False) -> Tuple[str, list]:
        """
        Parses ``text`` (markdown, HTML, or a mix of both, depending on
        ``mode``) and returns ``(clean_text, entities)`` with entities
        using correct UTF-16 offsets.

        :param mode:
            * ``'mixed'`` (default): markdown delimiters and HTML tags
              are both recognised (Pyrogram-like).
            * ``'markdown'``: only markdown delimiters are parsed; any
              literal HTML in the input is treated as plain text.
            * ``'html'``: only HTML tags are parsed (delegates to
              :mod:`telethon.extensions.html`); markdown delimiters are
              left untouched.
            * ``'markdown2'``: MarkdownV2-style syntax; behaves like
              ``'mixed'`` but is the explicit "strict" MarkdownV2 name.
            * ``'legacy'``: legacy Telethon markdown (delegates to
              :mod:`telethon.extensions.markdown`; non-nesting).
        :param strict:
            If `True`, HTML-escapes the input before doing anything
            else with it (defends against HTML/markdown injection).
        """
        if not text:
            return '', []

        if mode not in VALID_PARSE_MODES:
            raise ValueError('Unknown MarkdownV3 parse mode {!r}'.format(mode))

        if strict:
            text = html_module.escape(text)

        if mode == 'legacy':
            return legacy_markdown.parse(text)

        if mode == 'html':
            text, entities = htmlparser.parse(text)
            return text, _postprocess_entities(entities)
        
        # Math must be extracted *before* ``_protect_escapes`` so TeX
        # backslashes aren't mistaken for markdown escapes; existing
        # code spans are temporarily shielded around that one step so a
        # literal ``$$`` inside a fenced/backtick code span is never
        # mistaken for a math block.
        text, _tmp_code_ph = _protect_code_spans(text)
        text, _tmp_md_code_ph = _protect_markdown_code_spans(text)
        text, _tmp_esc_math_ph = _protect_escaped_math_delims(text)
        text, math_placeholders = _protect_math_blocks(text)
        text = _restore_escaped_math_delims(text, _tmp_esc_math_ph)
        text = _restore_markdown_code_spans(text, _tmp_md_code_ph)
        text = _restore_code_spans(text, _tmp_code_ph)

        text, esc_table = _protect_escapes(text)

        if mode == 'markdown':
            # Markdown-only: literal HTML in the input stays plain text.
            text = html_module.escape(text)

        text = add_surrogate(text)

        # Protect existing HTML <code>/<pre> spans and raw markdown
        # code spans (```fenced``` and `inline`) *before* blockquote
        # parsing, so a ">" inside either is never mistaken for a
        # blockquote marker.
        text, code_placeholders = _protect_code_spans(text)
        text, md_code_placeholders = _protect_markdown_code_spans(text)

        text = _blockquote_parser(text)

        # Headings/lists/tables/callouts/admonitions/HR: line-based,
        # must run while code spans are still opaque placeholders and
        # after blockquote lines have already become <blockquote> HTML
        # (callouts key off that shape). ``already_escaped`` tells the
        # table path (the only one that re-escapes its own generated
        # text) not to double-escape cell content that the
        # ``mode == 'markdown'``/``strict`` html-escape above already
        # escaped once.
        text, heading_levels = _process_block_structure(
            text, already_escaped=(strict or mode == 'markdown'))

        # Tables/callouts/admonitions above generate their own
        # verbatim ``<pre>``/``<b>`` HTML fragments; shield those too
        # so e.g. a table's dashed separator row isn't later mistaken
        # for an ``--`` underline delimiter.
        text, block_code_placeholders = _protect_code_spans(text)

        # Give the raw backticks back so the delimiter engine below
        # still converts them as normal.
        text = _restore_markdown_code_spans(text, md_code_placeholders)

        # Protect every bare HTML tag (attributes and all) so markdown
        # delimiters inside e.g. an href="..." attribute are never
        # rewritten; text between tags is left alone and still gets
        # converted.
        text, tag_placeholders = _protect_html_tags(text)
        text = _convert_markdown_delimiters(text)
        text = _restore_html_tags(text, tag_placeholders)

        text = _restore_code_spans(text, block_code_placeholders)
        text = _restore_code_spans(text, code_placeholders)

        # Expand math placeholders to their final verbatim HTML now,
        # before ``_restore_escapes`` (its placeholder range overlaps
        # this one) and before the HTML->entity pass.
        text = _restore_math_blocks(text, math_placeholders)

        # Restore backslash-escaped characters now, before the final
        # HTML->entity pass, not after: see ``_restore_escapes`` for why.
        text = _restore_escapes(text, esc_table)

        clean_text, entities = htmlparser.parse(text)
        entities = _postprocess_entities(entities)
        clean_text, entities = _apply_heading_entities(clean_text, entities, heading_levels)

        return clean_text, entities

    # region unparse

    def unparse(self, text: str, entities: Iterable, flavor: str = 'markdown2') -> str:
        """
        Performs the reverse operation to `parse`, formatting ``text``
        with markup for its ``entities`` according to ``flavor``:

        * ``'markdown2'``/``'mdv2'``/``'markdown'``/``'md'``: MarkdownV2
          -style delimiters (``**``, ``__``, ``--``, ``~~``, ``||``,
          fenced code, ``[text](url)`` links, ``> quote``).
        * ``'legacy'``: legacy Telethon delimiters (delegates to
          :mod:`telethon.extensions.markdown`).
        * ``'html'``: HTML tags.
        """
        if not text:
            return text

        if isinstance(entities, TLObject):
            entities = [entities]
        else:
            entities = list(entities or [])

        flavor = (flavor or 'markdown2').lower()

        if flavor == 'legacy':
            return legacy_markdown.unparse(text, entities)
        if flavor == 'html':
            return self._unparse_html(text, entities)
        if flavor in ('markdown2', 'mdv2', 'markdown', 'md', 'v3', 'mdv3', 'markdownv3'):
            return self._unparse_markdown2(text, entities)

        raise ValueError('Unknown MarkdownV3 unparse flavor {!r}'.format(flavor))

    def _unparse_markdown2(self, text: str, entities: list) -> str:
        text = add_surrogate(text)
        insertions = []

        # Everything in ``text`` is literal content by definition (the
        # formatting lives in ``entities``), so any inline-delimiter
        # sequence occurring in it (``**``, ``*``, ``~~``, ``~``,
        # ``||``, `` ` ``, etc.) must be backslash-escaped or a fresh
        # ``parse()`` would read it as markup and the round trip would
        # be lossy. This global pass subsumes the narrower per-entity
        # "own delimiter" escaping that used to live here: it scans the
        # original (markup-free) text once, longest delimiter first.
        # The +inf priority sorts each backslash after every open/close
        # delimiter inserted at the same offset, keeping it immediately
        # adjacent to the character it escapes.
        for match in _DELIM_RE.finditer(text):
            for offset in range(match.start(), match.end()):
                insertions.append((offset, float('inf'), '\\'))

        # Same (offset, priority, text) scheme as markdown.py/html.py:
        # opening insertions are keyed by the entity's index ``i``,
        # closing insertions by ``-i``, then sorted ascending and
        # applied back-to-front (via ``pop()``) so that ties at the
        # same offset nest/adjoin in the right order.
        for i, entity in enumerate(entities):
            start = entity.offset
            end = start + entity.length

            delim = _MD2_DELIMS.get(type(entity))
            if delim:
                insertions.append((start, i, delim))
                insertions.append((end, -i, delim))
            elif isinstance(entity, types.MessageEntityPre):
                lang = getattr(entity, 'language', '') or ''
                insertions.append((start, i, '{}{}\n'.format(PRE_DELIM, lang)))
                insertions.append((end, -i, '\n{}'.format(PRE_DELIM)))
            elif isinstance(entity, types.MessageEntityCustomEmoji):
                insertions.append((start, i, '['))
                insertions.append((end, -i, '](emoji/{})'.format(entity.document_id)))
            elif isinstance(entity, types.MessageEntityTextUrl):
                insertions.append((start, i, '['))
                insertions.append((end, -i, ']({})'.format(_escape_md2_url(entity.url))))
            elif isinstance(entity, types.MessageEntityMentionName):
                insertions.append((start, i, '['))
                insertions.append(
                    (end, -i, '](tg://user?id={})'.format(entity.user_id)))
            elif isinstance(entity, types.MessageEntityBlockquote):
                prefix = (
                    BLOCKQUOTE_EXPANDABLE_DELIM
                    if getattr(entity, 'collapsed', False)
                    else BLOCKQUOTE_DELIM
                )
                insertions.append((start, i, '{} '.format(prefix)))
                for j, ch in enumerate(text[start:end]):
                    # Only continue the quote when quoted text follows
                    # the newline; a trailing newline shouldn't extend
                    # the quote over unrelated following text.
                    if ch == '\n' and start + j + 1 < end:
                        insertions.append((start + j + 1, i, '{} '.format(prefix)))
            # Auto-detected entities (Url, Email, Mention, Hashtag,
            # BotCommand, Phone, Cashtag, Unknown, ...) are preserved as
            # plain text: no markup needed since they already look right.

        if not insertions:
            return del_surrogate(text)

        insertions.sort(key=lambda t: (t[0], t[1]))
        while insertions:
            offset, _, tag = insertions.pop()
            while within_surrogate(text, offset):
                offset += 1
            text = text[:offset] + tag + text[offset:]

        return del_surrogate(text)

    def _unparse_html(self, text: str, entities: list) -> str:
        if not entities:
            return html_module.escape(text)

        text = add_surrogate(text)
        insert_at = []
        for i, entity in enumerate(entities):
            s = entity.offset
            e = entity.offset + entity.length
            markup = _HTML_FORMATTERS.get(type(entity))
            if markup is None:
                continue
            if callable(markup):
                markup = markup(entity, text[s:e])
            insert_at.append((s, i, markup[0]))
            insert_at.append((e, -i, markup[1]))

        if not insert_at:
            return html_module.escape(del_surrogate(text))

        insert_at.sort(key=lambda t: (t[0], t[1]))
        next_escape_bound = len(text)
        while insert_at:
            at, _, what = insert_at.pop()
            while within_surrogate(text, at):
                at += 1
            text = (text[:at] + what
                    + html_module.escape(text[at:next_escape_bound])
                    + text[next_escape_bound:])
            next_escape_bound = at

        text = html_module.escape(text[:next_escape_bound]) + text[next_escape_bound:]
        return del_surrogate(text)

    # endregion




# Symmetric open/close delimiters, keyed by entity type like
# markdown.py's ``delimiters`` and html.py's ``ENTITY_TO_FORMATTER``.
_MD2_DELIMS = {
    types.MessageEntityBold: BOLD_DELIM,
    types.MessageEntityItalic: ITALIC_DELIM,
    types.MessageEntityUnderline: UNDERLINE_DELIM,
    types.MessageEntityStrike: STRIKE_DELIM,
    types.MessageEntitySpoiler: SPOILER_DELIM,
    types.MessageEntityCode: CODE_DELIM,
}


def _escape_md2_url(url: str) -> str:
    # Only ')' and '\' are structurally significant inside the URL part
    # of a markdown link; escape those so the ']( ... )' syntax survives
    # a round trip.
    return url.replace('\\', '\\\\').replace(')', '\\)')


_HTML_FORMATTERS = {
    types.MessageEntityBold: ('<b>', '</b>'),
    types.MessageEntityItalic: ('<i>', '</i>'),
    types.MessageEntityUnderline: ('<u>', '</u>'),
    types.MessageEntityStrike: ('<del>', '</del>'),
    types.MessageEntitySpoiler: ('<tg-spoiler>', '</tg-spoiler>'),
    types.MessageEntityCode: ('<code>', '</code>'),
    types.MessageEntityBlockquote: lambda e, _: (
        '<blockquote expandable>' if getattr(e, 'collapsed', False) else '<blockquote>',
        '</blockquote>'
    ),
    types.MessageEntityPre: lambda e, _: (
        '<pre language="{}">'.format(html_module.escape(getattr(e, 'language', '') or '', quote=True)),
        '</pre>'
    ),
    types.MessageEntityEmail: lambda _, t: ('<a href="mailto:{}">'.format(t), '</a>'),
    types.MessageEntityUrl: lambda _, t: ('<a href="{}">'.format(t), '</a>'),
    types.MessageEntityTextUrl: lambda e, _: (
        '<a href="{}">'.format(html_module.escape(e.url, quote=True)), '</a>'),
    types.MessageEntityMentionName: lambda e, _: (
        '<a href="tg://user?id={}">'.format(e.user_id), '</a>'),
    types.MessageEntityCustomEmoji: lambda e, _: (
        '<tg-emoji emoji-id="{}">'.format(e.document_id), '</tg-emoji>'),
}


# Backwards-compatible alias.
Markdown = MarkdownV3

_default = MarkdownV3()


def parse(text: str, mode: str = 'mixed', strict: bool = False) -> Tuple[str, list]:
    """Module-level convenience wrapper around ``MarkdownV3().parse``."""
    return _default.parse(text, mode=mode, strict=strict)


def unparse(text: str, entities: Iterable, flavor: str = 'markdown2') -> str:
    """Module-level convenience wrapper around ``MarkdownV3().unparse``."""
    return _default.unparse(text, entities, flavor=flavor)
