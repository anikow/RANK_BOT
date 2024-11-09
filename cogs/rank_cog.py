import logging
import time

import discord
from discord.ext import commands, tasks
from discord import app_commands

from utils.rank_manager import RankManager
import config

logger = logging.getLogger(__name__)

class RankCog(commands.Cog):
    """Discord Cog that provides commands and listeners for managing user ranks."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rank_manager = RankManager()
        self.check_nicknames.start()
    
    @commands.Cog.listener()
    async def on_ready(self):
        """
        Called when the bot is ready.
        Initializes user ranks for each guild and enforces ranks on Discord nicknames.
        """
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
        Changes a user's rank to a new value and adjusts other users' ranks accordingly.
        """
        # Check if the user has Admin permission or authorized role
        if not (
            interaction.user.guild_permissions.administrator or
            discord.utils.get(interaction.user.roles, name=config.AUTHORIZED_ROLE)
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
            logger.exception(f"An error occurred in rank set command for member {member.display_name} with rank {new_rank}")
            if not interaction.is_expired():
                await interaction.followup.send("🚫 An error occurred while processing the command.", ephemeral=True)
        finally:
            end_time = time.monotonic()
            elapsed_time = end_time - start_time
            logger.info(f"Rank set command executed in {elapsed_time:.2f} seconds")

    @rank_set.error
    async def rank_set_error(self, interaction: discord.Interaction, error):
        """Handles errors for the rank set command."""
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

    # 'remove' subcommand
    @rank.command(name="remove", description="Remove a user's rank and adjust other users' ranks accordingly.")
    @app_commands.describe(member='The member to remove rank from')
    async def rank_remove(self, interaction: discord.Interaction, member: discord.Member):
        """
        Removes a user's rank and adjusts other users' ranks accordingly to fill any gaps.
        """
        # Check if the user has Admin permission or authorized role
        if not (
            interaction.user.guild_permissions.administrator or
            discord.utils.get(interaction.user.roles, name=config.AUTHORIZED_ROLE)
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

            # Decrement ranks of members with rank > old_rank
            affected_user_ids = set()
            for uid in self.rank_manager.user_ranks:
                if self.rank_manager.user_ranks[uid] > old_rank:
                    self.rank_manager.user_ranks[uid] -= 1
                    affected_user_ids.add(uid)

            # Update nicknames of affected members
            for uid in affected_user_ids:
                member_id = int(uid)
                member = interaction.guild.get_member(member_id)
                if member is None:
                    try:
                        member = await interaction.guild.fetch_member(member_id)
                    except discord.NotFound:
                        logger.warning(f"Member with ID {member_id} not found.")
                        continue
                rank = self.rank_manager.user_ranks[uid]
                await self.rank_manager.update_nickname(member, rank)
                logger.info(f"Updated nickname for {member.display_name} to include rank {rank}")

            # Update the member's nickname to remove the rank
            await self.rank_manager.update_nickname(member, None)
            self.rank_manager.save_ranks_to_file()
            # Update the rank list message
            await self.rank_manager.update_rank_message(interaction.guild)

            await interaction.followup.send(f"✅ {member.mention}'s rank has been removed.")
        except Exception as e:
            # Log the error and send an error message
            logger.exception(f"An error occurred in rank remove command for member {member.display_name}")
            if not interaction.is_expired():
                await interaction.followup.send("🚫 An error occurred while processing the command.", ephemeral=True)
        finally:
            end_time = time.monotonic()
            elapsed_time = end_time - start_time
            logger.info(f"Rank remove command executed in {elapsed_time:.2f} seconds")

        @rank_remove.error
        async def rank_remove_error(self, interaction: discord.Interaction, error):
            """Handles errors for the rank remove command."""
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
        """
        Periodically checks and enforces ranks on Discord nicknames every 5 minutes.
        Ensures that all members' nicknames are in sync with their assigned ranks.
        """
        logger.info("Periodic check: Enforcing ranks on Discord nicknames...")
        for guild in self.bot.guilds:
            # Use cached members
            members = guild.members
            await self.rank_manager.enforce_ranks_on_discord(guild, members)

    @check_nicknames.before_loop
    async def before_check_nicknames(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """
        Handles new members joining the guild.
        Enforces ranks on their nickname in case they should have a rank.
        """
        logger.info(f"New member joined: {member.display_name}")
        # Enforce rank on the new member
        await self.rank_manager.enforce_ranks_on_discord(member.guild, [member])

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.nick != after.nick:
            logger.info(f"Member nickname changed: {before.display_name} -> {after.display_name}")

            # Check if the rank in the nickname matches the expected rank
            expected_rank = self.rank_manager.user_ranks.get(str(after.id))
            current_rank_in_nickname = self.rank_manager.parse_rank(after.nick)

            if expected_rank is not None and current_rank_in_nickname != expected_rank:
                logger.info(f"Enforcing correct rank for {after.display_name}")
                await self.rank_manager.update_nickname(after, expected_rank)
            elif expected_rank is None and current_rank_in_nickname is not None:
                logger.info(f"Removing rank from nickname of {after.display_name} as they should not have one")
                await self.rank_manager.update_nickname(after, None)
            else:
                # Nickname is already correct; no action needed
                logger.debug(f"Nickname for {after.display_name} is already correct.")
