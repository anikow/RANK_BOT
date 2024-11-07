import discord
from discord.ext import commands, tasks
import os
from dotenv import load_dotenv
import asyncio
from discord import app_commands
import json
import re
import time  # For timing the command execution

load_dotenv()

# Intents setup
intents = discord.Intents.default()
intents.members = True            # Required to access member information
intents.message_content = False   # Not needed for this bot

class RankManager:
    """Class to manage user ranks."""

    def __init__(self):
        # In-memory storage for user ranks: {user_id: rank}
        self.user_ranks = {}
        # Store the rank list message ID
        self.rank_message_id = None
        self.load_ranks_from_file()

    def load_ranks_from_file(self):
        """Load ranks and message ID from a JSON file."""
        if os.path.exists('ranks.json'):
            with open('ranks.json', 'r') as f:
                data = json.load(f)
                self.user_ranks = data.get('user_ranks', {})
                self.rank_message_id = data.get('rank_message_id')
                print("Loaded ranks and rank message ID from 'ranks.json'")
        else:
            print("'ranks.json' not found. Starting with empty ranks.")

    def save_ranks_to_file(self):
        """Save ranks and message ID to a JSON file."""
        data = {
            'user_ranks': self.user_ranks,
            'rank_message_id': self.rank_message_id
        }
        with open('ranks.json', 'w') as f:
            json.dump(data, f, indent=4)
            print("Saved ranks and rank message ID to 'ranks.json'")

    @staticmethod
    def parse_rank(nickname):
        """Extract rank from a nickname."""
        if nickname:
            # Use regex to find a pattern like '#number' at the end of the nickname
            match = re.search(r'#\s*(\d+)$', nickname)
            if match:
                rank = int(match.group(1))
                print(f"Parsed rank {rank} from nickname '{nickname}'")
                return rank
        # print(f"Failed to parse rank from nickname '{nickname}'")
        return None

    async def load_ranks_from_nicknames(self, guild, members):
        """Load ranks from existing member nicknames."""
        print("Loading ranks from nicknames...")
        for member in members:
            nickname = member.nick
            if nickname is None:
                continue  # Skip members without a nickname
            rank = self.parse_rank(nickname)
            if rank is not None:
                self.user_ranks[str(member.id)] = rank
                print(f"Loaded rank {rank} for member {member.display_name}")
            else:
                print(f"No rank found in nickname for member {member.display_name}")
        self.save_ranks_to_file()

    async def enforce_ranks_on_discord(self, guild, members):
        """Enforce ranks from user_ranks onto Discord nicknames."""
        print("Enforcing ranks on Discord nicknames...")
        for member in members:
            user_id_str = str(member.id)
            expected_rank = self.user_ranks.get(user_id_str)
            current_rank_in_nickname = self.parse_rank(member.nick)
            
            if expected_rank is not None:
                # Member should have a rank
                if current_rank_in_nickname != expected_rank:
                    print(f"Updating rank for member {member.display_name} to {expected_rank}")
                    await self.update_nickname(member, expected_rank)
                else:
                    print(f"Member {member.display_name} already has correct rank {expected_rank}")
            else:
                # Member should not have a rank, remove any rank from nickname
                if current_rank_in_nickname is not None:
                    print(f"Removing rank from member {member.display_name} as they are not in ranks.json")
                    await self.update_nickname(member, None)
                else:
                    print(f"Member {member.display_name} has no rank and is correct")

    async def update_nickname(self, member, new_rank):
        """Update a member's nickname with the new rank or remove it."""
        # Extract the base nickname without rank
        if member.nick is not None:
            # If member has a nickname, remove the rank from it
            name_without_rank = re.sub(r'#\s*\d+$', '', member.nick).strip()
        else:
            # If member does not have a nickname, use their username
            name_without_rank = member.name
        
        # Decide the new nickname
        if new_rank is not None:
            new_nickname = f"{name_without_rank} #{new_rank}"
        else:
            # No new rank, just use the name without rank
            new_nickname = name_without_rank

        # If the new nickname is the same as the username, set nick to None to remove nickname
        if new_nickname == member.name:
            new_nickname = None

        try:
            await member.edit(nick=new_nickname)
            print(f"Updated nickname for {member.display_name} to '{new_nickname}'")
        except discord.Forbidden:
            print(f"Permission denied to change nickname for {member.display_name}.")
        except Exception as e:
            print(f"An error occurred while changing nickname: {e}")

        self.save_ranks_to_file()

    async def adjust_ranks(self, guild, target_member_id, old_rank, new_rank):
        """Adjust ranks of other members based on the new rank assignment."""

        print(f"Adjusting ranks in guild: {guild.name}")

        # Determine the direction of rank movement
        if old_rank is not None and old_rank < new_rank:
            direction = 'down'
        elif old_rank is not None and old_rank > new_rank:
            direction = 'up'
        else:
            direction = None  # Either new assignment or same rank

        # Check if new_rank is occupied (excluding the target member)
        rank_is_occupied = any(
            rank == new_rank and int(member_id_str) != target_member_id
            for member_id_str, rank in self.user_ranks.items()
        )

        # If assigning to a new rank that is occupied, we need to shift
        # If moving a member from an existing rank to a new one, we may also need to shift to fill the gap
        needs_shift = rank_is_occupied or (old_rank is not None)

        if not needs_shift:
            # No need to adjust other ranks
            print(f"New rank {new_rank} is unoccupied and no old rank to adjust. No need to adjust other ranks.")
            self.user_ranks[str(target_member_id)] = new_rank
            self.save_ranks_to_file()
            await self.update_rank_message(guild)  # Update the rank list message
            await self.update_nickname(guild.get_member(target_member_id), new_rank)
            return

        # If shifting is needed, determine the range based on the direction
        if direction == 'down':
            # Moving down in rank numbers (e.g., from 15 to 60)
            # Shift members in the range (old_rank, new_rank] up by 1
            shift_start = old_rank + 1
            shift_end = new_rank
            shift_amount = -1  # Decrease rank by 1
            print(f"Moving down: Shifting ranks {shift_start} to {shift_end} up by 1.")
        elif direction == 'up':
            # Moving up in rank numbers (e.g., from 60 to 15)
            # Shift members in the range [new_rank, old_rank) down by 1
            shift_start = new_rank
            shift_end = old_rank - 1
            shift_amount = 1  # Increase rank by 1
            print(f"Moving up: Shifting ranks {shift_start} to {shift_end} down by 1.")
        else:
            # No specific direction, likely assigning a new rank without old_rank
            # Shift members at new_rank and above up by 1
            shift_start = new_rank
            shift_end = max(self.user_ranks.values())  # Adjust as needed
            shift_amount = 1
            print(f"Assigning new rank without direction: Shifting ranks {shift_start} and above down by 1.")

        # Collect members to shift
        members_to_shift = []
        for member_id_str, rank in self.user_ranks.items():
            member_id = int(member_id_str)
            if shift_start <= rank <= shift_end:
                members_to_shift.append((member_id, rank))

        # Sort members appropriately to avoid conflicts during shifting
        if shift_amount == -1:
            # Shift up: process lower ranks first
            members_to_shift.sort(key=lambda x: x[1])
        else:
            # Shift down: process higher ranks first
            members_to_shift.sort(key=lambda x: x[1], reverse=True)

        for member_id, rank in members_to_shift:
            new_member_rank = rank + shift_amount
            self.user_ranks[str(member_id)] = new_member_rank
            try:
                member = guild.get_member(member_id)
                if member is None:
                    member = await guild.fetch_member(member_id)
                await self.update_nickname(member, new_member_rank)
                print(f"Updated {member.display_name}'s rank to {new_member_rank}")
            except discord.NotFound:
                print(f"Member with ID {member_id} not found.")
                continue

        # Assign the new rank to the target member
        self.user_ranks[str(target_member_id)] = new_rank
        try:
            target_member = guild.get_member(target_member_id)
            if target_member is None:
                target_member = await guild.fetch_member(target_member_id)
            await self.update_nickname(target_member, new_rank)
            print(f"Assigned rank {new_rank} to {target_member.display_name}")
        except discord.NotFound:
            print(f"Target member with ID {target_member_id} not found.")

        self.save_ranks_to_file()
        await self.update_rank_message(guild)  # Update the rank list message
        await self.fill_rank_gaps(guild)


    async def fill_rank_gaps(self, guild):
        """Reassign ranks to fill any gaps."""
        print("Filling rank gaps...")
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
            old_rank = self.user_ranks[user_id_str]
            if old_rank != new_rank:
                member_id = int(user_id_str)
                try:
                    member = guild.get_member(member_id)
                    if member is None:
                        member = await guild.fetch_member(member_id)
                    self.user_ranks[user_id_str] = new_rank
                    await self.update_nickname(member, new_rank)
                    print(f"Adjusted rank of {member.display_name} from {old_rank} to {new_rank}")
                except discord.NotFound:
                    print(f"Member with ID {member_id} not found.")
                    continue

        self.user_ranks = new_user_ranks
        self.save_ranks_to_file()
        await self.update_rank_message(guild)  # Update the rank list message

    async def update_rank_message(self, guild):
        """Create or update the rank list message in a designated channel."""
        channel_name = "rank-list"  # Name of the channel to post the rank list
        channel = discord.utils.get(guild.text_channels, name=channel_name)

        if channel is None:
            # Create the channel if it doesn't exist
            try:
                channel = await guild.create_text_channel(channel_name)
                print(f"Created channel '{channel_name}' in guild '{guild.name}'")
            except Exception as e:
                print(f"Failed to create channel '{channel_name}': {e}")
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
                print(f"Updated rank list message in channel '{channel_name}'")
            except discord.NotFound:
                # Message not found; send a new one
                message = await channel.send(f"```\n{rank_list}\n```")
                self.rank_message_id = message.id
                self.save_ranks_to_file()
                print(f"Sent new rank list message in channel '{channel_name}'")
            except Exception as e:
                print(f"Failed to update rank list message: {e}")
        else:
            # No message ID stored; send a new message
            try:
                message = await channel.send(f"```\n{rank_list}\n```")
                self.rank_message_id = message.id
                self.save_ranks_to_file()
                print(f"Sent new rank list message in channel '{channel_name}'")
            except Exception as e:
                print(f"Failed to send rank list message: {e}")


class RankCog(commands.Cog):
    """Cog for managing user ranks."""

    def __init__(self, bot):
        self.bot = bot
        self.rank_manager = RankManager()
        self.check_nicknames.start()

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"{self.bot.user.name} has connected to Discord!")

        for guild in self.bot.guilds:
            print(f"Processing guild: {guild.name}")
            # Fetch all members once during startup
            members = [member async for member in guild.fetch_members(limit=None)]
            print(f"Fetched {len(members)} members from guild '{guild.name}'")
            
            if not self.rank_manager.user_ranks:
                # If no ranks in 'ranks.json', load from nicknames and save
                print("No ranks found in 'ranks.json', loading from Discord nicknames.")
                await self.rank_manager.load_ranks_from_nicknames(guild, members)
            else:
                # Enforce ranks from 'ranks.json' onto Discord
                print("Ranks loaded from 'ranks.json', enforcing ranks on Discord.")
                await self.rank_manager.enforce_ranks_on_discord(guild, members)
            
            # Update the rank list message in the designated channel
            await self.rank_manager.update_rank_message(guild)
        print("User ranks have been initialized.")

    # Create a command group for 'rank'
    rank = app_commands.Group(name="rank", description="Commands to manage user ranks.")

    @rank.command(name="set", description="Change a user's rank and adjust other users' ranks accordingly.")
    @app_commands.describe(member='The member to change rank for', new_rank='The new rank to assign')
    async def rank_set(self, interaction: discord.Interaction, member: discord.Member, new_rank: int):
        """
        Change a user's rank and adjust other users' ranks accordingly.
        """
        # Check if the user has Admin permission or "Mommy" role
        if not (
            interaction.user.guild_permissions.administrator or
            discord.utils.get(interaction.user.roles, name="Mommy")
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
            if new_rank < 1:
                await interaction.followup.send("🚫 Rank must be a positive integer.", ephemeral=True)
                return

            old_rank = self.rank_manager.user_ranks.get(str(member.id))
            self.rank_manager.user_ranks[str(member.id)] = new_rank
            await self.rank_manager.update_nickname(member, new_rank)

            await self.rank_manager.adjust_ranks(
                interaction.guild, member.id, old_rank, new_rank
            )

            await interaction.followup.send(f"✅ {member.mention}'s rank has been updated to {new_rank}.")
        except Exception as e:
            # Log the error and send an error message
            print(f"An error occurred in rank set command: {e}")
            if not interaction.is_expired():
                await interaction.followup.send("🚫 An error occurred while processing the command.", ephemeral=True)
        finally:
            end_time = time.monotonic()
            elapsed_time = end_time - start_time
            print(f"Rank set command executed in {elapsed_time:.2f} seconds")

    @rank_set.error
    async def rank_set_error(self, interaction: discord.Interaction, error):
        """Handle errors for the rank set command."""
        if isinstance(error, app_commands.errors.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message("🚫 You do not have permission to change ranks.", ephemeral=True)
        elif isinstance(error, app_commands.AppCommandError):
            if not interaction.response.is_done():
                await interaction.response.send_message("🚫 Invalid arguments or an error occurred.", ephemeral=True)
            print(f"Error in rank set command: {error}")
        else:
            if not interaction.response.is_done():
                await interaction.response.send_message("🚫 An unexpected error occurred.", ephemeral=True)
            print(f"Error in rank set command: {error}")

    # New 'remove' subcommand
    @rank.command(name="remove", description="Remove a user's rank and adjust other users' ranks accordingly.")
    @app_commands.describe(member='The member to remove rank from')
    async def rank_remove(self, interaction: discord.Interaction, member: discord.Member):
        """
        Remove a user's rank and adjust other users' ranks accordingly.
        """
        # Check if the user has Admin permission or "Mommy" role
        if not (
            interaction.user.guild_permissions.administrator or
            discord.utils.get(interaction.user.roles, name="Mommy")
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
            print(f"An error occurred in rank remove command: {e}")
            if not interaction.is_expired():
                await interaction.followup.send("🚫 An error occurred while processing the command.", ephemeral=True)
        finally:
            end_time = time.monotonic()
            elapsed_time = end_time - start_time
            print(f"Rank remove command executed in {elapsed_time:.2f} seconds")

    @rank_remove.error
    async def rank_remove_error(self, interaction: discord.Interaction, error):
        """Handle errors for the rank remove command."""
        if isinstance(error, app_commands.errors.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message("🚫 You do not have permission to remove ranks.", ephemeral=True)
        elif isinstance(error, app_commands.AppCommandError):
            if not interaction.response.is_done():
                await interaction.response.send_message("🚫 Invalid arguments or an error occurred.", ephemeral=True)
            print(f"Error in rank remove command: {error}")
        else:
            if not interaction.response.is_done():
                await interaction.response.send_message("🚫 An unexpected error occurred.", ephemeral=True)
            print(f"Error in rank remove command: {error}")

    @tasks.loop(seconds=10)  # Adjusted to run every 3 minutes
    async def check_nicknames(self):
        """Periodically enforce ranks from 'ranks.json' onto Discord."""
        print("Checking nicknames for discrepancies...")
        for guild in self.bot.guilds:
            # Use cached members
            members = guild.members
            await self.rank_manager.enforce_ranks_on_discord(guild, members)

    @check_nicknames.before_loop
    async def before_check_nicknames(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Handle new members joining the guild."""
        # Optionally, add logic here if you want to assign default ranks or handle new members
        print(f"New member joined: {member.display_name}")
        # For now, we can enforce ranks on this member
        await self.rank_manager.enforce_ranks_on_discord(member.guild, [member])

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
        self.initial_extensions = []

    async def setup_hook(self):
        await self.add_cog(RankCog(self))
        # Sync the application commands with Discord
        await self.tree.sync()
        print("Application commands have been synced.")

bot = MyBot()

async def main():
    async with bot:
        await bot.start(os.getenv('DISCORD_BOT_TOKEN'))

asyncio.run(main())
