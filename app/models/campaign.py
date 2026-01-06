"""Campaign-related models"""
from pydantic import BaseModel


class CampaignCreate(BaseModel):
    """Model for creating a new campaign"""
    contacts: list[str]


class DispositionData(BaseModel):
    """Model for saving call disposition"""
    phone: str
    disposition: str
    notes: str = ""

