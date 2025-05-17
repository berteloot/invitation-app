from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class Post:
    """Represents a LinkedIn post with its engagement metrics."""
    id: str
    content: str
    post_date: datetime
    likes: int
    comments: int
    shares: int
    impressions: Optional[int] = None
    media_type: Optional[str] = None  # 'text', 'image', 'video', 'article'
    
    @property
    def total_engagement(self) -> int:
        """Calculate total engagement (likes + comments + shares)."""
        return self.likes + self.comments + self.shares
    
    @property
    def engagement_rate(self) -> float:
        """Calculate engagement rate if impressions are available."""
        if self.impressions and self.impressions > 0:
            return (self.total_engagement / self.impressions) * 100
        return 0.0
    
    @property
    def post_hour(self) -> int:
        """Get the hour of the day when the post was published."""
        return self.post_date.hour
    
    @property
    def post_day(self) -> int:
        """Get the day of the week when the post was published (0 = Monday, 6 = Sunday)."""
        return self.post_date.weekday() 