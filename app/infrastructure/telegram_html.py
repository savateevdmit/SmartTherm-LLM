import html
import re
from bs4 import BeautifulSoup

ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "a", "code", "pre", "tg-spoiler", "tg-emoji", "blockquote"
}


def sanitize_telegram_html(text: str) -> str:
    if not text:
        return ""
    s = str(text)
    s = html.unescape(s)
    s = re.sub(
        r"(?i)(?:<b>|<strong>)?Код\s*\(если\s*нужен\):?(?:</b>|</strong>)?\s*(?:—|-|Никакой\s+дополнительный\s+код\s+не\s+требуется[^\n]*)",
        "",
        s
    )
    s = s.strip()

    def replace_pre_code(m: re.Match) -> str:
        code_attrs = m.group(1) or ""
        lang_match = re.search(r'class=["\']language-([^"\']+)["\']', code_attrs)
        lang = lang_match.group(1) if lang_match else ""
        if lang:
            return f'\n```{lang}\n'
        return '\n```\n'

    s = re.sub(r'(?i)<pre>\s*<code([^>]*)>', replace_pre_code, s)
    s = re.sub(r'(?i)</code>\s*</pre>', '\n```\n', s)

    s = s.replace("``<code>", "\n```\n")
    s = s.replace("</code>``", "\n```\n")
    s = s.replace("```<code>", "\n```\n")
    s = s.replace("</code>```", "\n```\n")

    s = re.sub(r'(?i)</?pre>', '\n```\n', s)
    parts = s.split("```")
    out = []

    for i, part in enumerate(parts):
        if i % 2 == 0:
            part = re.sub(r"(?<!`)`([^`\n]+)`(?!`)", r"<code>\1</code>", part)
            out.append(part)
        else:
            m = re.match(r"^\n?([a-zA-Z0-9_+-]+)[ \t]*\n(.*)", part, flags=re.DOTALL)
            if m:
                lang = m.group(1) or ""
                code = m.group(2) or ""
            else:
                lang = ""
                code = part

            code = code.strip("\n")
            if not code.strip():
                continue

            code_escaped = html.escape(code, quote=False)

            if lang:
                out.append(f'<pre><code class="language-{lang}">{code_escaped}</code></pre>')
            else:
                out.append(f'<pre><code>{code_escaped}</code></pre>')

    s = "".join(out)

    soup = BeautifulSoup(s, "html.parser")

    for tag in soup.find_all(True):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()

    for pre_tag in soup.find_all("pre"):
        if not pre_tag.find("code", recursive=False):
            code_tag = soup.new_tag("code")
            code_tag.extend(pre_tag.contents)
            pre_tag.clear()
            pre_tag.append(code_tag)

    return str(soup).strip()