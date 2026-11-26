# Security

This project handles text from incidents and news, and it enforces that a named person, never a model, approves what is published. A bug that lets something be approved or published without that, or that leaks a secret through the verify or publish stages, is a security issue.

## Reporting
Please use GitHub's private vulnerability reporting for this repository (Security tab, "Report a vulnerability"). Do not open a public issue for it. If that option is not available, open an issue that says only that you have a security report and ask for a private channel; do not include details.

## What helps
- The commands that reproduce it and what you expected.
- Whether it needs a real platform (a speech server, a chat bot, a wiki) or shows up with the offline fakes.
- Do not include real tokens, hostnames or personal data. Treat any secret you find in a log or file as leaked.

## Scope notes
- Credentials are never read from the repository. They come from environment variables that the owner sets.
- `compose/` talks to a speech server you run; its security is yours. Whether a speech server keeps what it transcribes is outside this code (see `docs/design.md`).
