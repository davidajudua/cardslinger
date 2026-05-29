# CardSlinger

**Hand out single-use cards to a team — one at a time, with tracking — instead of a shared spreadsheet.**

CardSlinger is a Discord-native distribution system for handing controlled, single-use items to a
team and knowing exactly where each one went. The canonical use case is a company issuing
**employee expense cards** for purchases, but it works for any resource that must be handed out one
at a time with an audit trail — gift cards, license keys, promo codes.

---

## The problem it solves

Distributing cards to a team by hand is slow and leaky: numbers get copied into DMs and
spreadsheets, the same card gets handed to two people, no one can say which card was used or by
whom, and there's no record when something goes wrong. CardSlinger replaces that with a single
self-serve flow where **every card has exactly one owner at a time and every state change is logged.**

## Who it's for

Admins who need to distribute cards to a team without manual tracking, and team members who just
need one card, on demand, without pinging anyone.

## How it works

1. An admin loads cards into the pool (CSV upload or manual entry).
2. A team member runs `/card` and is assigned exactly one card.
3. They resolve it with a button:
   - **Used** — consumed forever (never recycled)
   - **Not Used** — returned to the pool (requires a confirmation step)
   - **Error** — flagged as bad; a fresh card is auto-assigned
4. They can't request another card until the current one is resolved.

No spreadsheets, no DMs, no manual reconciliation.

---

## Engineering & design decisions

These are the deliberate trade-offs that make it safe to put in front of a team:

- **One card per user at a time.** Prevents hoarding and double-assignment by construction, not by
  policy — a user simply can't hold two.
- **Used/errored cards are never recycled.** Eliminates the worst failure mode (re-handing a spent card).
- **Destructive actions are guarded.** "Not Used" requires a confirmation; buttons only respond to
  the assigned user; persistent buttons survive bot restarts.
- **Everything is auditable.** Every assignment, resolution, and admin action lands in a configurable
  log channel — you can reconstruct the full history of any card.
- **Multi-tenant by default.** Each Discord server keeps independent settings, roles, and pool.
- **Operational safety nets.** Low-stock warnings ping the admin role; duplicate cards are skipped on load.

## Architecture

- **Single-file Python Discord bot** (`bot.py`) backed by **SQLite** (`cards.db`, auto-created) —
  intentionally minimal so it's trivial to read, audit, and self-host.
- **Stateless restarts:** persistent component IDs mean in-flight cards and buttons survive a redeploy.
- **Two deploy paths:** bare Python (venv) or Docker Compose with auto-restart.

---

## Commands

### Staff
| Command | Description |
|---|---|
| `/card` | Request a card (one at a time) |
| `/mycard` | View your currently assigned card |

### Admin — Pool Management
| Command | Description |
|---|---|
| `/loadcards` | Bulk-load cards from a CSV file |
| `/addcard` | Add a single card manually |
| `/removecard` | Remove a specific card by number |
| `/purgepool` | Bulk-remove available cards (with optional filters) |
| `/exportpool` | Download the pool as a CSV (filterable by status) |
| `/cardstatus` | View pool stats |
| `/clearcards` | Clear used/errored cards from the database |

### Admin — Operations
| Command | Description |
|---|---|
| `/resetuser @user` | Force-release a user's card back to the pool |
| `/toggle` | Enable or disable CardSlinger |

### Admin — Configuration
| Command | Description |
|---|---|
| `/setadminrole @role` | Set the admin role (admin commands + low-stock pings) |
| `/setcardrole @role` | Set the role required to use `/card` |
| `/setlogchannel #channel` | Set the log channel for activity tracking |
| `/setlowstock 10` | Set the low-stock warning threshold |

---

## Quick Start

### Option A: Python

```bash
git clone https://github.com/davidajudua/cardslinger.git
cd cardslinger
python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env`, replace `your-bot-token-here` with your bot token, then:

```bash
python bot.py
```

### Option B: Docker

```bash
git clone https://github.com/davidajudua/cardslinger.git
cd cardslinger
cp .env.example .env                 # add your bot token
docker compose up -d                 # auto-restarts on crash; logs: docker compose logs -f
```

---

## Creating a Discord Bot

1. [discord.com/developers/applications](https://discord.com/developers/applications) → **New Application** → **Bot** tab
2. **Reset Token** → copy it into your `.env`
3. Enable **Server Members Intent** under Privileged Gateway Intents
4. **OAuth2 → URL Generator** → select `bot` + `applications.commands`
5. Bot Permissions: `Send Messages`, `Embed Links`, `Use Slash Commands`, `Read Message History`
6. Open the generated URL to invite the bot

## First-Time Setup (in Discord)

1. `/setadminrole @YourAdminRole`
2. `/setcardrole @YourTeamRole`
3. `/setlogchannel #logs`
4. `/loadcards` — upload a CSV to fill the pool
5. Team can now use `/card`

## CSV Format

```csv
provider,card_number,exp_date,cvv,zip_code
C,5187259558019101,03/2031,698,90703
A,374512349876001,11/2029,4821,10001
M,4000123456789010,06/2028,331,30301
```

The `provider` column is freeform and displays exactly as written. Duplicates are skipped automatically.

---

## License

MIT
