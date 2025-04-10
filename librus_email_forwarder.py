#!/usr/bin/env python3
import asyncio
import os
import sys
import json
import base64
import mimetypes
import signal
import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import aiohttp
import yaml

# Import the Librus class from the existing library
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from lib.api.librus import Librus

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('librus_forwarder.log')
    ]
)
logger = logging.getLogger('LibrusForwarder')

class LibrusEmailForwarder:
    def __init__(self, config_path="config.yaml"):
        """Initialize the forwarder with configuration from a YAML file"""
        self.config_path = config_path
        self.config = self._load_config()
        self.librus = Librus()
        self.processed_message_ids = {}  # Changed from set to dict to store ID -> date mapping
        self.running = False
        
        # Load previously processed message IDs if the file exists
        self._load_processed_ids()
        
    def _load_processed_ids(self):
        """Load previously processed message IDs from a file"""
        try:
            if os.path.exists('processed_messages.json'):
                with open('processed_messages.json', 'r') as f:
                    self.processed_message_ids = json.load(f)
                logger.info(f"Loaded {len(self.processed_message_ids)} previously processed message IDs")
        except Exception as e:
            logger.error(f"Error loading processed message IDs: {e}")
            self.processed_message_ids = {}
            
    def _save_processed_ids(self):
        """Save processed message IDs to a file"""
        try:
            with open('processed_messages.json', 'w') as f:
                # Format the JSON to have each entry on a single line
                json_str = json.dumps(self.processed_message_ids, indent=None, separators=(',', ':'))
                # Split by key-value pairs and join with newlines
                formatted_json = "{\n"
                entries = []
                for key, value in self.processed_message_ids.items():
                    entries.append(f'"{key}":"{value}"')
                formatted_json += ",\n".join(entries)
                formatted_json += "\n}"
                f.write(formatted_json)
            logger.info(f"Saved {len(self.processed_message_ids)} processed message IDs with dates")
        except Exception as e:
            logger.error(f"Error saving processed message IDs: {e}")
        
    def _load_config(self):
        """Load configuration from YAML file"""
        try:
            with open(self.config_path, 'r') as file:
                config = yaml.safe_load(file)
                
            # Validate required configuration
            required_keys = ['librus_username', 'librus_password', 'recipients', 'check_interval', 
                            'smtp_server', 'smtp_port', 'smtp_username', 'smtp_password', 'sender_email']
            for key in required_keys:
                if key not in config:
                    raise ValueError(f"Missing required configuration: {key}")
                    
            return config
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            sys.exit(1)
    
    def _send_email(self, recipients, subject, html_content, attachments=None):
        """Send an email using SMTP"""
        # Get email configuration from config
        smtp_server = self.config['smtp_server']
        smtp_port = self.config['smtp_port']
        smtp_username = self.config['smtp_username']
        smtp_password = self.config['smtp_password']
        sender_email = self.config['sender_email']
        
        # Create multipart message
        message = MIMEMultipart('mixed')
        message['Subject'] = subject
        message['From'] = sender_email
        message['To'] = ', '.join(recipients)
        
        # Create the HTML part as an alternative part
        msg_alternative = MIMEMultipart('alternative')
        
        # Attach HTML content
        html_part = MIMEText(html_content, 'html')
        msg_alternative.attach(html_part)
        
        # Attach the alternative part to the main message
        message.attach(msg_alternative)
        
        # Add attachments if any
        if attachments:
            logger.info(f"Adding {len(attachments)} attachments to email")
            for attachment in attachments:
                try:
                    filename = attachment['name']
                    content = attachment['content']
                    
                    # Ensure content is bytes
                    if not isinstance(content, bytes):
                        logger.warning(f"Attachment content for {filename} is not bytes, attempting to convert")
                        if isinstance(content, str):
                            content = content.encode('utf-8')
                        else:
                            content = bytes(content)
                    
                    # Guess the content type based on the file's extension
                    content_type, encoding = mimetypes.guess_type(filename)
                    if content_type is None or encoding is not None:
                        content_type = 'application/octet-stream'
                    
                    main_type, sub_type = content_type.split('/', 1)
                    
                    # Create the attachment
                    att = MIMEBase(main_type, sub_type)
                    att.set_payload(content)
                    encoders.encode_base64(att)
                    att.add_header('Content-Disposition', 'attachment', filename=filename)
                    message.attach(att)
                    logger.info(f"  Attached: {filename} ({len(content)} bytes)")
                except Exception as e:
                    logger.error(f"  Error attaching {attachment.get('name', 'unknown')}: {e}")
        
        # Connect to SMTP server and send the email
        try:
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()  # Secure the connection
            server.login(smtp_username, smtp_password)
            server.send_message(message)
            server.quit()
            logger.info(f"Email sent successfully: {subject}")
            return True
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return False
    
    async def authenticate(self):
        """Authenticate with Librus using provided credentials"""
        logger.info("Authenticating with Librus...")
        result = await self.librus.mktoken(
            self.config['librus_username'], 
            self.config['librus_password']
        )
        if not result:
            logger.error("Authentication failed. Please check your Librus credentials.")
            return False
        logger.info("Librus authentication successful!")
        return True

    async def get_all_messages(self):
        """Get all messages from the Librus inbox"""
        logger.info("Fetching messages from Librus...")
        messages = await self.librus.get_messages()
        logger.info(f"Found {len(messages)} messages in total.")
        return messages
    
    async def process_messages(self, messages, only_unread=True):
        """Process messages and forward them via email"""
        unread_count = 0
        forwarded_count = 0
        new_processed_ids = {}  # Changed from list to dict
        
        # Get recipient emails from config
        recipients = self.config['recipients']
        if not recipients:
            logger.warning("No recipients specified in config. Exiting.")
            return 0, 0
            
        for message in messages:
            # Skip already processed messages
            message_id = message["link"]
            if message_id in self.processed_message_ids:
                continue
                
            # Get full message details
            msg_details = await self.librus.get_message(message_id)
            
            # Extract message date
            message_date = msg_details["date"]
            
            # Check if message is unread
            is_unread = "nieprzeczytana" in msg_details["read"].lower()
            
            if is_unread:
                unread_count += 1
                
            # Skip if we only want unread messages and this one is read
            if only_unread and not is_unread:
                # Still mark as processed with its date
                new_processed_ids[message_id] = message_date
                continue
                
            logger.info(f"Processing message: {msg_details['subject']}")
            
            # Prepare email subject with [Librus] prefix
            email_subject = f"[Librus] {msg_details['subject']}"
            
            # Prepare email content with metadata and original content
            email_content = f"""
            <html>
            <head></head>
            <body>
                <h2>Message from Librus</h2>
                <p><strong>From:</strong> {msg_details['from']}</p>
                <p><strong>Date:</strong> {msg_details['date']}</p>
                <p><strong>Subject:</strong> {msg_details['subject']}</p>
                <hr>
                <div>{msg_details['content']}</div>
            </body>
            </html>
            """
            
            # Download attachments if any
            attachments = []
            if msg_details["attachments"]:
                logger.info(f"  Found {len(msg_details['attachments'])} attachments")
                
                for attachment in msg_details["attachments"]:
                    attachment_filename = attachment["name"]
                    
                    # Download the attachment
                    file_data = await self.librus.download_file(attachment["nice"])
                    
                    if file_data and "content" in file_data:
                        logger.info(f"  Downloaded: {attachment_filename}")
                        
                        # Add attachment to the list - ensure content is bytes
                        attachments.append({
                            'name': attachment_filename,
                            'content': file_data["content"]
                        })
                        logger.debug(f"  Attachment size: {len(file_data['content'])} bytes")
                    else:
                        logger.warning(f"  Failed to download: {attachment_filename}")
            
            # Send the email
            result = self._send_email(
                recipients,
                email_subject,
                email_content,
                attachments
            )
            
            if result:
                logger.info(f"  Email sent successfully: {email_subject}")
                if attachments:
                    logger.info(f"  Included {len(attachments)} attachments")
                forwarded_count += 1
                new_processed_ids[message_id] = message_date
            else:
                logger.error(f"  Failed to send email: {email_subject}")
                
        # Update processed message IDs
        self.processed_message_ids.update(new_processed_ids)
        self._save_processed_ids()
                
        return forwarded_count, unread_count
        
    async def check_and_forward(self):
        """Check for new messages and forward them"""
        try:
            # Re-authenticate if needed
            if not await self.authenticate():
                return
            
            # Get all messages
            messages = await self.get_all_messages()
            
            # Get forwarding preference from config
            only_unread = self.config.get('only_unread', True)
            
            # Process and forward messages
            forwarded, unread = await self.process_messages(messages, only_unread)
            
            if forwarded > 0:
                logger.info(f"Summary: Forwarded {forwarded} messages out of {unread} unread messages")
        except Exception as e:
            logger.error(f"Error in check_and_forward: {e}")
            
    async def run_server(self):
        """Run the server that periodically checks for new messages"""
        self.running = True
        
        logger.info("Starting Librus Email Forwarder server")
        logger.info(f"Checking for new messages every {self.config['check_interval']} minutes")
        
        # Create a task for checking messages
        check_task = None
        
        try:
            # Set up signal handlers for asyncio
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(
                    sig,
                    lambda s=sig: asyncio.create_task(self._async_shutdown(s))
                )
            
            while self.running:
                # Create a task for checking messages
                check_task = asyncio.create_task(self.check_and_forward())
                
                # Wait for the check to complete
                await check_task
                check_task = None
                
                if not self.running:
                    break
                
                # Sleep for the configured interval
                interval_minutes = self.config['check_interval']
                logger.info(f"Next check in {interval_minutes} minutes")
                
                # Create a sleep task that can be cancelled
                sleep_task = asyncio.create_task(asyncio.sleep(interval_minutes * 60))
                
                try:
                    # Wait for the sleep to complete or be cancelled
                    await sleep_task
                except asyncio.CancelledError:
                    logger.info("Sleep interrupted, shutting down...")
                    break
                
        except asyncio.CancelledError:
            logger.info("Server task cancelled")
        finally:
            # Cancel any pending tasks
            if check_task and not check_task.done():
                check_task.cancel()
                try:
                    await check_task
                except asyncio.CancelledError:
                    pass
                
            logger.info("Server stopped")
    
    async def _async_shutdown(self, sig):
        """Handle shutdown signals asynchronously"""
        logger.info(f"Received signal {sig}, shutting down...")
        self.running = False
        
        # Save processed IDs before exiting
        self._save_processed_ids()
        
        # Get the current event loop
        loop = asyncio.get_running_loop()
        
        # Cancel all running tasks except the current one
        for task in asyncio.all_tasks(loop):
            if task is not asyncio.current_task():
                task.cancel()
    
    def _handle_shutdown(self, sig, frame):
        """Legacy signal handler for non-asyncio contexts"""
        logger.info(f"Received signal {sig}, shutting down...")
        self.running = False
        self._save_processed_ids()

async def main():
    # Default config file path
    config_path = "config.yaml"
    
    # Check if config file path is provided as argument
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
    
    # Create forwarder
    forwarder = LibrusEmailForwarder(config_path)
    
    # Run the server
    await forwarder.run_server()

if __name__ == "__main__":
    asyncio.run(main()) 