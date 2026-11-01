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

from .subscriptions import CAREER_SCOPES, LOOKBACK_DAYS, TOPIC_LABELS

ACADEMIC = ("predoc", "phd", "postdoc", "research")
LIFE_SCIENCES = "life_sciences_phd"
CAREERS = ("data_scientist", "data_analyst", "econ_consulting", "research_analyst")
REGION_LABELS = {
    "en": {
        "north_america": "North America", "latin_america": "Latin America",
        "europe": "Europe (incl. UK)", "middle_east": "Middle East",
        "asia": "Asia", "oceania": "Oceania", "africa": "Africa",
        "unknown": "Other / unspecified",
    },
    "fa": {
        "north_america": "آمریکای شمالی", "latin_america": "آمریکای لاتین",
        "europe": "اروپا (شامل بریتانیا)", "middle_east": "خاورمیانه",
        "asia": "آسیا", "oceania": "اقیانوسیه", "africa": "آفریقا",
        "unknown": "سایر / مکان نامشخص",
    },
}
PAGE_SIZE = 4
MAX_LATEST_PAGES = 500  # At most the 2,000-row uploaded snapshot at four per page

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


SHORT_ROLE_NAMES = {
    "en": {
        "predoc": "Predoc / RA", "phd": "PhD positions",
        "postdoc": "Postdocs", "research": "Research staff",
        "data_scientist": "Data science", "data_analyst": "Data analysis / BI",
        "econ_consulting": "Econ consulting", "research_analyst": "Research analyst",
    },
    "fa": {
        "predoc": "پیشادکتری / دستیار", "phd": "فرصت دکتری",
        "postdoc": "پسادکتری", "research": "پژوهشگر حرفه‌ای",
        "data_scientist": "علم داده", "data_analyst": "تحلیل داده / BI",
        "econ_consulting": "مشاوره اقتصادی", "research_analyst": "تحلیلگر پژوهش",
    },
}


def _role_grid(keys: tuple[str, ...], topics: dict[str, str],
               lang: str) -> list[list[dict[str, str]]]:
    """Short 2-column Telegram buttons; descriptions live in the message."""
    return [
        [
            _button(
                ("☑ " if key in topics else "☐ ") + SHORT_ROLE_NAMES[lang][key],
                f"sub:t:{key}",
            )
            for key in keys[offset:offset + 2]
        ]
        for offset in range(0, len(keys), 2)
    ]


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
    regions = member.get("academic_regions", {}) if member else {}
    region_summary = ", ".join(
        REGION_LABELS[lang][key] for key in regions if key != "all"
    )
    region_summary = region_summary or ("همه جهان" if fa else "Worldwide")
    if page == "markets":
        page = "careers"  # Legacy callbacks remain valid.
    paused = bool(member and member.get("paused"))
    buttons: list[list[dict[str, str]]] = []
    if page == "subscriptions":
        academic = sum(key in topics for key in ACADEMIC)
        careers = sum(key in topics for key in CAREERS)
        life = LIFE_SCIENCES in topics
        market_names = [
            ("ایران" if fa else "Iran") if "iran" in scopes else "",
            ("دورکاری" if fa else "Remote") if "remote" in scopes else "",
        ]
        market_summary = " · ".join(name for name in market_names if name) or (
            "انتخاب نشده" if fa else "Not selected"
        )
        body = (
            "🧭 <b>ویرایش اشتراک‌ها</b>\n<i>هر انتخاب فوری ذخیره می‌شود.</i>\n\n"
            f"<b>🎓 دانشگاهی</b> · {academic}/۴ انتخاب‌شده\n"
            f"🌍 {escape(region_summary)}\n\n"
            f"<b>💼 مشاغل</b> · {careers}/۴ انتخاب‌شده\n"
            f"محدوده‌ها · {len(scopes)}/۲ · {escape(market_summary)}\n\n"
            f"<b>🧬 علوم زیستی</b> · {'فعال' if life else 'خاموش'}"
            if fa else
            "🧭 <b>Edit subscriptions</b>\n<i>Changes save as you tap.</i>\n\n"
            f"<b>🎓 Academic</b> · {academic}/4 selected\n"
            f"🌍 {escape(region_summary)}\n\n"
            f"<b>💼 Careers</b> · {careers}/4 selected\n"
            f"Job markets · {len(scopes)}/2 · {escape(market_summary)}\n\n"
            f"<b>🧬 Life Sciences</b> · {'On' if life else 'Off'}"
        )
        if careers and not scopes:
            body += ("\n\n⚠️ برای دیدن مشاغل یک محدوده انتخاب کنید." if fa
                     else "\n\n⚠️ Choose a market to enable career matches.")
        buttons = [
            [_button("🎓 دانشگاهی" if fa else "🎓 Academic", "sub:p:academic"),
             _button("💼 مشاغل" if fa else "💼 Careers", "sub:p:careers")],
            [_button("🧬 علوم زیستی" if fa else "🧬 Life Sciences",
                     "sub:p:life_sciences")],
            [_button("🔎 مشاهده فرصت‌ها" if fa else "🔎 Browse my matches",
                     "sub:p:latest")],
            _back(lang),
        ]
    elif page == "academic":
        selected = sum(key in topics for key in ACADEMIC)
        body = (
            "🎓 <b>فرصت‌های دانشگاهی</b>\n<i>برای انتخاب یا حذف ضربه بزنید.</i>\n\n"
            f"<b>مرحله ۱ · نقش‌ها</b>  {selected}/۴ انتخاب‌شده\n"
            "پیشادکتری قبل از دکتری است؛ پسادکتری و پژوهشگر معمولاً به دکتری نیاز دارند.\n\n"
            f"<b>مرحله ۲ · مناطق</b>\n🌍 {escape(region_summary)}"
            if fa else
            "🎓 <b>Academic roles</b>\n<i>Tap to select or remove.</i>\n\n"
            f"<b>Step 1 · Roles</b>  {selected}/4 selected\n"
            "Predoc comes before a PhD; postdocs and research staff may require one.\n\n"
            f"<b>Step 2 · Regions</b>\n🌍 {escape(region_summary)}"
        )
        buttons = _role_grid(ACADEMIC, topics, lang)
        all_set = all(key in topics for key in ACADEMIC)
        buttons += [
            [_button(
                "حذف همه نقش‌ها" if fa and all_set else
                "انتخاب همه نقش‌ها" if fa else "Clear roles" if all_set else "Select all roles",
                f"sub:b:academic:{'off' if all_set else 'on'}",
            )],
            [_button("🌍 انتخاب مناطق" if fa else "🌍 Edit academic regions",
                     "sub:p:academic_regions")],
            [_button("🔎 مشاهده فرصت‌ها" if fa else "🔎 View matches", "sub:p:latest")],
            [_button("← اشتراک‌ها" if fa else "← Subscriptions",
                     "sub:p:subscriptions")],
        ]
    elif page == "academic_regions":
        ordered = [
            "north_america", "latin_america", "europe", "middle_east",
            "asia", "oceania", "africa", "unknown",
        ]
        for offset in range(0, len(ordered), 2):
            buttons.append([
                _button(
                    ("☑ " if region in regions else "☐ ") + REGION_LABELS[lang][region],
                    f"sub:r:{region}",
                ) for region in ordered[offset:offset + 2]
            ])
        buttons.extend([
            [_button(("☐ " if regions else "☑ ") +
                     ("همه جهان (حذف فیلتر)" if fa else "Worldwide (clear filters)"),
                     "sub:r:all")],
            [_button("← دانشگاهی" if fa else "← Academic", "sub:p:academic")],
        ])
        description = (
            "هر منطقه دلخواه را انتخاب کنید. «همه جهان» فیلتر را پاک می‌کند."
            if fa else "Select regions or choose Worldwide to clear filters."
        )
        body = (
            "🌍 <b>مناطق دانشگاهی</b>" if fa else "🌍 <b>Academic regions</b>"
        ) + f"\n\n{description}\n\n" + (
            "انتخاب فعلی: " if fa else "Current: "
        ) + escape(region_summary)
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
                ("☑ " if LIFE_SCIENCES in topics else "☐ ") +
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
                ("☑ " if key in topics else "☐ ") + _label(key, lang), f"sub:t:{key}",
            )])
        all_set = all(key in topics for key in CAREERS)
        buttons.append([_button(
            "پاک‌کردن همه" if fa and all_set else
            "انتخاب همه" if fa else "Clear all" if all_set else "Select all",
            f"sub:b:careers:{'off' if all_set else 'on'}",
        )])
        for key in CAREER_SCOPES:
            buttons.append([_button(
                ("☑ " if key in scopes else "☐ ") + _label(key, lang),
                f"sub:g:{key}",
            )])
        buttons.append([_button("← اشتراک‌ها" if fa else "← Subscriptions",
                                "sub:p:subscriptions")])
        body = f"{title}\n\n{caption}\n\n" + (
            f"محدوده‌ها: {len(scopes)}/2" if fa else
            f"Job markets: {len(scopes)}/2 selected"
        )
        if any(key in topics for key in CAREERS) and not scopes:
            body += ("\n\n⚠️ حداقل یک محدوده را انتخاب کنید." if fa else
                     "\n\n⚠️ Select at least one market to receive career matches.")
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
            "Edit subscriptions and language, get help, or manage your privacy."
        )
        buttons = [
            [_button("🧭 اشتراک‌ها" if fa else "🧭 Edit subscriptions", "sub:p:subscriptions"),
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
            "۲. محدوده‌های شغلی در همان صفحه‌اند؛ مناطق دانشگاهی جدا هستند.\n"
            "۳. اعلان‌ها فقط برای آگهی‌های جدید پس از عضویت هستند.\n"
            "۴. «تازه‌ترین‌ها» آگهی‌های قبلی را هم برای مرور نشان می‌دهد.\n"
            "۵. توقف اعلان‌ها اشتراک را نگه می‌دارد.\n"
            "برای حذف اشتراک، «لغو عضویت» را انتخاب کنید.\n"
            "برای اطلاعات نگهداری داده‌ها، /privacy را باز کنید."
            if fa else
            "ℹ️ <b>How alerts work</b>\n\n"
            "1. Choose academic roles, Life Sciences PhD, or specialist careers.\n"
            "2. Choose career markets on the same screen; academic regions are separate.\n"
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
            "Edit subscriptions to choose roles and regions. Browse before subscribing."
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
                "💼 تعیین محدوده مشاغل" if fa else "💼 Set career markets",
                "sub:p:careers",
            )])
        buttons.insert(0, [_button(
            "🧭 ویرایش اشتراک‌ها" if fa else "🧭 Edit subscriptions",
            "sub:p:subscriptions",
        )])
    return body, {"inline_keyboard": buttons}


def latest_panel(
    jobs: list[dict[str, str]], *, page: int, lang: str = "en",
    lookback_days: int = 14,
) -> tuple[str, dict[str, Any]]:
    """An editable view of a selected history window, not an alert backfill."""
    if lookback_days not in LOOKBACK_DAYS:
        raise ValueError("Unsupported match-history window")
    jobs = [
        item for item in jobs
        if _verified_https(item.get("url", ""))
    ]
    count = min(len(jobs), PAGE_SIZE * MAX_LATEST_PAGES)
    pages = max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)
    current = max(0, min(page, pages - 1))
    fa = lang == "fa"
    title = "🔎 <b>فرصت‌های تازه</b>" if fa else "🔎 <b>Latest matches</b>"
    period = f"{lookback_days} روز اخیر" if fa else f"Last {lookback_days} days"
    lines = [title, period, f"{current + 1} / {pages}", ""]
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
    labels = {
        7: ("7 days", "۷ روز"), 14: ("14 days", "۱۴ روز"),
        30: ("1 month", "۱ ماه"), 60: ("2 months", "۲ ماه"),
        90: ("3 months", "۳ ماه"),
    }
    for group in ((7, 14), (30, 60), (90,)):
        keyboard.append([
            _button(
                f"{'☑' if days == lookback_days else '☐'} {labels[days][1 if fa else 0]}",
                f"sub:p:latest:{days}:0",
            ) for days in group
        ])
    nav = []
    if current:
        nav.append(_button("‹ قبلی" if fa else "‹ Previous",
                           f"sub:p:latest:{lookback_days}:{current-1}"))
    if current + 1 < pages:
        nav.append(_button("بعدی ›" if fa else "Next ›",
                           f"sub:p:latest:{lookback_days}:{current+1}"))
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
