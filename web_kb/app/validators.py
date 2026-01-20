from typing import List, Tuple


def parse_tags(tags_raw: str) -> Tuple[str, List[str]]:
    """
    Input: 'tag1, tag2 tag3' -> store as CSV 'tag1,tag2,tag3' (<=10, each trimmed).
    Returns (csv, list).
    """
    if not tags_raw:
        return "", []
    # split by comma
    parts = [p.strip() for p in tags_raw.split(",")]
    parts = [p for p in parts if p]
    # unique preserving order
    seen = set()
    uniq = []
    for p in parts:
        low = p.lower()
        if low in seen:
            continue
        seen.add(low)
        uniq.append(p)
    if len(uniq) > 10:
        raise ValueError("Можно указать максимум 10 тегов.")
    csv = ",".join(uniq)
    if len(csv) > 255:
        raise ValueError("Слишком длинное поле tags (превышает 255 символов).")
    return csv, uniq


def validate_question_text(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise ValueError("Поле 'Вопрос' обязательно.")
    if len(text) > 500:
        raise ValueError("Вопрос не должен превышать 500 символов.")
    return text


def validate_answer_text(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise ValueError("Поле 'Ответ' обязательно.")
    if len(text) > 2000:
        raise ValueError("Ответ не должен превышать 2000 символов.")
    return text