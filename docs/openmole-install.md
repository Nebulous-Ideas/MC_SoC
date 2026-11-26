# Installing the review tool in OpenMOLE

Applied 2026-11-11 (see design.md decision 5 for what was learned). OpenMOLE is an Open WebUI stack (image `v0.13.2`, OIDC login, so approvers are named users). Differences from this draft: the host needed network access to the Git server over SSH and a read-only deploy key generated on the host; the compose change was applied by hand because the stack's CI deploy job was not working.

## 1. Put the code where the container can read it
On the LXC, next to the compose file:
```
git clone https://github.com/Nebulous-Ideas/MC_SoC.git /opt/mc-soc
```
Add to the `open-webui` service in `docker-compose.yml`:
```
    env_file:
      - ./admin.env
      - ./oidc.env
      - ./mcsoc.env            # new, gitignored
    environment:
      - MCSOC_PATH=/opt/mc-soc
    volumes:
      - openwebui-data:/app/backend/data
      - /opt/mc-soc:/opt/mc-soc:ro
```
`mcsoc.env` (host only, never committed; copy from a `.example` with blanks):
```
OUTLINE_URL=https://outline.example.org
OUTLINE_API_TOKEN=<a token for a dedicated Outline user limited to the "MC SOC lesson records" collection>
```
Use a dedicated Outline user with edit access to that one collection, not an admin token. Then `docker compose up -d open-webui`.

## 2. Add the tool
Admin panel, Workspace, Tools, new tool, paste `openmole_tool.py`. Set the `collection_id` valve if it differs from the default. Grant access only to the people who may review.

## 3. Check the three assumptions (the stub depends on them)
1. `__user__["name"]` is the logged-in person's name (OIDC may populate a different display name; if it is blank, `approve` correctly refuses).
2. `__event_call__` with `{"type": "confirmation", ...}` shows a dialog and returns the click.
3. The container imports the code (`MCSOC_PATH`), and `list_records` returns the three records.
Try `approve` on a throwaway record first and confirm the Outline doc's `signoff` changed, then `reject` it back.

## 4. Things to know
- The model can call `approve`, but the dialog needs a human click and the name comes from the platform, not the model.
- A pull to the local cache (`sync.py pull`) carries approvals back into `records/`.
- Updating the tool means `git pull` in `/opt/mc-soc`; the pasted tool file only changes if `openmole_tool.py` does.
