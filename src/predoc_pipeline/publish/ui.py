"""Compact, accessible native Telegram navigation for private Collegeum chats.

Buttons use stable short callback payloads; all actions are implemented by the
private interaction controller, not an external web app. No user identifier is
embedded in any keyboard or callback.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .subscriptions import CAREER_SCOPES, TOPIC_LABELS

ACADEMIC = ("predoc", "phd", "postdoc", "research")
LIFE_SCIENCES = "life_sciences_phd"
CAREERS = ("data_scientist", "data_analyst", "econ_consulting", "research_analyst")
PAGE_SIZE = 4
MAX_LATEST_PAGES = 10

PERSIAN_LABELS = {
    "predoc": "دستیار پژوهشی / پیشادکتری",
    "phd": "فرصت دکتری",
    "life_sciences_phd": "دکتری علوم زیستی · اروپا",
    "postdoc": "پسادکتری",
    "research": "پژوهشگر حرفه‌ای دارای دکتری",
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
        caption = (
            "پیشادکتری پیش از ورود به دکتری است؛ دکتری برای دانشجویان دکتری است؛ "
            "پسادکتری و پژوهشگر حرفه‌ای معمولاً مدرک دکتری می‌خواهند. "
            "موضوع‌ها مستقل‌اند و فقط آگهی‌های تازه اعلان می‌شوند."
            if fa else
            "Predoc = before a PhD; PhD = doctoral student openings; "
            "postdoc and research staff may require a completed PhD. "
            "Tap a role to turn its alerts on or off."
        )
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
    elif page == "life_sciences":
        title = (
            "🧬 <b>دکتری علوم زیستی · اروپا</b>" if fa
            else "🧬 <b>Life Sciences PhD · Europe</b>"
        )
        caption = (
            "دکتری در ژنتیک، اپی‌ژنتیک، کروماتین، تنظیم ژن، زیست‌شناسی "
            "مولکولی، ژنومیک و علوم اعصاب. فقط اروپای قاره‌ای با مکان "
            "مشخص (بدون بریتانیا). بورسیه، حقوق و شهریه باید جداگانه بررسی شوند."
            if fa else
            "Doctoral positions in epigenetics, chromatin, gene regulation, "
            "genomics, molecular biology, bioinformatics and neuroscience. "
            "Continental Europe only, with a known location (not the UK). "
            "Funding, salary and tuition must be verified in each advert."
        )
        buttons = [
            [_button(
                ("✓ " if LIFE_SCIENCES in topics else "○ ") +
                _label(LIFE_SCIENCES, lang),
                "sub:t:life_sciences_phd",
            )],
            _back(lang),
        ]
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
    elif page == "delivery":
        mode = member.get("delivery_mode", "instant") if member else "instant"
        limit = member.get("daily_limit", 6) if member else 6
        quiet = bool(member and member.get("quiet_hours"))
        zone = member.get("timezone", "UTC") if member else "UTC"
        body = (
            "🔔 <b>تنظیمات ارسال اعلان‌ها</b>\n\n"
            f"روش: {'خلاصه روزانه' if mode == 'digest' else 'اعلان جداگانه'}\n"
            f"حد روزانه: {limit} فرصت\n"
            f"ساعات آرام: {'۲۲ تا ۸' if quiet else 'خاموش'}\n"
            f"منطقه زمانی: {escape(zone)}"
            if fa else
            "🔔 <b>Notification delivery</b>\n\n"
            f"Mode: {'Daily digest' if mode == 'digest' else 'Individual alerts'}\n"
            f"Daily maximum: {limit} opportunities\n"
            f"Quiet hours: {'22:00–08:00' if quiet else 'Off'}\n"
            f"Time zone: {escape(zone)}"
        )
        buttons = [
            [_button(
                "📬 اعلان تکی" if fa and mode == "digest" else
                "📬 خلاصه روزانه" if fa else
                "📬 Switch to individual" if mode == "digest" else
                "📬 Switch to daily digest",
                "sub:d:mode",
            )],
            [_button(
                (f"حد روزانه: {limit}" if fa else f"Daily maximum: {limit}")
                + " →", "sub:d:limit",
            )],
            [_button(
                "ساعات آرام: " + ("روشن" if quiet else "خاموش") if fa else
                "Quiet hours: " + ("On" if quiet else "Off"),
                "sub:d:quiet",
            )],
            [_button(
                ("منطقه زمانی: " if fa else "Time zone: ") + zone,
                "sub:d:zone",
            )],
            _back(lang),
        ]
    elif page == "more":
        body = (
            "⚙️ <b>تنظیمات و راهنما</b>\n\n"
            "تنظیمات منطقه، زبان و حریم خصوصی و راهنمای استفاده."
            if fa else
            "⚙️ <b>More options</b>\n\n"
            "Adjust job markets and language, get help, or manage your privacy."
        )
        buttons = [
            [_button("🌍 محدوده" if fa else "🌍 Job markets", "sub:p:markets"),
             _button("🌐 منابع" if fa else "🌐 Sources", "sub:p:sources")],
            [_button("ℹ️ راهنما" if fa else "ℹ️ Help", "sub:p:help"),
             _button("🔒 حریم خصوصی" if fa else "🔒 Privacy", "sub:p:privacy")],
            [_button("🇬🇧 English" if fa else "🇮🇷 فارسی",
                     "sub:l:en" if fa else "sub:l:fa")],
            [_button("لغو عضویت" if fa else "Unsubscribe", "sub:p:stop")],
            _back(lang),
        ]
    elif page == "privacy":
        body = (
            "🔒 <b>حریم خصوصی</b>\n\n"
            "شناسه گفت‌وگو، موضوع‌های انتخابی و سوابق ارسال با رمزنگاری "
            "Fernet ذخیره می‌شوند. در حالت قدیمی، نسخه‌های رمزگذاری‌شده در "
            "تاریخچه مخزن عمومی باقی می‌مانند. /delete اشتراک فعال را حذف "
            "می‌کند، نه نسخه‌های تاریخی را."
            if fa else
            "🔒 <b>Privacy</b>\n\n"
            "Your chat ID, topics and delivery records are Fernet-encrypted. "
            "In legacy public-repository mode, old encrypted revisions remain "
            "accessible in Git history. /delete removes active subscription "
            "records, not historical repository revisions."
        )
        buttons = [_back(lang)]
    elif page == "help":
        body = (
            "ℹ️ <b>راهنما</b>\n\n"
            "۱. در «دانشگاهی»، «دکتری علوم زیستی» یا «مشاغل» موضوع دلخواه را انتخاب کنید.\n"
            "۲. برای مشاغل، ایران یا دورکاری جهانی را جداگانه انتخاب کنید.\n"
            "۳. اعلان‌ها فقط برای آگهی‌های جدید پس از عضویت هستند.\n"
            "۴. «تازه‌ترین‌ها» آگهی‌های قبلی را هم برای مرور نشان می‌دهد.\n"
            "۵. توقف اعلان‌ها اشتراک را نگه می‌دارد.\n"
            "برای حذف اشتراک، «لغو عضویت» را انتخاب کنید.\n"
            "برای اطلاعات نگهداری داده‌ها، /privacy را باز کنید."
            if fa else
            "ℹ️ <b>How alerts work</b>\n\n"
            "1. Choose academic roles, Life Sciences PhD, or specialist careers.\n"
            "2. For careers, select Iran and/or worldwide remote.\n"
            "3. Notifications cover new matches after you opt in.\n"
            "4. Browse latest to view existing positions on demand.\n"
            "5. Pausing keeps your preferences but stops new alerts.\n"
            "Unsubscribe removes your active private alert records. "
            "Encrypted snapshots may remain in the public repository history. "
            "See /privacy for storage details."
        )
        body += (
            "\n\nبا /ask درباره اطلاعات ذخیره‌شده فرصت‌ها بپرسید. "
            "با /forget زمینه گفت‌وگوی هوش مصنوعی را پاک کنید."
            if fa else
            "\n\nUse /ask to question the stored vacancy database, "
            "and /forget to clear AI follow-up context."
        )
        buttons = [_back(lang)]
    elif page == "stop":
        body = (
            "🗑 <b>لغو عضویت؟</b>\n\n"
            "موضوع‌ها و سوابق ارسال شما از وضعیت فعال حذف می‌شوند."
            if fa else
            "🗑 <b>Unsubscribe?</b>\n\n"
            "Your active topics, markets, and delivery records will be removed. "
            "Historic encrypted Git snapshots cannot be erased by this command."
        )
        buttons = [
            [_button("لغو عضویت" if fa else "Yes, unsubscribe", "sub:stop:yes")],
            [_button("انصراف" if fa else "Keep my alerts", "sub:p:home")],
        ]
    else:
        academic = sum(key in topics for key in ACADEMIC)
        careers = sum(key in topics for key in CAREERS)
        life_active = LIFE_SCIENCES in topics
        selected_markets = [
            _label(key, lang) for key in CAREER_SCOPES if key in scopes
        ]
        alerts_ready = bool(academic or life_active or (careers and selected_markets))
        delivery_status_en = (
            "Not configured" if not alerts_ready else "Paused" if paused else "On"
        )
        market_line = ", ".join(selected_markets) if selected_markets else (
            "انتخاب نشده" if fa else "Not selected"
        )
        body = (
            "🧭 <b>Collegeum | اعلان فرصت‌ها</b>\n\n"
            f"🎓 دانشگاهی: {academic}/{len(ACADEMIC)}\n"
            f"💼 شغلی: {careers}/4\n"
            f"🧬 زیست‌شناسی: {'فعال' if life_active else 'غیرفعال'}\n"
            f"🌍 محدوده: {escape(market_line)}\n"
            f"🔔 وضعیت: {'تنظیم نشده' if not alerts_ready else 'متوقف' if paused else 'فعال'}\n\n"
            "برای تنظیم، یکی از دسته‌ها را انتخاب کنید."
            if fa else
            "🧭 <b>Collegeum | Job alerts</b>\n\n"
            f"🎓 Academic roles: {academic}/{len(ACADEMIC)}\n"
            f"💼 Career roles: {careers}/4\n"
            f"🧬 Life Sciences PhD: {'On' if life_active else 'Off'}\n"
            f"🌍 Markets: {escape(market_line)}\n"
            f"🔔 Alerts: {delivery_status_en}\n\n"
            "Choose roles below. Latest matches lets you browse before subscribing."
        )
        if careers and not selected_markets:
            body += (
                "\n\n⚠️ برای دریافت اعلان مشاغل، محدوده جستجو را انتخاب کنید."
                if fa else "\n\n⚠️ Choose a job market to enable career alerts."
            )
        buttons = [
            [_button("🎓 دانشگاهی" if fa else "🎓 Academic", "sub:p:academic"),
             _button("💼 مشاغل" if fa else "💼 Careers", "sub:p:careers")],
            [_button("🧬 دکتری علوم زیستی" if fa else "🧬 Life Sciences PhD",
                     "sub:p:life_sciences")],
            [_button("🔎 تازه‌ترین‌ها" if fa else "🔎 Latest matches", "sub:p:latest"),
             _button("🔔 تنظیم ارسال" if fa else "🔔 Delivery", "sub:p:delivery")],
            [_button(
                "▶ ازسرگیری" if fa and paused else "⏸ توقف" if fa else
                "▶ Resume" if paused else "⏸ Pause",
                "sub:a:resume" if paused else "sub:a:pause",
            ),
             _button("⚙️ بیشتر" if fa else "⚙️ More", "sub:p:more")],
        ]
        if careers and not selected_markets:
            buttons.insert(2, [_button(
                "🌍 محدوده را انتخاب کنید" if fa else "🌍 Choose a job market",
                "sub:p:markets",
            )])
    return body, {"inline_keyboard": buttons}


def latest_panel(
    jobs: list[dict[str, str]], *, page: int, lang: str = "en",
) -> tuple[str, dict[str, Any]]:
    """A single bounded browse card, not five unsolicited Telegram messages."""
    jobs = [
        item for item in jobs
        if _verified_https(item.get("url", ""))
    ]
    count = min(len(jobs), PAGE_SIZE * MAX_LATEST_PAGES)
    pages = max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)
    current = max(0, min(page, pages - 1))
    fa = lang == "fa"
    title = "🔎 <b>فرصت‌های تازه</b>" if fa else "🔎 <b>Latest matches</b>"
    lines = [title, f"{current + 1} / {pages}", ""]
    for i, job in enumerate(jobs[current * PAGE_SIZE:(current + 1) * PAGE_SIZE], 1):
        url = job["url"]
        label = escape(job.get("title", "Opportunity")[:110])
        source = escape(job.get("source", "")[:36])
        employer = escape(job.get("employer", "")[:70])
        market = escape(job.get("location", "")[:48])
        lines.append(
            f'{i + current * PAGE_SIZE}. <a href="{escape(url, quote=True)}">'
            f"{label}</a>\n   {employer} · {market} · {source}"
        )
    if not jobs:
        lines.append("موردی یافت نشد. موضوع‌ها را تغییر دهید یا بعداً بررسی کنید."
                     if fa else "No matching listings yet. Change your roles or check again later.")
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



def _verified_https(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return parsed.scheme == "https" and bool(parsed.hostname) and len(value) <= 1024
    except (TypeError, ValueError):
        return False


def sources_panel(
    health_path: str | Path, *, lang: str = "en",
) -> tuple[str, dict[str, Any]]:
    """Status of the last job-source poll, without secret or user data.

    Health is a small public-source-only JSON written by the collector.
    Unknown provider names and raw server errors never reach subscribers.
    """
    fa = lang == "fa"
    header = (
        "🌐 <b>وضعیت منابع فرصت‌های شغلی</b>"
        if fa else "🌐 <b>Job-source status</b>"
    )
    lines = [header]
    path = Path(health_path)
    health: dict[str, Any] | None = None
    try:
        if path.is_file() and path.stat().st_size <= 65536:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                health = value
    except (OSError, ValueError):
        pass
    if health is None:
        lines.append(
            "هنوز گزارش بررسی منابع در دسترس نیست."
            if fa else "No source-check report is available yet."
        )
    else:
        timestamp = str(health.get("checked_at", ""))[:16]
        if timestamp:
            lines.append(
                f"آخرین بررسی: {escape(timestamp)} UTC"
                if fa else f"Last check: {escape(timestamp)} UTC"
            )
        providers = {
            "jobicy": ("Jobicy", "جهانی / دورکاری", "Worldwide remote"),
            "jobinja": ("Jobinja", "داخل ایران", "Iran-based"),
            "irantalent": ("IranTalent", "داخل ایران", "Iran-based"),
        }
        sources = health.get("sources", {})
        if not isinstance(sources, dict):
            sources = {}
        for key, (name, fa_scope, en_scope) in providers.items():
            info = sources.get(key, {})
            if not isinstance(info, dict):
                info = {}
            enabled = info.get("requested") is True
            fetched = info.get("fetched", 0)
            accepted = info.get("accepted", 0)
            valid = (
                type(fetched) is int and type(accepted) is int
                and 0 <= fetched <= 100 and 0 <= accepted <= 2000
            )
            state = info.get("status")
            if state not in ("ok", "empty", "error", "degraded", "idle"):
                state = "ok" if enabled and fetched and valid else "error"
            if not enabled:
                state = "idle"
            try:
                last = datetime.fromisoformat(
                    str(health.get("checked_at", "")).replace("Z", "+00:00")
                )
                if last.tzinfo is None:
                    raise ValueError("naive health timestamp")
                stale = datetime.now(UTC) - last.astimezone(UTC) > timedelta(hours=12)
            except ValueError:
                stale = True
            if enabled and stale:
                state = "stale"
            marker = {"ok": "✓", "empty": "○", "idle": "○",
                      "error": "!", "degraded": "!", "stale": "!"}[state]
            summary = {
                "ok": ("فعال", "Healthy"),
                "empty": ("بدون مورد مرتبط", "No matching roles"),
                "idle": ("درخواستی نیست", "Not selected"),
                "error": ("خطا", "Source error"),
                "degraded": ("اختلال", "Degraded"),
                "stale": ("قدیمی", "Stale"),
            }[state][0 if fa else 1]
            count = str(accepted) if enabled and valid else "—"
            lines.append(
                f"{marker} <b>{name}</b> · {fa_scope if fa else en_scope}"
                f" · {summary} · {count} {'مورد' if fa else 'matches'}"
            )
        lines.append(
            "این اعداد پوشش کامل بازار کار را تضمین نمی‌کنند."
            if fa else
            "Source counts show observed matches, not full market coverage."
        )
    return "\n".join(lines), {
        "inline_keyboard": [_back(lang)],
    }
