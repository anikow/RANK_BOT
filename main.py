import discord
from discord.ext import commands, tasks
import os
from dotenv import load_dotenv
import asyncio
from discord import app_commands
import json
import re
import time  # For timing the command execution
import logging
from typing import Optional, Dict, List

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Intents setup
intents = discord.Intents.default()
intents.members = True
intents.message_content = False

# Configurable parameters
AUTHORIZED_ROLE = os.getenv('AUTHORIZED_ROLE', 'Mommy')
RANK_CHANNEL_NAME = os.getenv('RANK_CHANNEL_NAME', 'rank-list')

class RankManager:
    """Class to manage user ranks."""

    def __init__(self):
        self.user_ranks: Dict[str, int] = {}
        self.rank_message_id: Optional[int] = None
        self.lock = asyncio.Lock()
        self.load_ranks_from_file()

    def load_ranks_from_file(self):
        """Synchronously load ranks and message ID from a JSON file."""
        if os.path.exists('ranks.json'):
            try:
                with open('ranks.json', 'r') as f:
                    data = json.load(f)
                    self.user_ranks = data.get('user_ranks', {})
                    self.rank_message_id = data.get('rank_message_id')
                    logger.info("Loaded ranks and rank message ID from 'ranks.json'")
            except Exception as e:
                logger.exception("Failed to load ranks from 'ranks.json'")
        else:
            logger.info("'ranks.json' not found. Starting with empty ranks.")

    def save_ranks_to_file(self):
        """Synchronously save ranks and message ID to a JSON file."""
        data = {
            'user_ranks': self.user_ranks,
            'rank_message_id': self.rank_message_id
        }
        try:
            with open('ranks.json', 'w') as f:
                json.dump(data, f, indent=4)
                logger.info("Saved ranks and rank message ID to 'ranks.json'")
        except Exception as e:
            logger.exception("Failed to save ranks to 'ranks.json'")

    @staticmethod
    def parse_rank(nickname: Optional[str]) -> Optional[int]:
        """Extract rank from a nickname."""
        if nickname:
            match = re.search(r'#\s*(\d+)$', nickname)
            if match:
                rank = int(match.group(1))
                logger.debug(f"Parsed rank {rank} from nickname '{nickname}'")
                return rank
        return None

    async def load_ranks_from_nicknames(self, guild: discord.Guild, members: List[discord.Member]):
        """Load ranks from existing member nicknames."""
        logger.info("Loading ranks from nicknames...")
        for member in members:
            nickname = member.nick
            if nickname is None:
                continue  # Skip members without a nickname
            rank = self.parse_rank(nickname)
            if rank is not None:
                self.user_ranks[str(member.id)] = rank
                logger.debug(f"Loaded rank {rank} for member {member.display_name}")
            else:
                logger.debug(f"No rank found in nickname for member {member.display_name}")
        self.save_ranks_to_file()

    async def enforce_ranks_on_discord(self, guild: discord.Guild, members: List[discord.Member]):
        """Enforce ranks from user_ranks onto Discord nicknames."""
        logger.info("Enforcing ranks on Discord nicknames...")
        for member in members:
            user_id_str = str(member.id)
            expected_rank = self.user_ranks.get(user_id_str)
            current_rank_in_nickname = self.parse_rank(member.nick)

            if expected_rank is not None:
                # Member should have a rank
                if current_rank_in_nickname != expected_rank:
                    logger.info(f"Updating rank for member {member.display_name} to {expected_rank}")
                    await self.update_nickname(member, expected_rank)
                else:
                    logger.debug(f"Member {member.display_name} already has correct rank {expected_rank}")
            else:
                # Member should not have a rank, remove any rank from nickname
                if current_rank_in_nickname is not None:
                    logger.info(f"Removing rank from member {member.display_name} as they are not in ranks.json")
                    await self.update_nickname(member, None)
                else:
                    logger.debug(f"Member {member.display_name} has no rank and is correct")

    async def update_nickname(self, member: discord.Member, new_rank: Optional[int]):
        """Update a member's nickname with the new rank or remove it."""
        # Extract the base nickname without rank
        if member.nick is not None:
            name_without_rank = re.sub(r'#\s*\d+$', '', member.nick).strip()
        else:
            name_without_rank = member.name

        # Decide the new nickname
        if new_rank is not None:
            new_nickname = f"{name_without_rank} #{new_rank}"
        else:
            new_nickname = name_without_rank

        # If the new nickname is the same as the username, set nick to None to remove nickname
        if new_nickname == member.name:
            new_nickname = None

        try:
            if member.guild.me.guild_permissions.manage_nicknames:
                await member.edit(nick=new_nickname)
                logger.info(f"Updated nickname for {member.display_name} to '{new_nickname}'")
            else:
                logger.warning(f"Cannot change nickname for {member.display_name}: Missing 'Manage Nicknames' permission.")
        except discord.Forbidden:
            logger.warning(f"Permission denied to change nickname for {member.display_name}.")
        except Exception as e:
            logger.exception(f"An error occurred while changing nickname for {member.display_name}")

        # Save only if changes were successful
        self.save_ranks_to_file()

    async def adjust_ranks(self, guild: discord.Guild, target_member_id: int, old_rank: Optional[int], new_rank: int):
        """Adjust ranks of other members based on the new rank assignment."""
        logger.info(f"Adjusting ranks in guild: {guild.name}")

        async with self.lock:
            # Remove the old rank if any
            if old_rank is not None:
                self.user_ranks.pop(str(target_member_id), None)

            # Insert the new rank
            self.user_ranks[str(target_member_id)] = new_rank

            # Reassign all ranks to ensure they are sequential and start from 1
            await self.fill_rank_gaps(guild)

            # Update the target member's nickname
            target_member = guild.get_member(target_member_id)
            if target_member is None:
                try:
                    target_member = await guild.fetch_member(target_member_id)
                except discord.NotFound:
                    logger.warning(f"Target member with ID {target_member_id} not found.")
                    return
            await self.update_nickname(target_member, new_rank)
            logger.info(f"Assigned rank {new_rank} to {target_member.display_name}")

            await self.update_rank_message(guild)  # Update the rank list message

    async def fill_rank_gaps(self, guild: discord.Guild):
        """Reassign ranks to fill any gaps."""
        logger.info("Filling rank gaps...")
        # Get all user IDs and their ranks
        rank_items = list(self.user_ranks.items())
        # Sort the items by rank
        rank_items.sort(key=lambda x: x[1])
        # Reassign ranks starting from 1
        new_user_ranks = {}
        for i, (user_id_str, _) in enumerate(rank_items, start=1):
            new_user_ranks[user_id_str] = i

        # Update nicknames if ranks have changed
        for user_id_str, new_rank in new_user_ranks.items():
            old_rank = self.user_ranks.get(user_id_str)
            if old_rank != new_rank:
                member_id = int(user_id_str)
                member = guild.get_member(member_id)
                if member is None:
                    try:
                        member = await guild.fetch_member(member_id)
                    except discord.NotFound:
                        logger.warning(f"Member with ID {member_id} not found.")
                        continue
                self.user_ranks[user_id_str] = new_rank
                await self.update_nickname(member, new_rank)
                logger.info(f"Adjusted rank of {member.display_name} from {old_rank} to {new_rank}")

        self.user_ranks = new_user_ranks
        self.save_ranks_to_file()
        await self.update_rank_message(guild)  # Update the rank list message

    async def update_rank_message(self, guild: discord.Guild):
        """Create or update the rank list message in a designated channel."""
        channel_name = RANK_CHANNEL_NAME
        channel = discord.utils.get(guild.text_channels, name=channel_name)

        if channel is None:
            # Create the channel if it doesn't exist
            try:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False)
                }
                channel = await guild.create_text_channel(channel_name, overwrites=overwrites)
                logger.info(f"Created channel '{channel_name}' in guild '{guild.name}'")
            except Exception as e:
                logger.exception(f"Failed to create channel '{channel_name}'")
                return

        # Generate the rank list content
        if not self.user_ranks:
            rank_list = "No ranks available."
        else:
            sorted_ranks = sorted(self.user_ranks.items(), key=lambda x: x[1])
            rank_lines = []
            for user_id, rank in sorted_ranks:
                try:
                    member = guild.get_member(int(user_id)) or await guild.fetch_member(int(user_id))
                    nickname = member.nick if member.nick else member.name
                    rank_lines.append(f"Rank {rank}: {nickname}")
                except discord.NotFound:
                    rank_lines.append(f"Rank {rank}: User with ID {user_id} not found in guild")
            rank_list = "\n".join(rank_lines)

        # If a message ID is stored, try to fetch and edit the message
        if self.rank_message_id:
            try:
                message = await channel.fetch_message(self.rank_message_id)
                await message.edit(content=f"```\n{rank_list}\n```")
                logger.info(f"Updated rank list message in channel '{channel_name}'")
            except discord.NotFound:
                # Message not found; send a new one
                message = await channel.send(f"```\n{rank_list}\n```")
                self.rank_message_id = message.id
                self.save_ranks_to_file()
                logger.info(f"Sent new rank list message in channel '{channel_name}'")
            except Exception as e:
                logger.exception("Failed to update rank list message")
        else:
            # No message ID stored; send a new message
            try:
                message = await channel.send(f"```\n{rank_list}\n```")
                self.rank_message_id = message.id
                self.save_ranks_to_file()
                logger.info(f"Sent new rank list message in channel '{channel_name}'")
            except Exception as e:
                logger.exception("Failed to send rank list message")

class RankCog(commands.Cog):
    """Cog for managing user ranks."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rank_manager = RankManager()
        self.check_nicknames.start()

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            logger.info(f"{self.bot.user.name} has connected to Discord!")
            for guild in self.bot.guilds:
                logger.info(f"Processing guild: {guild.name}")
                # Fetch all members once during startup
                members = [member async for member in guild.fetch_members(limit=None)]
                logger.info(f"Fetched {len(members)} members from guild '{guild.name}'")

                if not self.rank_manager.user_ranks:
                    # If no ranks in 'ranks.json', load from nicknames and save
                    logger.info("No ranks found in 'ranks.json', loading from Discord nicknames.")
                    await self.rank_manager.load_ranks_from_nicknames(guild, members)
                else:
                    # Enforce ranks from 'ranks.json' onto Discord
                    logger.info("Ranks loaded from 'ranks.json', enforcing ranks on Discord.")
                    await self.rank_manager.enforce_ranks_on_discord(guild, members)

                # Update the rank list message in the designated channel
                await self.rank_manager.update_rank_message(guild)
            logger.info("User ranks have been initialized.")
        except Exception as e:
            logger.exception("An error occurred during on_ready")

    # Create a command group for 'rank'
    rank = app_commands.Group(name="rank", description="Commands to manage user ranks.")

    @rank.command(name="set", description="Change a user's rank and adjust other users' ranks accordingly.")
    @app_commands.describe(member='The member to change rank for', new_rank='The new rank to assign')
    async def rank_set(self, interaction: discord.Interaction, member: discord.Member, new_rank: int):
        """
        Change a user's rank and adjust other users' ranks accordingly.
        """
        # Check if the user has Admin permission or authorized role
        if not (
            interaction.user.guild_permissions.administrator or
            discord.utils.get(interaction.user.roles, name=AUTHORIZED_ROLE)
        ):
            await interaction.response.send_message(
                "🚫 You do not have permission to use this command. Only admins or authorized roles can use this.",
                ephemeral=True
            )
            return

        # Defer the interaction immediately
        await interaction.response.defer(thinking=True)

        start_time = time.monotonic()  # Start timing the command execution

        try:
            if not isinstance(new_rank, int) or new_rank < 1:
                await interaction.followup.send("🚫 Rank must be a positive integer.", ephemeral=True)
                return

            old_rank = self.rank_manager.user_ranks.get(str(member.id))
            await self.rank_manager.adjust_ranks(
                interaction.guild, member.id, old_rank, new_rank
            )

            await interaction.followup.send(f"✅ {member.mention}'s rank has been updated to {new_rank}.")
        except Exception as e:
            # Log the error and send an error message
            logger.exception("An error occurred in rank set command")
            if not interaction.is_expired():
                await interaction.followup.send("🚫 An error occurred while processing the command.", ephemeral=True)
        finally:
            end_time = time.monotonic()
            elapsed_time = end_time - start_time
            logger.info(f"Rank set command executed in {elapsed_time:.2f} seconds")

    @rank_set.error
    async def rank_set_error(self, interaction: discord.Interaction, error):
        """Handle errors for the rank set command."""
        if isinstance(error, app_commands.errors.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message("🚫 You do not have permission to change ranks.", ephemeral=True)
        elif isinstance(error, app_commands.AppCommandError):
            if not interaction.response.is_done():
                await interaction.response.send_message("🚫 Invalid arguments or an error occurred.", ephemeral=True)
            logger.exception("Error in rank set command")
        else:
            if not interaction.response.is_done():
                await interaction.response.send_message("🚫 An unexpected error occurred.", ephemeral=True)
            logger.exception("Error in rank set command")

    # New 'remove' subcommand
    @rank.command(name="remove", description="Remove a user's rank and adjust other users' ranks accordingly.")
    @app_commands.describe(member='The member to remove rank from')
    async def rank_remove(self, interaction: discord.Interaction, member: discord.Member):
        """
        Remove a user's rank and adjust other users' ranks accordingly.
        """
        # Check if the user has Admin permission or authorized role
        if not (
            interaction.user.guild_permissions.administrator or
            discord.utils.get(interaction.user.roles, name=AUTHORIZED_ROLE)
        ):
            await interaction.response.send_message(
                "🚫 You do not have permission to use this command. Only admins or authorized roles can use this.",
                ephemeral=True
            )
            return

        # Defer the interaction immediately
        await interaction.response.defer(thinking=True)

        start_time = time.monotonic()  # Start timing the command execution

        try:
            old_rank = self.rank_manager.user_ranks.pop(str(member.id), None)
            if old_rank is None:
                await interaction.followup.send(f"🚫 {member.mention} does not have a rank assigned.", ephemeral=True)
                return

            # Update the member's nickname to remove the rank
            await self.rank_manager.update_nickname(member, None)

            # Adjust the ranks of other members to fill the gap
            await self.rank_manager.fill_rank_gaps(interaction.guild)

            await interaction.followup.send(f"✅ {member.mention}'s rank has been removed.")
        except Exception as e:
            # Log the error and send an error message
            logger.exception("An error occurred in rank remove command")
            if not interaction.is_expired():
                await interaction.followup.send("🚫 An error occurred while processing the command.", ephemeral=True)
        finally:
            end_time = time.monotonic()
            elapsed_time = end_time - start_time
            logger.info(f"Rank remove command executed in {elapsed_time:.2f} seconds")

    @rank_remove.error
    async def rank_remove_error(self, interaction: discord.Interaction, error):
        """Handle errors for the rank remove command."""
        if isinstance(error, app_commands.errors.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message("🚫 You do not have permission to remove ranks.", ephemeral=True)
        elif isinstance(error, app_commands.AppCommandError):
            if not interaction.response.is_done():
                await interaction.response.send_message("🚫 Invalid arguments or an error occurred.", ephemeral=True)
            logger.exception("Error in rank remove command")
        else:
            if not interaction.response.is_done():
                await interaction.response.send_message("🚫 An unexpected error occurred.", ephemeral=True)
            logger.exception("Error in rank remove command")

    @tasks.loop(minutes=5)
    async def check_nicknames(self):
        """Periodically enforce ranks from 'ranks.json' onto Discord."""
        logger.info("Checking nicknames for discrepancies...")
        for guild in self.bot.guilds:
            # Use cached members
            members = guild.members
            await self.rank_manager.enforce_ranks_on_discord(guild, members)

    @check_nicknames.before_loop
    async def before_check_nicknames(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Handle new members joining the guild."""
        logger.info(f"New member joined: {member.display_name}")
        # For now, we can enforce ranks on this member
        await self.rank_manager.enforce_ranks_on_discord(member.guild, [member])

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Ensure that rank suffixes are maintained."""
        if before.nick != after.nick:
            await self.rank_manager.enforce_ranks_on_discord(after.guild, [after])

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        await self.add_cog(RankCog(self))
        # Sync the application commands with Discord
        await self.tree.sync()
        logger.info("Application commands have been synced.")

bot = MyBot()

async def main():
    async with bot:
        await bot.start(os.getenv('DISCORD_BOT_TOKEN'))

asyncio.run(main())
