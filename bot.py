from __future__ import annotations

import csv
import io
import os
import sqlite3
import traceback
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE = "cards.db"
DEFAULT_ROLE_NAME = "Card Permissions"
DEFAULT_LOW_STOCK = 10


# ── Database ───────────────────────────────────────────────────────────────────


@contextmanager
def db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                card_number TEXT NOT NULL,
                exp_date TEXT NOT NULL,
                cvv TEXT NOT NULL,
                zip_code TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'available',
                assigned_to INTEGER,
                assigned_at TEXT,
                message_id INTEGER,
                channel_id INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS card_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL,
                user_id INTEGER,
                action TEXT NOT NULL,
                timestamp TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (card_id) REFERENCES cards(id)
            );
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (guild_id, key)
            );
            CREATE INDEX IF NOT EXISTS idx_cards_status ON cards(status);
            CREATE INDEX IF NOT EXISTS idx_cards_assigned_to ON cards(assigned_to);
        """)
        conn.commit()


# ── Settings ───────────────────────────────────────────────────────────────────


def get_setting(guild_id: int, key: str) -> Optional[str]:
    with db() as conn:
        row = conn.execute(
            "SELECT value FROM guild_settings WHERE guild_id = ? AND key = ?",
            (guild_id, key),
        ).fetchone()
        return row["value"] if row else None


def set_setting(guild_id: int, key: str, value: str):
    with db() as conn:
        conn.execute(
            "INSERT INTO guild_settings (guild_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, key) DO UPDATE SET value = ?",
            (guild_id, key, value, value),
        )
        conn.commit()


# ── Permission Checks ──────────────────────────────────────────────────────────


def has_role(member: discord.Member, setting_key: str, fallback=None) -> bool:
    role_id = get_setting(member.guild.id, setting_key)
    if role_id:
        return any(r.id == int(role_id) for r in member.roles)
    if fallback == "role_name":
        return any(r.name == DEFAULT_ROLE_NAME for r in member.roles)
    if fallback == "admin_perm":
        return member.guild_permissions.administrator
    return False


def has_card_permission(member: discord.Member) -> bool:
    return has_role(member, "card_role_id", fallback="role_name")


def is_admin(member: discord.Member) -> bool:
    return has_role(member, "admin_role_id", fallback="admin_perm")


# ── Card Operations ────────────────────────────────────────────────────────────


def get_card(card_id: int):
    with db() as conn:
        return conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()


def get_assigned_card(user_id: int):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM cards WHERE assigned_to = ? AND status = 'assigned'",
            (user_id,),
        ).fetchone()


def assign_card(user_id: int):
    with db() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """UPDATE cards SET status = 'assigned', assigned_to = ?, assigned_at = datetime('now')
                   WHERE id = (SELECT id FROM cards WHERE status = 'available' ORDER BY id LIMIT 1)""",
                (user_id,),
            )
            card = conn.execute(
                "SELECT * FROM cards WHERE assigned_to = ? AND status = 'assigned' "
                "ORDER BY assigned_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            if not card:
                conn.rollback()
                return None
            conn.execute(
                "INSERT INTO card_log (card_id, user_id, action) VALUES (?, ?, 'assigned')",
                (card["id"], user_id),
            )
            conn.commit()
            return card
        except Exception:
            conn.rollback()
            raise


def mark_card(card_id: int, user_id: int, status: str):
    """Update a card's status. 'available' returns it to the pool; anything else is a terminal/assigned state."""
    with db() as conn:
        if status == "available":
            conn.execute(
                """UPDATE cards SET status = 'available', assigned_to = NULL, assigned_at = NULL,
                   message_id = NULL, channel_id = NULL WHERE id = ? AND assigned_to = ?""",
                (card_id, user_id),
            )
            action = "returned"
        else:
            conn.execute(
                "UPDATE cards SET status = ? WHERE id = ? AND assigned_to = ?",
                (status, card_id, user_id),
            )
            action = status
        conn.execute(
            "INSERT INTO card_log (card_id, user_id, action) VALUES (?, ?, ?)",
            (card_id, user_id, action),
        )
        conn.commit()


def force_release(user_id: int) -> bool:
    with db() as conn:
        card = conn.execute(
            "SELECT id FROM cards WHERE assigned_to = ? AND status = 'assigned'",
            (user_id,),
        ).fetchone()
        if not card:
            return False
        conn.execute(
            """UPDATE cards SET status = 'available', assigned_to = NULL, assigned_at = NULL,
               message_id = NULL, channel_id = NULL WHERE id = ?""",
            (card["id"],),
        )
        conn.execute(
            "INSERT INTO card_log (card_id, user_id, action) VALUES (?, ?, 'force_released')",
            (card["id"], user_id),
        )
        conn.commit()
        return True


def save_message(card_id: int, message_id: int, channel_id: int):
    with db() as conn:
        conn.execute(
            "UPDATE cards SET message_id = ?, channel_id = ? WHERE id = ?",
            (message_id, channel_id, card_id),
        )
        conn.commit()


def export_pool_csv(status_filter: Optional[str] = None) -> tuple[str, int]:
    """Export cards as CSV content. Returns (csv_string, row_count)."""
    with db() as conn:
        if status_filter:
            rows = conn.execute(
                "SELECT provider, card_number, exp_date, cvv, zip_code, status FROM cards WHERE status = ? ORDER BY id",
                (status_filter,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT provider, card_number, exp_date, cvv, zip_code, status FROM cards ORDER BY id"
            ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["provider", "card_number", "exp_date", "cvv", "zip_code", "status"])
    for row in rows:
        writer.writerow([row["provider"], row["card_number"], row["exp_date"], row["cvv"], row["zip_code"], row["status"]])

    return output.getvalue(), len(rows)


def pool_stats() -> dict:
    with db() as conn:
        return {
            s: conn.execute("SELECT COUNT(*) FROM cards WHERE status = ?", (s,)).fetchone()[0]
            for s in ("available", "assigned", "used", "error")
        }


def clear_completed_cards() -> int:
    """Delete all used and errored cards. Returns number of rows removed."""
    with db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE status IN ('used', 'error')"
        ).fetchone()[0]
        conn.execute("DELETE FROM cards WHERE status IN ('used', 'error')")
        conn.commit()
    return count


def add_single_card(provider: str, card_number: str, exp_date: str, cvv: str, zip_code: str) -> bool:
    """Add a single card. Returns False if the card number already exists."""
    with db() as conn:
        if conn.execute("SELECT 1 FROM cards WHERE card_number = ?", (card_number,)).fetchone():
            return False
        conn.execute(
            "INSERT INTO cards (provider, card_number, exp_date, cvv, zip_code) VALUES (?, ?, ?, ?, ?)",
            (provider, card_number, exp_date, cvv, zip_code),
        )
        conn.commit()
    return True


def remove_single_card(card_number: str) -> bool:
    """Remove a single available card by its number. Returns False if not found or not available."""
    with db() as conn:
        result = conn.execute(
            "DELETE FROM cards WHERE card_number = ? AND status = 'available'", (card_number,)
        )
        conn.commit()
    return result.rowcount > 0


def purge_available(provider: Optional[str] = None, count: Optional[int] = None) -> int:
    """Remove available cards from the pool. Returns number removed."""
    with db() as conn:
        where = "status = 'available'"
        params = []
        if provider:
            where += " AND provider = ?"
            params.append(provider)

        if count:
            ids = conn.execute(
                f"SELECT id FROM cards WHERE {where} ORDER BY id LIMIT ?", params + [count]
            ).fetchall()
            if not ids:
                return 0
            id_list = [r["id"] for r in ids]
            placeholders = ",".join("?" * len(id_list))
            conn.execute(f"DELETE FROM cards WHERE id IN ({placeholders})", id_list)
        else:
            conn.execute(f"DELETE FROM cards WHERE {where}", params)

        conn.commit()
        return conn.total_changes


def is_bot_enabled(guild_id: int) -> bool:
    value = get_setting(guild_id, "bot_enabled")
    return value != "0"


def load_csv(content: str) -> tuple[int, int, int]:
    with db() as conn:
        reader = csv.DictReader(io.StringIO(content))
        added, dupes, errors = 0, 0, 0

        for row in reader:
            try:
                n = {k.strip().lower().replace(" ", "_"): v.strip() for k, v in row.items()}
                fields = [n.get(f, "") for f in ("provider", "card_number", "exp_date", "cvv", "zip_code")]

                if not all(fields):
                    errors += 1
                    continue
                if conn.execute("SELECT 1 FROM cards WHERE card_number = ?", (fields[1],)).fetchone():
                    dupes += 1
                    continue

                conn.execute(
                    "INSERT INTO cards (provider, card_number, exp_date, cvv, zip_code) VALUES (?, ?, ?, ?, ?)",
                    fields,
                )
                added += 1
            except Exception:
                errors += 1

        conn.commit()
    return added, dupes, errors


# ── Helpers ────────────────────────────────────────────────────────────────────


def mask_card(number: str) -> str:
    return f"•••• {number[-4:]}" if len(number) >= 4 else number


def build_card_embed(card, user: Optional[discord.Member] = None) -> discord.Embed:
    embed = discord.Embed(title="💳 Card Details", color=discord.Color.dark_embed())
    for label, key in [("Provider", "provider"), ("Card Number", "card_number"),
                        ("Exp Date", "exp_date"), ("CVV", "cvv"), ("Zip Code", "zip_code")]:
        embed.add_field(name=label, value=f"```{card[key]}```", inline=False)
    if user:
        embed.set_footer(text=f"Assigned to {user.display_name}")
    return embed


async def send_log(guild: discord.Guild, *, title: str, description: str,
                   color: discord.Color = discord.Color.greyple(),
                   fields: Optional[list] = None):
    channel_id = get_setting(guild.id, "log_channel_id")
    if not channel_id:
        return
    channel = guild.get_channel(int(channel_id))
    if not channel:
        return

    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now())
    for name, value in (fields or []):
        embed.add_field(name=name, value=value, inline=True)

    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        pass


async def check_low_stock(guild: discord.Guild):
    stats = pool_stats()
    available = stats["available"]
    raw = get_setting(guild.id, "low_stock_threshold")
    threshold = int(raw) if raw else DEFAULT_LOW_STOCK

    if available > threshold:
        return

    admin_role_id = get_setting(guild.id, "admin_role_id")
    ping = f"<@&{admin_role_id}> " if admin_role_id else ""

    if available == 0:
        msg = f"{ping}**The card pool is completely empty.** Load more cards with `/loadcards`."
    else:
        msg = f"{ping}Only **{available}** card(s) remaining (threshold: {threshold})."

    await send_log(guild, title="⚠️ Low Card Stock", description=msg,
                   color=discord.Color.gold(), fields=[("Available", str(available))])


def _card_log_fields(card, user: discord.Member) -> tuple[str, list[tuple[str, str]]]:
    """Build a standardized log description snippet and field list for a card event."""
    desc = f"`{mask_card(card['card_number'])}` ({card['provider']})"
    fields = [("Card ID", str(card["id"])), ("User", user.display_name)]
    return desc, fields


# ── Bot Setup ──────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ── Views (Buttons) ───────────────────────────────────────────────────────────


class CardView(discord.ui.View):
    def __init__(self, card_id: int):
        super().__init__(timeout=None)
        self.card_id = card_id

        for label, style, custom_id, emoji, callback in [
            ("Used", discord.ButtonStyle.success, f"card_used:{card_id}", "✅", self.on_used),
            ("Not Used", discord.ButtonStyle.secondary, f"card_notused:{card_id}", "⚪", self.on_not_used),
            ("Error", discord.ButtonStyle.danger, f"card_error:{card_id}", "❌", self.on_error),
        ]:
            btn = discord.ui.Button(label=label, style=style, custom_id=custom_id, emoji=emoji)
            btn.callback = callback
            self.add_item(btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        card = get_card(self.card_id)
        if card is None or card["assigned_to"] != interaction.user.id:
            await interaction.response.send_message("⛔ This card isn't assigned to you.", ephemeral=True)
            return False
        if card["status"] != "assigned":
            await interaction.response.send_message("⚠️ This card has already been processed.", ephemeral=True)
            return False
        return True

    async def _resolve(self, interaction: discord.Interaction, status: str,
                       color: discord.Color, footer: str) -> sqlite3.Row:
        """Common handler: update DB, edit embed, disable buttons. Returns the card row."""
        card = get_card(self.card_id)
        mark_card(self.card_id, interaction.user.id, status)

        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if embed:
            embed.color = color
            embed.set_footer(text=f"{footer} by {interaction.user.display_name}")
        self._disable_all()
        await interaction.response.edit_message(embed=embed, view=self)
        return card

    async def on_used(self, interaction: discord.Interaction):
        card = await self._resolve(interaction, "used", discord.Color.green(), "✅ Marked as Used")
        desc, fields = _card_log_fields(card, interaction.user)
        await send_log(interaction.guild, title="✅ Card Marked as Used",
                       description=f"**{interaction.user.mention}** used card {desc}",
                       color=discord.Color.green(), fields=fields)

    async def on_not_used(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "⚠️ **Are you sure you have NOT used this card?**\n"
            "Returning it will make it available to others. Only confirm if you are "
            "**100% certain** the card was **not charged in any way**.",
            view=ConfirmReturnView(self.card_id, interaction.message),
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction):
        card = await self._resolve(interaction, "error", discord.Color.red(), "❌ Card Error — reported")
        desc, fields = _card_log_fields(card, interaction.user)
        await send_log(interaction.guild, title="❌ Card Error Reported",
                       description=f"**{interaction.user.mention}** reported card {desc} as errored",
                       color=discord.Color.red(), fields=fields)

        # Auto-assign replacement
        new_card = assign_card(interaction.user.id)
        if new_card:
            new_view = CardView(new_card["id"])
            msg = await interaction.channel.send(
                content=f"🔄 Previous card errored. Here's a new card for {interaction.user.mention}:",
                embed=build_card_embed(new_card, interaction.user), view=new_view,
            )
            save_message(new_card["id"], msg.id, msg.channel.id)
            new_desc, new_fields = _card_log_fields(new_card, interaction.user)
            await send_log(interaction.guild, title="🔄 Replacement Card Issued",
                           description=f"**{interaction.user.mention}** auto-assigned card {new_desc} after error",
                           color=discord.Color.orange(), fields=new_fields)
            await check_low_stock(interaction.guild)
        else:
            await interaction.channel.send(
                "🔄 Previous card errored, but **cards are currently out of stock.**\n"
                f"⏳ Wait for management to refill. {interaction.user.mention}"
            )
            await send_log(interaction.guild, title="📭 Out of Stock After Error",
                           description=f"**{interaction.user.mention}** needed a replacement but the pool is empty",
                           color=discord.Color.dark_red())

    def _disable_all(self):
        for item in self.children:
            item.disabled = True


class ConfirmReturnView(discord.ui.View):
    def __init__(self, card_id: int, original_message: discord.Message):
        super().__init__(timeout=30)
        self.card_id = card_id
        self.original_message = original_message

    @discord.ui.button(label="Yes, I have NOT used it — return card", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        card = get_card(self.card_id)
        mark_card(self.card_id, interaction.user.id, "available")

        embed = self.original_message.embeds[0] if self.original_message.embeds else None
        if embed:
            embed.color = discord.Color.light_grey()
            embed.set_footer(text=f"↩️ Returned to pool by {interaction.user.display_name}")

        disabled_view = CardView(self.card_id)
        disabled_view._disable_all()
        try:
            await self.original_message.edit(embed=embed, view=disabled_view)
        except discord.NotFound:
            pass

        await interaction.response.edit_message(
            content="✅ Card returned to the pool. You can request a new one with `/card`.", view=None,
        )

        if card and interaction.guild:
            desc, fields = _card_log_fields(card, interaction.user)
            await send_log(interaction.guild, title="↩️ Card Returned to Pool",
                           description=f"**{interaction.user.mention}** returned card {desc} — Not Used",
                           color=discord.Color.light_grey(), fields=fields)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Cancelled — the card is still assigned to you.", view=None)
        self.stop()


class ConfirmPurgeView(discord.ui.View):
    def __init__(self, provider: Optional[str], count: Optional[int]):
        super().__init__(timeout=30)
        self.provider = provider
        self.count = count

    @discord.ui.button(label="Yes, purge all available cards", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        removed = purge_available(self.provider, self.count)
        stats = pool_stats()
        await interaction.response.edit_message(
            content=f"🗑️ Removed **{removed}** available cards from the pool.\n"
                    f"📊 **Pool now:** {stats['available']} available · {stats['assigned']} assigned",
            view=None)
        await send_log(interaction.guild, title="🗑️ Pool Purged",
                       description=f"**{interaction.user.mention}** purged **{removed}** available cards from the pool",
                       color=discord.Color.orange(),
                       fields=[("Removed", str(removed)), ("Remaining", str(stats["available"]))])
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Cancelled — pool unchanged.", view=None)
        self.stop()


# ── Slash Commands — Staff ─────────────────────────────────────────────────────


@bot.tree.command(name="card", description="Request a virtual card for your order")
async def cmd_card(interaction: discord.Interaction):
    if not is_bot_enabled(interaction.guild.id):
        await interaction.response.send_message(
            "🔴 The card bot is currently **disabled**. Contact management.", ephemeral=True)
        return
    if not has_card_permission(interaction.user):
        await interaction.response.send_message(
            "⛔ You need the **Card Permissions** role to use this command.", ephemeral=True)
        return

    if get_assigned_card(interaction.user.id):
        await interaction.response.send_message(
            "⚠️ You already have a card assigned. Mark it as **Used**, **Not Used**, "
            "or **Error** before requesting a new one.", ephemeral=True)
        return

    card = assign_card(interaction.user.id)
    if not card:
        await interaction.response.send_message(
            "📭 **Cards are currently out of stock.**\n⏳ Wait for management to refill.")
        await send_log(interaction.guild, title="📭 Card Request — Out of Stock",
                       description=f"**{interaction.user.mention}** requested a card but the pool is empty",
                       color=discord.Color.dark_red())
        return

    await interaction.response.send_message(embed=build_card_embed(card, interaction.user), view=CardView(card["id"]))
    msg = await interaction.original_response()
    save_message(card["id"], msg.id, msg.channel.id)

    desc, fields = _card_log_fields(card, interaction.user)
    await send_log(interaction.guild, title="💳 Card Assigned",
                   description=f"**{interaction.user.mention}** was assigned card {desc}",
                   color=discord.Color.blue(), fields=fields)
    await check_low_stock(interaction.guild)


@bot.tree.command(name="mycard", description="View your currently assigned card")
async def cmd_mycard(interaction: discord.Interaction):
    if not is_bot_enabled(interaction.guild.id):
        await interaction.response.send_message(
            "🔴 The card bot is currently **disabled**. Contact management.", ephemeral=True)
        return
    card = get_assigned_card(interaction.user.id)
    if not card:
        await interaction.response.send_message(
            "ℹ️ You don't have a card assigned. Use `/card` to request one.", ephemeral=True)
        return
    await interaction.response.send_message(embed=build_card_embed(card, interaction.user), ephemeral=True)


# ── Slash Commands — Admin ─────────────────────────────────────────────────────


@bot.tree.command(name="addcard", description="[Admin] Add a single card to the pool")
@app_commands.describe(
    provider="Card provider (e.g. M, C, A, or any text)",
    card_number="Full card number",
    exp_date="Expiration date (e.g. 03/2031)",
    cvv="CVV code",
    zip_code="Billing zip code",
)
async def cmd_addcard(interaction: discord.Interaction, provider: str,
                      card_number: str, exp_date: str, cvv: str, zip_code: str):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Admin only.", ephemeral=True)
        return

    if add_single_card(provider.strip(), card_number.strip(), exp_date.strip(), cvv.strip(), zip_code.strip()):
        await interaction.response.send_message(
            f"✅ Card `{mask_card(card_number)}` added to the pool.", ephemeral=True)
        await send_log(interaction.guild, title="➕ Card Added",
                       description=f"**{interaction.user.mention}** manually added card `{mask_card(card_number)}` ({provider})",
                       color=discord.Color.teal())
    else:
        await interaction.response.send_message(
            f"⚠️ Card `{mask_card(card_number)}` already exists in the database.", ephemeral=True)


@bot.tree.command(name="removecard", description="[Admin] Remove a single card from the available pool")
@app_commands.describe(card_number="The full card number to remove")
async def cmd_removecard(interaction: discord.Interaction, card_number: str):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Admin only.", ephemeral=True)
        return

    if remove_single_card(card_number.strip()):
        await interaction.response.send_message(
            f"✅ Card `{mask_card(card_number)}` removed from the pool.", ephemeral=True)
        await send_log(interaction.guild, title="➖ Card Removed",
                       description=f"**{interaction.user.mention}** removed card `{mask_card(card_number)}` from the pool",
                       color=discord.Color.orange())
    else:
        await interaction.response.send_message(
            f"⚠️ Card not found or not available. Only cards with **available** status can be removed.", ephemeral=True)


@bot.tree.command(name="purgepool", description="[Admin] Bulk-remove available cards from the pool")
@app_commands.describe(
    provider="Only remove cards from this provider (optional)",
    count="Maximum number of cards to remove (optional, omit to remove all matching)",
)
async def cmd_purgepool(interaction: discord.Interaction, provider: Optional[str] = None, count: Optional[int] = None):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Admin only.", ephemeral=True)
        return

    if count is not None and count <= 0:
        await interaction.response.send_message("⚠️ Count must be a positive number.", ephemeral=True)
        return

    # No filters = destructive, require confirmation
    if not provider and not count:
        await interaction.response.send_message(
            "⚠️ **This will remove ALL available cards from the pool.** Are you sure?",
            view=ConfirmPurgeView(provider, count), ephemeral=True)
        return

    removed = purge_available(provider, count)
    stats = pool_stats()

    if provider and count:
        target = f"up to **{count}** available **{provider}** cards"
    elif provider:
        target = f"all available **{provider}** cards"
    else:
        target = f"up to **{count}** available cards"

    await interaction.response.send_message(
        f"🗑️ Removed **{removed}** {target} from the pool.\n"
        f"📊 **Pool now:** {stats['available']} available · {stats['assigned']} assigned",
        ephemeral=True)
    await send_log(interaction.guild, title="🗑️ Pool Purged",
                   description=f"**{interaction.user.mention}** removed **{removed}** cards from the pool",
                   color=discord.Color.orange(),
                   fields=[("Removed", str(removed)), ("Provider", provider or "All"),
                           ("Remaining", str(stats["available"]))])


@bot.tree.command(name="loadcards", description="[Admin] Bulk-load cards from a CSV file")
@app_commands.describe(file="CSV with columns: provider, card_number, exp_date, cvv, zip_code")
async def cmd_loadcards(interaction: discord.Interaction, file: discord.Attachment):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Admin only.", ephemeral=True)
        return
    if not file.filename.endswith(".csv"):
        await interaction.response.send_message("⚠️ Please upload a `.csv` file.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    content = (await file.read()).decode("utf-8")
    added, dupes, errors = load_csv(content)
    stats = pool_stats()

    await interaction.followup.send(
        f"📥 **Cards Loaded**\n"
        f"✅ Added: **{added}**\n"
        f"⏭️ Duplicates skipped: **{dupes}**\n"
        f"❌ Errors: **{errors}**\n\n"
        f"📊 **Pool:** {stats['available']} available · {stats['assigned']} assigned · {stats['used']} used",
        ephemeral=True)

    await send_log(interaction.guild, title="📥 Cards Loaded",
                   description=f"**{interaction.user.mention}** loaded cards from `{file.filename}`",
                   color=discord.Color.teal(),
                   fields=[("Added", str(added)), ("Duplicates", str(dupes)),
                           ("Errors", str(errors)), ("Pool Available", str(stats["available"]))])


@bot.tree.command(name="cardstatus", description="[Admin] View card pool statistics")
async def cmd_cardstatus(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Admin only.", ephemeral=True)
        return

    stats = pool_stats()
    total = sum(stats.values())

    embed = discord.Embed(title="📊 Card Pool Status", color=discord.Color.blue())
    for label, key in [("Available", "available"), ("Assigned", "assigned"),
                        ("Used", "used"), ("Errors", "error"), ("Total", None)]:
        embed.add_field(name=label, value=f"```{stats[key] if key else total}```", inline=True)
    embed.set_footer(text=f"Last checked · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="exportpool", description="[Admin] Download the current card pool as a CSV file")
@app_commands.describe(status="Filter by status: available, assigned, used, error (omit for all)")
@app_commands.choices(status=[
    app_commands.Choice(name="All cards", value="all"),
    app_commands.Choice(name="Available", value="available"),
    app_commands.Choice(name="Assigned", value="assigned"),
    app_commands.Choice(name="Used", value="used"),
    app_commands.Choice(name="Error", value="error"),
])
async def cmd_exportpool(interaction: discord.Interaction, status: Optional[str] = None):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Admin only.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    filter_val = None if (status is None or status == "all") else status
    csv_content, count = export_pool_csv(filter_val)

    if count == 0:
        await interaction.followup.send("ℹ️ No cards found matching that filter.", ephemeral=True)
        return

    label = status or "all"
    filename = f"cards_{label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    file = discord.File(fp=io.BytesIO(csv_content.encode()), filename=filename)

    await interaction.followup.send(
        f"📤 **{count}** card(s) exported — `{filename}`", file=file, ephemeral=True)


@bot.tree.command(name="resetuser", description="[Admin] Force-release a user's assigned card")
@app_commands.describe(user="The user whose card should be released")
async def cmd_resetuser(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Admin only.", ephemeral=True)
        return

    if force_release(user.id):
        await interaction.response.send_message(
            f"✅ Released {user.mention}'s card back to the pool.", ephemeral=True)
        await send_log(interaction.guild, title="🔓 User Card Force-Released",
                       description=f"**{interaction.user.mention}** force-released **{user.mention}**'s card",
                       color=discord.Color.yellow(),
                       fields=[("Admin", interaction.user.display_name), ("Target", user.display_name)])
    else:
        await interaction.response.send_message(
            f"ℹ️ {user.mention} doesn't have any assigned cards.", ephemeral=True)


# ── Slash Commands — Setup ─────────────────────────────────────────────────────


@bot.tree.command(name="setadminrole", description="[Owner] Set the admin role for bot management")
@app_commands.describe(role="The role that grants access to admin commands")
async def cmd_setadminrole(interaction: discord.Interaction, role: discord.Role):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "⛔ Only server administrators can set the admin role.", ephemeral=True)
        return

    set_setting(interaction.guild.id, "admin_role_id", str(role.id))
    await interaction.response.send_message(
        f"✅ Admin role set to **{role.name}**. Members with this role can manage the bot "
        f"and will be pinged for low stock warnings.", ephemeral=True)
    await send_log(interaction.guild, title="🛡️ Admin Role Updated",
                   description=f"**{interaction.user.mention}** set the admin role to **{role.name}**",
                   color=discord.Color.teal())


@bot.tree.command(name="setcardrole", description="[Admin] Set the role required to use /card")
@app_commands.describe(role="The role that grants access to /card")
async def cmd_setcardrole(interaction: discord.Interaction, role: discord.Role):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Admin only.", ephemeral=True)
        return

    set_setting(interaction.guild.id, "card_role_id", str(role.id))
    await interaction.response.send_message(
        f"✅ Card role set to **{role.name}**. Only members with this role can use `/card`.", ephemeral=True)
    await send_log(interaction.guild, title="🔑 Card Role Updated",
                   description=f"**{interaction.user.mention}** set the card role to **{role.name}**",
                   color=discord.Color.teal())


@bot.tree.command(name="setlogchannel", description="[Admin] Set the log channel for card activity")
@app_commands.describe(channel="The channel to send logs to")
async def cmd_setlogchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Admin only.", ephemeral=True)
        return

    set_setting(interaction.guild.id, "log_channel_id", str(channel.id))
    await interaction.response.send_message(
        f"✅ Log channel set to {channel.mention}.", ephemeral=True)
    await send_log(interaction.guild, title="📋 Log Channel Configured",
                   description=f"**{interaction.user.mention}** set this channel as the card activity log",
                   color=discord.Color.teal())


@bot.tree.command(name="setlowstock", description="[Admin] Set the low stock warning threshold")
@app_commands.describe(threshold="Warn when available cards drop to this number (default: 10)")
async def cmd_setlowstock(interaction: discord.Interaction, threshold: int):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Admin only.", ephemeral=True)
        return
    if threshold < 0:
        await interaction.response.send_message("⚠️ Threshold must be 0 or higher.", ephemeral=True)
        return

    set_setting(interaction.guild.id, "low_stock_threshold", str(threshold))
    await interaction.response.send_message(
        f"✅ Low stock warning set to **{threshold}** cards.", ephemeral=True)


@bot.tree.command(name="toggle", description="[Admin] Enable or disable the card bot")
async def cmd_toggle(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Admin only.", ephemeral=True)
        return

    enabling = not is_bot_enabled(interaction.guild.id)
    set_setting(interaction.guild.id, "bot_enabled", "1" if enabling else "0")

    state_str = "enabled" if enabling else "disabled"
    icon = "🟢" if enabling else "🔴"
    color = discord.Color.green() if enabling else discord.Color.red()

    await interaction.response.send_message(
        f"{icon} Card bot is now **{state_str}**.", ephemeral=True)
    await send_log(interaction.guild, title=f"{icon} Bot {state_str.capitalize()}",
                   description=f"**{interaction.user.mention}** {state_str} the card bot",
                   color=color)


@bot.tree.command(name="clearcards", description="[Admin] Delete all used and errored cards from the database")
async def cmd_clearcards(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Admin only.", ephemeral=True)
        return

    removed = clear_completed_cards()
    stats = pool_stats()
    await interaction.response.send_message(
        f"🗑️ Cleared **{removed}** used/errored card(s) from the database.\n"
        f"📊 **Pool now:** {stats['available']} available · {stats['assigned']} assigned",
        ephemeral=True)
    await send_log(interaction.guild, title="🗑️ Cards Cleared (Internal Database)",
                   description=(
                       f"**{interaction.user.mention}** cleared **{removed}** used/errored cards "
                       f"from the internal database.\n"
                       f"⚠️ No changes were made to any external card provider."
                   ),
                   color=discord.Color.orange(),
                   fields=[("Removed", str(removed)), ("Available", str(stats["available"]))])


# ── Error Handler ──────────────────────────────────────────────────────────────


@bot.tree.error
async def on_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"⏳ Slow down — try again in {error.retry_after:.0f}s.", ephemeral=True)
        return

    traceback.print_exception(type(error), error, error.__traceback__)
    msg = "❌ Something went wrong. Please try again or contact an admin."
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


# ── Events ─────────────────────────────────────────────────────────────────────


@bot.event
async def on_ready():
    with db() as conn:
        assigned = conn.execute("SELECT id FROM cards WHERE status = 'assigned'").fetchall()

    for row in assigned:
        bot.add_view(CardView(row["id"]))

    await bot.tree.sync()
    print(f"Logged in as {bot.user}  |  {len(assigned)} persistent view(s) restored")


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    if not TOKEN:
        print("ERROR: Set DISCORD_TOKEN in your .env file or environment.")
        raise SystemExit(1)
    bot.run(TOKEN)
