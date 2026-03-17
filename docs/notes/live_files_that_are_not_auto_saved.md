# Live files not automatically saved to GitHub

These live-runtime files exist outside the git repo and must be mirrored manually if changed:

- /home/rollan/.openclaw/openclaw.json
- /home/rollan/.config/systemd/user/openclaw-gateway.service
- /home/rollan/.config/systemd/user/openclaw-discord-outbox.service
- /home/rollan/.config/systemd/user/openclaw-discord-outbox.timer
- /home/rollan/.config/systemd/user/pinchtab.service

Do not commit:
- /home/rollan/.openclaw/secrets.env
- transient state/log/task JSON unless intentionally needed
