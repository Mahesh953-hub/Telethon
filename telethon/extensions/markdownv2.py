"""
Canonical modern markdown parser for this fork ("MarkdownV2").

This module is the single home for all modern markdown parsing. It merges
the previous ``markdownv2`` and ``markdownv3`` implementations:

* Offset-safe, reverse-order delimiter parsing (from v3).
* Telethon-correct ``unparse`` built on ``isinstance`` checks (from v3;
  the old v2 ``unparse`` compared ``entity.type`` against classes, which
  never worked with Telethon entities).
* Custom emoji (``[x](emoji/<id>)``) and spoiler post-processing (from v3).
* ``strict=True`` HTML-escaping and escaped-``&gt;`` blockquote handling
  (from v2).

``MarkdownV3`` is kept as an alias of ``Markdown`` for backwards
compatibility (downstream code imports it from ``telethon.extensions``);
new code should use ``Markdown`` / parse mode ``'mdv2'``.

``telethon/extensions/markdown.py`` is the legacy upstream parser and is
left untouched.
"""
import html
import re

from . import utils, html as htmlparser
from ..tl import types

# Kept for backwards compatibility with older consumers of this module.
DEFAULT_URL_RE = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
DEFAULT_URL_FORMAT = '[{0}]({1})'

# Delimiters
BOLD_DELIM = "**"
ITALIC_DELIM = "__"
UNDERLINE_DELIM = "--"
STRIKE_DELIM = "~~"
SPOILER_DELIM = "||"
CODE_DELIM = "`"
PRE_DELIM = "```"
BLOCKQUOTE_DELIM = ">"
BLOCKQUOTE_EXPANDABLE_DELIM = "**>"

MARKDOWN_RE = re.compile(
    r"({d})|\[(.+?)\]\((.+?)\)".format(
        d="|".join(
            [
                "".join([rf"\{j}" for j in i])
                for i in [
                    PRE_DELIM,
                    CODE_DELIM,
                    STRIKE_DELIM,
                    UNDERLINE_DELIM,
                    ITALIC_DELIM,
                    BOLD_DELIM,
                    SPOILER_DELIM,
                ]
            ]
        )
    )
)

OPENING_TAG = "<{}>"
CLOSING_TAG = "</{}>"
URL_MARKUP = '<a href="{}">{}</a>'
FIXED_WIDTH_DELIMS = [CODE_DELIM, PRE_DELIM]
CODE_TAG_RE = re.compile(r"<code>.*?</code>")

TAG_MAP = {
    BOLD_DELIM: "b",
    ITALIC_DELIM: "i",
    UNDERLINE_DELIM: "u",
    STRIKE_DELIM: "s",
    CODE_DELIM: "code",
    PRE_DELIM: "pre",
    SPOILER_DELIM: "spoiler",
}


class Markdown:
    """
    Modern markdown parser ("MarkdownV2"): ``**bold**``, ``__italic__``,
    ``--underline--``, ``~~strike~~``, ``||spoiler||``, ``` `code` ``` /
    fenced ``pre`` blocks with language, ``[text](url)`` links,
    ``[emoji](emoji/<document_id>)`` custom emoji, ``> blockquote`` and
    ``**> expandable blockquote``.
    """

    def __init__(self):
        self.html = htmlparser

    @staticmethod
    def blockquote_parser(text: str) -> str:
        if not text:
            return ""

        # Un-escape leading '&gt;' produced by strict HTML escaping so
        # escaped blockquote markers are still recognized.
        text = re.sub(r"\n&gt;", "\n>", re.sub(r"^&gt;", ">", text))

        lines = text.split("\n")
        result = []
        in_blockquote = False

        for line in lines:
            if line.startswith(BLOCKQUOTE_EXPANDABLE_DELIM) or line.startswith(BLOCKQUOTE_DELIM):
                current_expandable = line.startswith(BLOCKQUOTE_EXPANDABLE_DELIM)
                prefix = (
                    BLOCKQUOTE_EXPANDABLE_DELIM
                    if current_expandable
                    else BLOCKQUOTE_DELIM
                )
                content = line[len(prefix):].lstrip()

                if not in_blockquote:
                    tag = (
                        "blockquote expandable"
                        if current_expandable
                        else "blockquote"
                    )
                    result.append(f"<{tag}>{content}")
                    in_blockquote = True
                else:
                    result.append(content)
            else:
                if in_blockquote:
                    result[-1] += "</blockquote>"
                    in_blockquote = False
                result.append(line)

        if in_blockquote and result:
            result[-1] += "</blockquote>"

        return "\n".join(result)

    def parse(self, text: str, strict: bool = False):
        """
        Parses the given markdown message and returns its stripped
        representation plus a list of the MessageEntity's that were found.
        """
        if not text:
            return "", []

        if strict:
            text = html.escape(text)

        # 1. Handle blockquotes
        text = self.blockquote_parser(text)

        # 2. Protect existing code sections
        placeholders = {}
        code_matches = list(CODE_TAG_RE.finditer(text))
        for i, m in enumerate(reversed(code_matches)):
            placeholder = f"{{CODE_SECTION_{i}}}"
            placeholders[placeholder] = m.group(0)
            text = text[:m.start()] + placeholder + text[m.end():]

        # 3. Parse delimiters (reverse order to keep offsets valid).
        # First do a forward pass to find matches living inside fixed-width
        # (inline code / fenced pre) spans, which must stay literal.
        matches = list(MARKDOWN_RE.finditer(text))
        skip = set()
        is_fixed_width = False
        for i, match in enumerate(matches):
            delim = match.group(1)
            if delim in FIXED_WIDTH_DELIMS:
                is_fixed_width = not is_fixed_width
            elif is_fixed_width:
                skip.add(i)

        delims = {}
        for i in reversed(range(len(matches))):
            if i in skip:
                continue
            match = matches[i]
            start, end = match.span()
            delim, text_url, url = match.groups()

            if text_url:
                replacement = URL_MARKUP.format(url, text_url)
                text = text[:start] + replacement + text[end:]
                continue

            if delim not in TAG_MAP:
                continue

            tag = TAG_MAP[delim]
            count = delims.get(delim, 0)

            if count % 2 == 0:
                tag_str = CLOSING_TAG.format(tag)
            else:
                if delim == PRE_DELIM:
                    line_part = text[end:].split("\n")[0]
                    tag_str = f'<pre language="{line_part}">'
                    text = text[:end] + text[end + len(line_part):]
                else:
                    tag_str = OPENING_TAG.format(tag)

            delims[delim] = count + 1
            text = text[:start] + tag_str + text[end:]

        # Restore code placeholders
        for placeholder, code_section in placeholders.items():
            text = text.replace(placeholder, code_section)

        # 4. Convert HTML to entities
        clean_text, entities = self.html.parse(text)

        # 5. Post-process custom emojis and spoilers
        for i, e in enumerate(entities):
            if isinstance(e, types.MessageEntityTextUrl):
                if e.url == "spoiler":
                    entities[i] = types.MessageEntitySpoiler(
                        e.offset, e.length
                    )
                elif e.url.startswith("emoji/"):
                    try:
                        eid = int(e.url.split("/")[1])
                        entities[i] = types.MessageEntityCustomEmoji(
                            e.offset, e.length, eid
                        )
                    except (IndexError, ValueError):
                        pass

        return clean_text, entities

    def unparse(self, text: str, entities: list):
        """
        Performs the reverse operation to `parse`, effectively returning
        markdown-like syntax given a normal text and its MessageEntity's.
        """
        if not text:
            return ""

        text = utils.add_surrogates(text)
        insertions = []

        for entity in (entities or []):
            start = entity.offset
            end = start + entity.length

            if isinstance(entity, types.MessageEntityCustomEmoji):
                insertions.append((start, "["))
                insertions.append((end, f"](emoji/{entity.document_id})"))
            elif isinstance(entity, types.MessageEntitySpoiler):
                insertions.append((start, SPOILER_DELIM))
                insertions.append((end, SPOILER_DELIM))
            elif isinstance(entity, types.MessageEntityBold):
                insertions.append((start, BOLD_DELIM))
                insertions.append((end, BOLD_DELIM))
            elif isinstance(entity, types.MessageEntityItalic):
                insertions.append((start, ITALIC_DELIM))
                insertions.append((end, ITALIC_DELIM))
            elif isinstance(entity, types.MessageEntityUnderline):
                insertions.append((start, UNDERLINE_DELIM))
                insertions.append((end, UNDERLINE_DELIM))
            elif isinstance(entity, types.MessageEntityStrike):
                insertions.append((start, STRIKE_DELIM))
                insertions.append((end, STRIKE_DELIM))
            elif isinstance(entity, types.MessageEntityCode):
                insertions.append((start, CODE_DELIM))
                insertions.append((end, CODE_DELIM))
            elif isinstance(entity, types.MessageEntityPre):
                lang = getattr(entity, "language", "") or ""
                insertions.append((start, f"{PRE_DELIM}{lang}\n"))
                insertions.append((end, f"\n{PRE_DELIM}"))
            elif isinstance(entity, types.MessageEntityTextUrl):
                insertions.append((start, "["))
                insertions.append((end, f"]({entity.url})"))
            elif isinstance(entity, types.MessageEntityMentionName):
                insertions.append((start, "["))
                insertions.append(
                    (end, f"](tg://user?id={entity.user_id})")
                )
            elif isinstance(entity, types.MessageEntityBlockquote):
                prefix = (
                    BLOCKQUOTE_EXPANDABLE_DELIM
                    if getattr(entity, "collapsed", False)
                    else BLOCKQUOTE_DELIM
                )
                # Prefix the first line and every following line of the
                # quoted range so multi-line quotes round-trip correctly.
                insertions.append((start, f"{prefix} "))
                for i, ch in enumerate(text[start:end]):
                    # Only continue the quote when another quoted character
                    # follows the newline; a trailing newline must not
                    # extend the quote over the following unquoted text.
                    if ch == "\n" and start + i + 1 < end:
                        insertions.append((start + i + 1, f"{prefix} "))

        insertions.sort(key=lambda x: x[0], reverse=True)

        for offset, tag in insertions:
            text = text[:offset] + tag + text[offset:]

        return utils.remove_surrogates(text)


# Backwards-compatible alias: downstream code (e.g. SarahUB) imports
# ``MarkdownV3``; it is now the same merged implementation as ``Markdown``.
MarkdownV3 = Markdown
