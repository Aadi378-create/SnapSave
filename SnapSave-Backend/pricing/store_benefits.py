"""
SnapSave Store Benefits Database
--------------------------------
Centralized database of store thresholds, delivery rules, discounts,
free-item unlocks, cashback milestones, and future promotions for SnapSave.
"""

# Centralized store benefit rules config
STORE_BENEFITS = {
    "zepto": {
        "metadata": {
            "last_verified": "2026-06",
            "source": "manual_verified",
            "status": "active"
        },
        "free_delivery_threshold": 99,
        "milestones": [
            {
                "threshold": 1199,
                "type": "discount",
                "category": "discount",
                "value": 50,
                "description": "₹50 OFF"
            },
            {
                "threshold": 1899,
                "type": "discount",
                "category": "discount",
                "value": 100,
                "description": "₹100 OFF"
            },
            {
                "threshold": 2499,
                "type": "discount",
                "category": "discount",
                "value": 150,
                "description": "₹150 OFF"
            },
            {
                "threshold": 3099,
                "type": "discount",
                "category": "discount",
                "value": 200,
                "description": "₹200 OFF"
            }
        ]
    },
    "blinkit": {
        # TODO: Add Blinkit thresholds, delivery rules, discounts, and milestones
        "metadata": {
            "last_verified": "2026-06",
            "source": "manual_verified",
            "status": "todo"
        },
        "free_delivery_threshold": None,
        "milestones": []
    },
    "instamart": {
        # TODO: Add Instamart thresholds, delivery rules, discounts, and milestones
        "metadata": {
            "last_verified": "2026-06",
            "source": "manual_verified",
            "status": "todo"
        },
        "free_delivery_threshold": None,
        "milestones": []
    },
    "bigbasket": {
        "metadata": {
            "last_verified": "2026-06",
            "source": "manual_verified",
            "status": "needs_verification"
        },
        "free_delivery_threshold": 200,
        "milestones": []
    },
    "jiomart": {
        # TODO: Add JioMart thresholds, delivery rules, discounts, and milestones
        "metadata": {
            "last_verified": "2026-06",
            "source": "manual_verified",
            "status": "todo"
        },
        "free_delivery_threshold": None,
        "milestones": []
    }
}


def get_store_benefits(store: str) -> dict:
    """
    Retrieve the benefits configuration for a specific store.
    
    Args:
        store (str): The lowercase name of the store (e.g., 'zepto').
        
    Returns:
        dict: The store benefits configuration, or None if the store is not registered.
    """
    if not store:
        return None
    return STORE_BENEFITS.get(store.lower())


def get_next_milestone(store: str, cart_total: float) -> dict:
    """
    Find the next milestone that the cart_total is currently below.
    
    Args:
        store (str): The name of the store.
        cart_total (float): The current total of the cart.
        
    Returns:
        dict: The next milestone dictionary, or None if there are no further milestones.
    """
    benefits = get_store_benefits(store)
    if not benefits or not benefits.get("milestones"):
        return None
    
    # Milestones are expected to be sorted by threshold
    for milestone in benefits["milestones"]:
        if cart_total < milestone["threshold"]:
            return milestone
            
    return None


def get_remaining_amount(store: str, cart_total: float) -> float:
    """
    Calculate the amount remaining to reach the next milestone.
    
    Args:
        store (str): The name of the store.
        cart_total (float): The current total of the cart.
        
    Returns:
        float: The remaining amount required to reach the next milestone,
               or 0.0 if no next milestone is available.
    """
    next_milestone = get_best_next_benefit(store, cart_total)
    if not next_milestone:
        return 0.0
        
    return max(next_milestone["threshold"] - cart_total, 0.0)


def get_unlocked_benefits(store: str, cart_total: float) -> list:
    """
    Retrieve all benefits that have been unlocked based on the current cart_total.
    
    Args:
        store (str): The name of the store.
        cart_total (float): The current total of the cart.
        
    Returns:
        list: A list of unlocked milestone dictionaries.
    """
    benefits = get_store_benefits(store)
    if not benefits:
        return []
        
    unlocked = []
    
    # Check free delivery threshold
    fd_threshold = benefits.get("free_delivery_threshold")
    if fd_threshold is not None and cart_total >= fd_threshold:
        unlocked.append({
            "threshold": fd_threshold,
            "type": "free_delivery",
            "category": "delivery",
            "value": 0,
            "description": "Free Delivery"
        })
        
    for milestone in benefits.get("milestones", []):
        if cart_total >= milestone["threshold"]:
            unlocked.append(milestone)
            
    return unlocked


def get_best_next_benefit(store: str, cart_total: float) -> dict:
    """
    Determine the best (closest and most relevant) next benefit the user can unlock.
    This dynamically checks both the free delivery threshold (if not yet met)
    and any upcoming discount/promotional milestones, returning the closest one.
    
    Args:
        store (str): The name of the store.
        cart_total (float): The current total of the cart.
        
    Returns:
        dict: The next best benefit milestone, or None if no benefits remain to unlock.
    """
    benefits = get_store_benefits(store)
    if not benefits:
        return None
        
    candidates = []
    
    # 1. Check free delivery threshold
    fd_threshold = benefits.get("free_delivery_threshold")
    if fd_threshold is not None and cart_total < fd_threshold:
        candidates.append({
            "threshold": fd_threshold,
            "type": "free_delivery",
            "category": "delivery",
            "value": 0,
            "description": "Free Delivery"
        })
        
    # 2. Check upcoming milestones
    for milestone in benefits.get("milestones", []):
        if cart_total < milestone["threshold"]:
            candidates.append(milestone)
            
    if not candidates:
        return None
        
    # Sort candidates by threshold to find the closest one
    candidates.sort(key=lambda x: x["threshold"])
    return candidates[0]
