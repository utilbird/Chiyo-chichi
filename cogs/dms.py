from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import discord
from discord.ext import commands, tasks

log = logging.getLogger("deadman_switch")

# ---------------------------------------------------------------------------
# Configuration (TODO: put it in the actual config file)
# ---------------------------------------------------------------------------

DATA_FILE = Path(__file__).resolve().parent.parent / "store" / "deadman_switches.json"
ATTACHMENTS_DIR = Path(__file__).resolve().parent.parent / "store" / "deadman_attachments"
CHECK_INTERVAL_SECONDS = 60            # how often the background loop wakes up
MIN_SWITCH_SECONDS = 5 * 60            # 5 minutes - stops accidental instant triggers
MAX_SWITCH_SECONDS = 365 * 24 * 3600   # 1 year - sanity cap
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024  # 8 MB - stay well under Discord's DM upload cap

# Send the author a reminder DM once the remaining time drops below each of
# these thresholds. Only thresholds smaller than a given switch's total
# duration are actually used for that switch.
REMINDER_THRESHOLDS = [
    7 * 24 * 3600,   # 1 week
    3 * 24 * 3600,   # 3 days
    24 * 3600,       # 1 day
    6 * 3600,        # 6 hours
    3600,            # 1 hour
    15 * 60,         # 15 minutes
]

_DURATION_RE = re.compile(
    r"^\s*"
    r"(?:(?P<weeks>\d+)\s*w)?"
    r"(?:(?P<days>\d+)\s*d)?"
    r"(?:(?P<hours>\d+)\s*h)?"
    r"(?:(?P<minutes>\d+)\s*m)?"
    r"(?:(?P<seconds>\d+)\s*s)?"
    r"\s*$",
    re.IGNORECASE,
)


def parse_duration(text: str) -> int:
    """Parse strings like '3d', '36h', '1w2d', '90m' into seconds."""
    match = _DURATION_RE.match(text)
    if not match or not any(match.groupdict().values()):
        raise ValueError(
            f"Couldn't parse `{text}` as a duration. Combine w(eeks), d(ays), "
            "h(ours), m(inutes), s(econds), e.g. `3d`, `36h`, `1w2d`."
        )
    units = {k: int(v) for k, v in match.groupdict().items() if v}
    seconds = (
        units.get("weeks", 0) * 7 * 24 * 3600
        + units.get("days", 0) * 24 * 3600
        + units.get("hours", 0) * 3600
        + units.get("minutes", 0) * 60
        + units.get("seconds", 0)
    )
    if seconds <= 0:
        raise ValueError("Duration must be greater than zero.")
    return seconds


def format_duration(seconds: float) -> str:
    """Turn a number of seconds into a short human-readable string."""
    seconds = int(max(seconds, 0))
    weeks, seconds = divmod(seconds, 7 * 24 * 3600)
    days, seconds = divmod(seconds, 24 * 3600)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if weeks:
        parts.append(f"{weeks}w")
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class DeadManSwitch(commands.Cog):
    """Manage per-user dead man's switches."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._lock = asyncio.Lock()
        self.data: dict[str, Any] = self._load()
        self.check_loop.start()

    def cog_unload(self) -> None:
        self.check_loop.cancel()

    # -- persistence --------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if DATA_FILE.exists():
            try:
                with DATA_FILE.open("r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                log.exception("Failed to load %s, starting fresh.", DATA_FILE)
        return {"switches": {}}

    def _save(self) -> None:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = DATA_FILE.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2)
        tmp_path.replace(DATA_FILE)  # atomic replace on POSIX and Windows

    # -- helpers --------------------------------------------------------

    def _switches_for(self, author_id: int) -> dict[str, Any]:
        return {
            sid: sw
            for sid, sw in self.data["switches"].items()
            if sw["author_id"] == author_id
        }

    async def _dm(self, user_id: int, content: str, file_path: Path | None = None) -> bool:
        """Best-effort DM, optionally with a file attached. Returns True on success."""
        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            if file_path and file_path.exists():
                await user.send(content, file=discord.File(file_path, filename=file_path.name))
            else:
                await user.send(content)
            return True
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, OSError):
            log.warning("Could not DM user %s", user_id, exc_info=True)
            return False

    async def _save_attachment(self, sid: str, attachment: discord.Attachment) -> Path:
        """Download a command attachment to disk so it survives past the
        original Discord message (CDN URL can expire or be deleted)."""
        switch_dir = ATTACHMENTS_DIR / sid
        switch_dir.mkdir(parents=True, exist_ok=True)
        dest = switch_dir / attachment.filename
        await attachment.save(dest)
        return dest

    def _delete_attachment(self, sid: str) -> None:
        switch_dir = ATTACHMENTS_DIR / sid
        if switch_dir.exists():
            shutil.rmtree(switch_dir, ignore_errors=True)

    # -- background loop --------------------------------------------------

    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def check_loop(self) -> None:
        now = time.time()
        dirty = False

        async with self._lock:
            for sid, sw in list(self.data["switches"].items()):
                deadline = sw["last_checkin"] + sw["interval"]
                remaining = deadline - now

                if remaining <= 0:
                    await self._fire(sid, sw)
                    dirty = True
                    continue

                for threshold in REMINDER_THRESHOLDS:
                    if threshold >= sw["interval"]:
                        continue  # not meaningful for a switch this short
                    if remaining <= threshold and threshold not in sw["reminders_sent"]:
                        await self._dm(
                            sw["author_id"],
                            (
                                f"⏰ **Dead man's switch reminder** (id `{sid}`)\n"
                                f"This switch fires in about **{format_duration(remaining)}** "
                                f"unless you check in.\n"
                                f"Check in with: `deadman checkin {sid}`"
                            ),
                        )
                        sw["reminders_sent"].append(threshold)
                        dirty = True

        if dirty:
            self._save()

    async def _fire(self, sid: str, sw: dict[str, Any]) -> None:
        """Deliver the payload message (and attachment, if any) and remove the switch."""
        attachment_path = Path(sw["attachment"]) if sw.get("attachment") else None
        text = sw["message"] or "(no text — see attachment)"
        sent = await self._dm(
            sw["recipient_id"],
            (
                f"You've received a message via a dead man's switch set up by "
                f"<@{sw['author_id']}> (user ID {sw['author_id']}):\n\n"
                f"{text}"
            ),
            file_path=attachment_path,
        )
        await self._dm(
            sw["author_id"],
            (
                f"🔴 Your dead man's switch (id `{sid}`) has fired. The message was "
                f"{'delivered' if sent else 'attempted, but delivery failed'} to "
                f"<@{sw['recipient_id']}>."
            ),
        )
        self._delete_attachment(sid)
        del self.data["switches"][sid]

    @check_loop.before_loop
    async def before_check_loop(self) -> None:
        await self.bot.wait_until_ready()

    # -- commands (all DM-only) -------------------------------------------

    @commands.group(name="deadman", invoke_without_command=True)
    @commands.dm_only()
    async def deadman(self, ctx: commands.Context) -> None:
        """Manage dead man's switches."""
        await ctx.send(
            "Subcommands:\n"
            "`deadman set <recipient_id> <duration> <message>`\n"
            "`deadman checkin <id>`\n"
            "`deadman list`\n"
            "`deadman cancel <id>`"
        )

    @deadman.command(name="set")
    @commands.dm_only()
    async def deadman_set(
        self,
        ctx: commands.Context,
        recipient_id: int,
        duration: str,
        *,
        message: str = "",
    ) -> None:
        """Arm a new switch.

        Example:
            deadman set 123456789012345678 3d Here's the safe combination: ...
            (with a file attached to the same message, message text is now optional)
        """
        attachment = None
        if ctx.message.attachments:
            if ctx.message.attachments.count > 1:
                await ctx.send("Attachment limited to 1 per message") # I'm lazy
                return
            attachment = ctx.message.attachments[0]

        if not message and not attachment:
            await ctx.send("Provide a message, an attachment, or both.")
            return

        if attachment:
            # I don't *THINK* I need any other sanity checks
            if attachment.size > MAX_ATTACHMENT_BYTES:
                await ctx.send(
                    f"Attachment is too large (max {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB)."
                )
                return

        try:
            seconds = parse_duration(duration)
        except ValueError as exc:
            await ctx.send(str(exc))
            return

        if seconds < MIN_SWITCH_SECONDS:
            await ctx.send(f"Duration must be at least {format_duration(MIN_SWITCH_SECONDS)}.")
            return
        if seconds > MAX_SWITCH_SECONDS:
            await ctx.send(f"Duration can't exceed {format_duration(MAX_SWITCH_SECONDS)}.")
            return

        try:
            recipient = self.bot.get_user(recipient_id) or await self.bot.fetch_user(recipient_id)
        except discord.NotFound:
            await ctx.send("I can't find a user with that ID.")
            return
        except discord.HTTPException:
            await ctx.send("Discord wouldn't let me look up that user ID. Try again.")
            return

        sid = uuid.uuid4().hex[:8]
        # for the 1 in 4 billion chance
        while sid in self.data["switches"]:
            sid = uuid.uuid4().hex[:8]
        attachment_path = await self._save_attachment(sid, attachment) if attachment else None

        async with self._lock:
            self.data["switches"][sid] = {
                "author_id": ctx.author.id,
                "recipient_id": recipient_id,
                "message": message,
                "attachment": str(attachment_path) if attachment_path else None,
                "interval": seconds,
                "last_checkin": time.time(),
                "reminders_sent": [],
                "created_at": time.time(),
            }
            self._save()

        attach_note = f" plus `{attachment.filename}`" if attachment else ""
        await ctx.send(
            f"✅ Switch `{sid}` armed. If I don't hear a check-in from you within "
            f"**{format_duration(seconds)}**, I'll DM your message{attach_note} to "
            f"**{recipient}** ({recipient_id}).\n"
            f"Reset the timer any time with `deadman checkin {sid}`."
        )

    @deadman.command(name="checkin")
    @commands.dm_only()
    async def deadman_checkin(self, ctx: commands.Context, switch_id: str) -> None:
        """Reset the timer on one of your switches."""
        async with self._lock:
            sw = self.data["switches"].get(switch_id)
            if not sw or sw["author_id"] != ctx.author.id:
                await ctx.send("I couldn't find a switch with that id belonging to you.")
                return
            sw["last_checkin"] = time.time()
            sw["reminders_sent"] = []
            self._save()
            interval = sw["interval"]

        await ctx.send(
            f"✅ Checked in. Switch `{switch_id}` reset — next deadline in "
            f"{format_duration(interval)}."
        )

    @deadman.command(name="list")
    @commands.dm_only()
    async def deadman_list(self, ctx: commands.Context) -> None:
        """List your active switches."""
        mine = self._switches_for(ctx.author.id)
        if not mine:
            await ctx.send("You have no active dead man's switches.")
            return

        now = time.time()
        lines = []
        for sid, sw in mine.items():
            remaining = sw["last_checkin"] + sw["interval"] - now
            preview = sw["message"] if len(sw["message"]) <= 50 else sw["message"][:47] + "..."
            clip = " 📎" if sw.get("attachment") else ""
            lines.append(
                f"`{sid}` → <@{sw['recipient_id']}> in {format_duration(remaining)} — \"{preview}\"{clip}"
            )
        await ctx.send("Your active switches:\n" + "\n".join(lines))

    @deadman.command(name="cancel")
    @commands.dm_only()
    async def deadman_cancel(self, ctx: commands.Context, switch_id: str) -> None:
        """Permanently cancel one of your switches."""
        async with self._lock:
            sw = self.data["switches"].get(switch_id)
            if not sw or sw["author_id"] != ctx.author.id:
                await ctx.send("I couldn't find a switch with that id belonging to you.")
                return
            del self.data["switches"][switch_id]
            self._save()
        self._delete_attachment(switch_id)
        await ctx.send(f"🗑️ Switch `{switch_id}` cancelled.")

    # -- error handling ------------------------------------------------

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.PrivateMessageOnly):
            # Silently ignore in guild channels so switch details never leak there.
            return
        if isinstance(error, commands.BadArgument):
            await ctx.send(f"Bad argument: {error}")
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing argument: `{error.param.name}`.")
            return
        log.exception("Unhandled error in deadman switch command", exc_info=error)
        await ctx.send("Something went wrong handling that command.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DeadManSwitch(bot))