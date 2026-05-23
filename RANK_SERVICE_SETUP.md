# Roblox Rank Service Setup

This repo now includes a standalone HTTP rank service in `roblox_rank_service.py`.

## 1) Deploy the rank service
Deploy this file as a separate service/process.

Start command:

```bash
python roblox_rank_service.py
```

## 2) Set environment variables on the rank service

- `ROBLOX_SERVICE_SECRET` = shared secret used by your Discord bot.
- `ROBLOX_OPENCLOUD_API_KEY` = Roblox Open Cloud API key with permissions to list group roles and assign member roles.
- `ROBLOX_GROUP_ID` = your group id (defaults to `34438615`).
- `PORT` = service port (default `8080`).

## 3) Set environment variables on the Discord bot

- `ROBLOX_SERVICE_BASE` = base URL of deployed rank service (example: `https://your-rank-service.up.railway.app`)
- `ROBLOX_SERVICE_SECRET` = exact same secret as service.

## 4) Test endpoints

```bash
curl -H "X-Secret-Key: $ROBLOX_SERVICE_SECRET" "$ROBLOX_SERVICE_BASE/health"
curl -H "X-Secret-Key: $ROBLOX_SERVICE_SECRET" "$ROBLOX_SERVICE_BASE/ranks"
```

Set rank (replace ids):

```bash
curl -X POST "$ROBLOX_SERVICE_BASE/set-rank" \
  -H "X-Secret-Key: $ROBLOX_SERVICE_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"robloxId":123456,"groupId":34438615,"roleId":9876543}'
```
