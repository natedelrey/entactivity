"""
Engineering and Technical Service Operations Bot
- Discord slash commands
- Roblox verification
- Roblox activity webhooks
- Weekly activity reporting
- Strike management
- Roblox rank service integration

Designed for Railway + PostgreSQL.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp
import asyncpg
import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

UTC = dt.timezone.utc


# ============================================================
# Config helpers
# ============================================================

def getenv_str(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip()


def getenv_int(name: str, default: int | None = None) -> int | None:
    value = getenv_str(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        print(f"[CONFIG] {name} must be an integer. Using default: {default}")
        return default


def getenv_bool(name: str, default: bool = False) -> bool:
    value = getenv_str(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}


def getenv_color(name: str, default_hex: str = "2A3825") -> discord.Color:
    raw = getenv_str(name, default_hex) or default_hex
    raw = raw.strip().replace("#", "")
    try:
        return discord.Color(int(raw, 16))
    except ValueError:
        print(f"[CONFIG] Invalid color {name}={raw}. Using #{default_hex}.")
        return discord.Color(int(default_hex, 16))


def utcnow() -> dt.datetime:
    return dt.datetime.now(UTC)


def fmt_minutes(minutes: int) -> str:
    minutes = max(0, int(minutes))
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def week_key(date: dt.datetime | None = None) -> str:
    d = date or utcnow()
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def normalize_base_url(url: str | None) -> str | None:
    if not url:
        return None
    clean = url.strip().rstrip("/")
    if not clean.startswith(("http://", "https://")):
        clean = "https://" + clean
    return clean


LEGACY_WELCOME_TITLE = "Welcome to Engineering and Technical Service"
WELCOME_TITLE_DEFAULT = "Welcome to Engineering & Technical Service"
WELCOME_DEPARTMENT_DISPLAY_DEFAULT = "Engineering & Technical Service"
WELCOME_GUIDELINES_CHANNEL_DEFAULT = "<#1520160137132773376>"
WELCOME_INTERNSHIP_URL_DEFAULT = "https://trello.com/c/NqgrPAJF/6-internship-program"
LEGACY_WELCOME_MESSAGE = (
    "Welcome {member} to Engineering and Technical Service (E&T)! Please verify with `/verify`, "
    "review the department information, and stay active on-site.\n\n{description}\n\nGroup: {group_url}"
)
WELCOME_MESSAGE_DEFAULT = (
    "Welcome, {member}, to **{welcome_department}!** ({abbreviation})\n\n"
    "We’re glad to have you join the department. Before getting started, please make sure you complete the following:\n\n"
    "**1. Run `/verify` with this bot.**\n\n"
    "This is required so your activity, logs, and department progress can be properly tracked.\n\n"
    "**2. Read the Department Guidelines**\n"
    "Please review our full guidelines which can be found in {guidelines_channel}. These explain department expectations, logging rules, task validity, conduct, and other important information you are expected to follow.\n\n"
    "**3. Complete the Internship Program**\n"
    "All new members begin as **Trainee Technicians** and are required to complete the [Internship Program]({internship_url}) within **2 weeks** of joining.\n\n"
    "The Internship Program card contains the full requirements, expectations, and information needed to rank up to **Junior Technician** and become a full member of the department.\n\n"
    "Please read everything carefully, ask management if you have any questions, and good luck in {abbreviation}!"
)


def getenv_upgraded(name: str, default: str, legacy_value: str | None = None) -> str:
    value = getenv_str(name)
    if value is None or value == legacy_value:
        return default
    return value


@dataclass(frozen=True)
class BotConfig:
    # Core
    bot_token: str | None = getenv_str("BOT_TOKEN")
    database_url: str | None = getenv_str("DATABASE_URL")
    port: int = getenv_int("PORT", 8080) or 8080

    # Department branding
    department_name: str = getenv_str("DEPARTMENT_NAME", "Engineering and Technical Service") or "Engineering and Technical Service"
    department_abbrev: str = getenv_str("DEPARTMENT_ABBREVIATION", "E&T") or "E&T"
    department_color: discord.Color = getenv_color("DEPARTMENT_COLOR", "A3904C")
    department_group_url: str = getenv_str(
        "DEPARTMENT_GROUP_URL",
        "https://www.roblox.com/communities/515594004/SCPF-Engineering-and-Technical-Service#!/about",
    ) or "https://www.roblox.com/communities/515594004/SCPF-Engineering-and-Technical-Service#!/about"
    department_description: str = getenv_str(
        "DEPARTMENT_DESCRIPTION",
        "The Engineering and Technical Service Department (E&T) is responsible for the upkeep and maintenance of the facility. Whether it’s repairing a door or making changes to an SCP's containment zone, E&T is vital to ensuring smooth operations can persist within the facility.",
    ) or "The Engineering and Technical Service Department (E&T) is responsible for the upkeep and maintenance of the facility. Whether it’s repairing a door or making changes to an SCP's containment zone, E&T is vital to ensuring smooth operations can persist within the facility."

    # Discord channels
    activity_log_channel_id: int | None = getenv_int("ACTIVITY_LOG_CHANNEL_ID")
    command_log_channel_id: int | None = getenv_int("COMMAND_LOG_CHANNEL_ID")
    roblox_audit_log_channel_id: int | None = getenv_int("ROBLOX_AUDIT_LOG_CHANNEL_ID")
    welcome_channel_id: int | None = getenv_int("WELCOME_CHANNEL_ID")
    weekly_report_channel_id: int | None = getenv_int("WEEKLY_REPORT_CHANNEL_ID")

    # Roles
    management_role_id: int | None = getenv_int("MANAGEMENT_ROLE_ID")
    rank_manager_role_id: int | None = getenv_int("RANK_MANAGER_ROLE_ID")
    strike_manager_role_id: int | None = getenv_int("STRIKE_MANAGER_ROLE_ID")
    activity_manager_role_id: int | None = getenv_int("ACTIVITY_MANAGER_ROLE_ID")
    welcome_manager_role_id: int | None = getenv_int("WELCOME_MANAGER_ROLE_ID")
    department_role_id: int | None = getenv_int("DEPARTMENT_ROLE_ID")

    # Applications
    application_start_channel_id: int = getenv_int("APPLICATION_START_CHANNEL_ID", 1520168176703246496) or 1520168176703246496
    application_pending_channel_id: int = getenv_int("APPLICATION_PENDING_CHANNEL_ID", 1520219147986796575) or 1520219147986796575
    application_accepted_channel_id: int = getenv_int("APPLICATION_ACCEPTED_CHANNEL_ID", 1520219188977864704) or 1520219188977864704
    application_denied_channel_id: int = getenv_int("APPLICATION_DENIED_CHANNEL_ID", 1520219215309832212) or 1520219215309832212
    application_dm_help_channel_id: int = getenv_int("APPLICATION_DM_HELP_CHANNEL_ID", 1520162557774532649) or 1520162557774532649
    application_ticket_category_id: int = getenv_int("APPLICATION_TICKET_CATEGORY_ID", 1521669739414290462) or 1521669739414290462
    application_management_role_ids: tuple[int, ...] = (1520155690587390082, 1520155715455549530)

    # Roblox service/webhooks
    api_secret_key: str | None = getenv_str("API_SECRET_KEY")
    roblox_group_id: int = getenv_int("ROBLOX_GROUP_ID", 515594004) or 515594004
    roblox_service_base: str | None = normalize_base_url(getenv_str("ROBLOX_SERVICE_BASE"))
    roblox_service_secret: str | None = getenv_str("ROBLOX_SERVICE_SECRET")

    # Activity
    weekly_time_requirement: int = getenv_int("WEEKLY_TIME_REQUIREMENT", 120) or 120
    auto_weekly_report: bool = getenv_bool("AUTO_WEEKLY_REPORT", False)
    auto_weekly_reset: bool = getenv_bool("AUTO_WEEKLY_RESET", False)
    auto_report_weekday_utc: int = getenv_int("AUTO_REPORT_WEEKDAY_UTC", 6) or 6  # Sunday
    auto_report_hour_utc: int = getenv_int("AUTO_REPORT_HOUR_UTC", 0) or 0
    auto_inactivity_strikes: bool = getenv_bool("AUTO_INACTIVITY_STRIKES", False)

    # Strikes
    default_strike_duration_days: int = getenv_int("DEFAULT_STRIKE_DURATION_DAYS", 30) or 30
    max_strikes: int = getenv_int("MAX_STRIKES", 3) or 3

    # Welcome
    welcome_title: str = getenv_str("WELCOME_TITLE", "Welcome to Engineering & Technical Service") or "Welcome to Engineering & Technical Service"
    welcome_department_display: str = getenv_str("WELCOME_DEPARTMENT_DISPLAY", "Engineering & Technical Service") or "Engineering & Technical Service"
    welcome_guidelines_channel: str = getenv_str("WELCOME_GUIDELINES_CHANNEL", "<#1520160137132773376>") or "<#1520160137132773376>"
    welcome_internship_url: str = getenv_str(
        "WELCOME_INTERNSHIP_URL",
        "https://trello.com/c/NqgrPAJF/6-internship-program",
    ) or "https://trello.com/c/NqgrPAJF/6-internship-program"
    welcome_message: str = getenv_str(
        "WELCOME_MESSAGE",
        "Welcome, {member}, to **{welcome_department}!** ({abbreviation})\n\n"
        "We’re glad to have you join the department. Before getting started, please make sure you complete the following:\n\n"
        "**1. Run `/verify` with this bot.**\n\n"
        "This is required so your activity, logs, and department progress can be properly tracked.\n\n"
        "**2. Read the Department Guidelines**\n"
        "Please review our full guidelines which can be found in {guidelines_channel}. These explain department expectations, logging rules, task validity, conduct, and other important information you are expected to follow.\n\n"
        "**3. Complete the Internship Program**\n"
        "All new members begin as **Trainee Technicians** and are required to complete the [Internship Program]({internship_url}) within **2 weeks** of joining.\n\n"
        "The Internship Program card contains the full requirements, expectations, and information needed to rank up to **Junior Technician** and become a full member of the department.\n\n"
        "Please read everything carefully, ask management if you have any questions, and good luck in {abbreviation}!",
    ) or "Welcome, {member}, to **{welcome_department}!** ({abbreviation})"


CONFIG = BotConfig()


# ============================================================
# Discord setup
# ============================================================

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = False

activity_group = app_commands.Group(name="activity", description=f"{CONFIG.department_abbrev} activity tracking commands.")
strikes_group = app_commands.Group(name="strikes", description=f"{CONFIG.department_abbrev} strike management commands.")
verification_group = app_commands.Group(name="verification", description=f"{CONFIG.department_abbrev} verification management commands.")


def is_default_role(role: discord.Role) -> bool:
    return role.is_default() or role.id == role.guild.id


class ETBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.db_pool: asyncpg.Pool | None = None
        self.web_runner: web.AppRunner | None = None
        self.web_site: web.TCPSite | None = None
        self._bootstrap_lock = asyncio.Lock()
        self._bootstrapped = False
        self._application_views_registered = False

    async def setup_hook(self) -> None:
        if not CONFIG.database_url:
            print("[DB] Missing DATABASE_URL. Database commands will not work.")
        else:
            try:
                self.db_pool = await asyncpg.create_pool(CONFIG.database_url, min_size=1, max_size=10)
                async with self.db_pool.acquire() as conn:
                    await conn.execute("SELECT 1")
                print("[DB] Connected.")
            except Exception as exc:
                print(f"[DB] Connection failed: {exc}")

        await self.ensure_bootstrap()

    async def ensure_bootstrap(self) -> None:
        if self._bootstrapped:
            return
        async with self._bootstrap_lock:
            if self._bootstrapped:
                return

            if self.db_pool:
                await self.setup_database()

            await self.setup_web_server()

            try:
                self.tree.add_command(activity_group)
            except app_commands.CommandAlreadyRegistered:
                pass
            try:
                self.tree.add_command(strikes_group)
            except app_commands.CommandAlreadyRegistered:
                pass
            try:
                self.tree.add_command(verification_group)
            except app_commands.CommandAlreadyRegistered:
                pass

            try:
                synced = await self.tree.sync()
                print(f"[Slash] Synced {len(synced)} command(s).")
            except Exception as exc:
                print(f"[Slash] Sync failed: {exc}")

            self._bootstrapped = True

    async def setup_database(self) -> None:
        assert self.db_pool is not None
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS roblox_verification (
                    discord_id BIGINT PRIMARY KEY,
                    roblox_id BIGINT UNIQUE NOT NULL,
                    roblox_username TEXT,
                    verified_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS roblox_sessions (
                    roblox_id BIGINT PRIMARY KEY,
                    discord_id BIGINT,
                    started_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS roblox_activity (
                    id BIGSERIAL PRIMARY KEY,
                    discord_id BIGINT NOT NULL,
                    roblox_id BIGINT,
                    week_key TEXT NOT NULL,
                    minutes INT NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'webhook',
                    reason TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS activity_adjustments (
                    id BIGSERIAL PRIMARY KEY,
                    discord_id BIGINT NOT NULL,
                    minutes_delta INT NOT NULL,
                    reason TEXT NOT NULL,
                    adjusted_by BIGINT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS strikes (
                    strike_id BIGSERIAL PRIMARY KEY,
                    member_id BIGINT NOT NULL,
                    reason TEXT NOT NULL,
                    issued_by BIGINT,
                    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    expires_at TIMESTAMPTZ NOT NULL,
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    auto BOOLEAN NOT NULL DEFAULT FALSE,
                    removed_by BIGINT,
                    removed_reason TEXT,
                    removed_at TIMESTAMPTZ
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS member_ranks (
                    discord_id BIGINT PRIMARY KEY,
                    rank_name TEXT NOT NULL,
                    set_by BIGINT,
                    set_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS weekly_snapshots (
                    id BIGSERIAL PRIMARY KEY,
                    week_key TEXT NOT NULL,
                    report_json JSONB NOT NULL,
                    created_by BIGINT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS applications (
                    id BIGSERIAL PRIMARY KEY,
                    applicant_id BIGINT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    answers_json JSONB NOT NULL,
                    pending_message_id BIGINT,
                    pending_channel_id BIGINT,
                    decided_by BIGINT,
                    decision_reason TEXT,
                    ticket_channel_id BIGINT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    decided_at TIMESTAMPTZ
                );
            """)
            await conn.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS application_duration_seconds INT;")
            await conn.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS applicant_joined_at TIMESTAMPTZ;")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_panels (
                    panel_key TEXT PRIMARY KEY,
                    channel_id BIGINT NOT NULL,
                    message_id BIGINT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)
        print("[DB] Tables ready.")

    async def setup_web_server(self) -> None:
        if self.web_runner:
            return
        app = web.Application()
        app.router.add_get("/health", self.health_handler)
        app.router.add_post("/roblox", self.roblox_handler)
        app.router.add_post("/roblox/audit", self.roblox_audit_handler)
        self.web_runner = web.AppRunner(app)
        await self.web_runner.setup()
        self.web_site = web.TCPSite(self.web_runner, "0.0.0.0", CONFIG.port)
        await self.web_site.start()
        print(f"[Web] Server running on :{CONFIG.port}.")

    async def health_handler(self, request: web.Request) -> web.Response:
        return web.Response(text="ok", status=200)

    def check_webhook_secret(self, request: web.Request) -> bool:
        # If API_SECRET_KEY is configured, require it. If not configured, allow local/dev testing.
        if not CONFIG.api_secret_key:
            return True
        return request.headers.get("X-Secret-Key") == CONFIG.api_secret_key

    async def roblox_handler(self, request: web.Request) -> web.Response:
        if not self.check_webhook_secret(request):
            await self.log_command("Webhook Rejected", "`POST /roblox` rejected due to invalid secret.")
            return web.Response(status=401, text="unauthorized")
        if not self.db_pool:
            return web.json_response({"ok": False, "error": "database_unavailable"}, status=500)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)

        roblox_id = data.get("robloxId") or data.get("roblox_id")
        status = str(data.get("status") or data.get("event") or "").lower().strip()
        if not roblox_id or status not in {"joined", "left"}:
            return web.json_response({"ok": False, "error": "expected robloxId and status joined|left"}, status=400)

        try:
            roblox_id = int(roblox_id)
        except ValueError:
            return web.json_response({"ok": False, "error": "invalid_roblox_id"}, status=400)

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT discord_id, roblox_username FROM roblox_verification WHERE roblox_id=$1",
                roblox_id,
            )

        if not row:
            await self.log_command("Unverified Roblox Activity", f"Roblox ID `{roblox_id}` sent `{status}` but is not verified.")
            return web.json_response({"ok": True, "verified": False})

        discord_id = int(row["discord_id"])
        member = self.find_member(discord_id)
        display = member.mention if member else f"Discord ID `{discord_id}`"

        if status == "joined":
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO roblox_sessions (roblox_id, discord_id, started_at)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (roblox_id) DO UPDATE SET discord_id=$2, started_at=$3
                    """,
                    roblox_id,
                    discord_id,
                    utcnow(),
                )
            await self.send_activity_log("🟢 Joined Site", f"{display} started a site session.", discord.Color.green())
            return web.json_response({"ok": True, "status": "joined"})

        async with self.db_pool.acquire() as conn:
            session = await conn.fetchrow("SELECT started_at FROM roblox_sessions WHERE roblox_id=$1", roblox_id)
            if session:
                await conn.execute("DELETE FROM roblox_sessions WHERE roblox_id=$1", roblox_id)

        if not session:
            await self.send_activity_log(
                "🔴 Left Site",
                f"{display} ended a site session, but no start time was found.",
                discord.Color.orange(),
            )
            return web.json_response({"ok": True, "status": "left", "tracked_minutes": 0})

        started_at: dt.datetime = session["started_at"]
        minutes = max(0, int((utcnow() - started_at).total_seconds() // 60))
        wk = week_key()
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO roblox_activity (discord_id, roblox_id, week_key, minutes, source, reason)
                VALUES ($1, $2, $3, $4, 'webhook', 'Roblox session ended')
                """,
                discord_id,
                roblox_id,
                wk,
                minutes,
            )
            weekly = await self.fetch_weekly_minutes(conn, discord_id, wk)

        await self.send_activity_log(
            "🔴 Left Site",
            (
                f"{display} ended their site session.\n"
                f"Session time: **{fmt_minutes(minutes)}**\n"
                f"This week: **{fmt_minutes(weekly)}/{fmt_minutes(CONFIG.weekly_time_requirement)}**"
            ),
            discord.Color.red(),
        )
        return web.json_response({"ok": True, "status": "left", "tracked_minutes": minutes})

    async def roblox_audit_handler(self, request: web.Request) -> web.Response:
        if not self.check_webhook_secret(request):
            await self.log_command("Webhook Rejected", "`POST /roblox/audit` rejected due to invalid secret.")
            return web.Response(status=401, text="unauthorized")
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)

        event = str(data.get("event") or data.get("action") or data.get("eventType") or "Audit Event")
        actor = str(data.get("actor") or data.get("author") or data.get("username") or "Unknown")
        target = str(data.get("target") or data.get("recipient") or data.get("targetUser") or "Unknown")
        reason = str(data.get("reason") or data.get("description") or "No reason provided")
        occurred = str(data.get("timestamp") or data.get("createdAt") or utcnow().isoformat())

        embed = discord.Embed(title="📋 Roblox Group Audit Logged", color=CONFIG.department_color, timestamp=utcnow())
        embed.add_field(name="Event", value=event[:1024], inline=True)
        embed.add_field(name="By", value=actor[:1024], inline=True)
        embed.add_field(name="Target", value=target[:1024], inline=True)
        embed.add_field(name="Occurred", value=occurred[:1024], inline=False)
        embed.add_field(name="Reason", value=reason[:1024], inline=False)
        raw = json.dumps(data, ensure_ascii=False)
        if len(raw) > 1000:
            raw = raw[:997] + "..."
        embed.add_field(name="Payload", value=f"```json\n{raw}\n```", inline=False)

        channel_id = CONFIG.roblox_audit_log_channel_id or CONFIG.command_log_channel_id
        channel = self.get_channel(channel_id) if channel_id else None
        if channel:
            await channel.send(embed=embed)
        return web.json_response({"ok": True})

    async def fetch_weekly_minutes(self, conn: asyncpg.Connection, discord_id: int, wk: str | None = None) -> int:
        wk = wk or week_key()
        value = await conn.fetchval(
            "SELECT COALESCE(SUM(minutes), 0)::INT FROM roblox_activity WHERE discord_id=$1 AND week_key=$2",
            discord_id,
            wk,
        )
        return int(value or 0)

    async def fetch_all_time_minutes(self, conn: asyncpg.Connection, discord_id: int) -> int:
        value = await conn.fetchval(
            "SELECT COALESCE(SUM(minutes), 0)::INT FROM roblox_activity WHERE discord_id=$1",
            discord_id,
        )
        return int(value or 0)

    async def active_strike_count(self, conn: asyncpg.Connection, discord_id: int) -> int:
        value = await conn.fetchval(
            "SELECT COUNT(*)::INT FROM strikes WHERE member_id=$1 AND active=TRUE AND expires_at>$2",
            discord_id,
            utcnow(),
        )
        return int(value or 0)

    def find_member(self, discord_id: int) -> discord.Member | None:
        for guild in self.guilds:
            member = guild.get_member(discord_id)
            if member:
                return member
        return None

    async def send_activity_log(self, title: str, description: str, color: discord.Color) -> None:
        channel = self.get_channel(CONFIG.activity_log_channel_id) if CONFIG.activity_log_channel_id else None
        if not channel:
            return
        embed = discord.Embed(title=title, description=description, color=color, timestamp=utcnow())
        embed.set_footer(text=CONFIG.department_name)
        await channel.send(embed=embed)

    async def log_command(self, title: str, description: str, color: discord.Color | None = None) -> None:
        channel = self.get_channel(CONFIG.command_log_channel_id) if CONFIG.command_log_channel_id else None
        if not channel:
            print(f"[LOG] {title}: {description}")
            return
        embed = discord.Embed(
            title=title,
            description=description[:4000],
            color=color or discord.Color.dark_gray(),
            timestamp=utcnow(),
        )
        embed.set_footer(text=CONFIG.department_name)
        await channel.send(embed=embed)

    async def get_verified_roblox(self, discord_id: int) -> asyncpg.Record | None:
        if not self.db_pool:
            return None
        async with self.db_pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT roblox_id, roblox_username FROM roblox_verification WHERE discord_id=$1",
                discord_id,
            )


bot = ETBot()


# ============================================================
# Permission checks
# ============================================================

def member_has_role(member: discord.Member, role_id: int | None) -> bool:
    if role_id is None:
        return False
    return any(role.id == role_id for role in member.roles)


def is_management(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or member_has_role(member, CONFIG.management_role_id)


def can_manage_activity(member: discord.Member) -> bool:
    return is_management(member) or member_has_role(member, CONFIG.activity_manager_role_id)


def can_manage_strikes(member: discord.Member) -> bool:
    return is_management(member) or member_has_role(member, CONFIG.strike_manager_role_id)


def can_manage_ranks(member: discord.Member) -> bool:
    return is_management(member) or member_has_role(member, CONFIG.rank_manager_role_id)


def can_send_welcome(member: discord.Member) -> bool:
    return is_management(member) or member_has_role(member, CONFIG.welcome_manager_role_id)


async def require_db(interaction: discord.Interaction) -> bool:
    if bot.db_pool:
        return True
    await interaction.response.send_message("Database is not connected. Check Railway/Postgres configuration.", ephemeral=True)
    return False


# ============================================================
# Events
# ============================================================

@bot.event
async def on_ready() -> None:
    print(f"[READY] Logged in as {bot.user}.")
    if not bot._application_views_registered:
        bot.add_view(ApplicationStartView())
        bot.add_view(ApplicationReviewView())
        bot.add_view(ApplicationTicketView())
        bot._application_views_registered = True
    await ensure_application_panel()
    if CONFIG.auto_weekly_report or CONFIG.auto_weekly_reset:
        weekly_scheduler.start()


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    await bot.log_command(
        "Slash Command Error",
        f"Command: `/{getattr(interaction.command, 'qualified_name', 'unknown')}`\nError: `{error}`",
        discord.Color.red(),
    )
    if not interaction.response.is_done():
        await interaction.response.send_message("Something went wrong running that command.", ephemeral=True)


# ============================================================
# Roblox helpers
# ============================================================

async def lookup_roblox_user(username: str) -> tuple[int, str] | None:
    payload = {"usernames": [username], "excludeBannedUsers": True}
    async with aiohttp.ClientSession() as session:
        async with session.post("https://users.roblox.com/v1/usernames/users", json=payload, timeout=20) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
    results = data.get("data") or []
    if not results:
        return None
    return int(results[0]["id"]), str(results[0]["name"])


async def fetch_group_ranks() -> list[dict[str, Any]]:
    if not CONFIG.roblox_service_base or not CONFIG.roblox_service_secret:
        return []
    url = f"{CONFIG.roblox_service_base}/ranks"
    headers = {"X-Secret-Key": CONFIG.roblox_service_secret}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=20) as resp:
            text = await resp.text()
            if resp.status // 100 != 2:
                raise RuntimeError(f"Rank service /ranks failed {resp.status}: {text}")
            data = json.loads(text)
    return data.get("roles", []) or []


async def set_group_rank(roblox_id: int, rank_name: str) -> str:
    if not CONFIG.roblox_service_base or not CONFIG.roblox_service_secret:
        raise RuntimeError("ROBLOX_SERVICE_BASE and ROBLOX_SERVICE_SECRET are required for ranking.")

    roles = await fetch_group_ranks()
    requested = rank_name.strip().lower()
    target = None
    for role in roles:
        name = str(role.get("name") or "")
        if name.lower() == requested:
            target = role
            break
    if not target:
        available = ", ".join(str(r.get("name")) for r in roles[:20] if r.get("name")) or "No ranks returned"
        raise RuntimeError(f"Rank `{rank_name}` was not found. Available examples: {available}")

    body: dict[str, Any] = {"robloxId": int(roblox_id), "groupId": int(CONFIG.roblox_group_id)}
    role_id = target.get("roleId") if target.get("roleId") is not None else target.get("id")
    rank_number = target.get("rank") if target.get("rank") is not None else target.get("rankNumber")
    if role_id is not None:
        body["roleId"] = int(role_id)
    elif rank_number is not None:
        body["rankNumber"] = int(rank_number)
    else:
        raise RuntimeError(f"Rank service did not return a roleId or rank number for `{rank_name}`.")

    url = f"{CONFIG.roblox_service_base}/set-rank"
    headers = {"X-Secret-Key": CONFIG.roblox_service_secret, "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=body, timeout=25) as resp:
            text = await resp.text()
            if resp.status // 100 != 2:
                raise RuntimeError(f"Rank service /set-rank failed {resp.status}: {text}")
    return str(target.get("name") or rank_name)


async def rank_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    del interaction
    try:
        roles = await fetch_group_ranks()
    except Exception:
        roles = []
    current_lower = current.lower().strip()
    names = [str(role.get("name")) for role in roles if role.get("name")]
    if current_lower:
        names = [name for name in names if current_lower in name.lower()]
    return [app_commands.Choice(name=name[:100], value=name[:100]) for name in names[:25]]


# ============================================================
# Applications
# ============================================================

APPLICATION_QUESTIONS = [
    "Why do you want to join Engineering & Technical Service?",
    "What does Engineering & Technical Service do within the facility?",
    "If you made a mistake while completing a repair or log, what would you do?",
    "What qualities do you think a good E&T member should have?",
    "Do you understand that all new members must complete the Internship Program within 2 weeks before becoming a full member of the department?",
]

APPLICATION_START_COLOR = discord.Color.gold()
APPLICATION_PENDING_COLOR = discord.Color(0xA1904A)
APPLICATION_ACCEPTED_COLOR = discord.Color.green()
APPLICATION_DENIED_COLOR = discord.Color.red()
APPLICATION_INFO_COLOR = discord.Color.blurple()


def is_application_management(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or any(role.id in CONFIG.application_management_role_ids for role in member.roles)


def application_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="[E&T] Entrance Exam",
        description=(
            "🛠️ **Before completing the [E&T] Entrance Exam**, it is strongly "
            "recommended that you review the **E&T Information Hub**. This will help "
            "you better understand the department, expectations, and the questions "
            "on this application.\n\n"
            "📌 You should also make sure you are **pending in the Roblox group** "
            "before submitting your application.\n\n"
            "📚 **E&T Information Hub:**\n"
            "https://trello.com/b/YO1hYYQZ/et-information-hub\n\n"
            "👥 **Roblox Group:**\n"
            f"{CONFIG.department_group_url}\n\n"
            "✅ Once you have reviewed the information and are pending in the group, "
            "you may begin the entrance exam."
        ),
        color=APPLICATION_START_COLOR,
        timestamp=utcnow(),
    )
    return embed


def application_notice_embed(title: str, description: str, color: discord.Color | None = None) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color or APPLICATION_INFO_COLOR, timestamp=utcnow())
    embed.set_footer(text=CONFIG.department_name)
    return embed


def application_question_embed(index: int, question: str) -> discord.Embed:
    instructions = "Reply with your answer in one message. Type `cancel` at any time to stop."
    if index == len(APPLICATION_QUESTIONS):
        instructions = "Please click **Yes** or **No** below."
    embed = application_notice_embed(
        f"Question {index}/{len(APPLICATION_QUESTIONS)}",
        f"**{question}**\n\n{instructions}",
        APPLICATION_PENDING_COLOR,
    )
    return embed


def format_datetime(value: dt.datetime | None) -> str:
    if not value:
        return "Unknown"
    timestamp = int(value.timestamp())
    return f"<t:{timestamp}:F> (<t:{timestamp}:R>)"


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "Unknown"
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    hours, mins = divmod(minutes, 60)
    if hours:
        return f"{hours}h {mins}m {secs}s"
    if mins:
        return f"{mins}m {secs}s"
    return f"{secs}s"


def build_application_embed(
    app_id: int,
    applicant: discord.abc.User,
    answers: list[str],
    status: str = "Pending",
    *,
    duration_seconds: int | None = None,
    joined_guild_at: dt.datetime | None = None,
    submitted_at: dt.datetime | None = None,
) -> discord.Embed:
    normalized_status = status.lower()
    if normalized_status == "accepted":
        color = APPLICATION_ACCEPTED_COLOR
    elif normalized_status == "denied":
        color = APPLICATION_DENIED_COLOR
    else:
        color = APPLICATION_PENDING_COLOR
    status_icon = {"accepted": "✅", "denied": "❌"}.get(normalized_status, "🕒")
    embed = discord.Embed(
        title=f"{status_icon} [E&T] Application #{app_id} — {status}",
        description=f"**Applicant:** {applicant.mention} (`{applicant.id}`)",
        color=color,
        timestamp=utcnow(),
    )
    embed.add_field(
        name="📊 Submission Stats",
        value=(
            f"**UserId:** `{applicant.id}`\n"
            f"**Username:** `{applicant.name}`\n"
            f"**User:** {applicant.mention}\n"
            f"**Duration:** {format_duration(duration_seconds)}\n"
            f"**Joined guild:** {format_datetime(joined_guild_at)}\n"
            f"**Submitted:** {format_datetime(submitted_at)}"
        ),
        inline=False,
    )
    for idx, question in enumerate(APPLICATION_QUESTIONS, start=1):
        answer = answers[idx - 1] if idx - 1 < len(answers) else "No answer provided."
        embed.add_field(name=f"❔ Q{idx}: {question}", value=answer[:1024], inline=False)
    embed.set_footer(text=CONFIG.department_name)
    return embed


def build_application_ticket_embed(
    app_id: int,
    applicant: discord.abc.User,
    management_member: discord.abc.User,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎫 [E&T] Application #{app_id} Ticket",
        description="Use this private channel to discuss the application with the applicant and management team.",
        color=APPLICATION_PENDING_COLOR,
        timestamp=utcnow(),
    )
    embed.add_field(name="Application", value=f"Application #{app_id}", inline=True)
    embed.add_field(name="Management Member", value=management_member.mention, inline=True)
    embed.add_field(name="Applicant", value=f"{applicant.mention} (`{applicant.id}`)", inline=True)
    embed.set_footer(text=CONFIG.department_name)
    return embed


def build_application_preview_embed(answers: list[str]) -> discord.Embed:
    embed = discord.Embed(
        title="📝 [E&T] Application Submission Preview",
        description="Review your answers below. Use an edit button to change a specific answer, or submit when everything looks correct.",
        color=APPLICATION_PENDING_COLOR,
        timestamp=utcnow(),
    )
    for idx, question in enumerate(APPLICATION_QUESTIONS, start=1):
        answer = answers[idx - 1] if idx - 1 < len(answers) else "No answer provided."
        embed.add_field(name=f"❔ Q{idx}: {question}", value=answer[:1024], inline=False)
    return embed


class YesNoQuestionView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=900)
        self.user_id = user_id
        self.answer: str | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message("This application prompt is not for you.", ephemeral=True)
        return False

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        self.answer = "Yes"
        await interaction.response.edit_message(content="You selected **Yes**.", view=None)
        self.stop()

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        self.answer = "No"
        await interaction.response.edit_message(content="You selected **No**.", view=None)
        self.stop()


class ApplicationPreviewView(discord.ui.View):
    def __init__(self, user_id: int, answers: list[str]):
        super().__init__(timeout=900)
        self.user_id = user_id
        self.answers = answers
        self.submitted = False

        for idx in range(len(APPLICATION_QUESTIONS)):
            self.add_item(EditAnswerButton(idx))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message("This application preview is not for you.", ephemeral=True)
        return False

    async def refresh_preview(self, interaction: discord.Interaction) -> None:
        await interaction.message.edit(embed=build_application_preview_embed(self.answers), view=self)

    @discord.ui.button(label="Submit Application", style=discord.ButtonStyle.success, row=4)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        self.submitted = True
        await interaction.response.edit_message(content="Submitting your application...", embed=None, view=None)
        self.stop()


class EditAnswerButton(discord.ui.Button):
    def __init__(self, question_index: int):
        super().__init__(
            label=f"Edit Q{question_index + 1}",
            style=discord.ButtonStyle.secondary,
            row=question_index // 3,
        )
        self.question_index = question_index

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, ApplicationPreviewView):
            return
        question = APPLICATION_QUESTIONS[self.question_index]
        dm = interaction.channel
        if self.question_index == len(APPLICATION_QUESTIONS) - 1:
            yes_no_view = YesNoQuestionView(interaction.user.id)
            await interaction.response.send_message(
                f"Please choose your new answer for **Q{self.question_index + 1}: {question}**.",
                view=yes_no_view,
            )
            await yes_no_view.wait()
            if yes_no_view.answer is None:
                await dm.send("That edit timed out. You can press the edit button again if needed.")
                return
            view.answers[self.question_index] = yes_no_view.answer
            await dm.send(f"Updated **Q{self.question_index + 1}**.")
            if interaction.message:
                await view.refresh_preview(interaction)
            return
        await interaction.response.send_message(f"Please send your new answer for **Q{self.question_index + 1}: {question}**.", ephemeral=False)
        try:
            msg = await bot.wait_for(
                "message",
                timeout=900,
                check=lambda m: m.author.id == interaction.user.id and m.channel.id == dm.id,
            )
        except asyncio.TimeoutError:
            await dm.send("That edit timed out. You can press the edit button again if needed.")
            return
        if msg.content.strip().lower() == "cancel":
            await dm.send("Edit cancelled. Your previous answer was kept.")
            return
        view.answers[self.question_index] = msg.content.strip()[:3900] or "No answer provided."
        await dm.send(f"Updated **Q{self.question_index + 1}**.")
        if interaction.message:
            await view.refresh_preview(interaction)


class ApplicationStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Begin Application", style=discord.ButtonStyle.success, custom_id="application:begin")
    async def begin(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Applications must be started from the server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            dm = await interaction.user.create_dm()
            await dm.send(
                embed=application_notice_embed(
                    "🛠️ Entrance Exam Started",
                    "Please answer each question in one message. Type `cancel` at any time to stop.",
                    APPLICATION_START_COLOR,
                )
            )
        except discord.Forbidden:
            help_channel = bot.get_channel(CONFIG.application_dm_help_channel_id)
            if isinstance(help_channel, discord.TextChannel):
                await help_channel.send(
                    content=interaction.user.mention,
                    embed=application_notice_embed(
                        "DMs Required",
                        "Please allow Direct Messages for this server so the bot can begin your application.",
                        APPLICATION_DENIED_COLOR,
                    ),
                )
            await interaction.followup.send("I could not DM you. Please enable Direct Messages for this server and try again.", ephemeral=True)
            return

        await interaction.followup.send("I sent you a DM to begin your application.", ephemeral=True)
        answers: list[str] = []
        started_at = utcnow()
        for idx, question in enumerate(APPLICATION_QUESTIONS, start=1):
            if idx == len(APPLICATION_QUESTIONS):
                yes_no_view = YesNoQuestionView(interaction.user.id)
                await dm.send(embed=application_question_embed(idx, question), view=yes_no_view)
                await yes_no_view.wait()
                if yes_no_view.answer is None:
                    await dm.send(
                        embed=application_notice_embed(
                            "Application Timed Out",
                            "Please click **Begin Application** again when you are ready.",
                            APPLICATION_DENIED_COLOR,
                        )
                    )
                    return
                answers.append(yes_no_view.answer)
                continue
            await dm.send(embed=application_question_embed(idx, question))
            try:
                msg = await bot.wait_for(
                    "message",
                    timeout=900,
                    check=lambda m: m.author.id == interaction.user.id and isinstance(m.channel, discord.DMChannel),
                )
            except asyncio.TimeoutError:
                await dm.send(
                    embed=application_notice_embed(
                        "Application Timed Out",
                        "Please click **Begin Application** again when you are ready.",
                        APPLICATION_DENIED_COLOR,
                    )
                )
                return
            if msg.content.strip().lower() == "cancel":
                await dm.send(
                    embed=application_notice_embed(
                        "Application Cancelled",
                        "Your application has been cancelled. You can begin again when ready.",
                        APPLICATION_DENIED_COLOR,
                    )
                )
                return
            answers.append(msg.content.strip()[:3900] or "No answer provided.")

        preview_view = ApplicationPreviewView(interaction.user.id, answers)
        await dm.send(embed=build_application_preview_embed(answers), view=preview_view)
        await preview_view.wait()
        if not preview_view.submitted:
            await dm.send(
                embed=application_notice_embed(
                    "Preview Timed Out",
                    "Please click **Begin Application** again when you are ready.",
                    APPLICATION_DENIED_COLOR,
                )
            )
            return

        submitted_at = utcnow()
        duration_seconds = int((submitted_at - started_at).total_seconds())
        joined_guild_at = interaction.user.joined_at

        if not bot.db_pool:
            await dm.send(
                embed=application_notice_embed(
                    "Database Unavailable",
                    "Please contact management so they can help with your application.",
                    APPLICATION_DENIED_COLOR,
                )
            )
            return
        async with bot.db_pool.acquire() as conn:
            app_id = await conn.fetchval(
                """
                INSERT INTO applications (
                    applicant_id,
                    answers_json,
                    status,
                    application_duration_seconds,
                    applicant_joined_at,
                    created_at
                )
                VALUES ($1, $2, 'pending', $3, $4, $5)
                RETURNING id
                """,
                interaction.user.id,
                json.dumps(answers),
                duration_seconds,
                joined_guild_at,
                submitted_at,
            )
        pending_channel = bot.get_channel(CONFIG.application_pending_channel_id)
        if not isinstance(pending_channel, discord.TextChannel):
            await dm.send(
                embed=application_notice_embed(
                    "Application Saved",
                    "The pending applications channel could not be found. Please contact management.",
                    APPLICATION_DENIED_COLOR,
                )
            )
            return
        sent = await pending_channel.send(
            embed=build_application_embed(
                int(app_id),
                interaction.user,
                answers,
                duration_seconds=duration_seconds,
                joined_guild_at=joined_guild_at,
                submitted_at=submitted_at,
            ),
            view=ApplicationReviewView(),
        )
        async with bot.db_pool.acquire() as conn:
            await conn.execute("UPDATE applications SET pending_message_id=$1, pending_channel_id=$2 WHERE id=$3", sent.id, pending_channel.id, int(app_id))
        await dm.send(
            embed=application_notice_embed(
                "✅ Application Submitted",
                "Management will review your application and you will be notified when a decision is made.",
                APPLICATION_ACCEPTED_COLOR,
            )
        )


class DecisionReasonModal(discord.ui.Modal):
    def __init__(self, app_id: int, accepted: bool):
        super().__init__(title=f"{'Accept' if accepted else 'Deny'} Application #{app_id}")
        self.app_id = app_id
        self.accepted = accepted
        self.reason = discord.ui.TextInput(label="Reason", style=discord.TextStyle.paragraph, max_length=1000)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await process_application_decision(interaction, self.app_id, self.accepted, str(self.reason.value))


class ApplicationReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if isinstance(interaction.user, discord.Member) and is_application_management(interaction.user):
            return True
        await interaction.response.send_message("Only E&T management+ can process applications.", ephemeral=True)
        return False

    def app_id_from_embed(self, interaction: discord.Interaction) -> int | None:
        if not interaction.message or not interaction.message.embeds:
            return None
        title = interaction.message.embeds[0].title or ""
        try:
            return int(title.split("#", 1)[1].split()[0])
        except (IndexError, ValueError):
            return None

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="application:accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        app_id = self.app_id_from_embed(interaction)
        if app_id:
            await process_application_decision(interaction, app_id, True, None)

    @discord.ui.button(label="Accept with Reason", style=discord.ButtonStyle.primary, custom_id="application:accept_reason")
    async def accept_reason(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        app_id = self.app_id_from_embed(interaction)
        if app_id:
            await interaction.response.send_modal(DecisionReasonModal(app_id, True))

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, custom_id="application:deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        app_id = self.app_id_from_embed(interaction)
        if app_id:
            await process_application_decision(interaction, app_id, False, None)

    @discord.ui.button(label="Deny with Reason", style=discord.ButtonStyle.danger, custom_id="application:deny_reason")
    async def deny_reason(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        app_id = self.app_id_from_embed(interaction)
        if app_id:
            await interaction.response.send_modal(DecisionReasonModal(app_id, False))

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.secondary, custom_id="application:ticket")
    async def ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        app_id = self.app_id_from_embed(interaction)
        if app_id:
            await open_application_ticket(interaction, app_id)


class ApplicationTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if isinstance(interaction.user, discord.Member) and is_application_management(interaction.user):
            return True
        await interaction.response.send_message("Only E&T management+ can close application tickets.", ephemeral=True)
        return False

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="application_ticket:close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This button can only close a server ticket channel.", ephemeral=True)
            return
        await interaction.response.send_message("Closing this ticket and deleting the channel...", ephemeral=True)
        try:
            await interaction.channel.delete(reason=f"Application ticket closed by {interaction.user}")
        except discord.HTTPException:
            await interaction.followup.send("I could not delete this ticket channel. Please check my permissions.", ephemeral=True)

async def ensure_application_panel() -> None:
    if not bot.db_pool:
        return
    channel = bot.get_channel(CONFIG.application_start_channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    async with bot.db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT message_id FROM bot_panels WHERE panel_key='application_start'")
    if row:
        try:
            await channel.fetch_message(int(row["message_id"]))
            return
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    message = await channel.send(embed=application_panel_embed(), view=ApplicationStartView())
    async with bot.db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO bot_panels (panel_key, channel_id, message_id)
            VALUES ('application_start', $1, $2)
            ON CONFLICT (panel_key) DO UPDATE SET channel_id=EXCLUDED.channel_id, message_id=EXCLUDED.message_id
            """,
            channel.id,
            message.id,
        )


async def fetch_application(app_id: int) -> asyncpg.Record | None:
    if not bot.db_pool:
        return None
    async with bot.db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM applications WHERE id=$1", app_id)


async def delete_pending_application_message(row: asyncpg.Record) -> None:
    pending_channel_id = row["pending_channel_id"]
    pending_message_id = row["pending_message_id"]
    if not pending_channel_id or not pending_message_id:
        return
    channel = bot.get_channel(int(pending_channel_id))
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        message = await channel.fetch_message(int(pending_message_id))
        await message.delete()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


async def process_application_decision(interaction: discord.Interaction, app_id: int, accepted: bool, reason: str | None) -> None:
    row = await fetch_application(app_id)
    if not row:
        await interaction.response.send_message("I could not find that application.", ephemeral=True)
        return
    if row["status"] != "pending":
        await interaction.response.send_message("That application has already been processed.", ephemeral=True)
        return
    status = "accepted" if accepted else "denied"
    destination_id = CONFIG.application_accepted_channel_id if accepted else CONFIG.application_denied_channel_id
    applicant = interaction.guild.get_member(int(row["applicant_id"])) if interaction.guild else bot.get_user(int(row["applicant_id"]))
    if applicant is None:
        applicant = await bot.fetch_user(int(row["applicant_id"]))
    answers = json.loads(row["answers_json"])
    embed = build_application_embed(
        app_id,
        applicant,
        answers,
        status.title(),
        duration_seconds=row["application_duration_seconds"],
        joined_guild_at=row["applicant_joined_at"],
        submitted_at=row["created_at"],
    )
    embed.add_field(name="Processed By", value=interaction.user.mention, inline=True)
    embed.add_field(name="Reason", value=(reason or "No reason provided.")[:1024], inline=False)
    destination = bot.get_channel(destination_id)
    if isinstance(destination, discord.TextChannel):
        await destination.send(embed=embed)
    await delete_pending_application_message(row)
    async with bot.db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE applications SET status=$1, decided_by=$2, decision_reason=$3, decided_at=$4 WHERE id=$5",
            status,
            interaction.user.id,
            reason,
            utcnow(),
            app_id,
        )
    try:
        await applicant.send(
            embed=application_notice_embed(
                f"Application {status.title()}",
                f"Your **[E&T] Entrance Exam** application has been **{status}**."
                + (f"\n\n**Reason:** {reason}" if reason else ""),
                APPLICATION_ACCEPTED_COLOR if accepted else APPLICATION_DENIED_COLOR,
            )
        )
    except discord.Forbidden:
        pass
    if interaction.message and interaction.message.id != row["pending_message_id"]:
        await interaction.message.edit(view=None)
    await interaction.response.send_message(f"Application #{app_id} has been {status}.", ephemeral=True)


async def open_application_ticket(interaction: discord.Interaction, app_id: int) -> None:
    row = await fetch_application(app_id)
    if not row:
        await interaction.response.send_message("I could not find that application.", ephemeral=True)
        return
    if row["ticket_channel_id"]:
        await interaction.response.send_message(f"A ticket already exists: <#{row['ticket_channel_id']}>", ephemeral=True)
        return
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("Tickets can only be opened in the server.", ephemeral=True)
        return
    applicant = guild.get_member(int(row["applicant_id"])) or await guild.fetch_member(int(row["applicant_id"]))
    category = guild.get_channel(CONFIG.application_ticket_category_id)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        applicant: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),
    }
    for role_id in CONFIG.application_management_role_ids:
        role = guild.get_role(role_id)
        if role:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    channel = await guild.create_text_channel(
        name=f"app-{app_id}-{applicant.name}"[:100],
        category=category if isinstance(category, discord.CategoryChannel) else None,
        overwrites=overwrites,
        topic=f"Application #{app_id} discussion for {applicant} ({applicant.id})",
        reason=f"Application #{app_id} ticket opened by {interaction.user}",
    )
    async with bot.db_pool.acquire() as conn:
        await conn.execute("UPDATE applications SET ticket_channel_id=$1 WHERE id=$2", channel.id, app_id)
    await channel.send(
        f"{applicant.mention} <@&1520155690587390082> <@&1520155715455549530>",
        embed=build_application_ticket_embed(app_id, applicant, interaction.user),
        view=ApplicationTicketView(),
    )
    await interaction.response.send_message(f"Ticket opened: {channel.mention}", ephemeral=True)


# ============================================================
# /verify
# ============================================================

@bot.tree.command(name="verify", description="Link your Discord account to your Roblox account.")
@app_commands.describe(roblox_username="Your exact Roblox username")
async def verify(interaction: discord.Interaction, roblox_username: str) -> None:
    if not await require_db(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    result = await lookup_roblox_user(roblox_username)
    if not result:
        await interaction.followup.send("I could not find that Roblox username.", ephemeral=True)
        return
    roblox_id, roblox_name = result
    async with bot.db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO roblox_verification (discord_id, roblox_id, roblox_username, verified_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (discord_id)
            DO UPDATE SET roblox_id=EXCLUDED.roblox_id, roblox_username=EXCLUDED.roblox_username, verified_at=EXCLUDED.verified_at
            """,
            interaction.user.id,
            roblox_id,
            roblox_name,
            utcnow(),
        )
    await bot.log_command(
        "Verification Linked",
        f"User: {interaction.user.mention}\nRoblox: **{roblox_name}** (`{roblox_id}`)",
        CONFIG.department_color,
    )
    await interaction.followup.send(f"Successfully verified as **{roblox_name}**.", ephemeral=True)


# ============================================================
# /verification commands
# ============================================================

@verification_group.command(name="audit", description="(Mgmt) List department role members who have not verified yet.")
async def verification_audit(interaction: discord.Interaction) -> None:
    if not await require_db(interaction):
        return
    if not isinstance(interaction.user, discord.Member) or not can_manage_activity(interaction.user):
        await interaction.response.send_message("You do not have permission to run verification audits.", ephemeral=True)
        return
    if not interaction.guild:
        await interaction.response.send_message("Verification audits can only be run in the server.", ephemeral=True)
        return
    if not CONFIG.department_role_id:
        await interaction.response.send_message("DEPARTMENT_ROLE_ID is not configured, so I cannot audit department members.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    role = interaction.guild.get_role(CONFIG.department_role_id)
    if not role:
        await interaction.followup.send("I could not find the configured department role in this server.", ephemeral=True)
        return

    try:
        await interaction.guild.chunk(cache=True)
    except Exception:
        # Continue with the members currently cached for the role.
        pass

    department_members = [member for member in role.members if not member.bot]
    member_ids = [member.id for member in department_members]

    verified_ids: set[int] = set()
    if member_ids:
        async with bot.db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT discord_id FROM roblox_verification WHERE discord_id = ANY($1::bigint[])",
                member_ids,
            )
        verified_ids = {int(row["discord_id"]) for row in rows}

    unverified = sorted(
        (member for member in department_members if member.id not in verified_ids),
        key=lambda member: member.display_name.lower(),
    )

    if unverified:
        lines = [f"{idx}. {member.mention} (`{member.id}`)" for idx, member in enumerate(unverified[:50], start=1)]
        if len(unverified) > 50:
            lines.append(f"…and {len(unverified) - 50} more.")
        description = "\n".join(lines)
    else:
        description = "All cached department role members have verified with the bot."

    embed = discord.Embed(
        title=f"{CONFIG.department_abbrev} Verification Audit",
        description=description,
        color=CONFIG.department_color,
        timestamp=utcnow(),
    )
    embed.add_field(name="Department Role", value=role.mention, inline=True)
    embed.add_field(name="Members Checked", value=str(len(department_members)), inline=True)
    embed.add_field(name="Unverified", value=str(len(unverified)), inline=True)
    embed.set_footer(text=CONFIG.department_name)

    await bot.log_command(
        "Verification Audit Run",
        f"By: {interaction.user.mention}\nRole: {role.mention}\nMembers checked: **{len(department_members)}**\nUnverified: **{len(unverified)}**",
        CONFIG.department_color,
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


# ============================================================
# /activity commands
# ============================================================

def activity_status(minutes: int) -> str:
    if minutes >= CONFIG.weekly_time_requirement:
        return "✅ Met Requirement"
    if minutes > 0:
        return "❌ Below Requirement"
    return "🚫 No Activity"


async def build_activity_report(guild: discord.Guild, wk: str | None = None) -> tuple[discord.Embed, dict[str, Any]]:
    wk = wk or week_key()
    assert bot.db_pool is not None
    async with bot.db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                COALESCE(v_by_activity_roblox.discord_id, v_by_stored_id.discord_id, a.discord_id) AS discord_id,
                MAX(COALESCE(v_by_activity_roblox.roblox_username, v_by_discord.roblox_username, v_by_stored_id.roblox_username)) AS roblox_username,
                COALESCE(SUM(a.minutes), 0)::INT AS minutes
            FROM roblox_activity a
            LEFT JOIN roblox_verification v_by_activity_roblox
                ON a.roblox_id IS NOT NULL AND v_by_activity_roblox.roblox_id = a.roblox_id
            LEFT JOIN roblox_verification v_by_discord
                ON v_by_discord.discord_id = a.discord_id
            LEFT JOIN roblox_verification v_by_stored_id
                ON v_by_stored_id.roblox_id = a.discord_id
            WHERE a.week_key=$1
            GROUP BY 1
            """,
            wk,
        )

    minute_map = {int(row["discord_id"]): int(row["minutes"] or 0) for row in rows}
    roblox_name_map = {int(row["discord_id"]): row["roblox_username"] for row in rows if row["roblox_username"]}

    # Include department role members so no-activity people appear, if configured.
    member_ids: set[int] = set(minute_map.keys())
    if CONFIG.department_role_id:
        role = guild.get_role(CONFIG.department_role_id)
        if role:
            member_ids.update(member.id for member in role.members if not member.bot)

    met: list[str] = []
    below: list[str] = []
    none: list[str] = []
    records = []
    for member_id in sorted(member_ids):
        member = guild.get_member(member_id)
        name = member.display_name if member else roblox_name_map.get(member_id, f"Unknown ({member_id})")
        minutes = minute_map.get(member_id, 0)
        line = f"**{name}** — {fmt_minutes(minutes)}/{fmt_minutes(CONFIG.weekly_time_requirement)}"
        records.append({"discord_id": member_id, "name": name, "minutes": minutes})
        if minutes >= CONFIG.weekly_time_requirement:
            met.append(line)
        elif minutes > 0:
            below.append(line)
        else:
            none.append(line)

    def block(lines: list[str]) -> str:
        return "\n".join(lines[:30]) if lines else "—"

    embed = discord.Embed(
        title=f"{CONFIG.department_name} Weekly Activity Report",
        description=f"Week: **{wk}**\nRequirement: **{fmt_minutes(CONFIG.weekly_time_requirement)}**",
        color=CONFIG.department_color,
        timestamp=utcnow(),
    )
    embed.add_field(name=f"✅ Met Requirement ({len(met)})", value=block(met), inline=False)
    embed.add_field(name=f"❌ Below Requirement ({len(below)})", value=block(below), inline=False)
    embed.add_field(name=f"🚫 No Activity ({len(none)})", value=block(none), inline=False)
    embed.set_footer(text=CONFIG.department_name)

    snapshot = {"week_key": wk, "requirement_minutes": CONFIG.weekly_time_requirement, "records": records}
    return embed, snapshot


@activity_group.command(name="me", description="View your weekly activity.")
async def activity_me(interaction: discord.Interaction) -> None:
    if not await require_db(interaction):
        return
    async with bot.db_pool.acquire() as conn:
        weekly = await bot.fetch_weekly_minutes(conn, interaction.user.id)
        all_time = await bot.fetch_all_time_minutes(conn, interaction.user.id)
        strikes = await bot.active_strike_count(conn, interaction.user.id)
    embed = discord.Embed(title="Your Activity", color=CONFIG.department_color, timestamp=utcnow())
    embed.add_field(name="This Week", value=f"{fmt_minutes(weekly)}/{fmt_minutes(CONFIG.weekly_time_requirement)}", inline=True)
    embed.add_field(name="Status", value=activity_status(weekly), inline=True)
    embed.add_field(name="All-Time", value=fmt_minutes(all_time), inline=True)
    embed.add_field(name="Active Strikes", value=f"{strikes}/{CONFIG.max_strikes}", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@activity_group.command(name="member", description="View a member's activity.")
@app_commands.describe(member="Member to check")
async def activity_member(interaction: discord.Interaction, member: discord.Member) -> None:
    if not await require_db(interaction):
        return
    if member.id != interaction.user.id and not can_manage_activity(interaction.user):
        await interaction.response.send_message("You do not have permission to view other members' activity.", ephemeral=True)
        return
    async with bot.db_pool.acquire() as conn:
        weekly = await bot.fetch_weekly_minutes(conn, member.id)
        all_time = await bot.fetch_all_time_minutes(conn, member.id)
        strikes = await bot.active_strike_count(conn, member.id)
        verified = await conn.fetchrow("SELECT roblox_username, roblox_id FROM roblox_verification WHERE discord_id=$1", member.id)
    embed = discord.Embed(title=f"Activity for {member.display_name}", color=CONFIG.department_color, timestamp=utcnow())
    embed.add_field(name="This Week", value=f"{fmt_minutes(weekly)}/{fmt_minutes(CONFIG.weekly_time_requirement)}", inline=True)
    embed.add_field(name="Status", value=activity_status(weekly), inline=True)
    embed.add_field(name="All-Time", value=fmt_minutes(all_time), inline=True)
    embed.add_field(name="Active Strikes", value=f"{strikes}/{CONFIG.max_strikes}", inline=True)
    if verified:
        embed.add_field(name="Roblox", value=f"{verified['roblox_username']} (`{verified['roblox_id']}`)", inline=False)
    else:
        embed.add_field(name="Roblox", value="Not verified", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@activity_group.command(name="leaderboard", description="Show the weekly activity leaderboard.")
async def activity_leaderboard(interaction: discord.Interaction) -> None:
    if not await require_db(interaction):
        return
    async with bot.db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                COALESCE(v_by_activity_roblox.discord_id, v_by_stored_id.discord_id, a.discord_id) AS discord_id,
                MAX(COALESCE(v_by_activity_roblox.roblox_username, v_by_discord.roblox_username, v_by_stored_id.roblox_username)) AS roblox_username,
                COALESCE(SUM(a.minutes), 0)::INT AS minutes
            FROM roblox_activity a
            LEFT JOIN roblox_verification v_by_activity_roblox
                ON a.roblox_id IS NOT NULL AND v_by_activity_roblox.roblox_id = a.roblox_id
            LEFT JOIN roblox_verification v_by_discord
                ON v_by_discord.discord_id = a.discord_id
            LEFT JOIN roblox_verification v_by_stored_id
                ON v_by_stored_id.roblox_id = a.discord_id
            WHERE a.week_key=$1
            GROUP BY 1
            ORDER BY minutes DESC
            LIMIT 10
            """,
            week_key(),
        )
    if not rows:
        await interaction.response.send_message("No activity has been tracked this week.", ephemeral=True)
        return
    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for idx, row in enumerate(rows, start=1):
        member = interaction.guild.get_member(int(row["discord_id"])) if interaction.guild else None
        name = member.display_name if member else (row["roblox_username"] or f"Unknown ({row['discord_id']})")
        prefix = medals[idx - 1] if idx <= 3 else f"**{idx}.**"
        lines.append(f"{prefix} **{name}** — {fmt_minutes(int(row['minutes']))}")
    embed = discord.Embed(
        title=f"🏆 {CONFIG.department_abbrev} Weekly Activity Leaderboard",
        description="\n".join(lines),
        color=CONFIG.department_color,
        timestamp=utcnow(),
    )
    await interaction.response.send_message(embed=embed)


@activity_group.command(name="add", description="(Mgmt) Manually add activity time to a member.")
@app_commands.describe(member="Member to credit", minutes="Minutes to add", reason="Reason for the adjustment")
async def activity_add(interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 10000], reason: str) -> None:
    if not await require_db(interaction):
        return
    if not can_manage_activity(interaction.user):
        await interaction.response.send_message("You do not have permission to adjust activity.", ephemeral=True)
        return
    async with bot.db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO roblox_activity (discord_id, roblox_id, week_key, minutes, source, reason) VALUES ($1, NULL, $2, $3, 'manual_add', $4)",
            member.id,
            week_key(),
            int(minutes),
            reason,
        )
        await conn.execute(
            "INSERT INTO activity_adjustments (discord_id, minutes_delta, reason, adjusted_by) VALUES ($1, $2, $3, $4)",
            member.id,
            int(minutes),
            reason,
            interaction.user.id,
        )
        weekly = await bot.fetch_weekly_minutes(conn, member.id)
    await bot.log_command(
        "Activity Added",
        f"By: {interaction.user.mention}\nMember: {member.mention}\nAdded: **{fmt_minutes(minutes)}**\nReason: {reason}\nNew weekly total: **{fmt_minutes(weekly)}**",
        CONFIG.department_color,
    )
    await interaction.response.send_message(f"Added **{fmt_minutes(minutes)}** to {member.mention}. New weekly total: **{fmt_minutes(weekly)}**.", ephemeral=True)


@activity_group.command(name="remove", description="(Mgmt) Manually remove activity time from a member.")
@app_commands.describe(member="Member to adjust", minutes="Minutes to remove", reason="Reason for the adjustment")
async def activity_remove(interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 10000], reason: str) -> None:
    if not await require_db(interaction):
        return
    if not can_manage_activity(interaction.user):
        await interaction.response.send_message("You do not have permission to adjust activity.", ephemeral=True)
        return
    delta = -int(minutes)
    async with bot.db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO roblox_activity (discord_id, roblox_id, week_key, minutes, source, reason) VALUES ($1, NULL, $2, $3, 'manual_remove', $4)",
            member.id,
            week_key(),
            delta,
            reason,
        )
        await conn.execute(
            "INSERT INTO activity_adjustments (discord_id, minutes_delta, reason, adjusted_by) VALUES ($1, $2, $3, $4)",
            member.id,
            delta,
            reason,
            interaction.user.id,
        )
        weekly = await bot.fetch_weekly_minutes(conn, member.id)
    await bot.log_command(
        "Activity Removed",
        f"By: {interaction.user.mention}\nMember: {member.mention}\nRemoved: **{fmt_minutes(minutes)}**\nReason: {reason}\nNew weekly total: **{fmt_minutes(max(weekly, 0))}**",
        discord.Color.orange(),
    )
    await interaction.response.send_message(f"Removed **{fmt_minutes(minutes)}** from {member.mention}. New weekly total: **{fmt_minutes(max(weekly, 0))}**.", ephemeral=True)


@activity_group.command(name="weekly_preview", description="(Mgmt) Preview the weekly activity report.")
async def activity_weekly_preview(interaction: discord.Interaction) -> None:
    if not await require_db(interaction):
        return
    if not can_manage_activity(interaction.user):
        await interaction.response.send_message("You do not have permission to preview weekly reports.", ephemeral=True)
        return
    embed, _ = await build_activity_report(interaction.guild)
    embed.title += " (Preview)"
    await interaction.response.send_message(embed=embed, ephemeral=True)


@activity_group.command(name="report", description="(Mgmt) Post the weekly activity report.")
async def activity_report(interaction: discord.Interaction) -> None:
    if not await require_db(interaction):
        return
    if not can_manage_activity(interaction.user):
        await interaction.response.send_message("You do not have permission to post weekly reports.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    embed, snapshot = await build_activity_report(interaction.guild)
    channel = bot.get_channel(CONFIG.weekly_report_channel_id) if CONFIG.weekly_report_channel_id else interaction.channel
    await channel.send(embed=embed)
    async with bot.db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO weekly_snapshots (week_key, report_json, created_by) VALUES ($1, $2, $3)",
            week_key(),
            json.dumps(snapshot),
            interaction.user.id,
        )
    await bot.log_command("Weekly Activity Report Posted", f"By: {interaction.user.mention}\nWeek: **{week_key()}**", CONFIG.department_color)
    await interaction.followup.send("Weekly activity report posted.", ephemeral=True)


@activity_group.command(name="reset", description="(Mgmt) Reset this week's activity totals.")
async def activity_reset(interaction: discord.Interaction) -> None:
    if not await require_db(interaction):
        return
    if not can_manage_activity(interaction.user):
        await interaction.response.send_message("You do not have permission to reset activity.", ephemeral=True)
        return
    wk = week_key()
    async with bot.db_pool.acquire() as conn:
        deleted = await conn.execute("DELETE FROM roblox_activity WHERE week_key=$1", wk)
        await conn.execute("DELETE FROM roblox_sessions")
    await bot.log_command("Weekly Activity Reset", f"By: {interaction.user.mention}\nWeek reset: **{wk}**\nResult: `{deleted}`", discord.Color.orange())
    await interaction.response.send_message(f"Weekly activity for **{wk}** has been reset.", ephemeral=True)


# ============================================================
# /strikes commands
# ============================================================

@strikes_group.command(name="add", description="(Mgmt) Add a strike to a member.")
@app_commands.describe(member="Member receiving the strike", reason="Reason for the strike", duration_days="How long the strike lasts")
async def strikes_add(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str,
    duration_days: app_commands.Range[int, 1, 365] | None = None,
) -> None:
    if not await require_db(interaction):
        return
    if not can_manage_strikes(interaction.user):
        await interaction.response.send_message("You do not have permission to manage strikes.", ephemeral=True)
        return
    days = int(duration_days or CONFIG.default_strike_duration_days)
    expires = utcnow() + dt.timedelta(days=days)
    async with bot.db_pool.acquire() as conn:
        strike_id = await conn.fetchval(
            """
            INSERT INTO strikes (member_id, reason, issued_by, issued_at, expires_at, active, auto)
            VALUES ($1, $2, $3, $4, $5, TRUE, FALSE)
            RETURNING strike_id
            """,
            member.id,
            reason,
            interaction.user.id,
            utcnow(),
            expires,
        )
        active = await bot.active_strike_count(conn, member.id)
    await bot.log_command(
        "Strike Added",
        f"By: {interaction.user.mention}\nMember: {member.mention}\nStrike ID: `{strike_id}`\nActive strikes: **{active}/{CONFIG.max_strikes}**\nExpires: <t:{int(expires.timestamp())}:F>\nReason: {reason}",
        discord.Color.red(),
    )
    await interaction.response.send_message(f"Strike `{strike_id}` added to {member.mention}. Active strikes: **{active}/{CONFIG.max_strikes}**.", ephemeral=True)


@strikes_group.command(name="view", description="View active strikes for a member.")
@app_commands.describe(member="Member to check")
async def strikes_view(interaction: discord.Interaction, member: discord.Member | None = None) -> None:
    if not await require_db(interaction):
        return
    target = member or interaction.user
    if target.id != interaction.user.id and not can_manage_strikes(interaction.user):
        await interaction.response.send_message("You do not have permission to view other members' strikes.", ephemeral=True)
        return
    async with bot.db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT strike_id, reason, issued_by, issued_at, expires_at, auto
            FROM strikes
            WHERE member_id=$1 AND active=TRUE AND expires_at>$2
            ORDER BY issued_at DESC
            """,
            target.id,
            utcnow(),
        )
    if not rows:
        await interaction.response.send_message(f"{target.display_name} has no active strikes.", ephemeral=True)
        return
    lines = []
    for row in rows:
        issuer = f"<@{row['issued_by']}>" if row["issued_by"] else "System"
        auto_text = "Auto" if row["auto"] else "Manual"
        lines.append(
            f"**ID `{row['strike_id']}`** — {auto_text}\n"
            f"Reason: {row['reason']}\n"
            f"Issued by: {issuer}\n"
            f"Expires: <t:{int(row['expires_at'].timestamp())}:R>"
        )
    embed = discord.Embed(title=f"Active Strikes for {target.display_name}", description="\n\n".join(lines), color=discord.Color.red(), timestamp=utcnow())
    await interaction.response.send_message(embed=embed, ephemeral=True)


@strikes_group.command(name="remove", description="(Mgmt) Remove a strike by ID.")
@app_commands.describe(strike_id="The strike ID", reason="Reason for removing the strike")
async def strikes_remove(interaction: discord.Interaction, strike_id: int, reason: str) -> None:
    if not await require_db(interaction):
        return
    if not can_manage_strikes(interaction.user):
        await interaction.response.send_message("You do not have permission to manage strikes.", ephemeral=True)
        return
    async with bot.db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT member_id, active FROM strikes WHERE strike_id=$1", strike_id)
        if not row:
            await interaction.response.send_message("That strike ID does not exist.", ephemeral=True)
            return
        if not row["active"]:
            await interaction.response.send_message("That strike is already inactive.", ephemeral=True)
            return
        await conn.execute(
            """
            UPDATE strikes
            SET active=FALSE, removed_by=$1, removed_reason=$2, removed_at=$3
            WHERE strike_id=$4
            """,
            interaction.user.id,
            reason,
            utcnow(),
            strike_id,
        )
    await bot.log_command(
        "Strike Removed",
        f"By: {interaction.user.mention}\nStrike ID: `{strike_id}`\nMember: <@{row['member_id']}>\nReason: {reason}",
        CONFIG.department_color,
    )
    await interaction.response.send_message(f"Strike `{strike_id}` has been removed.", ephemeral=True)


@strikes_group.command(name="clear", description="(Mgmt) Clear all active strikes from a member.")
@app_commands.describe(member="Member whose active strikes should be cleared", reason="Reason for clearing strikes")
async def strikes_clear(interaction: discord.Interaction, member: discord.Member, reason: str) -> None:
    if not await require_db(interaction):
        return
    if not can_manage_strikes(interaction.user):
        await interaction.response.send_message("You do not have permission to manage strikes.", ephemeral=True)
        return
    async with bot.db_pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE strikes
            SET active=FALSE, removed_by=$1, removed_reason=$2, removed_at=$3
            WHERE member_id=$4 AND active=TRUE AND expires_at>$5
            """,
            interaction.user.id,
            reason,
            utcnow(),
            member.id,
            utcnow(),
        )
    await bot.log_command(
        "Strikes Cleared",
        f"By: {interaction.user.mention}\nMember: {member.mention}\nResult: `{result}`\nReason: {reason}",
        CONFIG.department_color,
    )
    await interaction.response.send_message(f"Active strikes cleared for {member.mention}.", ephemeral=True)


# ============================================================
# /rank and /welcome
# ============================================================

@bot.tree.command(name="rank", description="(Mgmt) Change a verified member's Roblox group rank.")
@app_commands.autocomplete(rank=rank_autocomplete)
@app_commands.describe(member="Discord member to rank", rank="Exact Roblox group rank name")
async def rank_member(interaction: discord.Interaction, member: discord.Member, rank: str) -> None:
    if not await require_db(interaction):
        return
    if not can_manage_ranks(interaction.user):
        await interaction.response.send_message("You do not have permission to manage ranks.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    verified = await bot.get_verified_roblox(member.id)
    if not verified:
        await interaction.followup.send("That member has not verified their Roblox account yet.", ephemeral=True)
        return
    try:
        final_rank = await set_group_rank(int(verified["roblox_id"]), rank)
    except Exception as exc:
        await interaction.followup.send(f"Ranking failed: `{exc}`", ephemeral=True)
        await bot.log_command("Rank Update Failed", f"By: {interaction.user.mention}\nMember: {member.mention}\nRank: `{rank}`\nError: `{exc}`", discord.Color.red())
        return

    async with bot.db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO member_ranks (discord_id, rank_name, set_by, set_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (discord_id)
            DO UPDATE SET rank_name=EXCLUDED.rank_name, set_by=EXCLUDED.set_by, set_at=EXCLUDED.set_at
            """,
            member.id,
            final_rank,
            interaction.user.id,
            utcnow(),
        )
    await bot.log_command(
        "Rank Updated",
        f"By: {interaction.user.mention}\nMember: {member.mention}\nRoblox: **{verified['roblox_username']}** (`{verified['roblox_id']}`)\nNew Rank: **{final_rank}**",
        CONFIG.department_color,
    )
    await interaction.followup.send(f"Updated {member.mention}'s Roblox rank to **{final_rank}**.", ephemeral=True)


@bot.tree.command(name="welcome", description="(Mgmt) Send the configurable welcome message for a member.")
@app_commands.describe(member="Member to welcome", channel="Optional channel to send the welcome message in")
async def welcome(interaction: discord.Interaction, member: discord.Member, channel: discord.TextChannel | None = None) -> None:
    if not can_send_welcome(interaction.user):
        await interaction.response.send_message("You do not have permission to send welcome messages.", ephemeral=True)
        return
    target = channel or (bot.get_channel(CONFIG.welcome_channel_id) if CONFIG.welcome_channel_id else interaction.channel)
    if not isinstance(target, discord.TextChannel):
        await interaction.response.send_message("I could not find a valid welcome channel.", ephemeral=True)
        return
    message = CONFIG.welcome_message.format(
        member=member.mention,
        member_name=member.display_name,
        department=CONFIG.department_name,
        welcome_department=CONFIG.welcome_department_display,
        abbreviation=CONFIG.department_abbrev,
        group_url=CONFIG.department_group_url,
        description=CONFIG.department_description,
        guidelines_channel=CONFIG.welcome_guidelines_channel,
        internship_url=CONFIG.welcome_internship_url,
    )
    embed = discord.Embed(title=CONFIG.welcome_title, description=message, color=CONFIG.department_color, timestamp=utcnow())
    embed.set_footer(text=CONFIG.department_name)
    await target.send(content=member.mention, embed=embed)
    await bot.log_command("Welcome Sent", f"By: {interaction.user.mention}\nMember: {member.mention}\nChannel: {target.mention}", CONFIG.department_color)
    await interaction.response.send_message(f"Welcome message sent in {target.mention}.", ephemeral=True)


# ============================================================
# Optional weekly scheduler
# ============================================================

@tasks.loop(minutes=30)
async def weekly_scheduler() -> None:
    if not bot.db_pool or not CONFIG.auto_weekly_report and not CONFIG.auto_weekly_reset:
        return
    now = utcnow()
    if now.weekday() != CONFIG.auto_report_weekday_utc or now.hour != CONFIG.auto_report_hour_utc:
        return
    # Guard: only run once per configured hour by writing a snapshot marker.
    marker_week = week_key(now)
    async with bot.db_pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT 1 FROM weekly_snapshots WHERE week_key=$1 AND report_json->>'auto_marker'='true'",
            marker_week,
        )
        if existing:
            return
    channel = bot.get_channel(CONFIG.weekly_report_channel_id) if CONFIG.weekly_report_channel_id else None
    report_guild = getattr(channel, "guild", None) or (bot.guilds[0] if bot.guilds else None)
    snapshot: dict[str, Any] = {"week_key": marker_week}
    action_performed = False

    if CONFIG.auto_weekly_report and channel and report_guild:
        embed, snapshot = await build_activity_report(report_guild, marker_week)
        await channel.send(embed=embed)
        action_performed = True
        await bot.log_command("Auto Weekly Report Posted", f"Week: **{marker_week}**", CONFIG.department_color)

    if CONFIG.auto_weekly_reset:
        async with bot.db_pool.acquire() as conn:
            await conn.execute("DELETE FROM roblox_activity WHERE week_key=$1", marker_week)
            await conn.execute("DELETE FROM roblox_sessions")
        action_performed = True
        await bot.log_command("Auto Weekly Activity Reset", f"Week: **{marker_week}**", discord.Color.orange())

    if not action_performed:
        return

    async with bot.db_pool.acquire() as conn:
        snapshot["auto_marker"] = "true"
        await conn.execute(
            "INSERT INTO weekly_snapshots (week_key, report_json, created_by) VALUES ($1, $2, NULL)",
            marker_week,
            json.dumps(snapshot),
        )


# ============================================================
# Entrypoint
# ============================================================

if __name__ == "__main__":
    if not CONFIG.bot_token:
        raise RuntimeError("Missing BOT_TOKEN in environment.")
    bot.run(CONFIG.bot_token)
