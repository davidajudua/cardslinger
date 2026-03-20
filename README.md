# CardSlinger

**Sling cards to your team, one at a time.**

CardSlinger is a Discord bot that manages and distributes cards to your team through slash commands. Load your cards, set permissions, and let your team request what they need — with built-in safeguards, admin controls, and full activity logging.

> **Why "CardSlinger"?** It slings cards — one at a time, on demand, to whoever needs one.

---

## Use Cases

- Distributing virtual cards (VCCs) to staff for purchases
- Issuing gift cards, promo codes, or license keys to a team
- Any workflow where items need to be handed out one at a time with tracking

---

## How It Works

1. An admin loads cards into the bot (CSV upload or manual entry)
2. A team member runs `/card` and gets one card assigned to them
3. They mark the card with a button:
   - **Used** — done, card is consumed forever
   - **Not Used** — returns it to the pool (with confirmation)
   - **Error** — flags it as bad, auto-assigns a new one
4. They can't request another card until the current one is resolved

That's it. No spreadsheets, no DMs, no manual tracking.

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
| `/setadminrole @role` | Set the admin role (for admin commands + low stock pings) |
| `/setcardrole @role` | Set the role required to use `/card` |
| `/setlogchannel #channel` | Set the log channel for activity tracking |
| `/setlowstock 10` | Set the low stock warning threshold |

---

## Safeguards

- One card at a time per user — no hoarding
- Used and errored cards are **never** recycled
- "Not Used" requires a confirmation step to prevent accidents
- Buttons only work for the assigned user
- Persistent buttons survive bot restarts
- Low stock warnings ping your admin role
- Multi-server support — each server has independent settings

---

## Quick Start

### Option A: Python

```bash
git clone https://github.com/davidajudua/cardslinger.git
cd cardslinger

python3 -m venv venv
source venv/bin/activate   # macOS/Linux
# venv\Scripts\activate    # Windows

pip install -r requirements.txt

cp .env.example .env
# Edit .env and paste your Discord bot token

python bot.py
```

### Option B: Docker

```bash
git clone https://github.com/davidajudua/cardslinger.git
cd cardslinger

cp .env.example .env
# Edit .env and paste your Discord bot token

docker compose up -d
```

Auto-restarts on crash. View logs with `docker compose logs -f`.

---

## Creating a Discord Bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. **New Application** → name it → go to the **Bot** tab
3. **Reset Token** → copy it (this goes in your `.env`)
4. Enable **Server Members Intent** under Privileged Gateway Intents
5. Go to **OAuth2 → URL Generator** → select `bot` + `applications.commands`
6. Under Bot Permissions: `Send Messages`, `Embed Links`, `Use Slash Commands`, `Read Message History`
7. Open the generated URL to invite the bot to your server

---

## First-Time Setup (in Discord)

1. `/setadminrole @YourAdminRole` — who can manage the bot
2. `/setcardrole @YourTeamRole` — who can request cards
3. `/setlogchannel #logs` — where activity gets logged
4. `/loadcards` — upload a CSV to fill the pool
5. Your team can now use `/card`

---

## CSV Format

```csv
provider,card_number,exp_date,cvv,zip_code
C,5187259558019101,03/2031,698,90703
A,374512349876001,11/2029,4821,10001
M,4000123456789010,06/2028,331,30301
```

The `provider` column is freeform — it displays exactly as written. Duplicates are automatically skipped.

---

## File Structure

```
cardslinger/
├── bot.py              # The entire bot (single file)
├── cards.db            # SQLite database (auto-created)
├── requirements.txt
├── .env                # Your bot token (not committed)
├── .env.example
├── .gitignore
├── sample_cards.csv
├── Dockerfile
├── docker-compose.yml
├── LICENSE
└── README.md
```

---

## License

MIT
