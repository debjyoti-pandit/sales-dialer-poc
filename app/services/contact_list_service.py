"""Service for managing shared contact list from file"""
import os
from typing import List, Set
from pathlib import Path


class ContactListService:
    """Service for managing shared contact list"""
    
    def __init__(self, contact_file_path: str = "contacts.txt"):
        """Initialize with path to contact file"""
        self.contact_file_path = contact_file_path
        self._contacts_cache = None
        self._last_modified = None
    
    def get_contacts(self) -> List[str]:
        """Load contacts from file, caching for performance"""
        file_path = Path(self.contact_file_path)
        
        # Check if file exists
        if not file_path.exists():
            print(f"Contact file {self.contact_file_path} not found. Creating empty file.")
            file_path.touch()
            return []
        
        # Check if file was modified
        current_modified = file_path.stat().st_mtime
        if self._contacts_cache is None or current_modified != self._last_modified:
            self._load_contacts_from_file(file_path)
            self._last_modified = current_modified
        
        return self._contacts_cache.copy()
    
    def _load_contacts_from_file(self, file_path: Path):
        """Load contacts from file"""
        contacts = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):  # Skip empty lines and comments
                        # Normalize phone number
                        if not line.startswith('+'):
                            # Assume default country code if not provided
                            line = '+' + line
                        contacts.append(line)
            self._contacts_cache = contacts
            print(f"Loaded {len(contacts)} contacts from {self.contact_file_path}")
        except Exception as e:
            print(f"Error loading contacts from file: {e}")
            self._contacts_cache = []
    
    def get_undialed_contacts(self, dialed_contacts: Set[str], count: int = 5) -> List[str]:
        """Get contacts that haven't been dialed by any agent"""
        all_contacts = self.get_contacts()
        undialed = [phone for phone in all_contacts if phone not in dialed_contacts]
        return undialed[:count]


# Singleton instance
contact_list_service = ContactListService()

