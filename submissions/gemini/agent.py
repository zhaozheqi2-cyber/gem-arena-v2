"""
Splendor AI Agent - V2 (Gem Arena 2.0 Base Rules)
"""

from typing import Dict, Any, Optional

def choose(observation: Dict[str, Any], memory: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    assert observation['version'] == 'gem-arena-2.0'
    
    actions = observation.get("legal_actions", [])
    if not actions:
        return {"action": 0, "memory": memory}
    if len(actions) == 1:
        return {"action": 0, "memory": memory}

    my_idx = observation["you"]
    me = observation["players"][my_idx]
    
    market_cards = [c for row in observation["market"] for c in row]
    my_reserved = [r["card"] for r in me["reserved"] if r.get("card")]
    all_visible_cards = market_cards + my_reserved
    
    def calculate_missing_tokens(card: Dict[str, Any], current_tokens: list) -> int:
        missing_colors = sum(max(0, card["cost"][i] - me["bonuses"][i] - current_tokens[i]) for i in range(5))
        return max(0, missing_colors - current_tokens[5])

    def card_desirability(card: Dict[str, Any]) -> float:
        vp_value = card["points"] * 20.0
        
        # 提取变量，绕过解析器嵌套括号 bug
        bonus_idx = card["bonus"]
        my_bonus_amt = me["bonuses"][bonus_idx]
        
        engine_value = 15.0 / (1.0 + my_bonus_amt)
        
        noble_synergy = 0.0
        for n in observation["nobles"]:
            req = n["requirements"]
            if req[bonus_idx] > my_bonus_amt:
                noble_synergy += 12.0
                
        dist = calculate_missing_tokens(card, me["tokens"])
        
        return vp_value + engine_value + noble_synergy - (dist * 7.0)

    top_targets = sorted(all_visible_cards, key=card_desirability, reverse=True)[:5]

    def evaluate_action(action: Dict[str, Any]) -> float:
        a_type = action["type"]
        
        if a_type == "noble":
            return 10000.0
            
        if a_type == "discard":
            after_tokens = [me["tokens"][i] - action["tokens"][i] for i in range(6)]
            hurt = 0.0
            for c in top_targets:
                gap_before = calculate_missing_tokens(c, me["tokens"])
                gap_after = calculate_missing_tokens(c, after_tokens)
                hurt += (gap_after - gap_before) * (15.0 + c["points"] * 5.0)
            
            gold_discarded = action["tokens"][5]
            return -hurt - (gold_discarded * 100.0)
            
        if a_type == "buy":
            card = next((c for c in all_visible_cards if c["id"] == action["card"]), None)
            if not card: return -9999.0
            
            vp = card["points"]
            if me["score"] + vp >= 15:
                return 100000.0 + vp * 1000.0 - sum(action["payment"])
                
            score = 50.0 + vp * 40.0
            
            # 提取变量，绕过解析器嵌套括号 bug
            bonus_idx = card["bonus"]
            my_bonus_amt = me["bonuses"][bonus_idx]
            
            for n in observation["nobles"]:
                before = sum(max(0, n["requirements"][i] - me["bonuses"][i]) for i in range(5))
                after = sum(max(0, n["requirements"][i] - me["bonuses"][i] - (1 if i == bonus_idx else 0)) for i in range(5))
                score += (before - after) * 15.0
                
            score += 15.0 / (1.0 + my_bonus_amt)
            
            score -= action["payment"][5] * 12.0
            score -= sum(action["payment"][:5]) * 2.0
            
            if action.get("source") == "reserved":
                score += 10.0
                
            return score
            
        if a_type == "take":
            after_tokens = [me["tokens"][i] + action["tokens"][i] for i in range(6)]
            benefit = 0.0
            
            for c in top_targets:
                gap_before = calculate_missing_tokens(c, me["tokens"])
                gap_after = calculate_missing_tokens(c, after_tokens)
                benefit += (gap_before - gap_after) * (15.0 + c["points"] * 8.0)
            
            score = benefit
            
            total_after = sum(after_tokens)
            if total_after > 10:
                score -= (total_after - 10) * 20.0
                
            return score
            
        if a_type == "reserve":
            gold_gained = 1 if observation["bank"][5] > 0 else 0
            
            if action["source"] == "deck":
                return -10.0 + gold_gained * 12.0
                
            card = next((c for c in market_cards if c["id"] == action["card"]), None)
            if not card: return -9999.0
            
            vp = card["points"]
            dist = calculate_missing_tokens(card, me["tokens"])
            
            score = vp * 12.0 - dist * 3.0 + gold_gained * 18.0
            score -= len(me["reserved"]) * 25.0
            return score
            
        if a_type == "pass":
            return -99999.0
            
        return 0.0

    best_idx = 0
    best_score = -float('inf')
    for i, a in enumerate(actions):
        s = evaluate_action(a)
        if s > best_score:
            best_score = s
            best_idx = i
            
    return {"action": best_idx, "memory": memory}