from typing import List, Dict, Tuple
import pandas as pd
import numpy as np
from datetime import datetime
from textblob import TextBlob
from ..models.post import Post

class PostAnalyzer:
    """Analyzes LinkedIn posts and generates insights."""
    
    def __init__(self, posts: List[Post]):
        self.posts = posts
        self.df = self._create_dataframe()
    
    def _create_dataframe(self) -> pd.DataFrame:
        """Convert posts to a pandas DataFrame for analysis."""
        data = []
        for post in self.posts:
            data.append({
                'id': post.id,
                'content': post.content,
                'post_date': post.post_date,
                'likes': post.likes,
                'comments': post.comments,
                'shares': post.shares,
                'impressions': post.impressions,
                'media_type': post.media_type,
                'total_engagement': post.total_engagement,
                'engagement_rate': post.engagement_rate,
                'post_hour': post.post_hour,
                'post_day': post.post_day
            })
        return pd.DataFrame(data)
    
    def get_engagement_stats(self) -> Dict:
        """Calculate basic engagement statistics."""
        return {
            'avg_engagement_rate': self.df['engagement_rate'].mean(),
            'max_engagement_rate': self.df['engagement_rate'].max(),
            'total_posts': len(self.df),
            'total_engagement': self.df['total_engagement'].sum(),
            'avg_likes': self.df['likes'].mean(),
            'avg_comments': self.df['comments'].mean(),
            'avg_shares': self.df['shares'].mean()
        }
    
    def get_best_posting_times(self) -> Tuple[List[int], List[int]]:
        """Determine the best days and hours for posting."""
        # Group by day and hour, calculate average engagement
        day_engagement = self.df.groupby('post_day')['engagement_rate'].mean()
        hour_engagement = self.df.groupby('post_hour')['engagement_rate'].mean()
        
        # Get top 3 days and hours
        best_days = day_engagement.nlargest(3).index.tolist()
        best_hours = hour_engagement.nlargest(3).index.tolist()
        
        return best_days, best_hours
    
    def analyze_sentiment(self) -> Dict:
        """Perform sentiment analysis on post content."""
        sentiments = []
        for content in self.df['content']:
            blob = TextBlob(content)
            sentiments.append(blob.sentiment.polarity)
        
        self.df['sentiment'] = sentiments
        
        return {
            'avg_sentiment': np.mean(sentiments),
            'positive_posts': len([s for s in sentiments if s > 0]),
            'negative_posts': len([s for s in sentiments if s < 0]),
            'neutral_posts': len([s for s in sentiments if s == 0])
        }
    
    def get_top_performing_posts(self, n: int = 5) -> pd.DataFrame:
        """Get the top n performing posts by engagement rate."""
        return self.df.nlargest(n, 'engagement_rate')
    
    def get_content_recommendations(self) -> Dict:
        """Generate basic content recommendations based on analysis."""
        best_posts = self.get_top_performing_posts(3)
        
        # Analyze common characteristics of top posts
        avg_length = best_posts['content'].str.len().mean()
        common_media = best_posts['media_type'].mode().iloc[0] if 'media_type' in best_posts else 'text'
        
        return {
            'optimal_post_length': int(avg_length),
            'recommended_media_type': common_media,
            'best_posting_times': {
                'days': self.get_best_posting_times()[0],
                'hours': self.get_best_posting_times()[1]
            }
        } 