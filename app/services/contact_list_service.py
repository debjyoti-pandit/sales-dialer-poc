"""Service for managing shared contact list from file"""
from typing import List, Set
from pathlib import Path
from app.logger import logger


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
            logger.warning(f"Contact file {self.contact_file_path} not found. Creating empty file.")
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
            logger.success(f"Loaded {len(contacts)} contacts from {self.contact_file_path}")
        except Exception as e:
            logger.error(f"Error loading contacts from file: {e}")
            self._contacts_cache = []
    
    def get_undialed_contacts(self, dialed_contacts: Set[str], count: int = 5) -> List[str]:
        """Get contacts that haven't been dialed by any agent, recycling when all are dialed"""
        all_contacts = self.get_contacts()

        if not all_contacts:
            return []

        # Get undialed contacts
        undialed = [phone for phone in all_contacts if phone not in dialed_contacts]

        # If we have enough undialed contacts, return them
        if len(undialed) >= count:
            return undialed[:count]

        # If we don't have enough undialed contacts, recycle from the beginning
        result = undialed.copy()  # Start with all undialed contacts

        # Add additional contacts from the beginning to make up the batch size
        needed = count - len(undialed)
        for phone in all_contacts:
            if len(result) >= count:
                break
            if phone not in result:  # Don't add duplicates
                result.append(phone)

        return result

    def get_next_batch_preview(self, dialed_contacts: Set[str], current_batch: List[str], count: int = 5) -> List[str]:
        """Get preview of next batch of contacts that will be dialed after current batch"""
        # Create a temporary set that includes the current batch as "dialed"
        # so we can see what would be dialed next
        temp_dialed = dialed_contacts.copy()
        temp_dialed.update(current_batch)

        return self.get_undialed_contacts(temp_dialed, count)


# Singleton instance
contact_list_service = ContactListService()

