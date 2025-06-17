"""
Simple AI Chat functionality for Anki flashcards
Uses built-in libraries and developer's API key for seamless user experience
"""

import json
import sqlite3
import os
import urllib.request
import urllib.parse
from typing import List, Dict, Optional
from datetime import datetime

from aqt import mw, gui_hooks
from aqt.qt import *
from aqt.utils import showInfo, showWarning, askUser
from anki.hooks import addHook
from anki.cards import Card

# Import API key from separate config file
try:
    from .api_config import OPENAI_API_KEY
except ImportError:
    # Fallback if api_config.py doesn't exist
    OPENAI_API_KEY = "your-openai-api-key-here"
    print("AI Chat: Please create api_config.py with your OpenAI API key")

class ChatDatabase:
    """Manages chat history storage for flashcards"""
    
    def __init__(self):
        self.db_path = os.path.join(mw.addonManager.addonsFolder(), "ai_chat_addon", "chat_history.db")
        self.init_db()
    
    def init_db(self):
        """Initialize the chat history database"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL
            )
        ''')
        conn.commit()
        conn.close()
    
    def save_message(self, card_id: int, role: str, content: str):
        """Save a chat message to the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO chat_history (card_id, timestamp, role, content)
            VALUES (?, ?, ?, ?)
        ''', (card_id, datetime.now().isoformat(), role, content))
        conn.commit()
        conn.close()
    
    def get_chat_history(self, card_id: int) -> List[Dict]:
        """Retrieve chat history for a specific card"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT timestamp, role, content FROM chat_history
            WHERE card_id = ?
            ORDER BY timestamp ASC
        ''', (card_id,))
        
        history = []
        for row in cursor.fetchall():
            history.append({
                'timestamp': row[0],
                'role': row[1],
                'content': row[2]
            })
        
        conn.close()
        return history

class AIChatWindow(QDialog):
    """Simple chat window for AI conversations about flashcards"""
    
    def __init__(self, parent, card: Card, card_content: str):
        super().__init__(parent)
        self.card = card
        self.card_content = card_content
        self.chat_db = ChatDatabase()
        
        self.setWindowTitle("AI Chat - Flashcard Assistant")
        self.setMinimumSize(600, 400)
        
        self.init_ui()
        self.load_chat_history()
    
    def init_ui(self):
        """Initialize the chat interface"""
        layout = QVBoxLayout(self)
        
        # Card content display
        card_group = QGroupBox("Flashcard Content")
        card_layout = QVBoxLayout(card_group)
        
        self.card_display = QTextEdit()
        self.card_display.setPlainText(self.card_content)
        self.card_display.setReadOnly(True)
        self.card_display.setMaximumHeight(120)
        card_layout.addWidget(self.card_display)
        
        layout.addWidget(card_group)
        
        # Chat history
        chat_group = QGroupBox("Chat History")
        chat_layout = QVBoxLayout(chat_group)
        
        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        chat_layout.addWidget(self.chat_history)
        
        layout.addWidget(chat_group)
        
        # Input area
        input_layout = QHBoxLayout()
        
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Ask a question about this flashcard...")
        self.message_input.returnPressed.connect(self.send_message)
        
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_message)
        
        input_layout.addWidget(self.message_input)
        input_layout.addWidget(self.send_button)
        
        layout.addLayout(input_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.clear_button = QPushButton("Clear History")
        self.clear_button.clicked.connect(self.clear_chat_history)
        
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        
        button_layout.addWidget(self.clear_button)
        button_layout.addStretch()
        button_layout.addWidget(self.close_button)
        
        layout.addLayout(button_layout)
    
    def load_chat_history(self):
        """Load and display existing chat history for this card"""
        history = self.chat_db.get_chat_history(self.card.id)
        
        for message in history:
            timestamp = datetime.fromisoformat(message['timestamp']).strftime("%H:%M:%S")
            role = "You" if message['role'] == "user" else "AI"
            
            self.append_to_chat(f"[{timestamp}] {role}: {message['content']}")
    
    def append_to_chat(self, text: str):
        """Add text to the chat history display"""
        self.chat_history.append(text)
        self.chat_history.append("")  # Add empty line for spacing
        
        # Scroll to bottom
        scrollbar = self.chat_history.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def send_message(self):
        """Send user message and get AI response"""
        user_message = self.message_input.text().strip()
        if not user_message:
            return
        
        # Clear input and disable button
        self.message_input.clear()
        self.send_button.setEnabled(False)
        self.send_button.setText("Sending...")
        
        # Display user message
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.append_to_chat(f"[{timestamp}] You: {user_message}")
        
        # Save user message
        self.chat_db.save_message(self.card.id, "user", user_message)
        
        # Get AI response
        ai_response = self.get_ai_response(user_message)
        
        if ai_response:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.append_to_chat(f"[{timestamp}] AI: {ai_response}")
            
            # Save AI response
            self.chat_db.save_message(self.card.id, "assistant", ai_response)
        
        # Re-enable button
        self.send_button.setEnabled(True)
        self.send_button.setText("Send")
    
    def get_ai_response(self, user_message: str) -> Optional[str]:
        """Get response from OpenAI API using built-in urllib"""
        try:
            # Prepare messages for OpenAI API
            messages = [
                {
                    "role": "system",
                    "content": f"You are a helpful study assistant. The user is studying a flashcard with the following content:\n\n{self.card_content}\n\nHelp them understand the material by answering questions and providing explanations. Keep responses concise and educational."
                }
            ]
            
            # Add recent chat history for context
            recent_history = self.chat_db.get_chat_history(self.card.id)[-6:]  # Last 6 messages
            for msg in recent_history:
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
            
            # Add current user message
            messages.append({
                "role": "user",
                "content": user_message
            })
            
            # Prepare API request
            data = {
                "model": "gpt-3.5-turbo",
                "messages": messages,
                "max_tokens": 500,
                "temperature": 0.7
            }
            
            # Make HTTP request to OpenAI
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=json.dumps(data).encode('utf-8'),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {OPENAI_API_KEY}"
                }
            )
            
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result['choices'][0]['message']['content'].strip()
            
        except Exception as e:
            return f"Sorry, I couldn't process your request right now. Error: {str(e)}"
    
    def clear_chat_history(self):
        """Clear chat history for this card"""
        if askUser("Are you sure you want to clear the chat history for this card?"):
            # Clear from database
            conn = sqlite3.connect(self.chat_db.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM chat_history WHERE card_id = ?", (self.card.id,))
            conn.commit()
            conn.close()
            
            # Clear display
            self.chat_history.clear()
            showInfo("Chat history cleared.")

class ReviewerButton:
    """Handles the chat button in the reviewer"""
    
    def __init__(self):
        self.current_card = None
    
    def add_chat_button(self, reviewer, card):
        """Add chat button to the reviewer"""
        self.current_card = card
        
        # Create button HTML that gets injected into the page
        chat_button_html = '''
        <div id="ai-chat-button-container" style="position: fixed; top: 10px; right: 10px; z-index: 9999;">
            <button id="ai-chat-button" onclick="pycmd('ai_chat')" style="
                background: linear-gradient(135deg, #0078d4, #005a9f);
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 25px;
                cursor: pointer;
                font-size: 14px;
                font-weight: bold;
                box-shadow: 0 2px 10px rgba(0,120,212,0.3);
                transition: all 0.3s ease;
                font-family: system-ui, -apple-system, sans-serif;
            " onmouseover="this.style.transform='scale(1.05)'" onmouseout="this.style.transform='scale(1)'">
                🤖 Chat with AI
            </button>
        </div>
        '''
        
        # Inject the button directly into the reviewer
        if hasattr(reviewer.web, 'eval'):
            # Remove any existing button first
            reviewer.web.eval("var existing = document.getElementById('ai-chat-button-container'); if (existing) existing.remove();")
            # Add the new button
            reviewer.web.eval(f"document.body.insertAdjacentHTML('beforeend', `{chat_button_html}`);")
    
    def open_chat_window(self):
        """Open the AI chat window"""
        if not self.current_card:
            showWarning("No card selected.")
            return
        
        # Extract card content (front and back)
        card_content = self.get_card_content(self.current_card)
        
        # Open chat window
        chat_window = AIChatWindow(mw, self.current_card, card_content)
        try:
            chat_window.exec()  # PyQt6 style
        except AttributeError:
            chat_window.exec_()  # PyQt5 style
    
    def get_card_content(self, card: Card) -> str:
        """Extract readable content from a card"""
        try:
            # Get the note
            note = card.note()
            
            # Extract field contents
            content_parts = []
            for field_name, field_value in note.items():
                # Remove HTML tags for cleaner text
                clean_value = self.strip_html(field_value)
                if clean_value.strip():
                    content_parts.append(f"{field_name}: {clean_value}")
            
            return "\n\n".join(content_parts)
            
        except Exception as e:
            return f"Error extracting card content: {str(e)}"
    
    def strip_html(self, text: str) -> str:
        """Remove HTML tags from text"""
        import re
        # Simple HTML tag removal
        clean = re.compile('<.*?>')
        return re.sub(clean, '', text)

# Global instances
reviewer_button = ReviewerButton()
chat_db = ChatDatabase()

def init_addon():
    """Initialize the add-on"""
    # Add hooks for reviewer
    addHook("reviewStateShortcuts", on_reviewer_shortcuts)
    gui_hooks.reviewer_did_show_question.append(on_show_question)
    gui_hooks.reviewer_did_show_answer.append(on_show_answer)
    gui_hooks.webview_did_receive_js_message.append(on_js_message)

def on_reviewer_shortcuts(shortcuts):
    """Add keyboard shortcuts for the reviewer"""
    shortcuts.append(("Cmd+Option+C", lambda: reviewer_button.open_chat_window()))

def on_show_question(card):
    """Called when a question is shown in the reviewer"""
    reviewer_button.add_chat_button(mw.reviewer, card)

def on_show_answer(card):
    """Called when an answer is shown in the reviewer"""
    reviewer_button.add_chat_button(mw.reviewer, card)

def on_js_message(handled, message, context):
    """Handle JavaScript messages from the reviewer"""
    if message == "ai_chat":
        reviewer_button.open_chat_window()
        return (True, None)
    return handled 