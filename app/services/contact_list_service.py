"""Service for managing shared contact list from JSON file"""
from typing import List, Set, Optional, Dict
from pathlib import Path
import json
from app.logger import logger


class ContactListService:
    """Service for managing shared contact list from campaigns JSON"""
    
    def __init__(self, campaigns_file_path: str = "campaigns.json"):
        """Initialize with path to campaigns JSON file"""
        self.campaigns_file_path = campaigns_file_path
        self._campaigns_cache = None
        self._last_modified = None
    
    def get_campaigns(self) -> List[Dict]:
        """Load campaigns from JSON file, caching for performance"""
        file_path = Path(self.campaigns_file_path)
        
        # Check if file exists
        if not file_path.exists():
            logger.warning(f"Campaigns file {self.campaigns_file_path} not found.")
            return []
        
        # Check if file was modified
        current_modified = file_path.stat().st_mtime
        if self._campaigns_cache is None or current_modified != self._last_modified:
            self._load_campaigns_from_file(file_path)
            self._last_modified = current_modified
        
        return self._campaigns_cache.copy() if self._campaigns_cache else []
    
    def _load_campaigns_from_file(self, file_path: Path):
        """Load campaigns from JSON file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                campaigns_data = json.load(f)
            
            # Normalize phone numbers (ensure they start with +)
            for campaign in campaigns_data:
                normalized_contacts = []
                for phone in campaign.get("contacts", []):
                    phone_str = str(phone).strip()
                    if phone_str and not phone_str.startswith('+'):
                        phone_str = '+' + phone_str
                    normalized_contacts.append(phone_str)
                campaign["contacts"] = normalized_contacts
            
            self._campaigns_cache = campaigns_data
            logger.success(f"Loaded {len(campaigns_data)} campaigns from {self.campaigns_file_path}")
        except Exception as e:
            logger.error(f"Error loading campaigns from file: {e}")
            self._campaigns_cache = []
    
    def get_campaign_by_id(self, campaign_id: int) -> Optional[Dict]:
        """Get a specific campaign by ID"""
        campaigns = self.get_campaigns()
        for campaign in campaigns:
            if campaign.get("id") == campaign_id:
                return campaign
        return None
    
    def get_contacts(self, campaign_id: Optional[int] = None) -> List[str]:
        """Get contacts for a specific campaign, or all contacts if no campaign_id"""
        if campaign_id:
            campaign = self.get_campaign_by_id(campaign_id)
            if campaign:
                return campaign.get("contacts", []).copy()
            return []
        
        # If no campaign_id, return all contacts from all campaigns (legacy support)
        all_contacts = []
        campaigns = self.get_campaigns()
        for campaign in campaigns:
            all_contacts.extend(campaign.get("contacts", []))
        # Remove duplicates while preserving order
        seen = set()
        unique_contacts = []
        for contact in all_contacts:
            if contact not in seen:
                seen.add(contact)
                unique_contacts.append(contact)
        return unique_contacts
    
    def get_undialed_contacts(self, dialed_contacts: Set[str], count: int = 5, campaign_id: Optional[int] = None) -> List[str]:
        """Get contacts that haven't been dialed by any agent, cycling through all contacts"""
        all_contacts = self.get_contacts(campaign_id)

        if not all_contacts:
            return []

        # Get undialed contacts first
        undialed = [phone for phone in all_contacts if phone not in dialed_contacts]

        # If we have enough undialed contacts, return them
        if len(undialed) >= count:
            return undialed[:count]

        # If we don't have enough undialed contacts, cycle through all contacts
        # This ensures we always return contacts, cycling through the list
        result = undialed.copy()  # Start with undialed contacts

        # Add more contacts from the beginning of the list to fill the batch
        needed = count - len(undialed)
        for phone in all_contacts:
            if len(result) >= count:
                break
            if phone not in result:  # Don't add duplicates
                result.append(phone)

        return result

    def get_next_batch_preview(self, dialed_contacts: Set[str], current_batch: List[str], count: int = 5, campaign_id: Optional[int] = None) -> List[str]:
        """Get preview of next batch of contacts that will be dialed after current batch"""
        all_contacts = self.get_contacts(campaign_id)

        if not all_contacts:
            return []

        # Simple approach: return the next contacts in the list after the current batch
        # This ensures cycling through all contacts regardless of dial status
        if current_batch:
            # Find the last contact in the current batch
            last_contact = current_batch[-1]
            try:
                last_index = all_contacts.index(last_contact)
                # Start from the next contact, wrapping around to the beginning
                next_index = (last_index + 1) % len(all_contacts)
                result = []
                for i in range(count):
                    result.append(all_contacts[next_index])
                    next_index = (next_index + 1) % len(all_contacts)
                return result
            except ValueError:
                # If last_contact not found, start from beginning
                pass

        # Default: return first 'count' contacts
        return all_contacts[:count]


# Singleton instance
contact_list_service = ContactListService()
