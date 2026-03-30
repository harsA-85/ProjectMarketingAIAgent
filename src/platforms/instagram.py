import os
from typing import Optional, Dict, Any, List
from datetime import datetime
import requests


class InstagramPlatform:
    """Instagram integration for agent posting and engagement"""

    def __init__(self, access_token: str, username: str):
        self.access_token = access_token
        self.username = username
        self.api_url = "https://graph.instagram.com"
        self.version = "v18.0"

    def authenticate(self) -> bool:
        """Verify access token is valid"""
        url = f"{self.api_url}/{self.version}/me"
        params = {'access_token': self.access_token, 'fields': 'id,username'}

        try:
            response = requests.get(url, params=params, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"Instagram authentication error: {e}")
            return False

    def post_content(
        self,
        caption: str,
        image_url: Optional[str] = None,
        video_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """Post content to Instagram"""
        # Stub implementation - requires Instagram Graph API setup
        return {
            'success': False,
            'message': 'Implementation requires Instagram Graph API credentials',
            'platform': 'instagram',
            'timestamp': datetime.utcnow()
        }

    def engage_with_post(
        self,
        post_id: str,
        interaction_type: str,
        comment_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Engage with Instagram posts (like, comment, etc.)
        interaction_type: 'like', 'comment'
        """
        return {
            'success': False,
            'message': 'Instagram engagement requires Graph API setup',
            'post_id': post_id,
            'interaction_type': interaction_type
        }

    def follow_user(self, user_id: str) -> Dict[str, Any]:
        """Follow an Instagram user"""
        return {
            'success': False,
            'message': 'Instagram follow requires Graph API setup',
            'user_id': user_id
        }

    def get_feed_data(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get Instagram feed data for engagement analysis"""
        return []

    def get_account_stats(self) -> Dict[str, Any]:
        """Get account statistics"""
        return {
            'followers': 0,
            'following': 0,
            'posts': 0,
            'engagement_rate': 0.0
        }


class InstagramAuth:
    """Handles Instagram OAuth flow"""

    def __init__(self, app_id: str, app_secret: str, redirect_uri: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.redirect_uri = redirect_uri

    def get_authorization_url(self) -> str:
        """Generate Instagram authorization URL"""
        scope = "instagram_business_content_publish,instagram_graph_user_profile"
        return (f"https://api.instagram.com/oauth/authorize"
                f"?client_id={self.app_id}"
                f"&redirect_uri={self.redirect_uri}"
                f"&scope={scope}"
                f"&response_type=code")

    def exchange_code_for_token(self, code: str) -> Optional[str]:
        """Exchange authorization code for access token"""
        url = "https://graph.instagram.com/v18.0/oauth/access_token"
        data = {
            'client_id': self.app_id,
            'client_secret': self.app_secret,
            'grant_type': 'authorization_code',
            'redirect_uri': self.redirect_uri,
            'code': code
        }

        try:
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                return response.json().get('access_token')
        except Exception as e:
            print(f"Token exchange error: {e}")

        return None
