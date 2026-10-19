"""Gem Arena v2 Agent —— 多阶段启发式评分

适配 gem-arena-2.0：
- 六维 tokens（含 gold），五维 bonuses / cost / requirements
- phase: main / discard / noble
- buy 带 source 和 payment（六维），同一张牌多种支付是不同索引
- 新增 reserve / discard / noble；移除 return 和随意 pass

策略：
1. main：buy / take / reserve 统一打分，选净收益最高者
2. discard：退回价值最低的筹码（低需求颜色优先，黄金最后）
3. noble：都是 3 分，选第一个

不使用 memory，纯确定性；异常时返回 0，绝不崩溃。
"""

VERSION_OK = 'gem-arena-2.0'


def choose(observation, memory):
    try:
        return _choose(observation, memory)
    except Exception:
        return {'action': 0, 'memory': None}


def _choose(obs, memory):
    if not isinstance(obs, dict) or obs.get('version') != VERSION_OK:
        return {'action': 0, 'memory': None}
    actions = obs.get('legal_actions') or []
    if not actions:
        return {'action': 0, 'memory': None}
    phase = obs.get('phase', 'main')
    if phase == 'discard':
        return {'action': _choose_discard(obs, actions), 'memory': None}
    if phase == 'noble':
        return {'action': 0, 'memory': None}
    return {'action': _choose_main(obs, actions), 'memory': None}


# ---------------- main ----------------

def _choose_main(obs, actions):
    me = obs['players'][obs['you']]
    opp = obs['players'][1 - obs['you']]
    my_tokens = list(me['tokens'])
    my_bonus = list(me['bonuses'])
    my_score = me['score']
    opp_score = opp['score']
    turn = obs.get('turn', 0)
    end_triggered = bool(obs.get('end_triggered'))

    market_cards = [c for row in obs['market'] for c in row]
    market_by_id = {c['id']: c for c in market_cards}
    my_reserved_cards = [r['card'] for r in me['reserved'] if r.get('card')]
    reserved_by_id = {c['id']: c for c in my_reserved_cards}
    demand = _estimate_demand(market_cards, my_reserved_cards)
    nobles = obs.get('nobles', [])

    best_i = 0
    best_v = -1e18
    for i, a in enumerate(actions):
        t = a.get('type')
        if t == 'buy':
            cid = a['card']
            card = reserved_by_id.get(cid) or market_by_id.get(cid)
            if card is None:
                continue
            v = _score_buy(card, a['payment'], a.get('source'),
                           my_bonus, my_score, opp_score,
                           demand, nobles, turn, end_triggered)
        elif t == 'take':
            v = _score_take(a['tokens'], my_tokens, my_bonus,
                            market_cards, my_reserved_cards, demand)
        elif t == 'reserve':
            v = _score_reserve(a, obs, me, opp, market_by_id, demand, turn)
        else:
            v = -500.0
        if v > best_v:
            best_v = v
            best_i = i
    return best_i


def _score_buy(card, payment, source, my_bonus, my_score, opp_score,
               demand, nobles, turn, end_triggered):
    pts = card['points']
    v = pts * 14.0

    # 终局冲刺
    if my_score + pts >= 15:
        v += 800.0
    elif end_triggered or my_score >= 12:
        v += pts * 6.0

    # 折扣价值
    v += demand[card['bonus']] * 5.0

    # 早期 1 级牌是折扣主力
    if card['tier'] == 1 and turn < 24:
        v += 4.0

    # 贵族进度
    new_bonus = list(my_bonus)
    new_bonus[card['bonus']] += 1
    v += _noble_gain(nobles, my_bonus, new_bonus) * 10.0

    # 支付成本：黄金昂贵、彩色便宜
    gold = payment[5]
    colored = sum(payment[:5])
    v -= gold * 3.5
    v -= colored * 0.15

    # 买预留牌能释放一个预留位
    if source == 'reserved':
        v += 1.0

    return v


def _score_take(tokens, my_tokens, my_bonus, market_cards, my_reserved_cards, demand):
    new_tokens = [t + n for t, n in zip(my_tokens, tokens)]
    new_total = sum(new_tokens)
    v = 0.0
    targets = list(market_cards) + list(my_reserved_cards)
    for c in targets:
        old_s = _shortfall(c, my_tokens, my_bonus)
        new_s = _shortfall(c, new_tokens, my_bonus)
        gain = old_s - new_s
        if gain > 0:
            card_v = c['points'] * 14.0 + demand[c['bonus']] * 5.0 + 4.0
            v += gain * card_v / (new_s + 1) * 0.55

    # 超限会触发 discard，抑制
    if new_total > 10:
        v -= (new_total - 10) * 5.0
    elif new_total == 10:
        v -= 1.5
    return v


def _score_reserve(a, obs, me, opp, market_by_id, demand, turn):
    if len(me['reserved']) >= 3:
        return -1000.0
    gold_available = obs['bank'][5] > 0
    v = 0.0

    if a.get('source') == 'market':
        c = market_by_id.get(a['card'])
        if c is None:
            return -1000.0
        v += c['points'] * 1.5
        v += demand[c['bonus']] * 1.0
        v -= 1.5  # 占用预留位
        if gold_available:
            v += 2.5
        # 对手快能买 → 抢先
        opp_s = _shortfall(c, opp['tokens'], opp['bonuses'])
        if opp_s <= 1 and c['points'] >= 2:
            v += 5.0
        elif opp_s <= 2 and c['points'] >= 3:
            v += 3.0
        # 自己短期也买不起时，先囤着
        my_s = _shortfall(c, me['tokens'], me['bonuses'])
        if my_s >= 2 and c['points'] >= 3:
            v += 1.5
    else:  # deck 盲抽
        v = -0.5
        if gold_available:
            v += 2.0
        if a.get('tier') == 1 and turn < 10:
            v += 0.5
    return v


# ---------------- discard / noble ----------------

def _choose_discard(obs, actions):
    me = obs['players'][obs['you']]
    market_cards = [c for row in obs['market'] for c in row]
    my_reserved_cards = [r['card'] for r in me['reserved'] if r.get('card')]
    demand = _estimate_demand(market_cards, my_reserved_cards)

    best_i = 0
    best_v = -1e18
    for i, a in enumerate(actions):
        v = 0.0
        for j in range(5):
            v -= a['tokens'][j] * (demand[j] + 0.3)
        v -= a['tokens'][5] * 3.0
        if v > best_v:
            best_v = v
            best_i = i
    return best_i


# ---------------- helpers ----------------

def _estimate_demand(market_cards, reserved_cards):
    """每色需求，0~1 归一化。用当前市场和可见预留做样本。"""
    demand = [0.0] * 5
    for c in list(market_cards) + list(reserved_cards):
        total = sum(c['cost'])
        if total == 0:
            continue
        w = 1.0 + c['points'] * 0.8
        for i in range(5):
            n = c['cost'][i]
            if n > 0:
                demand[i] += w * n / total
    m = max(demand) if max(demand) > 0 else 1.0
    return [d / m for d in demand]


def _shortfall(card, tokens, bonus):
    """还差多少枚（把现有黄金算作万能）。"""
    need = [max(0, cost - b) for cost, b in zip(card['cost'], bonus)]
    used = [min(need[i], tokens[i]) for i in range(5)]
    remain = sum(need[i] - used[i] for i in range(5))
    return max(0, remain - tokens[5])


def _noble_gain(nobles, old_bonus, new_bonus):
    """买这张牌对任意贵族进度的加权贡献，接近完成时权重更高。"""
    best = 0.0
    for n in nobles:
        old_s = sum(max(0, r - b) for r, b in zip(n['requirements'], old_bonus))
        new_s = sum(max(0, r - b) for r, b in zip(n['requirements'], new_bonus))
        if old_s > new_s:
            best = max(best, (old_s - new_s) / (new_s + 1))
    return best