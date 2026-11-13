# Non-US Economics PhDs in Telegram and private favorites

**Approved design (13 November 2026).** This specification defines the channel and bot changes implemented in PR #153.

## Objective and scope
Broadcast actionable, non-US **Economics doctoral vacancies** to Telegram in addition to their website/X destination; on activation, catch up eligible previously collected positions. Add per-item **🔖 Save in bot** deep links for *all* channel readers, with private per-user favorites. No automatic deployment, posting, webhook switch, historical private alert backfill, or bot replacement.

## Eligibility and routing
Only real doctoral research vacancies where a candidate will pursue a PhD, with evidence of an Economics/econometrics/applied-economics topic and a confidently known non-US work location. Reject US or unknown location, generic admissions/doctoral degree information, unrelated disciplines, completed-PhD staffing and postdoctoral openings. Keep existing non-US predoc and US website rules. Preserve website/X publication for every existing web listing.

## Historical send safety
Restore committed `data/listings.ndjson` to SQLite, examine already-published web-only entries and new approved vacancies, apply current policy, avoid expired/closed positions, verify official links and deduplicate aliases. Post past listings in bounded **Previously collected Economics PhD positions** digests with unknown-availability disclosure. Continue remaining work on later scheduled runs. Record independent Telegram send state (`not_attempted`, `pending`, `confirmed`, `uncertain`, `permanent_failure`) and message IDs in the committed journal without rewriting `published_at` or X receipts. Repeated and ambiguous deliveries must not be automatically resent. Operator resolution is required for ambiguous outcomes.

## Favorite UX
Cards show **Apply/View advert** and **🔖 Save in bot**. Digest item N shows **🔖 Save N**. Deep link `https://t.me/<bot_username>?start=f_<16 lowercase hex URL-hash prefix>` opens a private chat. Initial save is idempotent; before the next snapshot users see a saved placeholder. `/favorites` and `/bookmarks` list saved entries; Remove deletes only the requesting user's bookmark. Non-owner `/saved` may point to favorites, but owner `/saved` retains existing owner-tracking semantics. Saved closed listings remain with appropriate warning. Max 200 favorites per user, no silent eviction, and no alert subscription side effect.

## Privacy and recovery
Authenticate every private command/callback using Telegram sender ID and matching positive private chat ID. Store webhook-mode favorites separately under user-prefixed private Durable Object keys; polling uses the same encrypted `FeedbackStore` backup separate from global owner marks. Authenticate sync, seed only on first activation, treat Worker state as authoritative afterward, and prevent stale snapshots from resurrecting deleted bookmarks. Never put private favorites/user associations in the public listing journal, dashboard, logs, or channel announcements. Unsubscribe must not remove favorites; explicitly confirmed account deletion does. Never run webhook and polling concurrently.

## Verification/rollout
CI must validate Python 3.11/3.12, lint/type checks, journal recovery, routing, Telegram rendering, multi-user isolation, pre-snapshot save, webhook replay, polling fallback and Worker tests. Set `TELEGRAM_BOT_USERNAME` and deploy a compatible bot first. Keep `TELEGRAM_NON_US_ECON_PHD_ENABLED=false` until approved production activation and verified snapshot/encryption/webhook compatibility. Enable only after checking historical candidate counts and verifying no repeated sends. Roll back by disabling routing while retaining receipts and private state. PR review and merge do **not** authorize production sends, Worker deployment, or webhook reconfiguration.
