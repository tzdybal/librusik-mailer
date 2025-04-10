# Librus Email Forwarder

This script runs as a server that periodically checks for new messages in Librus and forwards them to specified email addresses using the Gmail API.

## Features

- Runs as a background server that checks for new messages at configurable intervals
- Forwards Librus messages to specified email addresses
- Includes all message attachments
- Configurable to forward only unread messages or all messages
- Uses Gmail API for reliable email delivery
- Tracks which messages have been processed to avoid duplicates
- Logs all activity to both console and file
- Configuration stored in YAML file

## Prerequisites

1. Python 3.6 or higher
2. The following Python packages:
   - aiohttp
   - pyyaml
   - google-api-python-client
   - google-auth-oauthlib
   - google-auth

## Installation

### On Debian/Ubuntu:
```
sudo apt install python3-pip
pip3 install aiohttp pyyaml google-api-python-client google-auth-oauthlib google-auth
```

### On Arch Linux:
```
# Using pacman and AUR
sudo pacman -S python python-pip python-aiohttp python-yaml
yay -S python-google-api-python-client python-google-auth-oauthlib python-google-auth

# OR using virtualenv (recommended)
sudo pacman -S python-virtualenv
virtualenv venv
source venv/bin/activate
pip install aiohttp pyyaml google-api-python-client google-auth-oauthlib google-auth
```

## Configuration

1. Copy `config.yaml.example` to `config.yaml`:
   ```
   cp config.yaml.example config.yaml
   ```

2. Edit `config.yaml` with your information:
   - `librus_username`: Your Librus username
   - `librus_password`: Your Librus password
   - `recipients`: List of email addresses to forward messages to
   - `sender_email`: Your Gmail address (the one you created API credentials for)
   - `gmail_credentials_path`: Path to your Gmail API credentials file
   - `only_unread`: Set to `true` to forward only unread messages, `false` to forward all
   - `check_interval`: How often to check for new messages (in minutes)

## Usage

Run the server:

```
python librus_email_forwarder.py
```

You can also specify a different configuration file:

```
python librus_email_forwarder.py /path/to/your/config.yaml
```

The first time you run the script, it will open a browser window asking you to authorize the application to send emails on your behalf. After authorization, a token will be saved locally so you won't need to authorize again.

### Running as a Service

#### Using systemd (Linux):

1. Create a systemd service file:

```
sudo nano /etc/systemd/system/librus-forwarder.service
```

2. Add the following content (adjust paths as needed):

```
[Unit]
Description=Librus Email Forwarder
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/script/directory
ExecStart=/usr/bin/python3 /path/to/script/directory/librus_email_forwarder.py
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

3. Enable and start the service:

```
sudo systemctl enable librus-forwarder.service
sudo systemctl start librus-forwarder.service
```

4. Check the status:

```
sudo systemctl status librus-forwarder.service
```

## Logging

The server logs all activity to both the console and a file named `librus_forwarder.log` in the same directory as the script. This log includes:

- Authentication attempts
- Message checks
- Email forwarding status
- Errors and warnings

## Security Notes

- The configuration file contains sensitive information (passwords). Make sure to:
  - Set appropriate file permissions: `chmod 600 config.yaml`
  - Keep it in a secure location
- The Gmail API token is stored in `token.json`. Protect this file as well.
- The script keeps track of processed messages in `processed_messages.json` to avoid duplicates.

## Troubleshooting

- If authentication fails, check your Librus credentials in the config file
- If Gmail authentication fails, ensure your credentials.json file is correct and you've completed the OAuth flow
- For Gmail API quota issues, increase the check interval in the configuration
- Check the log file for detailed error messages
- If the server stops unexpectedly, check system logs: `journalctl -u librus-forwarder.service` 
