# Discord Card Bot

A Discord bot that distributes disposable virtual cards (VCCs) to staff one at a time via slash commands. Built for teams that need to issue single-use cards per order — replacing manual card managers with automated, trackable distribution.

## Features

### Staff Commands
| Command | Description |
|---|---|
| `/card` | Request a card (one at a time, requires configured role) |
| `/mycard` | View your currently assigned card again |

### Admin Commands — Pool Management
| Command | Description |
|---|---|
| `/loadcards` | Bulk-load cards from a CSV file |
| `/addcard` | Manually add a single card to the pool |
| `/removecard` | Remove a specific card from the pool by card number |
| `/purgepool` | Bulk-remove available cards (with optional provider/count filters) |
| `/exportpool` | Download the current pool as a CSV file (filterable by status) |
| `/cardstatus` | View pool statistics (available / assigned / used / errors) |
| `/clearcards` | Delete all used and errored cards from the internal database |

### Admin Commands — Operations
| Command | Description |
|---|---|
| `/resetuser @user` | Force-release a user's assigned card back to the pool |
| `/toggle` | Enable or disable the card bot (blocks `/card` when off) |

### Admin Commands — Configuration
| Command | Description |
|---|---|
| `/setadminrole @role` | Set the admin role (required for all admin commands + low stock pings) |
| `/setcardrole @role` | Set the role required to use `/card` |
| `/setlogchannel #channel` | Set the admin log channel for activity tracking |
| `/setlowstock 10` | Set the low stock warning threshold |

### Card Lifecycle

1. Admin uploads a CSV (or adds cards manually) → cards enter the **available** pool
2. User runs `/card` → one card is **assigned** to them
3. User clicks a button:
   - **Used** — card is consumed (can never be reissued)
   - **Not Used** — two-step confirmation, then card returns to the available pool
   - **Error** — card is marked bad (never reused), and a new card is auto-assigned

### Safeguards

- A user cannot request a new card until their current one is resolved
- Cards marked Used or Error are **never** returned to the pool
- "Not Used" requires explicit confirmation to prevent accidental returns
- Buttons only work for the user the card was assigned to
- Persistent buttons survive bot restarts
- Low stock warnings ping the admin role when the pool runs low
- Admin can disable the bot with `/toggle` to pause all card requests
- Multi-server support — each server has its own independent settings

## Setup

### Option A: Run with Python

#### 1. Create a Discord Bot

1. Go to https://discord.com/developers/applications
2. Click **New Application** → name it → go to the **Bot** tab
3. Click **Reset Token** and copy the token
4. Under **Privileged Gateway Intents**, enable **Server Members Intent**
5. Go to **OAuth2 → URL Generator**, select scopes `bot` + `applications.commands`
6. Under Bot Permissions, select: `Send Messages`, `Embed Links`, `Use Slash Commands`, `Read Message History`
7. Copy the generated URL and open it in your browser to invite the bot to your server

#### 2. Install & Run

```bash
cd discord-card-bot

python3 -m venv venv
source venv/bin/activate   # macOS/Linux
# venv\Scripts\activate    # Windows

pip install -r requirements.txt

cp .env.example .env
# Edit .env and paste your bot token

python bot.py
```

### Option B: Run with Docker

```bash
cd discord-card-bot

cp .env.example .env
# Edit .env and paste your bot token

docker compose up -d
```

The bot runs in the background and auto-restarts if it crashes.

- View logs: `docker compose logs -f`
- Stop: `docker compose down`

### First-Time Discord Setup

1. Create a role for admins and run `/setadminrole @YourAdminRole`
2. Create a role for card access (e.g. "Card Permissions") and run `/setcardrole @CardRole`
3. Create an admin-only channel and run `/setlogchannel #card-logs`
4. Upload your cards with `/loadcards` and attach a CSV file
5. Staff can now request cards with `/card`

## CSV Format

```csv
provider,card_number,exp_date,cvv,zip_code
C,5187259558019101,03/2031,698,90703
A,374512349876001,11/2029,4821,10001
M,4000123456789010,06/2028,331,30301
```

The `provider` column can be anything — it's displayed exactly as written.

Duplicate card numbers are automatically skipped when loading.

## File Structure

```
discord-card-bot/
├── bot.py              # The bot (single file, everything included)
├── cards.db            # SQLite database (auto-created on first run)
├── requirements.txt
├── .env                # Your bot token (not committed to git)
├── .env.example
├── .gitignore
├── sample_cards.csv    # Example CSV format
├── Dockerfile
├── docker-compose.yml
├── LICENSE
└── README.md
```

## License

MIT
