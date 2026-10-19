# agent.py
# Gem Arena v2 submission
# 单文件、Python 3.12 标准库、无 stdout 调试输出。
# 适配 gem-arena-2.0：main / discard / noble 三阶段，六维筹码，黄金、预留、贵族。


def choose(observation, memory):
    try:
        if not isinstance(observation, dict):
            return {"action": 0, "memory": None}

        legal = observation.get("legal_actions")
        if isinstance(legal, tuple):
            legal = list(legal)

        if not isinstance(legal, list) or len(legal) == 0:
            return {"action": 0, "memory": None}

        phase = str(observation.get("phase", "main")).strip().lower()

        if phase == "discard":
            idx = _choose_discard(observation, legal)
        elif phase == "noble":
            idx = _choose_noble(observation, legal)
        else:
            idx = _choose_main(observation, legal)

        try:
            idx = int(idx)
        except Exception:
            idx = 0

        if idx < 0 or idx >= len(legal):
            idx = 0

        return {"action": idx, "memory": None}

    except Exception:
        # 任何异常都不能导致 crash。
        return {"action": 0, "memory": None}


def _choose_main(observation, legal):
    ctx = _build_context(observation)
    if ctx is None:
        return _fallback_legal(legal, "main")

    # 如果回合剩余时间非常低，退化为安全优先级，避免超时。
    try:
        rem = observation.get("time_remaining_ms")
        if rem is not None and float(rem) < 90.0:
            return _fallback_legal(legal, "main")
    except Exception:
        pass

    best_idx = 0
    best_score = -10**100

    for i, action in enumerate(legal):
        typ = _action_type(action)

        if typ == "buy":
            score = _score_buy(action, ctx)
        elif typ == "take":
            score = _score_take(action, ctx)
        elif typ == "reserve":
            score = _score_reserve(action, ctx)
        elif typ == "pass":
            score = -100000.0
        else:
            score = -50000.0

        # 极小 tie-break，保证稳定。
        score -= i * 0.000001

        if score > best_score:
            best_score = score
            best_idx = i

    return best_idx


def _choose_discard(observation, legal):
    ctx = _build_context(observation)
    if ctx is None:
        return 0

    best_idx = 0
    best_score = -10**100

    for i, action in enumerate(legal):
        if isinstance(action, dict):
            discard = _vec(action.get("tokens"), 6)
        else:
            discard = [0, 0, 0, 0, 0, 0]

        after = [ctx["my_tokens"][j] - discard[j] for j in range(6)]
        for j in range(6):
            if after[j] < 0:
                after[j] = 0

        score = _token_retention_score(after, ctx)
        score -= i * 0.000001

        if score > best_score:
            best_score = score
            best_idx = i

    return best_idx


def _choose_noble(observation, legal):
    ctx = _build_context(observation)
    if ctx is None:
        return 0

    best_idx = 0
    best_score = -10**100

    for i, action in enumerate(legal):
        score = 1000.0

        if isinstance(action, dict):
            noble_id = action.get("noble")
            noble = ctx["noble_by_id"].get(noble_id)

            if noble is not None:
                req = _vec(noble.get("requirements"), 5)

                opp_missing = 0
                for j in range(5):
                    d = req[j] - ctx["opp_bonuses"][j]
                    if d > 0:
                        opp_missing += d

                # 贵族本身都是 +3，若对手也接近这个贵族，则优先拿走产生阻断价值。
                score += max(0, 7 - opp_missing) * 36.0

        score -= i * 0.000001

        if score > best_score:
            best_score = score
            best_idx = i

    return best_idx


def _build_context(observation):
    try:
        me = _seat(observation)

        players = observation.get("players")
        if not isinstance(players, (list, tuple)) or len(players) < 2:
            return None

        my = players[me] if isinstance(players[me], dict) else {}
        opp = players[1 - me] if isinstance(players[1 - me], dict) else {}

        my_tokens = _vec(my.get("tokens"), 6)
        my_bonuses = _vec(my.get("bonuses"), 5)
        my_score = _int(my.get("score"), 0)

        opp_tokens = _vec(opp.get("tokens"), 6)
        opp_bonuses = _vec(opp.get("bonuses"), 5)
        opp_score = _int(opp.get("score"), 0)

        bank = _vec(observation.get("bank"), 6)
        market_cards = _cards_from_market(observation.get("market"))

        reserved_entries = my.get("reserved")
        reserved_count = 0
        my_reserved_cards = []

        if isinstance(reserved_entries, (list, tuple)):
            reserved_count = len(reserved_entries)
            for entry in reserved_entries:
                if isinstance(entry, dict):
                    card = entry.get("card")
                    if isinstance(card, dict):
                        my_reserved_cards.append(card)

        nobles = []
        raw_nobles = observation.get("nobles")
        if isinstance(raw_nobles, (list, tuple)):
            for n in raw_nobles:
                if isinstance(n, dict):
                    nobles.append(n)

        noble_by_id = {}
        for n in nobles:
            nid = n.get("id")
            if nid is not None:
                noble_by_id[nid] = n

        candidate_cards = []
        seen = set()

        for card in market_cards + my_reserved_cards:
            if not isinstance(card, dict):
                continue
            cid = card.get("id")
            if cid is None:
                candidate_cards.append(card)
            elif cid not in seen:
                seen.add(cid)
                candidate_cards.append(card)

        target = _int(observation.get("target"), 15)

        points_w = 125.0
        if opp_score >= target - 4:
            points_w += 55.0
        if my_score < opp_score:
            points_w += 18.0

        token_color_value, bonus_color_value = _color_values(
            candidate_cards,
            my_bonuses,
            nobles
        )

        card_info_by_id = {}
        infos = []

        for card in candidate_cards:
            value = _card_future_value(
                card,
                my_bonuses,
                nobles,
                bonus_color_value,
                points_w
            )
            gap = _gap(card, my_tokens, my_bonuses)
            cost = _vec(card.get("cost"), 5)

            req_total = 0
            for i in range(5):
                r = cost[i] - my_bonuses[i]
                if r > 0:
                    req_total += r

            attract = value - gap * 55.0 - req_total * 3.0

            info = {
                "card": card,
                "id": card.get("id"),
                "value": value,
                "gap": gap,
                "attract": attract,
            }

            infos.append(info)

            cid = card.get("id")
            if cid is not None:
                card_info_by_id[cid] = info

        infos.sort(key=lambda x: x["attract"], reverse=True)
        top_targets = infos[:10]

        return {
            "my_tokens": my_tokens,
            "my_bonuses": my_bonuses,
            "my_score": my_score,
            "opp_tokens": opp_tokens,
            "opp_bonuses": opp_bonuses,
            "opp_score": opp_score,
            "bank": bank,
            "nobles": nobles,
            "noble_by_id": noble_by_id,
            "reserved_count": reserved_count,
            "token_color_value": token_color_value,
            "bonus_color_value": bonus_color_value,
            "top_targets": top_targets,
            "card_info_by_id": card_info_by_id,
            "target": target,
            "points_w": points_w,
        }

    except Exception:
        return None


def _score_buy(action, ctx):
    if not isinstance(action, dict):
        return 100.0

    cid = action.get("card")
    info = ctx["card_info_by_id"].get(cid)

    if info is None:
        return 150.0

    card = info["card"]
    payment = _vec(action.get("payment"), 6)

    after_tokens = [ctx["my_tokens"][i] - payment[i] for i in range(6)]
    for i in range(6):
        if after_tokens[i] < 0:
            after_tokens[i] = 0

    points = _int(card.get("points"), 0)
    bonus = _int(card.get("bonus"), 0)

    after_bonuses = ctx["my_bonuses"].copy()
    if 0 <= bonus < 5:
        after_bonuses[bonus] += 1

    score = 120.0 + points * ctx["points_w"]

    # 新永久折扣的价值：帮助后续购牌，以及推进贵族。
    if 0 <= bonus < 5:
        score += _noble_progress_value(bonus, ctx["my_bonuses"], ctx["nobles"])
        score += ctx["bonus_color_value"][bonus] * 0.9

    # 购买后若立即满足贵族，会在同一回合 noble 阶段 +3。
    eligible = 0
    for noble in ctx["nobles"]:
        req = _vec(noble.get("requirements"), 5)
        ok = True
        for i in range(5):
            if after_bonuses[i] < req[i]:
                ok = False
                break
        if ok:
            eligible += 1

    if eligible > 0:
        score += 320.0 + (eligible - 1) * 40.0

    potential_score = ctx["my_score"] + points + (3 if eligible > 0 else 0)
    if potential_score >= ctx["target"]:
        score += 12000.0

    # 支付成本：黄金很值钱，高需求颜色也更值钱。
    penalty = payment[5] * 30.0
    for i in range(5):
        penalty += payment[i] * ctx["token_color_value"][i] * 0.65

    score -= penalty

    # 购买后仍保留的筹码略有一点灵活性价值。
    score += after_tokens[5] * 3.0
    for i in range(5):
        score += after_tokens[i] * ctx["token_color_value"][i] * 0.04

    # 买自己的预留牌可以释放预留位，并兑现此前规划。
    if action.get("source") == "reserved":
        score += 28.0

    return score


def _score_take(action, ctx):
    if not isinstance(action, dict):
        return 50.0

    add = _vec(action.get("tokens"), 6)

    # take 不应拿黄金，但为了安全强制黄金位为 0。
    add[5] = 0

    temp = [ctx["my_tokens"][i] + add[i] for i in range(6)]
    excess = sum(temp) - 10

    if excess > 0:
        final_tokens = _best_final_tokens(temp, excess, ctx)
    else:
        final_tokens = temp

    score = 85.0

    # 即时颜色价值。
    for i in range(5):
        score += add[i] * ctx["token_color_value"][i] * 0.75

    # 对当前最优目标牌的逼近程度。
    for info in ctx["top_targets"][:8]:
        before = info["gap"]
        after = _gap(info["card"], final_tokens, ctx["my_bonuses"])
        reduction = before - after

        if reduction > 0:
            score += reduction * 48.0

            # 如果这次拿币后就能买这张目标牌，加成。
            if after == 0 and before > 0:
                score += max(0.0, info["value"]) * 0.28 + 150.0

    if excess > 0:
        score -= excess * 10.0

    return score


def _score_reserve(action, ctx):
    if not isinstance(action, dict):
        return 20.0

    gold_gain = 1 if ctx["bank"][5] > 0 else 0
    reserved_count = ctx["reserved_count"]

    if action.get("source") == "market":
        cid = action.get("card")
        info = ctx["card_info_by_id"].get(cid)

        if info is None:
            return 25.0

        value = info["value"]
        gap = info["gap"]

        # 预留得到的黄金可以降低未来支付缺口。
        effective_gap = gap
        if gold_gain and effective_gap > 0:
            effective_gap -= 1

        score = 75.0
        score += value * 0.5
        score -= effective_gap * 18.0
        score += gold_gain * 36.0
        score -= reserved_count * 30.0

        # 如果现在就能买，通常购买优于预留。
        if gap == 0:
            score -= 45.0

        if gold_gain:
            temp = ctx["my_tokens"].copy()
            temp[5] += 1
            excess = sum(temp) - 10

            if excess > 0:
                final_tokens = _best_final_tokens(temp, excess, ctx)
            else:
                final_tokens = temp

            before_retention = _token_retention_score(ctx["my_tokens"], ctx)
            after_retention = _token_retention_score(final_tokens, ctx)
            score += (after_retention - before_retention) * 0.20

        return score

    # source == 'deck'：盲抽预留。
    tier = _int(action.get("tier"), 1)

    if tier == 1:
        tier_value = 22.0
    elif tier == 2:
        tier_value = 42.0
    elif tier == 3:
        tier_value = 65.0
    else:
        tier_value = 22.0

    score = 18.0
    score += tier_value
    score += gold_gain * 48.0
    score -= reserved_count * 38.0

    # 没有黄金时，盲抽价值明显下降。
    if gold_gain == 0:
        score -= 30.0

    return score


def _token_retention_score(tokens, ctx):
    score = tokens[5] * 48.0

    for i in range(5):
        score += tokens[i] * ctx["token_color_value"][i] * 0.75

    # 保留的筹码应尽量服务近期目标牌。
    for info in ctx["top_targets"][:6]:
        score -= _gap(info["card"], tokens, ctx["my_bonuses"]) * 24.0

    return score


def _best_final_tokens(tokens, excess, ctx):
    try:
        total = int(excess)
    except Exception:
        total = 0

    if total <= 0:
        return tokens

    limits = [max(0, int(tokens[i])) for i in range(6)]
    cap = sum(limits)

    if total > cap:
        total = cap

    if total <= 0:
        return tokens

    # 正常 v2 主行动导致的超额很小；若异常过大，用贪心避免组合爆炸。
    if total > 5:
        return _greedy_discard(tokens, total, ctx)

    best = None
    best_score = -10**100

    for vec in _discard_vectors(limits, total):
        after = [tokens[i] - vec[i] for i in range(6)]
        score = _token_retention_score(after, ctx)

        if score > best_score:
            best_score = score
            best = after

    if best is None:
        return tokens

    return best


def _greedy_discard(tokens, excess, ctx):
    after = tokens.copy()

    for _ in range(excess):
        best_i = -1
        best_val = None

        for i in range(6):
            if after[i] <= 0:
                continue

            if i == 5:
                val = 48.0
            else:
                val = ctx["token_color_value"][i]

            if best_val is None or val < best_val:
                best_val = val
                best_i = i

        if best_i < 0:
            break

        after[best_i] -= 1

    return after


def _discard_vectors(limits, total):
    if total <= 0:
        yield [0] * len(limits)
        return

    def visit(i, left, prefix):
        if i == len(limits) - 1:
            if 0 <= left <= limits[i]:
                yield prefix + [left]
            return

        max_n = min(limits[i], left)
        for n in range(max_n + 1):
            yield from visit(i + 1, left - n, prefix + [n])

    yield from visit(0, total, [])


def _card_future_value(card, bonuses, nobles, bonus_color_value, points_w):
    points = _int(card.get("points"), 0)
    bonus = _int(card.get("bonus"), 0)
    tier = _int(card.get("tier"), 1)
    cost = _vec(card.get("cost"), 5)

    value = points * points_w

    if 0 <= bonus < 5:
        value += _noble_progress_value(bonus, bonuses, nobles)
        value += bonus_color_value[bonus] * 0.85

    req_total = 0
    for i in range(5):
        r = cost[i] - bonuses[i]
        if r > 0:
            req_total += r

    value -= req_total * 5.0
    value += (tier - 1) * 7.0

    return value


def _noble_progress_value(color, bonuses, nobles):
    if color < 0 or color >= 5:
        return 0.0

    total = 0.0

    for noble in nobles:
        req = _vec(noble.get("requirements"), 5)

        before = 0
        after = 0

        for i in range(5):
            r = req[i]
            b = bonuses[i]

            if r > b:
                before += r - b

            ab = b + (1 if i == color else 0)
            if r > ab:
                after += r - ab

        improvement = before - after
        if improvement > 0:
            total += improvement * 160.0 / (after + 1.0)

    return total


def _gap(card, tokens, bonuses):
    """
    估算购买这张牌还缺多少“有效代币”。
    先扣本色折扣，再用手上的普通代币，最后用黄金补缺口。
    """
    cost = _vec(card.get("cost"), 5)

    missing = 0
    for i in range(5):
        need = cost[i] - bonuses[i]
        if need > 0:
            d = need - tokens[i]
            if d > 0:
                missing += d

    gold = tokens[5]
    if gold <= 0:
        return missing

    return max(0, missing - gold)


def _color_values(cards, bonuses, nobles):
    demand = [0.0, 0.0, 0.0, 0.0, 0.0]
    bonus_demand = [0.0, 0.0, 0.0, 0.0, 0.0]

    for card in cards:
        cost = _vec(card.get("cost"), 5)
        points = _int(card.get("points"), 0)
        tier = _int(card.get("tier"), 1)

        weight = 1.0 + points * 2.0 + (tier - 1) * 1.0

        for i in range(5):
            need = cost[i] - bonuses[i]
            if need > 0:
                demand[i] += need * weight

            bonus_demand[i] += cost[i] * weight

    for noble in nobles:
        req = _vec(noble.get("requirements"), 5)
        for i in range(5):
            bonus_demand[i] += req[i] * 8.0

    max_demand = max(demand)
    max_bonus_demand = max(bonus_demand)

    token_value = []
    bonus_value = []

    for i in range(5):
        if max_demand > 0:
            token_value.append(6.0 + 18.0 * (demand[i] / max_demand))
        else:
            token_value.append(6.0)

        if max_bonus_demand > 0:
            bonus_value.append(8.0 + 30.0 * (bonus_demand[i] / max_bonus_demand))
        else:
            bonus_value.append(8.0)

    return token_value, bonus_value


def _cards_from_market(market):
    cards = []

    def add_part(part):
        if isinstance(part, dict):
            cards.append(part)
        elif isinstance(part, (list, tuple)):
            for item in part:
                if isinstance(item, dict):
                    cards.append(item)

    if isinstance(market, (list, tuple)):
        for part in market:
            add_part(part)

    elif isinstance(market, dict):
        for key in ("0", "1", "2", 0, 1, 2, "tier1", "tier2", "tier3"):
            if key in market:
                add_part(market[key])

        if not cards:
            for value in market.values():
                add_part(value)

    return cards


def _fallback_legal(legal, phase):
    if phase in ("discard", "noble"):
        return 0

    for i, action in enumerate(legal):
        if _action_type(action) == "buy":
            return i

    for i, action in enumerate(legal):
        if _action_type(action) == "take":
            return i

    for i, action in enumerate(legal):
        if _action_type(action) == "reserve":
            return i

    return 0


def _action_type(action):
    if isinstance(action, dict):
        return str(action.get("type", "")).strip().lower()
    return ""


def _seat(observation):
    me = _int(observation.get("you"), -1)
    if me not in (0, 1):
        me = _int(observation.get("to_play"), 0)
    if me not in (0, 1):
        me = 0
    return me


def _int(x, default=0):
    if isinstance(x, bool):
        return int(x)
    try:
        return int(x)
    except Exception:
        return default


def _vec(x, length):
    out = [0] * length

    if isinstance(x, (list, tuple)):
        for i in range(length):
            if i < len(x):
                try:
                    v = int(x[i])
                    out[i] = v if v >= 0 else 0
                except Exception:
                    out[i] = 0

    return out