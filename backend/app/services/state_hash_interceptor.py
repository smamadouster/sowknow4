import hashlib
import redis
import sys
import logging

logger = logging.getLogger(__name__)

def check_state_hash(current_state_data: str, agent_name: str) -> bool:
    """
    Returns True if the state has NOT changed (No-Op).
    Returns False if the state HAS changed (Proceed to LLM).
    """
    try:
        # Connect to your local Redis (using the alias we fixed earlier)
        r = redis.Redis(host='redis', port=6379, db=0, decode_responses=True)
        
        # Create a deterministic hash of the current logs/metrics
        current_hash = hashlib.md5(current_state_data.encode('utf-8')).hexdigest()
        redis_key = f"patrol_hash:{agent_name}"
        
        # Get the hash from the last run
        last_hash = r.get(redis_key)
        
        if current_hash == last_hash:
            logger.info(f"[{agent_name}] No-Op: System state unchanged. Exiting early ($0.00).")
            return True # State is identical, abort LLM call
            
        # State has changed, update Redis and proceed
        r.set(redis_key, current_hash, ex=86400) # Cache for 24 hours
        logger.info(f"[{agent_name}] State changed. Proceeding to LLM analysis.")
        return False
        
    except Exception as e:
        logger.warning(f"Redis unavailable for state hashing: {e}. Proceeding to LLM.")
        return False # Fail open: if Redis is down, let the agent run
