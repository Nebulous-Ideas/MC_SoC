# Signing off a derived work

A derived work (`works/<id>.json`) is content made from approved lessons. It cannot be approved or published
until a named person signs it off (decision 23). Only a person can do this; a model, a bot or a process name
is refused.

## Before you approve

- The work's `redaction.status` must be `passed`. A pending redaction is refused.
- Every lesson in `lesson_ids` must exist and already be approved.
- `python3 verify.py --all` must report no errors.

## Approve one work

Run this in a terminal, with your own name:

```bash
python3 review.py show <work-id> --works
python3 review.py approve <work-id> --works --as "Your Name"
```

`show` prints the work and its status without changing anything. `approve` shows the text again and asks
`[y/N]`. Only `y` writes the sign-off. Set `MCSOC_APPROVERS` (comma-separated names) to limit who may approve.

The record then holds your name, the channel, and the time. Commit the change to the work file on a branch
and open a pull request, the same as any other change.

## Practice without touching a real work

`works/practice-sign-off.json` is a copy for trying the flow. Its status is `draft` and it is not a song.

```bash
python3 review.py show practice-sign-off --works
python3 review.py approve practice-sign-off --works --as "Your Name"
```

Practice approvals are for learning only. Do not commit a practice approval to `main`. To reset the practice work,
restore it from git:

```bash
git checkout -- works/practice-sign-off.json
```

## Do not

- Approve with a placeholder name, a process name or a model's name. The approval is then recorded as a person's.
- Edit the `signoff` block by hand. The review routine is the only write path.
