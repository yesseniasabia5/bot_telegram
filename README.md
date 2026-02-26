# Telegram Bot

A Python-based Telegram bot designed to automate messaging and data management tasks.

## 📋 Features

- **Automated Messaging**: Send messages to multiple users via Telegram
- **Data Management**: Import and export data from CSV files
- **Modular Architecture**: Organized functionality separated into different modules
- **Easy Configuration**: Simple setup and configuration process

## 🗂️ Project Structure

```
bot_telegram/
├── bot/                  # Bot core modules
├── Funcionalidades/      # Feature implementations
├── tools/                # Utility tools and helpers
├── export/               # Export results directory
├── bot_unico.py          # Main bot entry point
├── lista.csv             # User/contact list
└── requirements.txt      # Python dependencies
```

## 🚀 Getting Started

### Prerequisites

- Python 3.7 or higher
- pip (Python package manager)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yesseniasabia5/bot_telegram.git
cd bot_telegram
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure your Telegram bot token in the configuration file

### Usage

Run the bot using:
```bash
python bot_unico.py
```

## 📦 Dependencies

The project uses the following main dependencies:

- **python-telegram-bot**: Telegram Bot API wrapper for Python
- Additional utilities for data processing and management

For a complete list, see `requirements.txt`

## 📁 Key Files

- `bot_unico.py` - Main entry point for the bot
- `lista.csv` - CSV file containing contacts/users
- `requirements.txt` - Python package dependencies
- `bot/` - Core bot modules and handlers
- `Funcionalidades/` - Feature-specific implementations
- `tools/` - Utility functions and helpers

## 🔧 Configuration

1. Set up your Telegram bot token (obtain from BotFather on Telegram)
2. Add your contact list to `lista.csv`
3. Customize features in the `Funcionalidades` directory

## 📤 Export

Results and data exports are saved to the `export/` directory

## 📝 License

This project is open source and available under the MIT License.

## 👤 Author

**yesseniasabia5**

## 📞 Support

For issues, questions, or contributions, please open an issue on GitHub.

---

**Note**: Make sure to keep your Telegram bot token secure and never commit it to version control.