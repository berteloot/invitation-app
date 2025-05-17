import pandas as pd
from typing import List, Optional
from datetime import datetime
from ..models.post import Post

class DataHandler:
    """Handles data import and export for LinkedIn posts."""
    
    @staticmethod
    def import_from_csv(file_path: str) -> List[Post]:
        """Import LinkedIn posts from a CSV file."""
        try:
            df = pd.read_csv(file_path)
            posts = []
            
            # Map CSV columns to Post attributes
            for _, row in df.iterrows():
                post = Post(
                    id=str(row.get('id', '')),
                    content=str(row.get('content', '')),
                    post_date=datetime.strptime(row['post_date'], '%Y-%m-%d %H:%M:%S'),
                    likes=int(row.get('likes', 0)),
                    comments=int(row.get('comments', 0)),
                    shares=int(row.get('shares', 0)),
                    impressions=int(row.get('impressions', 0)) if 'impressions' in row else None,
                    media_type=row.get('media_type', 'text')
                )
                posts.append(post)
            
            return posts
        except Exception as e:
            raise ValueError(f"Error importing CSV: {str(e)}")
    
    @staticmethod
    def export_to_csv(posts: List[Post], output_path: str) -> None:
        """Export posts to a CSV file."""
        data = []
        for post in posts:
            data.append({
                'id': post.id,
                'content': post.content,
                'post_date': post.post_date.strftime('%Y-%m-%d %H:%M:%S'),
                'likes': post.likes,
                'comments': post.comments,
                'shares': post.shares,
                'impressions': post.impressions,
                'media_type': post.media_type,
                'total_engagement': post.total_engagement,
                'engagement_rate': post.engagement_rate
            })
        
        df = pd.DataFrame(data)
        df.to_csv(output_path, index=False)
    
    @staticmethod
    def validate_csv_structure(df: pd.DataFrame) -> bool:
        """Validate that the CSV has the required columns."""
        required_columns = ['content', 'post_date', 'likes', 'comments', 'shares']
        return all(col in df.columns for col in required_columns)
    
    @staticmethod
    def clean_data(df: pd.DataFrame) -> pd.DataFrame:
        """Clean and preprocess the data."""
        # Remove duplicates
        df = df.drop_duplicates()
        
        # Convert post_date to datetime
        df['post_date'] = pd.to_datetime(df['post_date'])
        
        # Fill missing values
        df['likes'] = df['likes'].fillna(0)
        df['comments'] = df['comments'].fillna(0)
        df['shares'] = df['shares'].fillna(0)
        
        # Ensure numeric columns are integers
        numeric_columns = ['likes', 'comments', 'shares']
        for col in numeric_columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
        
        return df 