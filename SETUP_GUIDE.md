# Setup guide (GitHub website only, no programming)

This guide walks you through deploying the pipeline and connecting your Telegram channel and optional LLM providers. Plan for about 10 minutes.

You will need: your Telegram **bot token** and your **public channel ID** (or chat ID).

---

## Step 1 — Prepare your Telegram Bot and Channel

Ensure your Telegram bot is added as an administrator to your target Telegram channel so it has permission to post messages.

## Step 2 — Configure Repository Secrets

In your GitHub repository:
1. Go to **Settings** → **Secrets and variables** → **Actions**.
2. Click **New repository secret** and add your credentials.

## Step 3 — Upload the files

1. Unzip `predoc-pipeline.zip` on your computer.
2. On the new repository page click **uploading an existing file**.
3. Open the unzipped `predoc-pipeline` folder, select **everything inside it**
   (`src`, `config`, `docs`, `tests`, `tools`, `pyproject.toml`, `README.md`
   and the other files) and drag it onto the GitHub page.
4. Wait until all files are listed, then click **Commit changes**.

Folders whose name starts with a dot (`.github`) are hidden on most computers
and are not uploaded this way. That is expected: you create the two
important files by hand in the next step. (If the repository page *does* show
a `.github` folder after the upload, it worked anyway: skip Step 4.)

## Step 4 — Create the two automatic jobs

Do this twice, once per file:

1. In the repository click **Add file** → **Create new file**.
2. In the name box type exactly `.github/workflows/pipeline.yml`
   (typing the `/` creates the folders).
3. Open the file **`pipeline.yml`** I sent you in the chat, copy **all** of
   it, and paste it into the big text box.
4. Click **Commit changes…** → **Commit changes**.

Then repeat with the name `.github/workflows/telegram.yml` and the content of
**`telegram.yml`**.

(The other two workflow files are optional: `ci.yml` re-runs the tests after
each upload and uses extra free minutes; `pages.yml` is the web dashboard,
which only works on a public repository. You can skip both.)

## Step 5 — Allow the jobs to save their data

1. **Settings** (top of the repository) → **Actions** (left) → **General**.
2. Scroll to **Workflow permissions**, choose **Read and write permissions**,
   click **Save**.

## Step 6 — Add your two secrets

**Settings** → **Secrets and variables** (left) → **Actions** →
**New repository secret**. Add:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | your bot token (same as the old bot) |
| `TELEGRAM_PUBLIC_CHANNEL_ID` | your chat id, the number you used as `TELEGRAM_CHAT_ID` before |

Type the names exactly as shown (capital letters, underscores). You do **not**
need `GEMINI_API_KEY`: without it the bot uses its own rules, which is also the
only option that works from Iran.

## Step 7 — First run

1. **Actions** tab → **predoc-pipeline** (left) → **Run workflow** → green
   **Run workflow** button.
2. It takes about 5–15 minutes (it reads every new job page). A green tick
   means it finished.
3. In Telegram you receive the positions that are open right now. On this
   first run that can be many, so they arrive as numbered lists of 6 with
   buttons under each list.

After this, it runs by itself every morning at 07:30 Tehran time and only
sends positions it has not sent before.

## Step 8 — Use the buttons and commands

Under every position:

* ✅ **Interested** — keeps it in `/valid`
* ❌ **Not for me** — hides it everywhere, for good
* 📝 **Applied** — moves it to `/applied`, so you can track your applications

Tap the same button again to undo. Commands you can send to the bot:
`/positions` (all open positions, soonest deadline first), `/applied`,
`/valid`, `/hidden`, `/help`.

The bot checks for your messages every 30 minutes between 06:45 and 00:15
Tehran time, so an answer can take up to half an hour. To get an answer right
away: **Actions** → **telegram-sync** → **Run workflow**.

---

## Changing what the bot sends

Open `config/preferences.toml` on GitHub and click the pencil icon ✏️ to edit.
For example, to never see a particular employer again, add its name to
`excluded_employers`:

```toml
excluded_employers = [
  "J-PAL", "JPAL", "Poverty Action Lab", "povertyactionlab.org",
  "Some Institute",
]
```

Click **Commit changes**. The next run uses the new rules, and positions
already sent that no longer match are removed from `/positions`.

To switch a source off, open `config/sources.toml`, find its `[[board]]`
block and add the line `enabled = false`.

## If something goes wrong

* **A red ✗ in Actions**: click it, then the failed step, and send me a
  screenshot of the red lines.
* **"N source(s) failing for 3+ runs in a row"** in Telegram: a website
  changed or blocks GitHub. The bot keeps working with the other sources.
  Send me the message and I'll fix that source.
* **No reply to /positions**: wait 30 minutes, or run **telegram-sync** by
  hand (see Step 8). Check that the old bot's workflows are disabled (Step 1).

## Free minutes

A private repository gets 2,000 free GitHub Actions minutes a month. The daily
run uses about 250 of them, the 30-minute Telegram check about 1,100. If you
ever run short, open `.github/workflows/telegram.yml`, change
`"15,45 3,5-20 * * *"` to `"15 3,5-20 * * *"` (once an hour) and commit.
