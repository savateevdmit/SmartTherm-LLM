import re
import html

ALLOWED_URLS = [
    "https://www.umkikit.ru/index.php?route=product/product&path=67&product_id=103",
    "https://github.com/Evgen2/SmartTherm",
    "https://t.me/smartTherm",
]


class TelegramCleaner:
    @staticmethod
    def clean_harmony_garbage(text: str) -> str:
        if "<|message|>" in text:
            parts = text.split("<|message|>")
            text = parts[-1]
        text = text.replace("<|end|>", "").replace("<|start|>", "").strip()
        text = text.replace("assistant\n", "").strip()
        return text

    @staticmethod
    def validate_links(text: str) -> str:
        url_pattern = r"https?://[^\s\)]+"

        def replace_match(match):
            url = match.group(0).rstrip(".,;:")
            for allowed in ALLOWED_URLS:
                if allowed in url:
                    return allowed
            return ""

        cleaned_text = re.sub(url_pattern, replace_match, text)
        cleaned_text = cleaned_text.replace("()", "").replace("[]", "")
        cleaned_text = re.sub(r"[ \t]+", " ", cleaned_text)
        return cleaned_text

    @staticmethod
    def _md_bold_to_html(s: str) -> str:
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)

    @staticmethod
    def _md_inline_code_to_html(s: str) -> str:
        return re.sub(r"`([^`]+?)`", r"<code>\1</code>", s)

    @staticmethod
    def _md_fenced_code_to_html(s: str) -> str:
        # Telegram HTML friendly block code
        def repl(m):
            code = (m.group(2) or "").strip("\n")
            return f"<pre>{code}</pre>"

        return re.sub(r"```(\w+)?\n([\s\S]*?)\n```", repl, s)

    @staticmethod
    def _beautify_steps(text: str) -> str:
        text = re.sub(r"(?m)^\s*-\s+", "• ", text)

        text = re.sub(r"(?m)^\s*•\s*(\d+)\)\s*", r"**\1)** ", text)
        text = re.sub(r"(?m)^\s*•\s*(\d+)\.\s+", r"**\1.** ", text)

        text = re.sub(r"(?m)^(\s*)(\d+)\)\s*", r"\1**\2)** ", text)
        text = re.sub(r"(?m)^(\s*)(\d+)\.\s+", r"\1**\2.** ", text)

        return text

    @staticmethod
    def format_for_telegram(text: str) -> str:
        text = TelegramCleaner.clean_harmony_garbage(text)
        text = TelegramCleaner.validate_links(text)

        text = re.sub(r"^#+\s*(.*)$", r"**\1**", text, flags=re.MULTILINE)
        text = re.sub(r"^-{3,}$", "", text, flags=re.MULTILINE)

        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)

        lines = text.split("\n")
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("|") and set(stripped) <= {"|", "-", " ", ":"}:
                continue
            if stripped.startswith("|") and stripped.endswith("|"):
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                new_lines.append("• " + " → ".join(cells))
            else:
                new_lines.append(line)
        text = "\n".join(new_lines)

        text = TelegramCleaner._beautify_steps(text)

        if len(text) > 3000:
            cut_text = text[:3000]
            last_dot = cut_text.rfind(".")
            text = cut_text[: last_dot + 1] if last_dot > 0 else (cut_text + "...")

        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        text = html.escape(text)

        text = TelegramCleaner._md_fenced_code_to_html(text)
        text = TelegramCleaner._md_inline_code_to_html(text)
        text = TelegramCleaner._md_bold_to_html(text)

        return text.strip()