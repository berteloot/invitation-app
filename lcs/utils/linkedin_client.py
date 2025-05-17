from linkedin_api import Linkedin
import re
from typing import Dict, List, Optional
from datetime import datetime
from ..models.post import Post

class LinkedInClient:
    """Handles LinkedIn API interactions and data extraction."""
    
    def __init__(self, email: str, password: str):
        """Initialize the LinkedIn client with authentication credentials."""
        self.client = Linkedin(email, password)
    
    def extract_profile_id(self, profile_url: str) -> str:
        """Extract the profile ID from a LinkedIn URL."""
        # Handle both personal and company profile URLs
        patterns = [
            r'linkedin\.com/in/([^/]+)',
            r'linkedin\.com/company/([^/]+)',
            r'linkedin\.com/company/([^/]+)/posts'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, profile_url)
            if match:
                return match.group(1)
        
        raise ValueError("Invalid LinkedIn profile URL")
    
    def get_profile_type(self, profile_url: str) -> str:
        """Determine if the URL is for a personal or company profile."""
        if 'company' in profile_url:
            return 'company'
        return 'personal'
    
    def get_profile_posts(self, profile_url: str, limit: int = 100) -> List[Post]:
        """Fetch posts from a LinkedIn profile."""
        profile_id = self.extract_profile_id(profile_url)
        profile_type = self.get_profile_type(profile_url)
        
        try:
            if profile_type == 'company':
                posts_data = self.client.get_company_updates(profile_id, limit=limit)
            else:
                posts_data = self.client.get_profile_posts(profile_id, limit=limit)
            
            posts = []
            for post_data in posts_data:
                # Extract engagement metrics
                likes = post_data.get('likes', {}).get('count', 0)
                comments = post_data.get('comments', {}).get('count', 0)
                shares = post_data.get('shares', {}).get('count', 0)
                impressions = post_data.get('impressions', 0)
                
                # Extract content
                content = post_data.get('commentary', {}).get('text', '')
                
                # Extract media type
                media_type = 'text'
                if post_data.get('images'):
                    media_type = 'image'
                elif post_data.get('videos'):
                    media_type = 'video'
                elif post_data.get('article'):
                    media_type = 'article'
                
                # Create Post object
                post = Post(
                    id=post_data.get('id', ''),
                    content=content,
                    post_date=datetime.fromtimestamp(post_data.get('created', {}).get('time', 0) / 1000),
                    likes=likes,
                    comments=comments,
                    shares=shares,
                    impressions=impressions,
                    media_type=media_type
                )
                posts.append(post)
            
            return posts
            
        except Exception as e:
            raise ValueError(f"Error fetching posts: {str(e)}")
    
    def get_profile_info(self, profile_url: str) -> Dict:
        """Get basic profile information."""
        profile_id = self.extract_profile_id(profile_url)
        profile_type = self.get_profile_type(profile_url)
        
        try:
            if profile_type == 'company':
                profile_data = self.client.get_company(profile_id)
                return {
                    'name': profile_data.get('name', ''),
                    'description': profile_data.get('description', ''),
                    'followers': profile_data.get('followersCount', 0),
                    'type': 'company'
                }
            else:
                profile_data = self.client.get_profile(profile_id)
                return {
                    'name': f"{profile_data.get('firstName', '')} {profile_data.get('lastName', '')}",
                    'headline': profile_data.get('headline', ''),
                    'connections': profile_data.get('connections', 0),
                    'type': 'personal'
                }
        except Exception as e:
            raise ValueError(f"Error fetching profile info: {str(e)}") 