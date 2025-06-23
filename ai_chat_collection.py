"""
AI Chat functionality for Anki flashcards with Collection Database Integration
Uses standalone floating window with comprehensive user settings
"""

import json
import sqlite3
import os
import urllib.request
import urllib.parse
import re
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path

from aqt import mw, gui_hooks
from aqt.qt import *
from aqt.qt import Qt, QPoint
from aqt.utils import showInfo, showWarning, askUser
from anki.hooks import addHook
from anki.cards import Card

# Embedded API key for private use
# IMPORTANT: Replace this with your actual OpenAI API key
OPENAI_API_KEY = "your-openai-api-key-here"

# Modal window approach - much simpler and more reliable!

# Default configuration
DEFAULT_CONFIG = {
    "openai_model": "gpt-3.5-turbo",
    "max_tokens": 300,
    "temperature": 0.7,
    "show_button": True,
    "button_position": {"x": 50, "y": 50},  # pixels from top-left
    "hotkey": "Ctrl+Shift+A",
    "button_size": 50,
    "button_opacity": 0.9,
    "window_width": 400,
    "window_height": 600,
    "window_always_on_top": True,
    "auto_focus_input": True,
    "ai_instructions": "You are a helpful AI assistant helping a student study flashcards. Please provide helpful, concise responses related to the flashcard content.",
    
    # Color scheme customization
    "color_scheme": "auto",  # auto, light, dark, custom
    "custom_colors": {
        "bg_main": "#ffffff",
        "bg_secondary": "#f8f9fa", 
        "bg_input": "#f8f9fa",
        "text_primary": "#333333",
        "text_secondary": "#666666",
        "border": "#e9ecef",
        "ai_bubble_bg": "#f1f3f4",
        "ai_bubble_text": "#333333",
        "accent_color": "#6c5ce7"
    },
    
    # Button icon customization
    "button_icon": "🤖",  # emoji or "custom" for custom image
    "custom_button_image_path": ""  # path to custom image file
}

class ConfigManager:
    """Manages user configuration settings"""
    
    def __init__(self):
        self.config_path = os.path.join(mw.addonManager.addonsFolder(), "ai_chat_addon", "config.json")
        self.config = self.load_config()
    
    def load_config(self):
        """Load configuration from file or create default"""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
                    # Merge with defaults for any missing keys
                    for key, value in DEFAULT_CONFIG.items():
                        if key not in config:
                            config[key] = value
                    return config
        except Exception as e:
            print(f"Error loading config: {e}")
        
        return DEFAULT_CONFIG.copy()
    
    def save_config(self):
        """Save configuration to file"""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Error saving config: {e}")
    
    def get(self, key, default=None):
        """Get configuration value"""
        return self.config.get(key, default)
    
    def set(self, key, value):
        """Set configuration value and save"""
        self.config[key] = value
        self.save_config()

class ChatDatabase:
    """Manages chat history storage in Anki's collection database"""
    
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
    
    def clear_chat_history(self, card_id: int):
        """Clear chat history for a specific card"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_history WHERE card_id = ?", (card_id,))
        conn.commit()
        conn.close()

def is_dark_mode():
    """Detect if Anki is using dark mode"""
    try:
        # Check Anki's theme setting
        if hasattr(mw.pm, 'night_mode'):
            return mw.pm.night_mode()
        
        # Fallback: check application palette
        palette = QApplication.instance().palette()
        window_color = palette.color(QPalette.ColorRole.Window)
        return window_color.lightness() < 128
    except:
        return False

def get_theme_colors():
    """Get appropriate colors based on current theme and user preferences"""
    color_scheme = config_manager.get("color_scheme", "auto")
    
    # Custom color scheme
    if color_scheme == "custom":
        custom_colors = config_manager.get("custom_colors", DEFAULT_CONFIG["custom_colors"])
        return custom_colors.copy()
    
    # Light theme
    elif color_scheme == "light":
        return {
            'bg_main': '#ffffff',
            'bg_secondary': '#f8f9fa',
            'bg_input': '#f8f9fa',
            'text_primary': '#333333',
            'text_secondary': '#666666',
            'border': '#e9ecef',
            'ai_bubble_bg': '#f1f3f4',
            'ai_bubble_text': '#333333',
            'accent_color': '#6c5ce7'
        }
    
    # Dark theme
    elif color_scheme == "dark":
        return {
            'bg_main': '#2b2b2b',
            'bg_secondary': '#383838',
            'bg_input': '#404040',
            'text_primary': '#ffffff',
            'text_secondary': '#cccccc',
            'border': '#555555',
            'ai_bubble_bg': '#404040',
            'ai_bubble_text': '#ffffff',
            'accent_color': '#9c88ff'
        }
    
    # Auto (follow Anki's theme)
    else:
        if is_dark_mode():
            return {
                'bg_main': '#2b2b2b',
                'bg_secondary': '#383838',
                'bg_input': '#404040',
                'text_primary': '#ffffff',
                'text_secondary': '#cccccc',
                'border': '#555555',
                'ai_bubble_bg': '#404040',
                'ai_bubble_text': '#ffffff',
                'accent_color': '#9c88ff'
            }
        else:
            return {
                'bg_main': '#ffffff',
                'bg_secondary': '#f8f9fa',
                'bg_input': '#f8f9fa',
                'text_primary': '#333333',
                'text_secondary': '#666666',
                'border': '#e9ecef',
                'ai_bubble_bg': '#f1f3f4',
                'ai_bubble_text': '#333333',
                'accent_color': '#6c5ce7'
            }

def convert_markdown_to_html(text: str) -> str:
    """Convert basic markdown formatting to HTML"""
    # Convert headers BEFORE converting line breaks
    # ### Header 3 -> <h3>
    text = re.sub(r'^### (.+)$', r'<h3 style="font-size: 16px; font-weight: bold; margin: 12px 0 8px 0; color: #6c5ce7;">\1</h3>', text, flags=re.MULTILINE)
    # ## Header 2 -> <h2>  
    text = re.sub(r'^## (.+)$', r'<h2 style="font-size: 18px; font-weight: bold; margin: 16px 0 10px 0; color: #6c5ce7;">\1</h2>', text, flags=re.MULTILINE)
    # # Header 1 -> <h1>
    text = re.sub(r'^# (.+)$', r'<h1 style="font-size: 20px; font-weight: bold; margin: 20px 0 12px 0; color: #6c5ce7;">\1</h1>', text, flags=re.MULTILINE)
    
    # Convert **bold** to <b>bold</b>
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    
    # Convert *italic* to <i>italic</i>
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    
    # Convert `code` to <code>code</code>
    text = re.sub(r'`(.*?)`', r'<code style="background-color: rgba(128,128,128,0.2); padding: 2px 4px; border-radius: 3px; font-family: monospace;">\1</code>', text)
    
    # Convert newlines to <br> for proper line breaks
    text = text.replace('\n', '<br>')
    
    # Convert numbered lists (basic support)
    text = re.sub(r'^(\d+)\.\s+(.+)$', r'<div style="margin: 4px 0;"><b>\1.</b> \2</div>', text, flags=re.MULTILINE)
    
    # Convert bullet points
    text = re.sub(r'^[•\-\*]\s+(.+)$', r'<div style="margin: 4px 0;">• \1</div>', text, flags=re.MULTILINE)
    
    return text

class AIFloatingChatWindow(QDialog):
    """Standalone floating chat window with modern UI"""
    
    def __init__(self, parent, card: Card, card_content: str):
        super().__init__(parent)
        self.card = card
        self.card_content = card_content
        self.chat_db = ChatDatabase()
        self.config = config_manager.config
        self.theme_colors = get_theme_colors()
        self.current_ai_bubble = None  # Track current streaming bubble
        
        self.init_window()
        self.init_ui()
        self.load_chat_history()
        
        # Make window stay on top if configured
        if self.config.get("window_always_on_top", True):
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        
        # Modal window naturally prevents key conflicts with Anki
    
    def init_window(self):
        """Initialize window properties"""
        self.setWindowTitle("🤖 AI Chat Assistant")
        
        # Make window resizable instead of fixed size
        self.setMinimumSize(300, 400)
        self.resize(
            self.config.get("window_width", 400),
            self.config.get("window_height", 600)
        )
        
        # Remove window frame for modern look but keep resize capability
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Set window style with theme colors
        bg_color = self.theme_colors['bg_secondary']
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {bg_color};
                border-radius: 12px;
                border: 1px solid rgba(108, 92, 231, 0.3);
            }}
        """)
    
    def init_ui(self):
        """Initialize the modern chat interface"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header with close button (fixed size, not responsive)
        header = QWidget()
        header.setStyleSheet("""
            QWidget {
                background-color: #6c5ce7;
                color: white;
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
            }
        """)
        header.setFixedHeight(50)  # Fixed header height
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(15, 10, 15, 10)
        
        # Drag handle
        self.drag_handle = QLabel("🤖 AI Chat")
        self.drag_handle.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
        """)
        
        # Summary button
        summary_btn = QPushButton("📋")
        summary_btn.setToolTip("Generate conversation summary")
        summary_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: white;
                font-size: 16px;
                font-weight: bold;
                border-radius: 15px;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.2);
            }
        """)
        summary_btn.setFixedSize(30, 30)
        summary_btn.clicked.connect(self.generate_conversation_summary)
        
        # Generate flashcards button
        flashcards_btn = QPushButton("🃏")
        flashcards_btn.setToolTip("Generate new flashcards from conversation")
        flashcards_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: white;
                font-size: 16px;
                font-weight: bold;
                border-radius: 15px;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.2);
            }
        """)
        flashcards_btn.setFixedSize(30, 30)
        flashcards_btn.clicked.connect(self.generate_flashcards)
        
        # Settings button (fixed size)
        settings_btn = QPushButton("⚙")
        settings_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: white;
                font-size: 14px;
                border-radius: 15px;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.2);
            }
        """)
        settings_btn.setFixedSize(30, 30)
        settings_btn.clicked.connect(self.show_settings)
        
        # Close button (fixed size)
        close_btn = QPushButton("✕")
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: white;
                font-size: 16px;
                font-weight: bold;
                border-radius: 15px;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.2);
            }
        """)
        close_btn.setFixedSize(30, 30)
        close_btn.clicked.connect(self.close)
        
        header_layout.addWidget(self.drag_handle)
        header_layout.addStretch()
        header_layout.addWidget(summary_btn)
        header_layout.addWidget(flashcards_btn)
        header_layout.addWidget(settings_btn)
        header_layout.addWidget(close_btn)
        
        layout.addWidget(header)
        
        # Chat area with theme-aware styling (fixed padding)
        self.chat_scroll = QScrollArea()
        bg_main = self.theme_colors['bg_main']
        self.chat_scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {bg_main};
            }}
            QScrollBar:vertical {{
                background-color: #f1f3f4;
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: #c1c8cd;
                border-radius: 4px;
                min-height: 20px;
            }}
        """)
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.chat_widget = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_widget)
        self.chat_layout.setContentsMargins(15, 15, 15, 15)  # Fixed padding
        self.chat_layout.setSpacing(10)  # Fixed spacing
        self.chat_layout.addStretch()
        
        self.chat_scroll.setWidget(self.chat_widget)
        layout.addWidget(self.chat_scroll)
        
        # Input area with theme-aware styling (fixed sizing)
        input_container = QWidget()
        bg_secondary = self.theme_colors['bg_secondary']
        border_color = self.theme_colors['border']
        input_container.setStyleSheet(f"""
            QWidget {{
                background-color: {bg_secondary};
                border-bottom-left-radius: 12px;
                border-bottom-right-radius: 12px;
                border-top: 1px solid {border_color};
            }}
        """)
        input_container.setFixedHeight(70)  # Fixed input height
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(15, 15, 15, 15)
        
        # Simple QLineEdit with theme-aware styling (fixed sizing)
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Ask about this flashcard...")
        bg_input = self.theme_colors['bg_input']
        text_color = self.theme_colors['text_primary']
        border_color = self.theme_colors['border']
        self.message_input.setStyleSheet(f"""
            QLineEdit {{
                border: 1px solid {border_color};
                border-radius: 20px;
                padding: 10px 15px;
                font-size: 14px;
                background-color: {bg_input};
                color: {text_color};
            }}
            QLineEdit:focus {{
                border: 2px solid #6c5ce7;
                background-color: {bg_input};
            }}
        """)
        self.message_input.returnPressed.connect(self.send_message)
        
        # Send button (fixed sizing)
        self.send_button = QPushButton("➤")
        self.send_button.setStyleSheet("""
            QPushButton {
                background-color: #6c5ce7;
                color: white;
                border: none;
                border-radius: 20px;
                font-size: 16px;
                font-weight: bold;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #5a4fcf;
            }
            QPushButton:pressed {
                background-color: #4c43c7;
            }
            QPushButton:disabled {
                background-color: #adb5bd;
            }
        """)
        self.send_button.setFixedSize(40, 40)
        self.send_button.clicked.connect(self.send_message)
        
        input_layout.addWidget(self.message_input)
        input_layout.addWidget(self.send_button)
        
        layout.addWidget(input_container)
        
        # Enable dragging and resizing
        self.dragging = False
        self.resizing = False
        self.drag_position = QPoint()
        self.resize_direction = None
        self.resize_start_geometry = QRect()
        self.resize_start_mouse = QPoint()
        
        # Auto-focus input if configured
        if self.config.get("auto_focus_input", True):
            self.message_input.setFocus()
    
    def closeEvent(self, event):
        """Handle window close event"""
        # Save window size to config
        config_manager.set("window_width", self.width())
        config_manager.set("window_height", self.height())
        super().closeEvent(event)
    
    def mousePressEvent(self, event):
        """Handle mouse press for window dragging and resizing"""
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if clicking on resize area
            self.resize_direction = self.get_resize_direction(event.position().toPoint())
            if self.resize_direction:
                self.resizing = True
                self.resize_start_mouse = event.globalPosition().toPoint()
                self.resize_start_geometry = QRect(self.geometry())
                self.setCursor(self.get_resize_cursor(self.resize_direction))
            else:
                # Check if clicking on header for dragging (increased header area)
                header_rect = QRect(0, 0, self.width(), 60)  # Larger drag area
                if header_rect.contains(event.position().toPoint()):
                    self.dragging = True
                    self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            
            event.accept()
    
    def mouseMoveEvent(self, event):
        """Handle mouse move for window dragging and resizing"""
        if event.buttons() == Qt.MouseButton.LeftButton:
            if self.resizing and self.resize_direction:
                self.handle_resize(event.globalPosition().toPoint())
            elif self.dragging:
                new_pos = event.globalPosition().toPoint() - self.drag_position
                self.move(new_pos)
                
                # Save position
                config_manager.set("button_position", {
                    "x": new_pos.x(),
                    "y": new_pos.y()
                })
            event.accept()
        else:
            # Update cursor based on position for resize hints
            resize_dir = self.get_resize_direction(event.position().toPoint())
            if resize_dir:
                self.setCursor(self.get_resize_cursor(resize_dir))
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release for window dragging and resizing"""
        self.dragging = False
        self.resizing = False
        self.resize_direction = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
    
    def get_resize_direction(self, pos):
        """Determine resize direction based on cursor position"""
        margin = 20  # Increased resize margin for easier grabbing
        
        left = pos.x() <= margin
        right = pos.x() >= self.width() - margin
        top = pos.y() <= margin
        bottom = pos.y() >= self.height() - margin
        
        if left and top:
            return "top-left"
        elif right and top:
            return "top-right"
        elif left and bottom:
            return "bottom-left"
        elif right and bottom:
            return "bottom-right"
        elif left:
            return "left"
        elif right:
            return "right"
        elif top:
            return "top"
        elif bottom:
            return "bottom"
        
        return None
    
    def get_resize_cursor(self, direction):
        """Get appropriate cursor for resize direction"""
        cursors = {
            "top": Qt.CursorShape.SizeVerCursor,
            "bottom": Qt.CursorShape.SizeVerCursor,
            "left": Qt.CursorShape.SizeHorCursor,
            "right": Qt.CursorShape.SizeHorCursor,
            "top-left": Qt.CursorShape.SizeFDiagCursor,
            "bottom-right": Qt.CursorShape.SizeFDiagCursor,
            "top-right": Qt.CursorShape.SizeBDiagCursor,
            "bottom-left": Qt.CursorShape.SizeBDiagCursor,
        }
        return cursors.get(direction, Qt.CursorShape.ArrowCursor)
    
    def handle_resize(self, global_pos):
        """Handle window resizing based on direction with improved logic"""
        if not self.resize_direction or not self.resizing:
            return
            
        # Calculate mouse movement delta
        delta = global_pos - self.resize_start_mouse
        start_rect = self.resize_start_geometry
        
        # Calculate new geometry
        new_rect = QRect(start_rect)
        
        # Handle horizontal resizing
        if "left" in self.resize_direction:
            new_width = start_rect.width() - delta.x()
            if new_width >= self.minimumWidth():
                new_rect.setLeft(start_rect.left() + delta.x())
                new_rect.setWidth(new_width)
        elif "right" in self.resize_direction:
            new_width = start_rect.width() + delta.x()
            if new_width >= self.minimumWidth():
                new_rect.setWidth(new_width)
        
        # Handle vertical resizing
        if "top" in self.resize_direction:
            new_height = start_rect.height() - delta.y()
            if new_height >= self.minimumHeight():
                new_rect.setTop(start_rect.top() + delta.y())
                new_rect.setHeight(new_height)
        elif "bottom" in self.resize_direction:
            new_height = start_rect.height() + delta.y()
            if new_height >= self.minimumHeight():
                new_rect.setHeight(new_height)
        
        # Apply the new geometry
        self.setGeometry(new_rect)
    
    def load_chat_history(self):
        """Load and display existing chat history for this card"""
        history = self.chat_db.get_chat_history(self.card.id)
        
        for message in history:
            is_user = message['role'] == "user"
            self.add_message_bubble(message['content'], is_user)
    
    def add_message_bubble(self, text: str, is_user: bool):
        """Add a message to the chat - bubble for user, full-width for AI"""
        message_widget = QWidget()
        message_layout = QHBoxLayout(message_widget)
        message_layout.setContentsMargins(0, 0, 0, 0)
        
        if is_user:
            # User messages: Keep as chat bubbles on the right
            message_layout.addStretch()
        
            # Create message bubble with fixed sizing (don't scale with window)
            bubble = QLabel(text)
            bubble.setWordWrap(True)
            bubble.setMaximumWidth(300)  # Fixed max width for user bubbles
            bubble.setMinimumWidth(50)
        
            bubble.setStyleSheet("""
                QLabel {
                    background-color: #6c5ce7;
                    color: white;
                    border-radius: 18px;
                    padding: 12px 16px;
                    font-size: 14px;
                    margin: 2px;
                }
            """)
            
            message_layout.addWidget(bubble)
        else:
            # AI messages: Full-width document style like ChatGPT with markdown support
            ai_content = QLabel()
            ai_content.setWordWrap(True)
            ai_content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            
            # Convert markdown to HTML and set as rich text
            html_text = convert_markdown_to_html(text)
            ai_content.setText(html_text)
            ai_content.setTextFormat(Qt.TextFormat.RichText)  # Enable HTML rendering
            
            # Use theme-aware colors for full-width AI content
            bg_color = self.theme_colors['bg_main']
            text_color = self.theme_colors['text_primary']
            
            ai_content.setStyleSheet(f"""
                QLabel {{
                    background-color: {bg_color};
                    color: {text_color};
                    font-size: 14px;
                    line-height: 1.6;
                    padding: 16px;
                    margin: 8px 0px;
                    border: none;
                    border-radius: 8px;
                }}
            """)
            
            # Use full width for AI responses
            message_layout.addWidget(ai_content)
        
        # Insert before the stretch
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, message_widget)
        
        # Scroll to bottom
        QTimer.singleShot(10, self.scroll_to_bottom)
    
    def scroll_to_bottom(self):
        """Scroll the chat to the bottom"""
        scrollbar = self.chat_scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def send_message(self):
        """Send user message and get AI response with streaming"""
        user_message = self.message_input.text().strip()
        if not user_message:
            return
        
        # Clear input
        self.message_input.clear()
        
        # Add user message to chat
        self.add_message_bubble(user_message, is_user=True)
        
        # Save user message to database
        self.chat_db.save_message(self.card.id, "user", user_message)
        
        # Disable send button during response
        self.send_button.setEnabled(False)
        self.message_input.setEnabled(False)
        
        # Create AI response bubble for streaming
        self.current_ai_bubble = self.create_streaming_ai_bubble()
        
        # Get AI response with streaming
        self.get_ai_response_streaming(user_message)
    
    def create_streaming_ai_bubble(self):
        """Create a full-width AI content area for streaming"""
        message_widget = QWidget()
        message_layout = QHBoxLayout(message_widget)
        message_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create full-width AI content area (not a bubble)
        ai_content = QLabel("...")  # Start with typing indicator
        ai_content.setWordWrap(True)
        ai_content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        ai_content.setTextFormat(Qt.TextFormat.RichText)  # Enable HTML rendering for streaming
        
        # Use theme-aware colors for full-width AI content
        bg_color = self.theme_colors['bg_main']
        text_color = self.theme_colors['text_primary']
        
        ai_content.setStyleSheet(f"""
            QLabel {{
                background-color: {bg_color};
                color: {text_color};
                font-size: 14px;
                line-height: 1.6;
                padding: 16px;
                margin: 8px 0px;
                border: none;
                border-radius: 8px;
            }}
        """)
        
        # Use full width for AI responses
        message_layout.addWidget(ai_content)
        
        # Insert before the stretch
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, message_widget)
        
        # Scroll to bottom
        QTimer.singleShot(10, self.scroll_to_bottom)
        
        return ai_content
    
    def update_streaming_bubble(self, text):
        """Update the streaming AI bubble with new text"""
        if self.current_ai_bubble:
            # Convert markdown to HTML for streaming updates
            html_text = convert_markdown_to_html(text)
            self.current_ai_bubble.setText(html_text)
            # Scroll to bottom to follow the conversation
            QTimer.singleShot(10, self.scroll_to_bottom)
    
    def finish_streaming_response(self, final_text):
        """Finish the streaming response and save to database"""
        if self.current_ai_bubble:
            # Convert final markdown to HTML
            html_text = convert_markdown_to_html(final_text)
            self.current_ai_bubble.setText(html_text)
            self.current_ai_bubble = None
        
        # Save AI response to database (save original markdown text)
        self.chat_db.save_message(self.card.id, "assistant", final_text)
        
        # Re-enable input
        self.send_button.setEnabled(True)
        self.message_input.setEnabled(True)
        self.message_input.setFocus()
        
        # Final scroll to bottom
        QTimer.singleShot(10, self.scroll_to_bottom)
    
    def get_ai_response_streaming(self, user_message: str):
        """Get AI response using OpenAI API with streaming"""
        # Create a worker thread to handle the streaming API call
        self.worker = StreamingWorker(user_message, self.card_content, self.config)
        self.worker.chunk_received.connect(self.update_streaming_bubble)
        self.worker.response_finished.connect(self.finish_streaming_response)
        self.worker.error_occurred.connect(self.handle_streaming_error)
        self.worker.start()
    
    def handle_streaming_error(self, error_message):
        """Handle errors during streaming"""
        if self.current_ai_bubble:
            self.current_ai_bubble.setText(f"Error: {error_message}")
            self.current_ai_bubble = None
        
        # Re-enable input
        self.send_button.setEnabled(True)
        self.message_input.setEnabled(True)
        self.message_input.setFocus()
    
    def show_settings(self):
        """Show settings dialog"""
        settings_dialog = SettingsDialog(self)
        if settings_dialog.exec():
            # Reload config after settings change
            self.config = config_manager.config
    
    def generate_conversation_summary(self):
        """Generate a summary of the conversation and show save dialog"""
        # Get all chat history for this card
        chat_history = self.chat_db.get_chat_history(self.card.id)
        
        if not chat_history or len(chat_history) < 2:
            showWarning("Not enough conversation to summarize. Have a chat first!")
            return
        
        # Build conversation text
        conversation_text = f"Flashcard: {self.card_content}\n\nConversation:\n"
        for message in chat_history:
            role = "You" if message['role'] == "user" else "AI"
            conversation_text += f"{role}: {message['content']}\n\n"
        
        # Open dialog immediately and start streaming
        dialog = SummaryDialog(self, "", self.card)  # Start with empty summary
        dialog.start_streaming_summary(conversation_text, self.config)
        dialog.exec()
    
    def create_summary_worker(self, conversation_text: str):
        """Create worker thread to generate summary"""
        self.summary_worker = SummaryWorker(conversation_text, self.config)
        self.summary_worker.summary_generated.connect(self.show_summary_dialog)
        self.summary_worker.error_occurred.connect(self.handle_summary_error)
        self.summary_worker.start()
        
        # Show loading indicator
        showInfo("Generating conversation summary... Please wait.")
    
    def show_summary_dialog(self, summary_text: str):
        """Show dialog with summary and save options"""
        dialog = SummaryDialog(self, summary_text, self.card)
        dialog.exec()
    
    def handle_summary_error(self, error_message: str):
        """Handle summary generation errors"""
        showWarning(f"Failed to generate summary: {error_message}")

    def generate_flashcards(self):
        """Generate new flashcards from the conversation"""
        # Get all chat history for this card
        chat_history = self.chat_db.get_chat_history(self.card.id)
        
        if not chat_history or len(chat_history) < 2:
            showWarning("Not enough conversation to generate flashcards. Have a chat first!")
            return
        
        # Build conversation text
        conversation_text = f"Flashcard: {self.card_content}\n\nConversation:\n"
        for message in chat_history:
            role = "You" if message['role'] == "user" else "AI"
            conversation_text += f"{role}: {message['content']}\n\n"
        
        # Open flashcard generation dialog
        dialog = FlashcardGenerationDialog(self, conversation_text, self.card, self.config)
        dialog.exec()

class SettingsDialog(QDialog):
    """Settings configuration dialog"""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.config = config_manager.config
        self.init_ui()
    
    def init_ui(self):
        """Initialize settings UI"""
        self.setWindowTitle("AI Chat Settings")
        self.setFixedSize(500, 700)
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        
        # Create tabs
        tabs = QTabWidget()
        
        # General tab
        general_tab = QWidget()
        general_layout = QFormLayout(general_tab)
        
        # AI Instructions
        self.ai_instructions_text = QTextEdit()
        self.ai_instructions_text.setPlainText(self.config.get("ai_instructions", DEFAULT_CONFIG["ai_instructions"]))
        self.ai_instructions_text.setMaximumHeight(100)
        general_layout.addRow("AI Instructions:", self.ai_instructions_text)
        
        # AI Model selection
        self.model_combo = QComboBox()
        self.model_combo.addItems([
            "gpt-3.5-turbo",
            "gpt-4",
            "gpt-4-turbo",
            "gpt-4o",
            "gpt-4o-mini"
        ])
        self.model_combo.setCurrentText(self.config.get("openai_model", "gpt-3.5-turbo"))
        general_layout.addRow("AI Model:", self.model_combo)
        
        # Max tokens
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(50, 2000)
        self.max_tokens_spin.setValue(self.config.get("max_tokens", 300))
        general_layout.addRow("Max Response Length:", self.max_tokens_spin)
        
        # Temperature
        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setDecimals(1)
        self.temperature_spin.setValue(self.config.get("temperature", 0.7))
        general_layout.addRow("Creativity (Temperature):", self.temperature_spin)
        
        # Auto focus input
        self.auto_focus_check = QCheckBox()
        self.auto_focus_check.setChecked(self.config.get("auto_focus_input", True))
        general_layout.addRow("Auto-focus input field:", self.auto_focus_check)
        
        # Always on top
        self.always_on_top_check = QCheckBox()
        self.always_on_top_check.setChecked(self.config.get("window_always_on_top", True))
        general_layout.addRow("Keep window on top:", self.always_on_top_check)
        
        tabs.addTab(general_tab, "General")
        
        # Appearance tab
        appearance_tab = QWidget()
        appearance_layout = QFormLayout(appearance_tab)
        
        # Window size
        self.window_width_spin = QSpinBox()
        self.window_width_spin.setRange(300, 800)
        self.window_width_spin.setValue(self.config.get("window_width", 400))
        appearance_layout.addRow("Window Width:", self.window_width_spin)
        
        self.window_height_spin = QSpinBox()
        self.window_height_spin.setRange(400, 1000)
        self.window_height_spin.setValue(self.config.get("window_height", 600))
        appearance_layout.addRow("Window Height:", self.window_height_spin)
        
        # Button settings
        self.show_button_check = QCheckBox()
        self.show_button_check.setChecked(self.config.get("show_button", True))
        appearance_layout.addRow("Show floating button:", self.show_button_check)
        
        self.button_size_spin = QSpinBox()
        self.button_size_spin.setRange(30, 80)
        self.button_size_spin.setValue(self.config.get("button_size", 50))
        appearance_layout.addRow("Button Size:", self.button_size_spin)
        
        self.button_opacity_spin = QDoubleSpinBox()
        self.button_opacity_spin.setRange(0.1, 1.0)
        self.button_opacity_spin.setSingleStep(0.1)
        self.button_opacity_spin.setDecimals(1)
        self.button_opacity_spin.setValue(self.config.get("button_opacity", 0.9))
        appearance_layout.addRow("Button Opacity:", self.button_opacity_spin)
        
        tabs.addTab(appearance_tab, "Appearance")
        
        # Theme tab
        theme_tab = QWidget()
        theme_layout = QFormLayout(theme_tab)
        
        # Color scheme selection
        self.color_scheme_combo = QComboBox()
        self.color_scheme_combo.addItems(["Auto (Follow Anki)", "Light", "Dark", "Custom"])
        current_scheme = self.config.get("color_scheme", "auto")
        scheme_map = {"auto": 0, "light": 1, "dark": 2, "custom": 3}
        self.color_scheme_combo.setCurrentIndex(scheme_map.get(current_scheme, 0))
        self.color_scheme_combo.currentTextChanged.connect(self.on_color_scheme_changed)
        theme_layout.addRow("Color Scheme:", self.color_scheme_combo)
        
        # Custom color section
        self.custom_colors_group = QGroupBox("Custom Colors")
        custom_colors_layout = QFormLayout(self.custom_colors_group)
        
        # Custom color controls
        custom_colors = self.config.get("custom_colors", DEFAULT_CONFIG["custom_colors"])
        self.color_buttons = {}
        
        color_labels = {
            "bg_main": "Main Background",
            "bg_secondary": "Secondary Background", 
            "bg_input": "Input Background",
            "text_primary": "Primary Text",
            "text_secondary": "Secondary Text",
            "border": "Border Color",
            "ai_bubble_bg": "AI Message Background",
            "ai_bubble_text": "AI Message Text",
            "accent_color": "Accent Color"
        }
        
        for key, label in color_labels.items():
            color_btn = QPushButton()
            color_btn.setFixedSize(50, 30)
            color_value = custom_colors.get(key, "#ffffff")
            color_btn.setStyleSheet(f"background-color: {color_value}; border: 1px solid #ccc;")
            color_btn.clicked.connect(lambda checked, k=key: self.choose_color(k))
            self.color_buttons[key] = color_btn
            custom_colors_layout.addRow(f"{label}:", color_btn)
        
        theme_layout.addRow(self.custom_colors_group)
        
        # Update custom colors visibility
        self.on_color_scheme_changed()
        
        tabs.addTab(theme_tab, "Theme")
        
        # Button Customization tab
        button_tab = QWidget()
        button_layout = QFormLayout(button_tab)
        
        # Button icon selection
        self.button_icon_combo = QComboBox()
        icon_options = ["🤖 Robot", "🧠 Brain", "💬 Chat", "⚡ Lightning", "🌟 Star", "🔥 Fire", "💎 Diamond", "🚀 Rocket", "Custom Image"]
        self.button_icon_combo.addItems(icon_options)
        
        current_icon = self.config.get("button_icon", "🤖")
        icon_map = {"🤖": 0, "🧠": 1, "💬": 2, "⚡": 3, "🌟": 4, "🔥": 5, "💎": 6, "🚀": 7, "custom": 8}
        self.button_icon_combo.setCurrentIndex(icon_map.get(current_icon, 0))
        self.button_icon_combo.currentTextChanged.connect(self.on_button_icon_changed)
        button_layout.addRow("Button Icon:", self.button_icon_combo)
        
        # Custom image path
        self.custom_image_group = QGroupBox("Custom Image")
        custom_image_layout = QHBoxLayout(self.custom_image_group)
        
        self.custom_image_path = QLineEdit()
        self.custom_image_path.setText(self.config.get("custom_button_image_path", ""))
        self.custom_image_path.setPlaceholderText("Path to image file (PNG, JPG, SVG)")
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_custom_image)
        
        custom_image_layout.addWidget(self.custom_image_path)
        custom_image_layout.addWidget(browse_btn)
        
        button_layout.addRow(self.custom_image_group)
        
        # Preview button
        self.preview_button = QPushButton("Preview")
        self.preview_button.setFixedSize(60, 60)
        self.update_button_preview()
        button_layout.addRow("Preview:", self.preview_button)
        
        # Update custom image visibility
        self.on_button_icon_changed()
        
        tabs.addTab(button_tab, "Button")
        
        # Controls tab
        controls_tab = QWidget()
        controls_layout = QFormLayout(controls_tab)
        
        # Hotkey setting
        self.hotkey_edit = QLineEdit()
        self.hotkey_edit.setText(self.config.get("hotkey", "Ctrl+Shift+A"))
        self.hotkey_edit.setPlaceholderText("e.g., Ctrl+Shift+A, Alt+C, F1")
        controls_layout.addRow("Hotkey to open chat:", self.hotkey_edit)
        
        # Button position
        pos = self.config.get("button_position", {"x": 50, "y": 50})
        
        self.button_x_spin = QSpinBox()
        self.button_x_spin.setRange(0, 2000)
        self.button_x_spin.setValue(pos.get("x", 50))
        controls_layout.addRow("Button X Position:", self.button_x_spin)
        
        self.button_y_spin = QSpinBox()
        self.button_y_spin.setRange(0, 2000)
        self.button_y_spin.setValue(pos.get("y", 50))
        controls_layout.addRow("Button Y Position:", self.button_y_spin)
        
        tabs.addTab(controls_tab, "Controls")
        
        layout.addWidget(tabs)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self.reset_defaults)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_settings)
        save_btn.setDefault(True)
        
        button_layout.addWidget(reset_btn)
        button_layout.addStretch()
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(save_btn)
        
        layout.addLayout(button_layout)
    
    def reset_defaults(self):
        """Reset all settings to default values"""
        if askUser("Reset all settings to default values?"):
            # Update UI with defaults
            self.ai_instructions_text.setPlainText(DEFAULT_CONFIG["ai_instructions"])
            self.model_combo.setCurrentText(DEFAULT_CONFIG["openai_model"])
            self.max_tokens_spin.setValue(DEFAULT_CONFIG["max_tokens"])
            self.temperature_spin.setValue(DEFAULT_CONFIG["temperature"])
            self.auto_focus_check.setChecked(DEFAULT_CONFIG["auto_focus_input"])
            self.always_on_top_check.setChecked(DEFAULT_CONFIG["window_always_on_top"])
            self.window_width_spin.setValue(DEFAULT_CONFIG["window_width"])
            self.window_height_spin.setValue(DEFAULT_CONFIG["window_height"])
            self.show_button_check.setChecked(DEFAULT_CONFIG["show_button"])
            self.button_size_spin.setValue(DEFAULT_CONFIG["button_size"])
            self.button_opacity_spin.setValue(DEFAULT_CONFIG["button_opacity"])
            self.hotkey_edit.setText(DEFAULT_CONFIG["hotkey"])
            self.button_x_spin.setValue(DEFAULT_CONFIG["button_position"]["x"])
            self.button_y_spin.setValue(DEFAULT_CONFIG["button_position"]["y"])
            
            # Reset theme settings
            self.color_scheme_combo.setCurrentIndex(0)  # Auto
            
            # Reset custom colors
            default_colors = DEFAULT_CONFIG["custom_colors"]
            for key, color_btn in self.color_buttons.items():
                color_value = default_colors.get(key, "#ffffff")
                color_btn.setStyleSheet(f"background-color: {color_value}; border: 1px solid #ccc;")
            
            # Reset button settings
            self.button_icon_combo.setCurrentIndex(0)  # Robot
            self.custom_image_path.setText("")
            self.update_button_preview()
    
    def on_color_scheme_changed(self):
        """Handle color scheme selection change"""
        is_custom = "Custom" in self.color_scheme_combo.currentText()
        self.custom_colors_group.setEnabled(is_custom)
    
    def choose_color(self, color_key):
        """Open color picker for the specified color"""
        current_color = self.color_buttons[color_key].styleSheet()
        # Extract current color from stylesheet
        import re
        match = re.search(r'background-color:\s*([^;]+)', current_color)
        if match:
            current_hex = match.group(1).strip()
        else:
            current_hex = "#ffffff"
        
        color = QColorDialog.getColor(QColor(current_hex), self, f"Choose {color_key} Color")
        if color.isValid():
            hex_color = color.name()
            self.color_buttons[color_key].setStyleSheet(f"background-color: {hex_color}; border: 1px solid #ccc;")
    
    def on_button_icon_changed(self):
        """Handle button icon selection change"""
        is_custom = "Custom Image" in self.button_icon_combo.currentText()
        self.custom_image_group.setEnabled(is_custom)
        self.update_button_preview()
    
    def browse_custom_image(self):
        """Browse for custom button image"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Select Button Image", 
            "", 
            "Image Files (*.png *.jpg *.jpeg *.svg *.bmp *.gif)"
        )
        if file_path:
            self.custom_image_path.setText(file_path)
            self.update_button_preview()
    
    def update_button_preview(self):
        """Update the button preview"""
        if "Custom Image" in self.button_icon_combo.currentText():
            image_path = self.custom_image_path.text().strip()
            if image_path and os.path.exists(image_path):
                try:
                    pixmap = QPixmap(image_path)
                    if not pixmap.isNull():
                        scaled_pixmap = pixmap.scaled(50, 50, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        self.preview_button.setIcon(QIcon(scaled_pixmap))
                        self.preview_button.setText("")
                    else:
                        self.preview_button.setIcon(QIcon())
                        self.preview_button.setText("Invalid")
                except:
                    self.preview_button.setIcon(QIcon())
                    self.preview_button.setText("Error")
            else:
                self.preview_button.setIcon(QIcon())
                self.preview_button.setText("No Image")
        else:
            # Extract emoji from selection
            text = self.button_icon_combo.currentText()
            if text:
                emoji = text.split()[0]  # Get first part (emoji)
                self.preview_button.setIcon(QIcon())
                self.preview_button.setText(emoji)
    
    def save_settings(self):
        """Save settings and close dialog"""
        try:
            # Validate hotkey format
            hotkey = self.hotkey_edit.text().strip()
            if not hotkey:
                showWarning("Please enter a hotkey.")
                return
            
            # Validate AI instructions
            ai_instructions = self.ai_instructions_text.toPlainText().strip()
            if not ai_instructions:
                showWarning("Please enter AI instructions.")
                return
            
            # Save all settings
            config_manager.set("ai_instructions", ai_instructions)
            config_manager.set("openai_model", self.model_combo.currentText())
            config_manager.set("max_tokens", self.max_tokens_spin.value())
            config_manager.set("temperature", self.temperature_spin.value())
            config_manager.set("auto_focus_input", self.auto_focus_check.isChecked())
            config_manager.set("window_always_on_top", self.always_on_top_check.isChecked())
            config_manager.set("window_width", self.window_width_spin.value())
            config_manager.set("window_height", self.window_height_spin.value())
            config_manager.set("show_button", self.show_button_check.isChecked())
            config_manager.set("button_size", self.button_size_spin.value())
            config_manager.set("button_opacity", self.button_opacity_spin.value())
            config_manager.set("hotkey", hotkey)
            config_manager.set("button_position", {
                "x": self.button_x_spin.value(),
                "y": self.button_y_spin.value()
            })
            
            # Save theme settings
            scheme_map = {0: "auto", 1: "light", 2: "dark", 3: "custom"}
            color_scheme = scheme_map.get(self.color_scheme_combo.currentIndex(), "auto")
            config_manager.set("color_scheme", color_scheme)
            
            # Save custom colors
            custom_colors = {}
            for key, color_btn in self.color_buttons.items():
                style = color_btn.styleSheet()
                import re
                match = re.search(r'background-color:\s*([^;]+)', style)
                if match:
                    custom_colors[key] = match.group(1).strip()
                else:
                    custom_colors[key] = "#ffffff"
            config_manager.set("custom_colors", custom_colors)
            
            # Save button icon settings
            icon_map = {0: "🤖", 1: "🧠", 2: "💬", 3: "⚡", 4: "🌟", 5: "🔥", 6: "💎", 7: "🚀", 8: "custom"}
            button_icon = icon_map.get(self.button_icon_combo.currentIndex(), "🤖")
            config_manager.set("button_icon", button_icon)
            config_manager.set("custom_button_image_path", self.custom_image_path.text().strip())
            
            # Notify that settings were saved
            showInfo("Settings saved successfully!")
            self.accept()
            
        except Exception as e:
            showWarning(f"Error saving settings: {str(e)}")

class FloatingButton(QWidget):
    """Floating button for opening chat"""
    
    def __init__(self):
        super().__init__()
        self.config = config_manager.config
        self.init_button()
        self.dragging = False
        self.drag_position = QPoint()
    
    def get_position_on_anki_monitor(self, relative_pos):
        """Get absolute position on the same monitor as Anki"""
        try:
            # Get the screen that contains Anki's main window
            anki_screen = mw.screen()
            screen_geometry = anki_screen.geometry()
            
            # Calculate absolute position relative to Anki's screen
            absolute_pos = {
                "x": screen_geometry.x() + relative_pos["x"],
                "y": screen_geometry.y() + relative_pos["y"]
            }
            
            print(f"AI Chat: Anki is on screen at {screen_geometry.x()}, {screen_geometry.y()}")
            print(f"AI Chat: Button position: relative {relative_pos} -> absolute {absolute_pos}")
            
            return absolute_pos
        except Exception as e:
            print(f"AI Chat: Error detecting Anki monitor, using original position: {e}")
            return relative_pos
    
    def get_relative_position_from_anki_monitor(self, absolute_pos):
        """Convert absolute position to relative position from Anki's monitor"""
        try:
            # Get the screen that contains Anki's main window
            anki_screen = mw.screen()
            screen_geometry = anki_screen.geometry()
            
            # Calculate relative position
            relative_pos = {
                "x": absolute_pos.x() - screen_geometry.x(),
                "y": absolute_pos.y() - screen_geometry.y()
            }
            
            print(f"AI Chat: Saving position: absolute {absolute_pos.x()}, {absolute_pos.y()} -> relative {relative_pos}")
            
            return relative_pos
        except Exception as e:
            print(f"AI Chat: Error converting position, using absolute: {e}")
            return {"x": absolute_pos.x(), "y": absolute_pos.y()}

    def init_button(self):
        """Initialize floating button"""
        print("AI Chat: Initializing floating button...")
        if not self.config.get("show_button", True):
            print("AI Chat: Button disabled in config, hiding...")
            self.hide()
            return
        
        print("AI Chat: Setting window properties...")
        # Set window properties
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        size = self.config.get("button_size", 50)
        self.setFixedSize(size, size)
        
        # Position - make it relative to Anki's monitor
        pos = self.config.get("button_position", {"x": 50, "y": 50})
        final_pos = self.get_position_on_anki_monitor(pos)
        self.move(final_pos["x"], final_pos["y"])
        
        # Get theme colors for button styling
        theme_colors = get_theme_colors()
        accent_color = theme_colors.get('accent_color', '#6c5ce7')
        
        # Convert hex to rgba for background
        from PyQt6.QtGui import QColor
        color = QColor(accent_color)
        r, g, b = color.red(), color.green(), color.blue()
        
        # Style with user's theme - no border/circle
        opacity = self.config.get("button_opacity", 0.9)
        self.setStyleSheet(f"""
            QWidget {{
                background: transparent;
                border: none;
            }}
            QWidget:hover {{
                background: transparent;
                transform: scale(1.1);
            }}
        """)
        
        # Add icon/emoji based on user preference
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        button_icon = self.config.get("button_icon", "🤖")
        if button_icon == "custom":
            # Use custom image
            custom_image_path = self.config.get("custom_button_image_path", "")
            if custom_image_path and os.path.exists(custom_image_path):
                try:
                    # Create label with image
                    image_label = QLabel()
                    pixmap = QPixmap(custom_image_path)
                    if not pixmap.isNull():
                        # Scale image to fit button
                        scaled_size = int(size * 0.8)
                        scaled_pixmap = pixmap.scaled(scaled_size, scaled_size, 
                                                    Qt.AspectRatioMode.KeepAspectRatio, 
                                                    Qt.TransformationMode.SmoothTransformation)
                        image_label.setPixmap(scaled_pixmap)
                        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        image_label.setStyleSheet("background: transparent;")
                        layout.addWidget(image_label)
                    else:
                        # Fallback to emoji if image is invalid
                        self._add_emoji_label(layout, "🤖", size)
                except Exception as e:
                    print(f"AI Chat: Error loading custom image: {e}")
                    # Fallback to emoji
                    self._add_emoji_label(layout, "🤖", size)
            else:
                # No custom image set, use default emoji
                self._add_emoji_label(layout, "🤖", size)
        else:
            # Use selected emoji
            self._add_emoji_label(layout, button_icon, size)
        
        print(f"AI Chat: Showing button at position ({pos['x']}, {pos['y']}) with size {size}x{size}")
        self.show()
        self.raise_()
        self.activateWindow()
        print(f"AI Chat: Button shown. Visible: {self.isVisible()}, Geometry: {self.geometry()}")
    
    def _add_emoji_label(self, layout, emoji, size):
        """Helper method to add emoji label to button"""
        emoji_label = QLabel(emoji)
        emoji_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        emoji_label.setStyleSheet(f"font-size: {size//2}px; background: transparent;")
        layout.addWidget(emoji_label)
    
    def mousePressEvent(self, event):
        """Handle mouse press for dragging"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        """Handle mouse move for dragging"""
        if event.buttons() == Qt.MouseButton.LeftButton and self.dragging:
            new_pos = event.globalPosition().toPoint() - self.drag_position
            self.move(new_pos)
            
            # Save position relative to Anki's monitor
            relative_pos = self.get_relative_position_from_anki_monitor(new_pos)
            config_manager.set("button_position", relative_pos)
            event.accept()
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release"""
        self.dragging = False
    
    def mouseDoubleClickEvent(self, event):
        """Handle double-click to open chat"""
        if event.button() == Qt.MouseButton.LeftButton:
            chat_manager.open_chat_window()

class ChatManager:
    """Manages chat windows and button"""
    
    def __init__(self):
        self.current_window = None
        self.current_card = None
        self.floating_button = None
        
        # Create floating button
        self.create_floating_button()
    
    def create_floating_button(self):
        """Create or recreate floating button"""
        try:
            if self.floating_button:
                self.floating_button.close()
            
            if config_manager.get("show_button", True):
                print("AI Chat: Creating floating button...")
                self.floating_button = FloatingButton()
                print(f"AI Chat: Button created successfully. Visible: {self.floating_button.isVisible()}")
            else:
                print("AI Chat: Button creation skipped (show_button is False)")
        except Exception as e:
            print(f"AI Chat: Error creating floating button: {e}")
            import traceback
            traceback.print_exc()
    
    def update_card(self, card):
        """Update current card"""
        self.current_card = card
        
        # Close existing window if card changed
        if self.current_window and self.current_window.card != card:
            self.current_window.close()
            self.current_window = None
    
    def open_chat_window(self):
        """Open or focus chat window"""
        if not self.current_card:
            showWarning("No card available for chat.")
            return
        
        # Close existing window
        if self.current_window:
            self.current_window.close()
        
        # Get card content
        card_content = self.get_card_content(self.current_card)
        
        # Create new modal window
        self.current_window = AIFloatingChatWindow(mw, self.current_card, card_content)
        self.current_window.setModal(True)  # Make it modal so it captures all input
        self.current_window.show()
        self.current_window.raise_()
        self.current_window.activateWindow()
    
    def get_card_content(self, card: Card) -> str:
        """Extract readable content from the card"""
        try:
            # Get question and answer
            question = self.strip_html(card.question())
            answer = self.strip_html(card.answer())
            
            content = f"Question: {question}\n"
            if answer and answer != question:
                content += f"Answer: {answer}"
            
            return content.strip()
            
        except Exception as e:
            print(f"Error getting card content: {e}")
            return "Unable to load card content"
    
    def strip_html(self, text: str) -> str:
        """Simple HTML tag removal"""
        import re
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Replace HTML entities
        text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>')
        return text.strip()
    
    def refresh_settings(self):
        """Refresh components after settings change"""
        self.create_floating_button()

# Global instances - Note: chat_manager is created after Anki is loaded
config_manager = ConfigManager()
chat_db = ChatDatabase()
chat_manager = None

def init_addon():
    """Initialize the addon"""
    global chat_manager
    print("AI Chat: Initializing floating window add-on...")
    
    # Create chat manager after Anki is loaded
    chat_manager = ChatManager()
    
    # Add menu item to top menu bar
    add_menu_item()
    
    # Add reviewer hooks
    gui_hooks.reviewer_did_show_question.append(on_show_question)
    gui_hooks.reviewer_did_show_answer.append(on_show_answer)
    
    # Add hotkey support
    addHook("reviewStateShortcuts", on_reviewer_shortcuts)
    
    # Add configuration menu (keep for compatibility)
    mw.addonManager.setConfigAction(__name__, show_config_dialog)
    
    print("AI Chat: Add-on initialization complete!")

def add_menu_item():
    """Add AI Chat menu to the top menu bar"""
    try:
        # Check if menu already exists to prevent duplicates
        existing_menus = mw.menuBar().findChildren(QMenu)
        for menu in existing_menus:
            if menu.title() == "AI Chat":
                print("AI Chat: Menu already exists, skipping creation")
                return
        
        # Create the main menu
        ai_chat_menu = QMenu("AI Chat", mw)
        
        # Add preferences action (main settings access)
        preferences_action = QAction("Preferences", mw)
        preferences_action.triggered.connect(show_config_dialog)
        ai_chat_menu.addAction(preferences_action)
        
        # Add separator
        ai_chat_menu.addSeparator()
        
        # Add open chat action
        open_chat_action = QAction("Open Chat Window", mw)
        open_chat_action.triggered.connect(lambda: chat_manager.open_chat_window() if chat_manager else None)
        ai_chat_menu.addAction(open_chat_action)
        
        # Add toggle button action
        toggle_button_action = QAction("Toggle Floating Button", mw)
        toggle_button_action.triggered.connect(toggle_floating_button)
        ai_chat_menu.addAction(toggle_button_action)
        
        # Add the menu to the menu bar
        mw.menuBar().addMenu(ai_chat_menu)
        
        print("AI Chat: Menu added successfully!")
        
    except Exception as e:
        print(f"AI Chat: Error adding menu: {e}")

def toggle_floating_button():
    """Toggle the floating button visibility"""
    if not chat_manager:
        showWarning("Chat manager not initialized!")
        return
        
    current_state = config_manager.get("show_button", True)
    new_state = not current_state
    config_manager.set("show_button", new_state)
    
    # Recreate the button with new state
    chat_manager.create_floating_button()
    
    if new_state:
        showInfo("Floating button enabled!")
    else:
        showInfo("Floating button disabled!")

def show_config_dialog():
    """Show configuration dialog from add-on menu"""
    try:
        dialog = SettingsDialog(mw)
        if dialog.exec():
            # Refresh settings after save
            if chat_manager:
                chat_manager.refresh_settings()
            showInfo("Settings applied successfully!")
    except Exception as e:
        showWarning(f"Error opening settings: {str(e)}")

def on_reviewer_shortcuts(shortcuts):
    """Add keyboard shortcut for AI chat"""
    hotkey = config_manager.get("hotkey", "Ctrl+Shift+A")
    # Parse hotkey string into QKeySequence format
    try:
        shortcuts.append((hotkey, lambda: chat_manager.open_chat_window() if chat_manager else None))
    except:
        # Fallback to default if parsing fails
        shortcuts.append(("Ctrl+Shift+A", lambda: chat_manager.open_chat_window() if chat_manager else None))

def on_show_question(card):
    """Called when a question is shown"""
    if chat_manager:
        chat_manager.update_card(card)

def on_show_answer(card):
    """Called when an answer is shown"""
    if chat_manager:
        chat_manager.update_card(card)

class StreamingWorker(QThread):
    """Worker thread for handling streaming OpenAI API responses"""
    
    chunk_received = pyqtSignal(str)  # Emitted when new text chunk arrives
    response_finished = pyqtSignal(str)  # Emitted when response is complete
    error_occurred = pyqtSignal(str)  # Emitted when error occurs
    
    def __init__(self, user_message: str, card_content: str, config: dict):
        super().__init__()
        self.user_message = user_message
        self.card_content = card_content
        self.config = config
        self.accumulated_text = ""
    
    def run(self):
        """Run the streaming API request in background thread"""
        try:
            # Get custom AI instructions from config
            ai_instructions = self.config.get("ai_instructions", DEFAULT_CONFIG["ai_instructions"])
            
            # Prepare the conversation context with custom instructions
            messages = [
                {
                    "role": "system",
                    "content": f"{ai_instructions} "
                               f"The current flashcard content is: {self.card_content}."
                },
                {
                    "role": "user",
                    "content": self.user_message
                }
            ]
            
            # Prepare request data with streaming enabled
            data = {
                "model": self.config.get("openai_model", "gpt-3.5-turbo"),
                "messages": messages,
                "max_tokens": self.config.get("max_tokens", 300),
                "temperature": self.config.get("temperature", 0.7),
                "stream": True
            }
            
            # Convert to JSON
            json_data = json.dumps(data).encode('utf-8')
            
            # Create request
            req = urllib.request.Request(
                'https://api.openai.com/v1/chat/completions',
                data=json_data,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {OPENAI_API_KEY}'
                }
            )
            
            # Make streaming API call
            with urllib.request.urlopen(req, timeout=60) as response:
                buffer = ""
                for line in response:
                    line = line.decode('utf-8').strip()
                    
                    if line.startswith('data: '):
                        line = line[6:]  # Remove 'data: ' prefix
                        
                        if line == '[DONE]':
                            break
                            
                        if line:
                            try:
                                chunk_data = json.loads(line)
                                if 'choices' in chunk_data and len(chunk_data['choices']) > 0:
                                    delta = chunk_data['choices'][0].get('delta', {})
                                    if 'content' in delta:
                                        new_content = delta['content']
                                        self.accumulated_text += new_content
                                        # Emit the accumulated text so far
                                        self.chunk_received.emit(self.accumulated_text)
                            except json.JSONDecodeError:
                                continue  # Skip malformed chunks
            
            # Emit final response
            if self.accumulated_text:
                self.response_finished.emit(self.accumulated_text)
            else:
                self.error_occurred.emit("No response received")
                
        except Exception as e:
            self.error_occurred.emit(str(e)) 

class SummaryWorker(QThread):
    """Worker thread for generating conversation summaries with streaming"""
    
    chunk_received = pyqtSignal(str)  # Emitted when new text chunk arrives
    summary_generated = pyqtSignal(str)  # Emitted when summary is complete
    error_occurred = pyqtSignal(str)  # Emitted when error occurs
    
    def __init__(self, conversation_text: str, config: dict):
        super().__init__()
        self.conversation_text = conversation_text
        self.config = config
        self.accumulated_text = ""
    
    def run(self):
        """Generate summary using OpenAI API with streaming"""
        try:
            # Create summary prompt
            summary_prompt = f"""You are summarizing a chat conversation between a user and an AI assistant about study material. 

IMPORTANT: Ignore the flashcard content at the beginning. Focus ONLY on the back-and-forth conversation between "You:" and "AI:" messages.

Create a single "Conversation Summary" section that captures the main explanations and information discussed during the chat. Focus primarily on what the AI explained in response to the user's questions.

Do NOT include:
- "Key Questions Asked" sections
- "Explanations Provided by AI" headers  
- "Clarifications Made" sections
- Information from the original flashcard unless specifically discussed

Just provide the key content and explanations that came up during the actual conversation, organized clearly with markdown formatting.

{self.conversation_text}

Conversation Summary:"""

            # Prepare request data with streaming
            messages = [
                {
                    "role": "system",
                    "content": "You are a helpful study assistant. Create clear, organized study notes from conversations using markdown formatting."
                },
                {
                    "role": "user", 
                    "content": summary_prompt
                }
            ]
            
            data = {
                "model": self.config.get("openai_model", "gpt-3.5-turbo"),
                "messages": messages,
                "max_tokens": self.config.get("max_tokens", 500),
                "temperature": 0.3,  # Lower temperature for more focused summaries
                "stream": True  # Enable streaming
            }
            
            # Convert to JSON
            json_data = json.dumps(data).encode('utf-8')
            
            # Create request
            req = urllib.request.Request(
                'https://api.openai.com/v1/chat/completions',
                data=json_data,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {OPENAI_API_KEY}'
                }
            )
            
            # Make streaming API call
            with urllib.request.urlopen(req, timeout=60) as response:
                for line in response:
                    line = line.decode('utf-8').strip()
                    
                    if line.startswith('data: '):
                        line = line[6:]  # Remove 'data: ' prefix
                        
                        if line == '[DONE]':
                            break
                            
                        if line:
                            try:
                                chunk_data = json.loads(line)
                                if 'choices' in chunk_data and len(chunk_data['choices']) > 0:
                                    delta = chunk_data['choices'][0].get('delta', {})
                                    if 'content' in delta:
                                        new_content = delta['content']
                                        self.accumulated_text += new_content
                                        # Emit the accumulated text so far
                                        self.chunk_received.emit(self.accumulated_text)
                            except json.JSONDecodeError:
                                continue  # Skip malformed chunks
            
            # Emit final response
            if self.accumulated_text:
                self.summary_generated.emit(self.accumulated_text)
            else:
                self.error_occurred.emit("No response received")
                
        except Exception as e:
            self.error_occurred.emit(str(e))

class SummaryDialog(QDialog):
    """Dialog for showing summary and choosing where to save it"""
    
    def __init__(self, parent, summary_text: str, card: Card):
        super().__init__(parent)
        self.summary_text = summary_text
        self.card = card
        self.theme_colors = get_theme_colors()
        self.summary_worker = None
        self.init_ui()
    
    def init_ui(self):
        """Initialize the summary dialog UI"""
        self.setWindowTitle("Conversation Summary")
        self.setModal(True)
        self.resize(600, 500)
        
        # Apply dark mode styling to dialog
        bg_color = self.theme_colors['bg_secondary']
        text_color = self.theme_colors['text_primary']
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {bg_color};
                color: {text_color};
            }}
        """)
        
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("📋 Conversation Summary")
        title.setStyleSheet(f"""
            QLabel {{
                font-size: 18px;
                font-weight: bold;
                color: #6c5ce7;
                padding: 10px;
                border-bottom: 2px solid #6c5ce7;
                margin-bottom: 15px;
                background-color: {bg_color};
            }}
        """)
        layout.addWidget(title)
        
        # Summary display with dark mode support
        self.summary_display = QTextEdit()
        if self.summary_text:
            # Convert markdown to HTML if we have initial text
            html_text = convert_markdown_to_html(self.summary_text)
            self.summary_display.setHtml(html_text)
        else:
            self.summary_display.setHtml("Generating summary...")
        
        bg_input = self.theme_colors['bg_input']
        border_color = self.theme_colors['border']
        self.summary_display.setStyleSheet(f"""
            QTextEdit {{
                border: 1px solid {border_color};
                border-radius: 8px;
                padding: 12px;
                font-size: 14px;
                line-height: 1.5;
                background-color: {bg_input};
                color: {text_color};
            }}
        """)
        layout.addWidget(self.summary_display)
        
        # Instructions
        instruction_label = QLabel("💡 You can edit the summary above before saving it to your flashcard.")
        instruction_label.setStyleSheet(f"color: {self.theme_colors['text_secondary']}; font-style: italic; margin: 10px 0;")
        layout.addWidget(instruction_label)
        
        # Field selection
        field_layout = QHBoxLayout()
        field_label = QLabel("Save to field:")
        field_label.setStyleSheet(f"color: {text_color};")
        field_layout.addWidget(field_label)
        
        self.field_combo = QComboBox()
        note = self.card.note()
        field_names = list(note.keys())
        self.field_combo.addItems(field_names)
        self.field_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {bg_input};
                color: {text_color};
                border: 1px solid {border_color};
                border-radius: 4px;
                padding: 5px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox::down-arrow {{
                color: {text_color};
            }}
        """)
        
        # Try to select a good default field
        preferred_fields = ["Extra", "Notes", "Summary", "Additional Info", "Details"]
        for preferred in preferred_fields:
            for i, field in enumerate(field_names):
                if preferred.lower() in field.lower():
                    self.field_combo.setCurrentIndex(i)
                    break
        
        field_layout.addWidget(self.field_combo)
        layout.addLayout(field_layout)
        
        # Append/Replace options
        self.append_checkbox = QCheckBox("Append to existing content (instead of replacing)")
        self.append_checkbox.setChecked(True)
        self.append_checkbox.setStyleSheet(f"color: {text_color};")
        layout.addWidget(self.append_checkbox)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        copy_btn = QPushButton("📋 Copy to Clipboard")
        copy_btn.clicked.connect(self.copy_to_clipboard)
        copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #17a2b8;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #138496;
            }
        """)
        
        save_btn = QPushButton("💾 Save to Card")
        save_btn.clicked.connect(self.save_to_card)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
        """)
        
        button_layout.addWidget(copy_btn)
        button_layout.addStretch()
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(save_btn)
        
        layout.addLayout(button_layout)
    
    def start_streaming_summary(self, conversation_text: str, config: dict):
        """Start streaming summary generation"""
        self.summary_worker = SummaryWorker(conversation_text, config)
        self.summary_worker.chunk_received.connect(self.update_streaming_summary)
        self.summary_worker.summary_generated.connect(self.finish_streaming_summary)
        self.summary_worker.error_occurred.connect(self.handle_summary_error)
        self.summary_worker.start()
    
    def update_streaming_summary(self, text: str):
        """Update the summary display with streaming text"""
        # Convert markdown to HTML for display
        html_text = convert_markdown_to_html(text)
        self.summary_display.setHtml(html_text)
        
        # Scroll to bottom to follow the generation
        cursor = self.summary_display.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.summary_display.setTextCursor(cursor)
    
    def finish_streaming_summary(self, final_text: str):
        """Finish streaming and store final text"""
        self.summary_text = final_text
        html_text = convert_markdown_to_html(final_text)
        self.summary_display.setHtml(html_text)
    
    def handle_summary_error(self, error_message: str):
        """Handle summary generation errors"""
        self.summary_display.setHtml(f"<p style='color: red;'>Error generating summary: {error_message}</p>")
    
    def copy_to_clipboard(self):
        """Copy summary to clipboard"""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.summary_display.toPlainText())
        showInfo("Summary copied to clipboard!")
    
    def save_to_card(self):
        """Save summary to selected card field"""
        try:
            note = self.card.note()
            field_name = self.field_combo.currentText()
            # Get plain text version for saving (without HTML)
            summary_text = self.summary_display.toPlainText()
            
            if self.append_checkbox.isChecked():
                # Append to existing content
                existing_content = note[field_name]
                if existing_content.strip():
                    new_content = existing_content + "\n\n" + "=== AI Chat Summary ===\n" + summary_text
                else:
                    new_content = summary_text
            else:
                # Replace existing content
                new_content = summary_text
            
            # Update the note
            note[field_name] = new_content
            note.flush()
            
            # Refresh the card display
            from aqt import mw
            mw.requireReset()
            
            showInfo(f"Summary saved successfully to '{field_name}' field!")
            self.accept()
            
        except Exception as e:
            showWarning(f"Failed to save summary: {str(e)}")

class FlashcardGenerationWorker(QThread):
    """Worker thread for generating flashcards with streaming"""
    
    chunk_received = pyqtSignal(str)  # Emitted when new text chunk arrives
    flashcards_generated = pyqtSignal(str)  # Emitted when generation is complete
    error_occurred = pyqtSignal(str)  # Emitted when error occurs
    
    def __init__(self, conversation_text: str, config: dict, custom_prompt: str = "", card_format: str = "basic", card_count: int = 5):
        super().__init__()
        self.conversation_text = conversation_text
        self.config = config
        self.custom_prompt = custom_prompt
        self.card_format = card_format
        self.card_count = card_count
        self.accumulated_text = ""
    
    def run(self):
        """Generate flashcards using OpenAI API with streaming"""
        try:
            # Create flashcard generation prompt
            format_instruction = ""
            if self.card_format == "cloze":
                format_instruction = """Create CLOZE DELETION cards using {{c1::text}} format. These should be STATEMENTS, not questions.

IMPORTANT: Use statements/facts, NOT question-answer format.

Example format:
{{c1::Acyclovir}} is primarily used for the treatment of {{c2::herpes simplex virus}} and {{c3::varicella-zoster virus}} infections.

DO NOT use "Question:" or "Answer:" format. Just provide the cloze statement directly.
"""
            else:
                format_instruction = """Create BASIC flashcards with STRICT Front/Back format. Do NOT use cloze deletion {{c1::}} syntax.

IMPORTANT: Use Front: and Back: format only, NO cloze deletions.

Example format:
Front: What is the primary use of Acyclovir?
Back: Acyclovir is primarily used for the treatment of herpes simplex virus and varicella-zoster virus infections.

Each card MUST have exactly "Front:" and "Back:" labels.
"""

            base_prompt = f"""Based on this conversation between a user and AI assistant, generate exactly {self.card_count} high-quality flashcards focusing on what the user learned during the discussion.

IMPORTANT: Focus ONLY on new information, explanations, or insights that came up during the conversation. Do not create cards about the original flashcard content unless it was specifically discussed or expanded upon.

{format_instruction}

Additional Instructions: {self.custom_prompt if self.custom_prompt else "Create clear, concise flashcards that test understanding of key concepts discussed."}

{self.conversation_text}

Generate exactly {self.card_count} flashcards:"""

            # Prepare request data with streaming
            messages = [
                {
                    "role": "system",
                    "content": "You are a helpful study assistant. Create clear, educational flashcards based on conversation content using the specified format."
                },
                {
                    "role": "user", 
                    "content": base_prompt
                }
            ]
            
            data = {
                "model": self.config.get("openai_model", "gpt-3.5-turbo"),
                "messages": messages,
                "max_tokens": self.config.get("max_tokens", 800),
                "temperature": 0.4,  # Balanced creativity for good flashcards
                "stream": True  # Enable streaming
            }
            
            # Convert to JSON
            json_data = json.dumps(data).encode('utf-8')
            
            # Create request
            req = urllib.request.Request(
                'https://api.openai.com/v1/chat/completions',
                data=json_data,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {OPENAI_API_KEY}'
                }
            )
            
            # Make streaming API call
            with urllib.request.urlopen(req, timeout=60) as response:
                for line in response:
                    line = line.decode('utf-8').strip()
                    
                    if line.startswith('data: '):
                        line = line[6:]  # Remove 'data: ' prefix
                        
                        if line == '[DONE]':
                            break
                            
                        if line:
                            try:
                                chunk_data = json.loads(line)
                                if 'choices' in chunk_data and len(chunk_data['choices']) > 0:
                                    delta = chunk_data['choices'][0].get('delta', {})
                                    if 'content' in delta:
                                        new_content = delta['content']
                                        self.accumulated_text += new_content
                                        # Emit the accumulated text so far
                                        self.chunk_received.emit(self.accumulated_text)
                            except json.JSONDecodeError:
                                continue  # Skip malformed chunks
            
            # Emit final response
            if self.accumulated_text:
                self.flashcards_generated.emit(self.accumulated_text)
            else:
                self.error_occurred.emit("No response received")
                
        except Exception as e:
            self.error_occurred.emit(str(e))

class FlashcardGenerationDialog(QDialog):
    """Dialog for generating and previewing new flashcards from conversation"""
    
    def __init__(self, parent, conversation_text: str, original_card: Card, config: dict):
        super().__init__(parent)
        self.conversation_text = conversation_text
        self.original_card = original_card
        self.config = config
        self.theme_colors = get_theme_colors()
        self.flashcard_worker = None
        self.generated_flashcards = ""
        self.conversation_summary = ""
        self.init_ui()
    
    def init_ui(self):
        """Initialize the flashcard generation dialog UI"""
        self.setWindowTitle("Generate Flashcards from Conversation")
        self.setModal(True)
        self.resize(800, 700)  # Larger window size
        
        # Apply dark mode styling to dialog
        bg_color = self.theme_colors['bg_secondary']
        text_color = self.theme_colors['text_primary']
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {bg_color};
                color: {text_color};
            }}
        """)
        
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("🃏 Generate New Flashcards")
        title.setStyleSheet(f"""
            QLabel {{
                font-size: 18px;
                font-weight: bold;
                color: #6c5ce7;
                padding: 10px;
                border-bottom: 2px solid #6c5ce7;
                margin-bottom: 15px;
                background-color: {bg_color};
            }}
        """)
        layout.addWidget(title)
        
        # Options section - more compact
        options_group = QWidget()
        options_layout = QHBoxLayout(options_group)  # Horizontal layout for compactness
        
        # Card format selection
        format_label = QLabel("Format:")
        format_label.setStyleSheet(f"color: {text_color}; font-weight: bold;")
        options_layout.addWidget(format_label)
        
        self.format_combo = QComboBox()
        self.format_combo.addItems(["Basic (Front/Back)", "Cloze Deletion"])
        bg_input = self.theme_colors['bg_input']
        border_color = self.theme_colors['border']
        self.format_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {bg_input};
                color: {text_color};
                border: 1px solid {border_color};
                border-radius: 4px;
                padding: 5px;
            }}
        """)
        self.format_combo.setMaximumWidth(200)
        options_layout.addWidget(self.format_combo)
        
        options_layout.addSpacing(20)
        
        # Card count selection
        count_label = QLabel("Cards to Generate:")
        count_label.setStyleSheet(f"color: {text_color}; font-weight: bold;")
        options_layout.addWidget(count_label)
        
        self.card_count_spin = QSpinBox()
        self.card_count_spin.setMinimum(1)
        self.card_count_spin.setMaximum(20)
        self.card_count_spin.setValue(5)  # Default to 5 cards
        self.card_count_spin.setStyleSheet(f"""
            QSpinBox {{
                background-color: {bg_input};
                color: {text_color};
                border: 1px solid {border_color};
                border-radius: 4px;
                padding: 5px;
                min-width: 60px;
            }}
        """)
        options_layout.addWidget(self.card_count_spin)
        
        options_layout.addSpacing(20)
        
        # Custom prompt
        prompt_label = QLabel("Instructions:")
        prompt_label.setStyleSheet(f"color: {text_color}; font-weight: bold;")
        options_layout.addWidget(prompt_label)
        
        self.custom_prompt = QLineEdit()  # Changed to single line for compactness
        self.custom_prompt.setPlaceholderText("e.g., Focus on pathophysiology, include mnemonics...")
        self.custom_prompt.setStyleSheet(f"""
            QLineEdit {{
                border: 1px solid {border_color};
                border-radius: 4px;
                padding: 8px;
                font-size: 12px;
                background-color: {bg_input};
                color: {text_color};
            }}
        """)
        options_layout.addWidget(self.custom_prompt)
        
        layout.addWidget(options_group)
        
        # Generate button
        generate_btn = QPushButton("🚀 Generate Flashcards")
        generate_btn.clicked.connect(self.start_generation)
        generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c5ce7;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #5a4fcf;
            }
        """)
        layout.addWidget(generate_btn)
        
        # Preview area
        preview_label = QLabel("📋 Preview Generated Flashcards:")
        preview_label.setStyleSheet(f"color: {text_color}; font-weight: bold; margin-top: 15px;")
        layout.addWidget(preview_label)
        
        # Scroll area for card previews
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setStyleSheet(f"""
            QScrollArea {{
                border: 1px solid {border_color};
                border-radius: 8px;
                background-color: {bg_input};
            }}
            QScrollBar:vertical {{
                background-color: {bg_color};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: #c1c8cd;
                border-radius: 4px;
                min-height: 20px;
            }}
        """)
        
        # Container widget for card previews
        self.preview_container = QWidget()
        self.preview_layout = QVBoxLayout(self.preview_container)
        self.preview_layout.setContentsMargins(10, 10, 10, 10)
        self.preview_layout.setSpacing(10)
        
        # Initial message
        initial_label = QLabel("Click 'Generate Flashcards' to see preview...")
        initial_label.setStyleSheet(f"color: {self.theme_colors['text_secondary']}; font-style: italic; padding: 20px; text-align: center;")
        initial_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_layout.addWidget(initial_label)
        self.preview_layout.addStretch()
        
        self.preview_scroll.setWidget(self.preview_container)
        layout.addWidget(self.preview_scroll)
        
        # Card checkboxes list (will be populated after generation)
        self.card_checkboxes = []
        
        # Buttons
        button_layout = QHBoxLayout()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
        """)
        
        self.create_btn = QPushButton("✅ Create Cards")
        self.create_btn.clicked.connect(self.create_flashcards)
        self.create_btn.setEnabled(False)  # Disabled until generation completes
        self.create_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
            QPushButton:disabled {
                background-color: #6c757d;
            }
        """)
        
        button_layout.addStretch()
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(self.create_btn)
        
        layout.addLayout(button_layout)
    
    def start_generation(self):
        """Start flashcard generation process"""
        # Get format selection and card count
        card_format = "cloze" if "Cloze" in self.format_combo.currentText() else "basic"
        custom_prompt = self.custom_prompt.text().strip()
        card_count = self.card_count_spin.value()
        
        # Clear previous previews and show loading message with progress
        self.clear_preview_cards()
        
        # Create animated loading widget
        loading_widget = QWidget()
        loading_layout = QVBoxLayout(loading_widget)
        
        # Animated text
        self.loading_label = QLabel(f"🚀 Generating {card_count} flashcards...")
        self.loading_label.setStyleSheet(f"""
            QLabel {{
                color: #6c5ce7;
                font-size: 16px;
                font-weight: bold;
                padding: 20px;
                text-align: center;
            }}
        """)
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_layout.addWidget(self.loading_label)
        
        # Progress indicator
        self.progress_label = QLabel("Connecting to AI...")
        self.progress_label.setStyleSheet(f"""
            QLabel {{
                color: {self.theme_colors['text_secondary']};
                font-style: italic;
                padding: 10px;
                text-align: center;
            }}
        """)
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_layout.addWidget(self.progress_label)
        
        # Placeholder cards that will fill in progressively
        self.card_placeholders = []
        placeholder_widget = QWidget()
        placeholder_layout = QVBoxLayout(placeholder_widget)
        
        for i in range(card_count):
            placeholder = self.create_placeholder_card(i + 1)
            self.card_placeholders.append(placeholder)
            placeholder_layout.addWidget(placeholder)
        
        loading_layout.addWidget(placeholder_widget)
        self.preview_layout.addWidget(loading_widget)
        
        self.create_btn.setEnabled(False)
        
        # Start worker thread
        self.flashcard_worker = FlashcardGenerationWorker(
            self.conversation_text, 
            self.config, 
            custom_prompt, 
            card_format,
            card_count
        )
        self.flashcard_worker.chunk_received.connect(self.update_progressive_preview)
        self.flashcard_worker.flashcards_generated.connect(self.finish_generation)
        self.flashcard_worker.error_occurred.connect(self.handle_generation_error)
        self.flashcard_worker.start()
    
    def clear_preview_cards(self):
        """Clear all preview cards from the layout"""
        # Clear the layout
        while self.preview_layout.count():
            child = self.preview_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        # Clear checkbox list
        self.card_checkboxes = []
    
    def create_placeholder_card(self, card_number: int) -> QWidget:
        """Create a placeholder card that shows loading state"""
        placeholder = QWidget()
        bg_color = self.theme_colors['bg_input']
        border_color = self.theme_colors['border']
        
        placeholder.setStyleSheet(f"""
            QWidget {{
                background-color: {bg_color};
                border: 2px dashed {border_color};
                border-radius: 10px;
                padding: 15px;
                min-height: 80px;
            }}
        """)
        
        layout = QVBoxLayout(placeholder)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Card number and loading animation
        header = QLabel(f"Card {card_number}")
        header.setStyleSheet(f"""
            QLabel {{
                color: {self.theme_colors['text_secondary']};
                font-weight: bold;
                font-size: 14px;
            }}
        """)
        layout.addWidget(header)
        
        # Loading dots animation
        loading_dots = QLabel("● ● ●")
        loading_dots.setStyleSheet(f"""
            QLabel {{
                color: {self.theme_colors['text_secondary']};
                font-size: 12px;
                text-align: center;
            }}
        """)
        loading_dots.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(loading_dots)
        
        return placeholder

    def update_progressive_preview(self, text: str):
        """Update preview with progressive card loading as they're generated"""
        # Update progress label
        if hasattr(self, 'progress_label'):
            self.progress_label.setText("🧠 AI is generating flashcards...")
        
        # Try to parse partial cards and update placeholders
        try:
            partial_cards = self.parse_flashcards(text)
            
            # Update placeholders with actual card content as they become available
            for i, card in enumerate(partial_cards):
                if i < len(self.card_placeholders):
                    # Replace placeholder with actual card preview
                    self.replace_placeholder_with_card(i, card)
                    
        except Exception:
            # If parsing fails, just continue with loading animation
            pass

    def replace_placeholder_with_card(self, index: int, flashcard: dict):
        """Replace a placeholder with actual card content"""
        if index >= len(self.card_placeholders):
            return
            
        # Create new card widget
        card_widget = self.create_card_preview_widget(flashcard, index)
        
        # Replace the placeholder in the layout
        placeholder = self.card_placeholders[index]
        layout = placeholder.parent().layout()
        
        if layout:
            # Find the position of the placeholder
            for i in range(layout.count()):
                if layout.itemAt(i).widget() == placeholder:
                    # Remove placeholder and insert card widget
                    layout.removeWidget(placeholder)
                    placeholder.deleteLater()
                    layout.insertWidget(i, card_widget)
                    self.card_placeholders[index] = card_widget
                    break
    
    def finish_generation(self, final_text: str):
        """Finish generation and create individual card previews"""
        self.generated_flashcards = final_text
        
        # Clear the generating message
        self.clear_preview_cards()
        
        # Parse the flashcards
        flashcards = self.parse_flashcards(final_text)
        
        if not flashcards:
            error_label = QLabel("❌ Could not parse any valid flashcards from the generated content.")
            error_label.setStyleSheet(f"color: red; padding: 20px; text-align: center;")
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.preview_layout.addWidget(error_label)
            return
        
        # Create individual preview cards
        for i, flashcard in enumerate(flashcards):
            card_widget = self.create_card_preview_widget(flashcard, i)
            self.preview_layout.addWidget(card_widget)
        
        # Add stretch at the end
        self.preview_layout.addStretch()
        
        # Enable create button
        self.create_btn.setEnabled(True)
        
        # Update button text to show selection
        self.update_create_button_text()
    
    def create_card_preview_widget(self, flashcard: dict, index: int) -> QWidget:
        """Create a preview widget for a single flashcard"""
        card_widget = QWidget()
        bg_color = self.theme_colors['bg_main']
        border_color = self.theme_colors['border']
        text_color = self.theme_colors['text_primary']
        
        card_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {bg_color};
                border: 2px solid {border_color};
                border-radius: 10px;
                padding: 5px;
            }}
        """)
        
        layout = QVBoxLayout(card_widget)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Header with checkbox, card number, and refine button
        header_layout = QHBoxLayout()
        
        # Checkbox for selection
        checkbox = QCheckBox(f"Card {index + 1}")
        checkbox.setChecked(False)  # Default to NOT selected
        checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: {text_color};
                font-weight: bold;
                font-size: 14px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
            }}
            QCheckBox::indicator:unchecked {{
                border: 2px solid {border_color};
                background-color: {bg_color};
                border-radius: 3px;
            }}
            QCheckBox::indicator:checked {{
                border: 2px solid #28a745;
                background-color: #28a745;
                border-radius: 3px;
            }}
        """)
        checkbox.stateChanged.connect(self.update_create_button_text)
        self.card_checkboxes.append(checkbox)
        
        header_layout.addWidget(checkbox)
        header_layout.addStretch()
        
        # Refine button
        refine_btn = QPushButton("🔧 Refine")
        refine_btn.setStyleSheet("""
            QPushButton {
                background-color: #17a2b8;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #138496;
            }
        """)
        refine_btn.clicked.connect(lambda: self.refine_card(index))
        header_layout.addWidget(refine_btn)
        
        layout.addLayout(header_layout)
        
        # Card content with editable fields
        if "cloze" in self.format_combo.currentText().lower():
            # Cloze card content
            content_label = QLabel("<b>Cloze Text:</b> <i>(double-click to edit)</i>")
            content_label.setStyleSheet(f"color: #6c5ce7; font-weight: bold;")
            layout.addWidget(content_label)
            
            content_text = QTextEdit(flashcard['content'])
            content_text.setMaximumHeight(80)
            content_text.setStyleSheet(f"""
                QTextEdit {{
                    color: {text_color};
                    background-color: {self.theme_colors['bg_input']};
                    border-radius: 6px;
                    border: 1px solid {border_color};
                    font-size: 13px;
                    padding: 8px;
                }}
            """)
            # Store reference for access during card creation
            flashcard['content_widget'] = content_text
            layout.addWidget(content_text)
        else:
            # Basic card content
            front_label = QLabel("<b>Front:</b> <i>(double-click to edit)</i>")
            front_label.setStyleSheet(f"color: #6c5ce7; font-weight: bold;")
            layout.addWidget(front_label)
            
            front_text = QTextEdit(flashcard['front'])
            front_text.setMaximumHeight(60)
            front_text.setStyleSheet(f"""
                QTextEdit {{
                    color: {text_color};
                    background-color: {self.theme_colors['bg_input']};
                    border-radius: 6px;
                    border: 1px solid {border_color};
                    font-size: 13px;
                    padding: 8px;
                }}
            """)
            # Store reference for access during card creation
            flashcard['front_widget'] = front_text
            layout.addWidget(front_text)
            
            back_label = QLabel("<b>Back:</b> <i>(double-click to edit)</i>")
            back_label.setStyleSheet(f"color: #6c5ce7; font-weight: bold; margin-top: 8px;")
            layout.addWidget(back_label)
            
            back_text = QTextEdit(flashcard['back'])
            back_text.setMaximumHeight(80)
            back_text.setStyleSheet(f"""
                QTextEdit {{
                    color: {text_color};
                    background-color: {self.theme_colors['bg_input']};
                    border-radius: 6px;
                    border: 1px solid {border_color};
                    font-size: 13px;
                    padding: 8px;
                }}
            """)
            # Store reference for access during card creation
            flashcard['back_widget'] = back_text
            layout.addWidget(back_text)
        
        return card_widget
    
    def refine_card(self, card_index: int):
        """Open refinement dialog for a specific card"""
        if card_index >= len(self.card_checkboxes):
            return
            
        dialog = CardRefinementDialog(self, card_index, self.config)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get the refinement prompt
            refinement_prompt = dialog.get_refinement_prompt()
            if refinement_prompt:
                # Start refinement worker
                self.start_card_refinement(card_index, refinement_prompt)
    
    def start_card_refinement(self, card_index: int, refinement_prompt: str):
        """Start refinement process for a specific card"""
        # Get current card content
        flashcards = self.parse_flashcards(self.generated_flashcards)
        if card_index >= len(flashcards):
            return
            
        current_card = flashcards[card_index]
        
        # Create refinement worker
        self.refinement_worker = CardRefinementWorker(
            current_card, refinement_prompt, self.config, 
            "cloze" if "Cloze" in self.format_combo.currentText() else "basic"
        )
        self.refinement_worker.refinement_complete.connect(
            lambda refined_content: self.update_card_content(card_index, refined_content)
        )
        self.refinement_worker.error_occurred.connect(
            lambda error: showWarning(f"Refinement failed: {error}")
        )
        self.refinement_worker.start()
    
    def update_card_content(self, card_index: int, refined_content: str):
        """Update the card content with refined version"""
        # Find the card widget and update its content
        card_widget = self.preview_layout.itemAt(card_index).widget()
        if not card_widget:
            return
            
        # Parse the refined content
        refined_card = self.parse_single_card(refined_content)
        if not refined_card:
            return
            
        # Update the text fields in the card widget
        if "cloze" in self.format_combo.currentText().lower():
            # Find and update cloze content
            for child in card_widget.findChildren(QTextEdit):
                if hasattr(child, 'toPlainText'):
                    child.setPlainText(refined_card.get('content', ''))
                    break
        else:
            # Find and update front/back content
            text_edits = card_widget.findChildren(QTextEdit)
            if len(text_edits) >= 2:
                text_edits[0].setPlainText(refined_card.get('front', ''))  # Front
                text_edits[1].setPlainText(refined_card.get('back', ''))   # Back
    
    def parse_single_card(self, text: str) -> dict:
        """Parse a single refined card"""
        if "cloze" in self.format_combo.currentText().lower():
            return {'content': text.strip()}
        else:
            # Try to parse front/back
            lines = text.split('\n')
            front = ""
            back = ""
            in_front = False
            in_back = False
            
            for line in lines:
                line = line.strip()
                if line.lower().startswith('front:'):
                    front = line[6:].strip()
                    in_front = True
                    in_back = False
                elif line.lower().startswith('back:'):
                    back = line[5:].strip()
                    in_front = False
                    in_back = True
                elif line and in_front:
                    front += "\n" + line
                elif line and in_back:
                    back += "\n" + line
            
            # If no front/back structure, treat as front only
            if not front and not back:
                front = text.strip()
                back = "[Refined content - please add back]"
                
            return {'front': front, 'back': back}
    
    def update_create_button_text(self):
        """Update the create button text to show how many cards are selected"""
        selected_count = sum(1 for cb in self.card_checkboxes if cb.isChecked())
        total_count = len(self.card_checkboxes)
        
        if selected_count == 0:
            self.create_btn.setText("✅ Create Cards")
            self.create_btn.setEnabled(False)
        elif selected_count == total_count:
            self.create_btn.setText(f"✅ Create All {total_count} Cards")
            self.create_btn.setEnabled(True)
        else:
            self.create_btn.setText(f"✅ Create {selected_count} of {total_count} Cards")
            self.create_btn.setEnabled(True)
    
    def handle_generation_error(self, error_message: str):
        """Handle generation errors"""
        self.clear_preview_cards()
        error_label = QLabel(f"❌ Error generating flashcards: {error_message}")
        error_label.setStyleSheet(f"color: red; padding: 20px; text-align: center;")
        error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_layout.addWidget(error_label)
    
    def create_flashcards(self):
        """Create the actual flashcards in Anki with loading feedback"""
        if not self.generated_flashcards:
            showWarning("No flashcards to create!")
            return
        
        # Show loading state
        original_text = self.create_btn.text()
        self.create_btn.setText("⏳ Creating cards...")
        self.create_btn.setEnabled(False)
        
        # Process application events to show the button change
        from aqt.qt import QApplication
        QApplication.processEvents()
        
        try:
            from aqt import mw
            
            # Get the original card's deck and tags
            original_note = self.original_card.note()
            deck_id = self.original_card.did
            
            # Get or create the appropriate note type for this addon
            card_format = "cloze" if "cloze" in self.format_combo.currentText().lower() else "basic"
            
            # Update button to show progress
            self.create_btn.setText("⏳ Setting up note type...")
            QApplication.processEvents()
            
            note_type = self.get_or_create_addon_note_type(card_format)
            
            # Generate conversation summary for each card
            self.create_btn.setText("⏳ Generating summary...")
            QApplication.processEvents()
            
            self.generate_conversation_summary_sync()
            
            # Parse the generated flashcards
            flashcards = self.parse_flashcards(self.generated_flashcards)
            
            if not flashcards:
                self.create_btn.setText(original_text)
                self.create_btn.setEnabled(True)
                showWarning("Could not parse any valid flashcards from the generated content.")
                return
            
            # Get selected flashcards with current edited content
            selected_flashcards = []
            for i, flashcard in enumerate(flashcards):
                if i < len(self.card_checkboxes) and self.card_checkboxes[i].isChecked():
                    # Get current content from the editable fields
                    card_widget = self.preview_layout.itemAt(i).widget()
                    if card_widget:
                        edited_card = self.get_current_card_content(card_widget, flashcard)
                        selected_flashcards.append(edited_card)
                    else:
                        selected_flashcards.append(flashcard)
            
            if not selected_flashcards:
                self.create_btn.setText(original_text)
                self.create_btn.setEnabled(True)
                showWarning("No flashcards selected for creation!")
                return
            
            # Create each selected flashcard with progress updates
            created_count = 0
            total_selected = len(selected_flashcards)
            
            for i, flashcard in enumerate(selected_flashcards):
                try:
                    # Update progress
                    self.create_btn.setText(f"⏳ Creating card {i+1}/{total_selected}...")
                    QApplication.processEvents()
                    
                    # Create new note
                    note = mw.col.new_note(note_type)
                    
                    # Copy tags from original card
                    note.tags = original_note.tags.copy()
                    
                    # Set the main content based on card format and note type structure
                    if "cloze" in self.format_combo.currentText().lower():
                        # For AI Chat Cloze: Text, Extra, AI Conversation Summary
                        note.fields[0] = flashcard['content']  # Text field
                        note.fields[1] = ""  # Extra field (empty for now)
                        note.fields[2] = self.conversation_summary  # AI Conversation Summary
                    else:
                        # For AI Chat Basic: Front, Back, AI Conversation Summary
                        note.fields[0] = flashcard['front']  # Front field
                        note.fields[1] = flashcard['back']   # Back field
                        note.fields[2] = self.conversation_summary  # AI Conversation Summary
                    
                    # Add note to collection
                    mw.col.add_note(note, deck_id)
                    created_count += 1
                    
                except Exception as e:
                    print(f"Error creating flashcard: {e}")
                    continue
            
            # Final save
            self.create_btn.setText("⏳ Saving to Anki...")
            QApplication.processEvents()
            
            if created_count > 0:
                # Save changes and refresh
                mw.col.save()
                mw.requireReset()
                
                # Success animation
                self.create_btn.setText("✅ Success!")
                self.create_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #28a745;
                        color: white;
                        border: none;
                        border-radius: 6px;
                        padding: 8px 16px;
                        font-weight: bold;
                    }
                """)
                QApplication.processEvents()
                
                showInfo(f"Successfully created {created_count} flashcard(s)!")
                self.accept()
            else:
                self.create_btn.setText(original_text)
                self.create_btn.setEnabled(True)
                showWarning("Failed to create any flashcards. Please check your note type fields.")
                
        except Exception as e:
            self.create_btn.setText(original_text)
            self.create_btn.setEnabled(True)
            showWarning(f"Error creating flashcards: {str(e)}")
    
    def get_current_card_content(self, card_widget: QWidget, original_card: dict) -> dict:
        """Get the current content from editable fields in a card widget"""
        if "cloze" in self.format_combo.currentText().lower():
            # Find the cloze content text edit
            for child in card_widget.findChildren(QTextEdit):
                if hasattr(child, 'toPlainText'):
                    return {'content': child.toPlainText()}
            return original_card
        else:
            # Find front and back text edits
            text_edits = card_widget.findChildren(QTextEdit)
            if len(text_edits) >= 2:
                return {
                    'front': text_edits[0].toPlainText(),
                    'back': text_edits[1].toPlainText()
                }
            return original_card
    
    def update_existing_template(self, note_type, card_format: str):
        """Update existing note type template with AnKing-style conversation summary button"""
        from aqt import mw
        
        if not note_type['tmpls']:
            return
            
        template = note_type['tmpls'][0]  # Get the first (and usually only) template
        
        if card_format == "cloze":
            template['afmt'] = """{{cloze:Text}}<br>{{Extra}}

{{#AI Conversation Summary}}
<span id="hint-ai-summary" class="hintBtn" data-name="AI Conversation Summary">
  <a href="#" class="hint" onclick="toggleHintBtn('hint-ai-summary')"></a>
  <button id="button-ai-summary" class="button-general" onclick="toggleHintBtn('hint-ai-summary')">
    💬 AI Chat Summary
  </button>
  <div dir="auto" id="ai-summary" class="hints" style="display: none;">{{AI Conversation Summary}}</div>
</span>

<script>
// AnKing-style toggle function for AI Chat Summary
window.toggleHintBtn = function(containerId, noScrolling=false) {
  const container = document.getElementById(containerId)
  const link = container.getElementsByTagName("a")[0]
  const button = container.getElementsByTagName("button")[0]
  const hint = container.getElementsByTagName("div")[0]

  if (hint.style.display == "none") {
    button.classList.add("expanded-button")
    hint.style.display = "block"
    link.style.display = "none"
    if (!noScrolling) {
      hint.scrollIntoView({
        behavior: "smooth",
        block: "start",
        inline: "nearest"
      });
    }
  } else {
    button.classList.remove("expanded-button")
    hint.style.display = "none"
    link.style.display = ""
  }
}

// AnKing-style button styling
const style = document.createElement('style');
style.textContent = `
.button-general {
  outline: 0;
  border-radius: 0.12em;
  border: 1px solid #525253 !important;
  padding: 5px 5px;
  text-align: center;
  display: inline-block;
  font-size: 9.5px;
  background-color: #424242;
  color: #AFAFAF !important;
  margin-top: 8px;
}

.expanded-button {
  display: block;
  margin: auto;
  margin-top: 10px;
  font-weight: bold;
  width: 50% !important;
  background: #ababab !important;
  color: black !important;
  font-weight: bold;
  width: 50% !important;
}

.hints {
  font-style: italic;
  font-size: 1.2rem;
  color: #4297F9;
}

html:not(.mobile) .button-general:hover {
  cursor: default;
  background-color: #E9E9E9 !important;
  color: #363638 !important;
}

/* Night mode styles */
.nightMode .hints, .night_mode .hints {
  color: cyan;
}

.nightMode .card, .night_mode .card {
  background-color: #272828 !important;
  color: #FFFAFA !important;
}
`;
document.head.appendChild(style);
</script>
{{/AI Conversation Summary}}"""
        else:  # basic
            template['afmt'] = """{{FrontSide}}<hr id="answer">{{Back}}

{{#AI Conversation Summary}}
<span id="hint-ai-summary" class="hintBtn" data-name="AI Conversation Summary">
  <a href="#" class="hint" onclick="toggleHintBtn('hint-ai-summary')"></a>
  <button id="button-ai-summary" class="button-general" onclick="toggleHintBtn('hint-ai-summary')">
    💬 AI Chat Summary
  </button>
  <div dir="auto" id="ai-summary" class="hints" style="display: none;">{{AI Conversation Summary}}</div>
</span>

<script>
// AnKing-style toggle function for AI Chat Summary
window.toggleHintBtn = function(containerId, noScrolling=false) {
  const container = document.getElementById(containerId)
  const link = container.getElementsByTagName("a")[0]
  const button = container.getElementsByTagName("button")[0]
  const hint = container.getElementsByTagName("div")[0]

  if (hint.style.display == "none") {
    button.classList.add("expanded-button")
    hint.style.display = "block"
    link.style.display = "none"
    if (!noScrolling) {
      hint.scrollIntoView({
        behavior: "smooth",
        block: "start",
        inline: "nearest"
      });
    }
  } else {
    button.classList.remove("expanded-button")
    hint.style.display = "none"
    link.style.display = ""
  }
}

// AnKing-style button styling
const style = document.createElement('style');
style.textContent = `
.button-general {
  outline: 0;
  border-radius: 0.12em;
  border: 1px solid #525253 !important;
  padding: 5px 5px;
  text-align: center;
  display: inline-block;
  font-size: 9.5px;
  background-color: #424242;
  color: #AFAFAF !important;
  margin-top: 8px;
}

.expanded-button {
  display: block;
  margin: auto;
  margin-top: 10px;
  font-weight: bold;
  width: 50% !important;
  background: #ababab !important;
  color: black !important;
  font-weight: bold;
  width: 50% !important;
}

.hints {
  font-style: italic;
  font-size: 1.2rem;
  color: #4297F9;
}

html:not(.mobile) .button-general:hover {
  cursor: default;
  background-color: #E9E9E9 !important;
  color: #363638 !important;
}

/* Night mode styles */
.nightMode .hints, .night_mode .hints {
  color: cyan;
}

.nightMode .card, .night_mode .card {
  background-color: #272828 !important;
  color: #FFFAFA !important;
}
`;
document.head.appendChild(style);
</script>
{{/AI Conversation Summary}}"""
        
        # Save the changes
        mw.col.models.save(note_type)

    def get_or_create_addon_note_type(self, card_format: str):
        """Get or create the appropriate note type for AI-generated cards"""
        from aqt import mw
        
        if card_format == "cloze":
            note_type_name = "AI Chat Cloze"
            # Check if note type already exists
            existing_type = mw.col.models.by_name(note_type_name)
            if existing_type:
                # Update the template with AnKing-style button
                self.update_existing_template(existing_type, "cloze")
                return existing_type
                
            # Create new cloze note type
            note_type = mw.col.models.new(note_type_name)
            note_type['type'] = 1  # Cloze type
            
            # Add fields
            field1 = mw.col.models.new_field("Text")
            mw.col.models.add_field(note_type, field1)
            
            field2 = mw.col.models.new_field("Extra")
            mw.col.models.add_field(note_type, field2)
            
            field3 = mw.col.models.new_field("AI Conversation Summary")
            mw.col.models.add_field(note_type, field3)
            
            # Add cloze template with AnKing-style conversation summary button
            template = mw.col.models.new_template("Cloze")
            template['qfmt'] = "{{cloze:Text}}"
            template['afmt'] = """{{cloze:Text}}<br>{{Extra}}

{{#AI Conversation Summary}}
<span id="hint-ai-summary" class="hintBtn" data-name="AI Conversation Summary">
  <a href="#" class="hint" onclick="toggleHintBtn('hint-ai-summary')"></a>
  <button id="button-ai-summary" class="button-general" onclick="toggleHintBtn('hint-ai-summary')">
    💬 AI Chat Summary
  </button>
  <div dir="auto" id="ai-summary" class="hints" style="display: none;">{{AI Conversation Summary}}</div>
</span>

<script>
// AnKing-style toggle function for AI Chat Summary
window.toggleHintBtn = function(containerId, noScrolling=false) {
  const container = document.getElementById(containerId)
  const link = container.getElementsByTagName("a")[0]
  const button = container.getElementsByTagName("button")[0]
  const hint = container.getElementsByTagName("div")[0]

  if (hint.style.display == "none") {
    button.classList.add("expanded-button")
    hint.style.display = "block"
    link.style.display = "none"
    if (!noScrolling) {
      hint.scrollIntoView({
        behavior: "smooth",
        block: "start",
        inline: "nearest"
      });
    }
  } else {
    button.classList.remove("expanded-button")
    hint.style.display = "none"
    link.style.display = ""
  }
}

// AnKing-style button styling
const style = document.createElement('style');
style.textContent = `
.button-general {
  outline: 0;
  border-radius: 0.12em;
  border: 1px solid #525253 !important;
  padding: 5px 5px;
  text-align: center;
  display: inline-block;
  font-size: 9.5px;
  background-color: #424242;
  color: #AFAFAF !important;
  margin-top: 8px;
}

.expanded-button {
  display: block;
  margin: auto;
  margin-top: 10px;
  font-weight: bold;
  width: 50% !important;
  background: #ababab !important;
  color: black !important;
  font-weight: bold;
  width: 50% !important;
}

.hints {
  font-style: italic;
  font-size: 1.2rem;
  color: #4297F9;
}

html:not(.mobile) .button-general:hover {
  cursor: default;
  background-color: #E9E9E9 !important;
  color: #363638 !important;
}

/* Night mode styles */
.nightMode .hints, .night_mode .hints {
  color: cyan;
}

.nightMode .card, .night_mode .card {
  background-color: #272828 !important;
  color: #FFFAFA !important;
}
`;
document.head.appendChild(style);
</script>
{{/AI Conversation Summary}}"""
            mw.col.models.add_template(note_type, template)
            
            # Save the model
            mw.col.models.add(note_type)
            return note_type
            
        else:  # basic
            note_type_name = "AI Chat Basic"
            # Check if note type already exists
            existing_type = mw.col.models.by_name(note_type_name)
            if existing_type:
                # Update the template with AnKing-style button
                self.update_existing_template(existing_type, "basic")
                return existing_type
                
            # Create new basic note type
            note_type = mw.col.models.new(note_type_name)
            note_type['type'] = 0  # Basic type
            
            # Add fields
            field1 = mw.col.models.new_field("Front")
            mw.col.models.add_field(note_type, field1)
            
            field2 = mw.col.models.new_field("Back")
            mw.col.models.add_field(note_type, field2)
            
            field3 = mw.col.models.new_field("AI Conversation Summary")
            mw.col.models.add_field(note_type, field3)
            
            # Add card template with AnKing-style conversation summary button
            template = mw.col.models.new_template("Card 1")
            template['qfmt'] = "{{Front}}"
            template['afmt'] = """{{FrontSide}}<hr id="answer">{{Back}}

{{#AI Conversation Summary}}
<span id="hint-ai-summary" class="hintBtn" data-name="AI Conversation Summary">
  <a href="#" class="hint" onclick="toggleHintBtn('hint-ai-summary')"></a>
  <button id="button-ai-summary" class="button-general" onclick="toggleHintBtn('hint-ai-summary')">
    💬 AI Chat Summary
  </button>
  <div dir="auto" id="ai-summary" class="hints" style="display: none;">{{AI Conversation Summary}}</div>
</span>

<script>
// AnKing-style toggle function for AI Chat Summary
window.toggleHintBtn = function(containerId, noScrolling=false) {
  const container = document.getElementById(containerId)
  const link = container.getElementsByTagName("a")[0]
  const button = container.getElementsByTagName("button")[0]
  const hint = container.getElementsByTagName("div")[0]

  if (hint.style.display == "none") {
    button.classList.add("expanded-button")
    hint.style.display = "block"
    link.style.display = "none"
    if (!noScrolling) {
      hint.scrollIntoView({
        behavior: "smooth",
        block: "start",
        inline: "nearest"
      });
    }
  } else {
    button.classList.remove("expanded-button")
    hint.style.display = "none"
    link.style.display = ""
  }
}

// AnKing-style button styling
const style = document.createElement('style');
style.textContent = `
.button-general {
  outline: 0;
  border-radius: 0.12em;
  border: 1px solid #525253 !important;
  padding: 5px 5px;
  text-align: center;
  display: inline-block;
  font-size: 9.5px;
  background-color: #424242;
  color: #AFAFAF !important;
  margin-top: 8px;
}

.expanded-button {
  display: block;
  margin: auto;
  margin-top: 10px;
  font-weight: bold;
  width: 50% !important;
  background: #ababab !important;
  color: black !important;
  font-weight: bold;
  width: 50% !important;
}

.hints {
  font-style: italic;
  font-size: 1.2rem;
  color: #4297F9;
}

html:not(.mobile) .button-general:hover {
  cursor: default;
  background-color: #E9E9E9 !important;
  color: #363638 !important;
}

/* Night mode styles */
.nightMode .hints, .night_mode .hints {
  color: cyan;
}

.nightMode .card, .night_mode .card {
  background-color: #272828 !important;
  color: #FFFAFA !important;
}
`;
document.head.appendChild(style);
</script>
{{/AI Conversation Summary}}"""
            mw.col.models.add_template(note_type, template)
            
            # Save the model
            mw.col.models.add(note_type)
            return note_type
    
    def generate_conversation_summary_sync(self):
        """Generate conversation summary synchronously"""
        try:
            # Create summary prompt (same as the summary feature)
            summary_prompt = f"""You are summarizing a chat conversation between a user and an AI assistant about study material. 

IMPORTANT: Ignore the flashcard content at the beginning. Focus ONLY on the back-and-forth conversation between "You:" and "AI:" messages.

Create a single "Conversation Summary" section that captures the main explanations and information discussed during the chat. Focus primarily on what the AI explained in response to the user's questions.

Do NOT include:
- "Key Questions Asked" sections
- "Explanations Provided by AI" headers  
- "Clarifications Made" sections
- Information from the original flashcard unless specifically discussed

Just provide the key content and explanations that came up during the actual conversation, organized clearly with markdown formatting.

{self.conversation_text}

Conversation Summary:"""

            # Prepare request data
            messages = [
                {
                    "role": "system",
                    "content": "You are a helpful study assistant. Create clear, organized study notes from conversations using markdown formatting."
                },
                {
                    "role": "user", 
                    "content": summary_prompt
                }
            ]
            
            data = {
                "model": self.config.get("openai_model", "gpt-3.5-turbo"),
                "messages": messages,
                "max_tokens": self.config.get("max_tokens", 500),
                "temperature": 0.3
            }
            
            # Convert to JSON
            json_data = json.dumps(data).encode('utf-8')
            
            # Create request
            req = urllib.request.Request(
                'https://api.openai.com/v1/chat/completions',
                data=json_data,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {OPENAI_API_KEY}'
                }
            )
            
            # Make API call
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                
            self.conversation_summary = result['choices'][0]['message']['content'].strip()
            
        except Exception as e:
            print(f"Error generating summary: {e}")
            self.conversation_summary = "Error generating conversation summary"
    
    def generate_conversation_summary(self):
        """Generate conversation summary for the cards"""
        try:
            # Use the same summary generation logic as the summary feature
            summary_worker = SummaryWorker(self.conversation_text, self.config)
            summary_worker.start()
            summary_worker.wait()  # Wait for completion
            
            # Get the summary (this is a simplified approach)
            # In a full implementation, you might want to make this async too
            self.conversation_summary = "Generated from AI conversation - see summary feature for details"
        except:
            self.conversation_summary = "AI conversation summary not available"
    
    def parse_flashcards(self, text: str) -> List[Dict]:
        """Parse the generated flashcard text into individual cards"""
        flashcards = []
        
        if "cloze" in self.format_combo.currentText().lower():
            # Parse cloze cards - look for {{c1:: patterns
            lines = text.split('\n')
            current_card = ""
            
            for line in lines:
                line = line.strip()
                if line and '{{c' in line:
                    if current_card:
                        flashcards.append({'content': current_card.strip()})
                    current_card = line
                elif line and current_card:
                    current_card += "\n" + line
                elif not line and current_card:
                    flashcards.append({'content': current_card.strip()})
                    current_card = ""
            
            if current_card:
                flashcards.append({'content': current_card.strip()})
        
        else:
            # Parse basic cards - look for Front:/Back: patterns
            lines = text.split('\n')
            current_front = ""
            current_back = ""
            in_front = False
            in_back = False
            
            for line in lines:
                line = line.strip()
                
                if line.lower().startswith('front:'):
                    if current_front and current_back:
                        flashcards.append({'front': current_front.strip(), 'back': current_back.strip()})
                    current_front = line[6:].strip()  # Remove "Front:"
                    current_back = ""
                    in_front = True
                    in_back = False
                elif line.lower().startswith('back:'):
                    current_back = line[5:].strip()  # Remove "Back:"
                    in_front = False
                    in_back = True
                elif line and in_front:
                    current_front += "\n" + line
                elif line and in_back:
                    current_back += "\n" + line
                elif not line and current_front and current_back:
                    flashcards.append({'front': current_front.strip(), 'back': current_back.strip()})
                    current_front = ""
                    current_back = ""
                    in_front = False
                    in_back = False
            
            # Add the last card if exists
            if current_front and current_back:
                flashcards.append({'front': current_front.strip(), 'back': current_back.strip()})
        
        return flashcards 

class CardRefinementWorker(QThread):
    """Worker thread for refining individual flashcards"""
    
    refinement_complete = pyqtSignal(str)  # Emitted when refinement is complete
    error_occurred = pyqtSignal(str)  # Emitted when error occurs
    
    def __init__(self, current_card: dict, refinement_prompt: str, config: dict, card_format: str):
        super().__init__()
        self.current_card = current_card
        self.refinement_prompt = refinement_prompt
        self.config = config
        self.card_format = card_format
    
    def run(self):
        """Refine the flashcard using OpenAI API"""
        try:
            # Format current card content
            if self.card_format == "cloze":
                current_content = f"Current cloze card: {self.current_card.get('content', '')}"
            else:
                current_content = f"Current card:\nFront: {self.current_card.get('front', '')}\nBack: {self.current_card.get('back', '')}"
            
            # Create refinement prompt
            if self.card_format == "cloze":
                format_instruction = """Output the refined card as cloze deletion format using {{c1::text}} syntax.
IMPORTANT: Use a statement/fact format, NOT question-answer. 
Example: {{c1::Acyclovir}} is used for {{c2::herpes virus}} treatment."""
            else:
                format_instruction = """Output the refined card in Front:/Back: format only. Do NOT use {{c1::}} cloze syntax.
IMPORTANT: Must have "Front:" and "Back:" labels.
Example:
Front: What is acyclovir used for?
Back: Treatment of herpes simplex and varicella-zoster virus infections."""
            
            refinement_request = f"""Please refine this flashcard based on the following instruction: {self.refinement_prompt}

{current_content}

{format_instruction}

Refined card:"""

            # Prepare request data
            messages = [
                {
                    "role": "system",
                    "content": "You are a helpful study assistant. Refine flashcards based on user instructions while maintaining educational quality."
                },
                {
                    "role": "user", 
                    "content": refinement_request
                }
            ]
            
            data = {
                "model": self.config.get("openai_model", "gpt-3.5-turbo"),
                "messages": messages,
                "max_tokens": self.config.get("max_tokens", 300),
                "temperature": 0.3
            }
            
            # Convert to JSON
            json_data = json.dumps(data).encode('utf-8')
            
            # Create request
            req = urllib.request.Request(
                'https://api.openai.com/v1/chat/completions',
                data=json_data,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {OPENAI_API_KEY}'
                }
            )
            
            # Make API call
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                
            refined_content = result['choices'][0]['message']['content'].strip()
            self.refinement_complete.emit(refined_content)
                
        except Exception as e:
            self.error_occurred.emit(str(e))

class CardRefinementDialog(QDialog):
    """Dialog for refining individual flashcards"""
    
    def __init__(self, parent, card_index: int, config: dict):
        super().__init__(parent)
        self.card_index = card_index
        self.config = config
        self.theme_colors = get_theme_colors()
        self.init_ui()
    
    def init_ui(self):
        """Initialize the refinement dialog UI"""
        self.setWindowTitle(f"Refine Card {self.card_index + 1}")
        self.setModal(True)
        self.resize(500, 300)
        
        # Apply dark mode styling
        bg_color = self.theme_colors['bg_secondary']
        text_color = self.theme_colors['text_primary']
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {bg_color};
                color: {text_color};
            }}
        """)
        
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel(f"🔧 Refine Card {self.card_index + 1}")
        title.setStyleSheet(f"""
            QLabel {{
                font-size: 16px;
                font-weight: bold;
                color: #17a2b8;
                padding: 10px;
                margin-bottom: 10px;
            }}
        """)
        layout.addWidget(title)
        
        # Instructions
        instructions = QLabel("Describe how you want to refine this flashcard:")
        instructions.setStyleSheet(f"color: {text_color}; font-weight: bold; margin-bottom: 5px;")
        layout.addWidget(instructions)
        
        # Refinement prompt input
        self.prompt_input = QTextEdit()
        self.prompt_input.setPlaceholderText("e.g., Make it more concise, add more detail about pathophysiology, focus on clinical symptoms, etc.")
        bg_input = self.theme_colors['bg_input']
        border_color = self.theme_colors['border']
        self.prompt_input.setStyleSheet(f"""
            QTextEdit {{
                border: 1px solid {border_color};
                border-radius: 6px;
                padding: 10px;
                font-size: 13px;
                background-color: {bg_input};
                color: {text_color};
                min-height: 80px;
            }}
        """)
        layout.addWidget(self.prompt_input)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
        """)
        
        refine_btn = QPushButton("🔧 Refine Card")
        refine_btn.clicked.connect(self.accept)
        refine_btn.setStyleSheet("""
            QPushButton {
                background-color: #17a2b8;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #138496;
            }
        """)
        
        button_layout.addStretch()
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(refine_btn)
        
        layout.addLayout(button_layout)
    
    def get_refinement_prompt(self) -> str:
        """Get the refinement prompt from the input field"""
        return self.prompt_input.toPlainText().strip() 