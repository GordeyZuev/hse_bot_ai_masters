import re


def build_custom_offset_prompt(reminder_number: int, cancel_callback: str) -> tuple[str, list[tuple[str, str]]]:
    """Return prompt text and inline buttons [(text, callback_data)]."""
    text = (
        f"✏️ <b>Настройка уведомления {reminder_number}</b>\n\n"
        "Отправьте сообщение в формате:\n"
        "<code>число единица</code>\n\n"
        "<b>Примеры:</b>\n"
        "• <code>2 дня</code> или <code>2 дн</code>\n"
        "• <code>6 часов</code> или <code>6 ч</code>\n\n"
        "Или нажмите 'Отмена' для возврата."
    )
    buttons = [("❌ Отмена", cancel_callback)]
    return text, buttons


def parse_offset_text(text: str) -> tuple[int | None, str | None, str | None]:
    """Parse human text like '2 дня' or '6 часов'. Returns (value, unit, error)."""
    lowered = text.strip().lower()
    patterns = [
        (r"(\d+)\s*(?:дн|день|дня|дней|days?)", "days"),
        (r"(\d+)\s*(?:ч|час|часа|часов|hours?)", "hours"),
    ]

    for pattern, unit in patterns:
        match = re.search(pattern, lowered)
        if match:
            value = int(match.group(1))
            return value, unit, None

    return None, None, (
        "❌ Не удалось распознать формат.\n"
        "Используйте формат: <code>число единица</code>\n"
        "Например: <code>2 дня</code>, <code>6 часов</code>"
    )


