
# Discord Rank_Bot

Rank_Bot is a Discord bot designed to manage and automatically update user ranks in a Discord server. It enables administrators or authorized roles to assign, adjust, and remove ranks for users, which are then reflected in their nicknames.

## Features

- Automatic nickname updates to include user ranks.
- Commands for managing user ranks.
- Maintenance of a rank list in a designated Discord channel.

## Prerequisites

- Python 3.12
- Discord Bot Token
- Discord Server access with administrative privileges

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/Rank_Bot.git
   cd Rank_Bot
   ```

2. **Set up the environment variables by creating a `.env` file in the project root:**
   ```
   DISCORD_BOT_TOKEN=your_discord_bot_token
   AUTHORIZED_ROLE=role_name
   RANK_CHANNEL_NAME=rank_channel_name
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## Usage

Run the bot using:
```bash
python bot.py
```

Alternatively, build and run with Docker:
```bash
docker build -t rank_bot .
docker run -d --name rank_bot --env-file .env rank_bot
```

## Commands

- `/rank set member:<member> new_rank:<new_rank>` - Assign a new rank to a user.
- `/rank remove member:<member>` - Remove the rank of a user.

## Permissions

The bot requires permissions to manage nicknames, read and send messages, and access message history.

## Contributing

Contributions are welcome.

## License

This project is licensed under the [MIT License](LICENSE).
