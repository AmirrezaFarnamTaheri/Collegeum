"""Compact, accessible native Telegram navigation for private Collegeum chats.

Buttons use stable short callback payloads; all actions are implemented by the
private interaction controller, not an external web app. No user identifier is
embedded in any keyboard or callback.
"""

from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import urlsplit

from .subscriptions import CAREER_SCOPES, TOPIC_LABELS

ACADEMIC = ("predoc", "phd", "postdoc")
CAREERS = ("data_scientist", "data_analyst", "econ_consulting", "research_analyst")
PAGE_SIZE = 4
MAX_LATEST_PAGES = 10

PERSIAN_LABELS = {
    "predoc": "دستیار پژوهشی / پیشادکتری",
    "phd": "فرصت دکتری",
    "postdoc": "پسادکتری",
    "data_scientist": "دانشمند داده",
    "data_analyst": "تحلیلگر داده و BI",
    "econ_consulting": "مشاوره اقتصادی",
    "research_analyst": "تحلیلگر پژوهش و اقتصاد",
    "iran": "مشاغل داخل ایران",
    "remote": "دورکاری جهانی",
}


def language(member: dict[str, Any] | None) -> str:
    """A persisted explicit preference is used, never a guessed nationality."""
    if member and member.get("language") == "fa":
        return "fa"
    return "en"


def _button(text: str, callback: str) -> dict[str, str]:
    if not 1 <= len(callback.encode("utf-8")) <= 64:
        raise ValueError("Telegram callback payload exceeds 64 bytes")
    return {"text": text, "callback_data": callback}


def _label(key: str, lang: str) -> str:
    if lang == "fa":
        return PERSIAN_LABELS.get(key, key)
    if key in TOPIC_LABELS:
        return TOPIC_LABELS[key].split(" ", 1)[-1]
    return CAREER_SCOPES.get(key, key).split(" ", 1)[-1]


def _back(lang: str) -> list[dict[str, str]]:
    return [_button("بازگشت به خانه ↩" if lang == "fa" else "← Home", "sub:p:home")]


def menu(
    member: dict[str, Any] | None, page: str = "home",
) -> tuple[str, dict[str, Any]]:
    """Small purpose-specific panels instead of a 10-button settings wall."""
    lang = language(member)
    fa = lang == "fa"
    topics = member.get("topics", {}) if member else {}
    scopes = member.get("scopes", {}) if member else {}
    paused = bool(member and member.get("paused"))
    buttons: list[list[dict[str, str]]] = []
    if page == "academic":
        title = "🎓 <b>فرصت‌های دانشگاهی</b>" if fa else "🎓 <b>Academic opportunities</b>"
        caption = ("موارد دلخواه را روشن کنید. فقط آگهی‌های تازه اعلان می‌شوند."
                   if fa else "Choose the roles you want. New matches start after opt-in.")
        for key in ACADEMIC:
            buttons.append([_button(
                ("✓ " if key in topics else "○ ") + _label(key, lang), f"sub:t:{key}",
            )])
        all_set = all(key in topics for key in ACADEMIC)
        buttons.append([_button(
            "پاک‌کردن همه" if fa and all_set else
            "انتخاب همه" if fa else "Clear all" if all_set else "Select all",
            f"sub:b:academic:{'off' if all_set else 'on'}",
        )])
        buttons.append(_back(lang))
        body = f"{title}\n\n{caption}"
    elif page == "careers":
        title = "💼 <b>مشاغل تخصصی</b>" if fa else "💼 <b>Specialist careers</b>"
        caption = ("ابتدا موضوع و سپس منطقه را مشخص کنید."
                   if fa else "Pick roles, then choose your job markets.")
        for key in CAREERS:
            buttons.append([_button(
                ("✓ " if key in topics else "○ ") + _label(key, lang), f"sub:t:{key}",
            )])
        all_set = all(key in topics for key in CAREERS)
        buttons.append([_button(
            "پاک‌کردن همه" if fa and all_set else
            "انتخاب همه" if fa else "Clear all" if all_set else "Select all",
            f"sub:b:careers:{'off' if all_set else 'on'}",
        )])
        buttons.append([_button(
            "محدوده جستجو →" if fa else "Choose job markets →", "sub:p:markets",
        )])
        buttons.append(_back(lang))
        body = f"{title}\n\n{caption}"
    elif page == "markets":
        title = "🌍 <b>محدوده مشاغل</b>" if fa else "🌍 <b>Job markets</b>"
        caption = ("ایران و دورکاری جهانی دو گزینه مستقل هستند."
                   if fa else "Iran-based and worldwide-remote are independent.")
        for key in CAREER_SCOPES:
            buttons.append([_button(
                ("✓ " if key in scopes else "○ ") + _label(key, lang), f"sub:g:{key}",
            )])
        buttons.append([_button(
            "انتخاب مشاغل ←" if fa else "← Career roles", "sub:p:careers",
        )])
        buttons.append(_back(lang))
        body = f"{title}\n\n{caption}"
    elif page == "help":
        body = (
            "ℹ️ <b>راهنما</b>\n\n"
            "۱. در «تحصیلات» یا «مشاغل» موضوع دلخواه را روشن کنید.\n"
            "۲. برای مشاغل، ایران یا دورکاری جهانی را جداگانه انتخاب کنید.\n"
            "۳. اعلان‌ها فقط برای آگهی‌های جدید پس از عضویت هستند.\n"
            "۴. «تازه‌ترین‌ها» آگهی‌های قبلی را هم برای مرور نشان می‌دهد.\n"
            "۵. توقف اعلان‌ها اشتراک را نگه می‌دارد.\n"
            "برای حذف اشتراک، «لغو عضویت» را انتخاب کنید."
            if fa else
            "ℹ️ <b>How alerts work</b>\n\n"
            "1. Choose academic or specialist roles.\n"
            "2. For careers, select Iran and/or worldwide remote.\n"
            "3. Notifications cover new matches after you opt in.\n"
            "4. Browse latest to view existing positions on demand.\n"
            "5. Pausing keeps your preferences but stops new alerts.\n"
            "Unsubscribe removes your active private alert records."
        )
        buttons = [_back(lang)]
    elif page == "stop":
        body = (
            "🗑 <b>لغو عضویت؟</b>\n\n"
            "موضوع‌ها و سوابق ارسال شما از وضعیت فعال حذف می‌شوند."
            if fa else
            "🗑 <b>Unsubscribe?</b>\n\n"
            "Your active topics, markets, and delivery records will be removed."
        )
        buttons = [
            [_button("لغو عضویت" if fa else "Yes, unsubscribe", "sub:stop:yes")],
            [_button("انصراف" if fa else "Keep my alerts", "sub:p:home")],
        ]
    else:
        academic = sum(key in topics for key in ACADEMIC)
        careers = sum(key in topics for key in CAREERS)
        selected_markets = [
            _label(key, lang) for key in CAREER_SCOPES if key in scopes
        ]
        market_line = ", ".join(selected_markets) if selected_markets else (
            "انتخاب نشده" if fa else "Not selected"
        )
        body = (
            "🧭 <b>Collegeum | اعلان فرصت‌ها</b>\n\n"
            f"🎓 دانشگاهی: {academic}/3\n"
            f"💼 شغلی: {careers}/4\n"
            f"🌍 محدوده: {escape(market_line)}\n"
            f"🔔 وضعیت: {'متوقف' if paused else 'فعال'}\n\n"
            "برای تنظیم، یکی از دسته‌ها را انتخاب کنید."
            if fa else
            "🧭 <b>Collegeum | Job alerts</b>\n\n"
            f"🎓 Academic roles: {academic}/3\n"
            f"💼 Career roles: {careers}/4\n"
            f"🌍 Markets: {escape(market_line)}\n"
            f"🔔 Alerts: {'Paused' if paused else 'On'}\n\n"
            "Choose a category to tailor your alerts."
        )
        buttons = [
            [_button("🎓 دانشگاهی" if fa else "🎓 Academic", "sub:p:academic"),
             _button("💼 مشاغل" if fa else "💼 Careers", "sub:p:careers")],
            [_button("🌍 محدوده" if fa else "🌍 Job markets", "sub:p:markets"),
             _button("🔎 تازه‌ترین‌ها" if fa else "🔎 Latest", "sub:p:latest")],
            [_button(
                "▶ ازسرگیری اعلان‌ها" if fa and paused else
                "⏸ توقف اعلان‌ها" if fa else
                "▶ Resume alerts" if paused else "⏸ Pause alerts",
                "sub:a:resume" if paused else "sub:a:pause",
            )],
            [_button("ℹ️ راهنما" if fa else "ℹ️ Help", "sub:p:help"),
             _button("🇬🇧 English" if fa else "🇮🇷 فارسی",
                     "sub:l:en" if fa else "sub:l:fa")],
            [_button("لغو عضویت" if fa else "Unsubscribe", "sub:p:stop")],
        ]
    return body, {"inline_keyboard": buttons}


def latest_panel(
    jobs: list[dict[str, str]], *, page: int, lang: str = "en",
) -> tuple[str, dict[str, Any]]:
    """A single bounded browse card, not five unsolicited Telegram messages."""
    count = min(len(jobs), PAGE_SIZE * MAX_LATEST_PAGES)
    pages = max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)
    current = max(0, min(page, pages - 1))
    fa = lang == "fa"
    title = "🔎 <b>فرصت‌های تازه</b>" if fa else "🔎 <b>Latest matches</b>"
    lines = [title, f"{current + 1} / {pages}", ""]
    for i, job in enumerate(jobs[current * PAGE_SIZE:(current + 1) * PAGE_SIZE], 1):
        url = job.get("url", "")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            continue
        label = escape(job.get("title", "Opportunity")[:110])
        source = escape(job.get("source", "")[:36])
        employer = escape(job.get("employer", "")[:70])
        market = escape(job.get("location", "")[:48])
        lines.append(
            f'{i + current * PAGE_SIZE}. <a href="{escape(url, quote=True)}">'
            f"{label}</a>\n   {employer} · {market} · {source}"
        )
    if not jobs:
        lines.append("موردی یافت نشد." if fa else "No matching listings yet.")
    keyboard: list[list[dict[str, str]]] = []
    nav = []
    if current:
        nav.append(_button("‹ قبلی" if fa else "‹ Previous", f"sub:p:latest:{current-1}"))
    if current + 1 < pages:
        nav.append(_button("بعدی ›" if fa else "Next ›", f"sub:p:latest:{current+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append(_back(lang))
    return "\n\n".join(lines), {"inline_keyboard": keyboard}
