# ig-wellness-bot

Automated "Myth vs Fact" Instagram poster, 3x a day: Gemini generates
the copy (rotating through different topics so it doesn't repeat
itself), Pillow renders a designed poster image, the image and a
small history file are committed straight to this GitHub repo (which
doubles as free public image hosting — no Imgur account needed), and
the Meta Graph API publishes it to an Instagram Business/Creator
account. GitHub Actions runs the whole thing on a cron schedule.

## Files

- `bot.py` — the pipeline (Gemini → Pillow → commit image to this
  repo → Graph API)
- `requirements.txt` — pinned dependencies
- `.github/workflows/daily_post.yml` — the cron job, 3x/day
- `setup_fonts.sh` — one-time local script to fetch the two Roboto
  font files (this sandbox has no internet access, so it couldn't
  download them for you — run this script yourself, once)
- `webhook_server.py` — a small always-on Flask app that listens for
  new comments and sends the "MYTH" commenter a private-reply DM
  with the guide (see the **Auto-DM** section below)
- `Procfile` — tells host platforms like Render/Railway to run
  `webhook_server.py` as a web process

## One-time local setup

```bash
cd ig-wellness-bot
chmod +x setup_fonts.sh
./setup_fonts.sh
```

This drops `Roboto-Bold.ttf` and `Roboto-Regular.ttf` into the repo
root, next to `bot.py`.

## Image hosting & content variety (no Imgur)

- **Hosting:** each run saves its poster to `posts/<timestamp>.jpg`
  in this same repo via the GitHub API, then uses the
  `raw.githubusercontent.com` link as the `image_url` Instagram
  fetches from. **Your repo must be Public** for this to work —
  Instagram can't authenticate to pull from a private repo. Your
  secrets stay safe either way; GitHub Secrets are encrypted and
  never exposed in the code, regardless of repo visibility.
- **No new secret needed for this:** GitHub Actions automatically
  injects `GITHUB_TOKEN` and `GITHUB_REPOSITORY` into every run — you
  don't create or add these yourself. The workflow just needs
  `permissions: contents: write` (already set in
  `daily_post.yml`) so that token is allowed to commit back to the
  repo.
- **Content variety:** `bot.py` cycles through 8 topic categories
  (menstrual health, contraception, fertility, etc.) one per run, and
  keeps a running log of the last 30 myths it's posted in
  `posted_topics.json` (also committed to the repo). Each Gemini call
  is told which category to focus on and which myths to avoid
  repeating.
- **Repo growth:** at 3 posts/day this adds roughly 3 small JPGs a
  day to `posts/`. Not a real problem at normal image sizes, but if
  the repo starts feeling cluttered, say so and I can add a step
  that prunes old post images after N days.

## Auto-DM (comment → private reply)

This is a genuinely different piece of infrastructure from `bot.py`,
not an add-on to it — worth understanding before you set it up:

**Why it can't live in GitHub Actions:** the daily post job runs
once, does its work, and exits. Auto-DM needs a server that's
listening *all the time*, because Meta calls your webhook URL the
instant someone comments — it doesn't wait for a cron tick. So
`webhook_server.py` has to run somewhere that stays up (Render,
Railway, Fly.io, a small VPS, etc. — not GitHub Actions).

**How it works:** it uses Meta's official "Private Replies" feature
— when someone comments on your post, Meta POSTs the comment to your
`/webhook` endpoint; if the comment contains "myth" (case-insensitive,
configurable via `TRIGGER_WORD`), the server sends them a one-time DM
via the Graph API's `/messages` endpoint with `recipient.comment_id`.

**New environment variables** (alongside the four `bot.py` already
uses):
- `WEBHOOK_VERIFY_TOKEN` — a string you make up; you'll enter the
  same value in Meta's webhook config in a moment
- `META_APP_SECRET` — from your Meta App Dashboard → Settings →
  Basic; used to verify a webhook call really came from Meta
- `GUIDE_REPLY_MESSAGE` — the actual text (or link) you want sent to
  the commenter; the placeholder in the code won't mean anything
  until you swap it in
- `TRIGGER_WORD` — optional, defaults to `myth`

**Setup:**
1. Test locally first: `pip install -r requirements.txt`, run
   `python webhook_server.py`, then `ngrok http 5000` to get a
   temporary public HTTPS URL for it
2. In Meta App Dashboard → your app → **Webhooks** → Instagram, add
   that URL + `/webhook` as the callback, enter your
   `WEBHOOK_VERIFY_TOKEN`, and subscribe to the `comments` field
3. Send yourself a test comment and confirm you get the private
   reply and see it logged
4. Deploy `webhook_server.py` for real (Render/Railway/Fly.io all
   have simple Python-app free tiers), set the env vars there, and
   re-point the webhook URL at that permanent address

**Permissions — the part most likely to trip you up:** private
replies need `instagram_business_basic` +
`instagram_business_manage_messages` (older Facebook Login app
setups may instead need `instagram_manage_comments` +
`pages_messaging` — Meta's docs are the source of truth for your
specific app type). These require **Meta App Review** to work for
real users, which can take days to weeks. Add your own account as an
**Instagram Tester** in the App Dashboard so you can test the full
flow on yourself while review is pending.

**Hard limits from Meta, not from this code:** one private reply per
comment, and it must be sent within 7 days of the comment.

**Host note:** this account's token comes from the "API setup with
Instagram login" page, so `bot.py` and `webhook_server.py` are both
already set to call `graph.instagram.com` (not `graph.facebook.com`)
— that's the host that matches this login flow.

## Checklist before it goes live

- [ ] Run `setup_fonts.sh` locally and confirm both `.ttf` files sit
      next to `bot.py`
- [ ] `git init`, commit everything (fonts included), and push this
      repo to GitHub **as a Public repo** (required so Instagram can
      fetch the posted images)
- [ ] In the repo's **Settings → Secrets and variables → Actions**,
      add these three secrets:
  - `GEMINI_API_KEY`
  - `IG_USER_ID`
  - `IG_ACCESS_TOKEN`
- [ ] Trigger the workflow once by hand (Actions tab → "Daily
      Instagram Publisher" → **Run workflow**) to confirm it posts
      successfully before trusting the cron schedule
- [ ] Fill in a real `GUIDE_REPLY_MESSAGE` (the placeholder is not
      usable as-is)
- [ ] Add yourself as an Instagram Tester in the Meta App Dashboard
      and test the full comment → DM flow on your own account
      before relying on it for real commenters
- [ ] Submit for Meta App Review (needed before it'll work for
      people who aren't your testers) and deploy `webhook_server.py`
      somewhere that stays running
- [ ] Since there's no human-review step before publishing, consider
      periodically spot-checking a few of the AI-generated myth/fact
      pairs for accuracy — an LLM can still get a clinical detail
      wrong, and this is health-adjacent content going out under
      your account
