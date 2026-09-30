# simplify-swe-watcher

Checks the [SimplifyJobs Summer 2027 internship list](https://github.com/SimplifyJobs/Summer2027-Internships) every 2 minutes with GitHub Actions and sends a Telegram message through a bot for each new software engineering or data science, AI and machine learning listing, formatted as `<company>: <title> @ <time posted>` with the posted date underneath, in US Central time. Listings Simplify records with only a date show the date alone.

A listing counts when its category is `Software`, `Software Engineering`, `AI/ML/Data` or `Data Science, AI & Machine Learning`, its terms include `Summer 2027`, and it is active and visible. IDs already notified are stored in `seen.json`. The first run seeds that file without sending anything, and each run sends at most 20 notifications, oldest first.

The bot token and chat ID come from the `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` repository secrets.

Each workflow run keeps checking for about 5 hours 40 minutes and then starts the next run itself, because GitHub often delays scheduled runs by hours. The 5 minute cron schedule is only a backstop in case that chain breaks. To stop the watcher, disable the workflow in the Actions tab.
