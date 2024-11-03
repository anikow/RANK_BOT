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
intents.message_content = True    # Required to read message content

class RankManager:
    """Class to manage user ranks."""

    def __init__(self):
        # In-memory storage for user ranks: {user_id: rank}
        self.user_ranks = {}
        self.load_ranks_from_file()

    def load_ranks_from_file(self):
        """Load ranks from a JSON file."""
        if os.path.exists('ranks.json'):
            with open('ranks.json', 'r') as f:
                self.user_ranks = json.load(f)
                print("Loaded ranks from 'ranks.json'")
        else:
            print("'ranks.json' not found. Starting with empty ranks.")

    def save_ranks_to_file(self):
        """Save ranks to a JSON file."""
        with open('ranks.json', 'w') as f:
            json.dump(self.user_ranks, f)
            print("Saved ranks to 'ranks.json'")

    async def load_ranks(self, members):
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
        print(f"Failed to parse rank from nickname '{nickname}'")
        return None

    async def update_nickname(self, member, new_rank):
        """Update a member's nickname with the new rank."""
        if member.nick is None:
            name_without_rank = member.name
        else:
            name_without_rank = re.sub(r'#\s*\d+$', '', member.nick).strip()

        rank_str = str(new_rank)
        new_nickname = f"{name_without_rank} #{rank_str}"

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

class RankCog(commands.Cog):
    """Cog for managing user ranks."""

    def __init__(self, bot):
        self.bot = bot
        self.rank_manager = RankManager()
        self.check_nicknames.start()

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"{self.bot.user.name} has connected to Discord!")

        # Load ranks for each guild
        for guild in self.bot.guilds:
            print(f"Processing guild: {guild.name}")
            # Fetch all members
            members = [member async for member in guild.fetch_members(limit=None)]
            print(f"Fetched {len(members)} members from guild '{guild.name}'")
            self.rank_manager.load_ranks(members)
        print("User ranks have been initialized.")

    @app_commands.command(name="rank", description="Change a user's rank and adjust other users' ranks accordingly.")
    @app_commands.describe(member='The member to change rank for', new_rank='The new rank to assign')
    async def rank(self, interaction: discord.Interaction, member: discord.Member, new_rank: int):
        """
        Change a user's rank and adjust other users' ranks accordingly.
        """
        # Check if the user has Admin permission or "founder" role
        if not (
            interaction.user.guild_permissions.administrator or
            discord.utils.get(interaction.user.roles, name="Mommy")
        ):
            await interaction.response.send_message(
                "🚫 You do not have permission to use this command. Only admins or founders can use this.",
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

    @tasks.loop(minutes=10)
    async def check_nicknames(self):
        """Periodically check for nickname changes."""
        print("Checking nicknames for manual changes...")
        for guild in self.bot.guilds:
            members = [member async for member in guild.fetch_members(limit=None)]
            for member in members:
                nickname = member.nick
                if nickname is None:
                    continue
                rank = self.rank_manager.parse_rank(nickname)
                if rank is not None:
                    current_rank = self.rank_manager.user_ranks.get(str(member.id))
                    if current_rank != rank:
                        print(f"Detected rank change for {member.display_name}: {current_rank} -> {rank}")
                        self.rank_manager.user_ranks[str(member.id)] = rank
                        self.rank_manager.save_ranks_to_file()
                else:
                    if str(member.id) in self.rank_manager.user_ranks:
                        print(f"Rank removed from nickname of {member.display_name}")
                        del self.rank_manager.user_ranks[str(member.id)]
                        self.rank_manager.save_ranks_to_file()

    @check_nicknames.before_loop
    async def before_check_nicknames(self):
        await self.bot.wait_until_ready()

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
