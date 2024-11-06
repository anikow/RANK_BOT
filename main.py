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
        if member.nick is None:
            name_without_rank = member.name
        else:
            name_without_rank = re.sub(r'#\s*\d+$', '', member.nick).strip()
        
        if new_rank is not None:
            # Append the new rank to the nickname
            new_nickname = f"{name_without_rank} #{new_rank}"
        else:
            # No rank to add, just use the name without rank
            new_nickname = name_without_rank if name_without_rank != member.name else None  # Reset nickname to None if same as username
        
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

        # Check if new_rank is occupied
        rank_is_occupied = any(
            rank == new_rank and int(member_id_str) != target_member_id
            for member_id_str, rank in self.user_ranks.items()
        )

        if not rank_is_occupied:
            # No need to adjust other ranks
            print(f"New rank {new_rank} is unoccupied. No need to adjust other ranks.")
            self.save_ranks_to_file()
            await self.update_rank_message(guild)  # Update the rank list message
            return

        # If new_rank is occupied, adjust other ranks
        print(f"New rank {new_rank} is occupied. Adjusting other ranks.")

        for member_id_str, rank in self.user_ranks.items():
            member_id = int(member_id_str)
            if member_id == target_member_id:
                continue

            try:
                member = guild.get_member(member_id)
                if member is None:
                    member = await guild.fetch_member(member_id)
            except discord.NotFound:
                print(f"Member with ID {member_id} not found.")
                continue  # Member not found in guild

            print(f"Processing member: {member.display_name}, Current Rank: {rank}")

            if old_rank is not None:
                if old_rank < new_rank:
                    # Moving down in rank numbers (e.g., from 5 to 10)
                    if old_rank < rank <= new_rank:
                        self.user_ranks[str(member_id)] = rank - 1
                        await self.update_nickname(member, rank - 1)
                        print(f"Decreased rank of {member.display_name} to {rank - 1}")
                else:
                    # Moving up in rank numbers (e.g., from 10 to 5)
                    if new_rank <= rank < old_rank:
                        self.user_ranks[str(member_id)] = rank + 1
                        await self.update_nickname(member, rank + 1)
                        print(f"Increased rank of {member.display_name} to {rank + 1}")
            else:
                # No old rank
                if rank >= new_rank:
                    self.user_ranks[str(member_id)] = rank + 1
                    await self.update_nickname(member, rank + 1)
                    print(f"Increased rank of {member.display_name} to {rank + 1}")

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

    @app_commands.command(name="rank", description="Change a user's rank and adjust other users' ranks accordingly.")
    @app_commands.describe(member='The member to change rank for', new_rank='The new rank to assign')
    async def rank(self, interaction: discord.Interaction, member: discord.Member, new_rank: int):
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
            print(f"An error occurred in rank command: {e}")
            if not interaction.is_expired():
                await interaction.followup.send("🚫 An error occurred while processing the command.", ephemeral=True)
        finally:
            end_time = time.monotonic()
            elapsed_time = end_time - start_time
            print(f"Rank command executed in {elapsed_time:.2f} seconds")

    @rank.error
    async def rank_error(self, interaction: discord.Interaction, error):
        """Handle errors for the rank command."""
        if isinstance(error, app_commands.errors.MissingPermissions):
            if not interaction.response.is_done():
                await interaction.response.send_message("🚫 You do not have permission to change ranks.", ephemeral=True)
        elif isinstance(error, app_commands.AppCommandError):
            if not interaction.response.is_done():
                await interaction.response.send_message("🚫 Invalid arguments or an error occurred.", ephemeral=True)
            print(f"Error in rank command: {error}")
        else:
            if not interaction.response.is_done():
                await interaction.response.send_message("🚫 An unexpected error occurred.", ephemeral=True)
            print(f"Error in rank command: {error}")

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
