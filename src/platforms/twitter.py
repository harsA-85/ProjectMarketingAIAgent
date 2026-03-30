import os
from typing import Optional, Dict, Any, List
from datetime import datetime
import requests


class TwitterPlatform:
    """Twitter/X integration for agent posting and engagement"""

    def __init__(self, api_key: str, api_secret: str, access_token: str, access_token_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self.access_token_secret = access_token_secret
        self.base_url = "https://api.twitter.com/2"

    def authenticate(self) -> bool:
        """Verify credentials are valid"""
        try:
            import tweepy
            auth = tweepy.OAuthHandler(self.api_key, self.api_secret)
            auth.set_access_token(self.access_token, self.access_token_secret)
            api = tweepy.API(auth)
            api.verify_credentials()
            return True
        except Exception as e:
            print(f"Twitter authentication error: {e}")
            return False

    def post_tweet(
        self,
        text: str,
        reply_settings: str = "everyone",
        media_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Post a tweet"""
        try:
            import tweepy
            auth = tweepy.OAuthHandler(self.api_key, self.api_secret)
            auth.set_access_token(self.access_token, self.access_token_secret)
            client = tweepy.Client(
                bearer_token=os.getenv('TWITTER_BEARER_TOKEN', ''),
                consumer_key=self.api_key,
                consumer_secret=self.api_secret,
                access_token=self.access_token,
                access_token_secret=self.access_token_secret
            )

            response = client.create_tweet(text=text)
            return {
                'success': True,
                'post_id': response.data.get('id') if response.data else None,
                'platform': 'twitter',
                'timestamp': datetime.utcnow()
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'platform': 'twitter'
            }

    def like_tweet(self, tweet_id: str) -> Dict[str, Any]:
        """Like a tweet"""
        try:
            import tweepy
            auth = tweepy.OAuthHandler(self.api_key, self.api_secret)
            auth.set_access_token(self.access_token, self.access_token_secret)
            api = tweepy.API(auth)
            api.create_favorite(id=tweet_id)

            return {
                'success': True,
                'action': 'like',
                'tweet_id': tweet_id
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'action': 'like'
            }

    def reply_to_tweet(self, tweet_id: str, reply_text: str) -> Dict[str, Any]:
        """Reply to a tweet"""
        try:
            import tweepy
            auth = tweepy.OAuthHandler(self.api_key, self.api_secret)
            auth.set_access_token(self.access_token, self.access_token_secret)
            api = tweepy.API(auth)
            response = api.update_status(
                status=reply_text,
                in_reply_to_status_id=tweet_id,
                auto_populate_reply_metadata=True
            )

            return {
                'success': True,
                'action': 'reply',
                'tweet_id': response.id,
                'reply_to': tweet_id
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'action': 'reply'
            }

    def follow_user(self, user_id: str) -> Dict[str, Any]:
        """Follow a Twitter user"""
        try:
            import tweepy
            auth = tweepy.OAuthHandler(self.api_key, self.api_secret)
            auth.set_access_token(self.access_token, self.access_token_secret)
            api = tweepy.API(auth)
            api.create_friendship(user_id=user_id)

            return {
                'success': True,
                'action': 'follow',
                'user_id': user_id
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'action': 'follow'
            }

    def search_tweets(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Search for tweets"""
        try:
            import tweepy
            client = tweepy.Client(bearer_token=os.getenv('TWITTER_BEARER_TOKEN', ''))
            tweets = client.search_recent_tweets(query=query, max_results=min(max_results, 100))
            return tweets.data if tweets.data else []
        except Exception as e:
            print(f"Search error: {e}")
            return []

    def get_account_stats(self) -> Dict[str, Any]:
        """Get account statistics"""
        try:
            import tweepy
            auth = tweepy.OAuthHandler(self.api_key, self.api_secret)
            auth.set_access_token(self.access_token, self.access_token_secret)
            api = tweepy.API(auth)
            user = api.verify_credentials()

            return {
                'followers': user.followers_count,
                'following': user.friends_count,
                'tweets': user.statuses_count,
                'verified': user.verified
            }
        except Exception as e:
            return {'error': str(e)}
