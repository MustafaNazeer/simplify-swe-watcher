# simplify-swe-watcher

Checks the [SimplifyJobs Summer 2027 internship list](https://github.com/SimplifyJobs/Summer2027-Internships) every 5 minutes with GitHub Actions and sends a push notification through [ntfy](https://ntfy.sh) for each new software engineering listing.

A listing counts when its category is `Software` or `Software Engineering`, its terms include `Summer 2027`, and it is active and visible. IDs already notified are stored in `seen.json`. The first run seeds that file without sending anything, and each run sends at most 20 notifications, oldest first.

The ntfy topic comes from the `NTFY_TOPIC` repository secret.
