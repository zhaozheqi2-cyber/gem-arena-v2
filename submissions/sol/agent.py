"""Sol / Prism II -- standalone gem-arena-2.0 agent, Python stdlib only.

Bounded public-information beam search with gold, reservations and nobles.
Unknown cards are never reconstructed. No file/network/referee access.
"""
import heapq
import itertools
import time

DEPTH = 4
WIDTH = 18


def _vectors(limits, total):
    if total == 0:
        yield (0,) * len(limits)
        return
    def visit(i, left, prefix):
        if i == len(limits) - 1:
            if 0 <= left <= limits[i]:
                yield prefix + (left,)
            return
        for n in range(min(limits[i], left) + 1):
            yield from visit(i + 1, left - n, prefix + (n,))
    yield from visit(0, total, ())


def choose(observation, memory):
    if observation['version'] != 'gem-arena-2.0':
        raise ValueError('Prism II requires gem-arena-2.0')
    started = time.perf_counter()
    actions = observation['legal_actions']
    if len(actions) == 1 or observation.get('time_remaining_ms',3000.) < 150.:
        # An emergency legal response; never spend the last allowance on search.
        return {'action': 0, 'memory': None}
    me = observation['players'][observation['you']]
    opponent = observation['players'][1 - observation['you']]
    nobles = observation['nobles']
    market = [c for row in observation['market'] for c in row]
    owned_reservations = [r['card'] for r in me['reserved'] if r.get('card') is not None]
    cards = market + owned_reservations
    ids = {c['id']: j for j, c in enumerate(cards)}
    costs = [tuple(c['cost']) for c in cards]
    pts = [c['points'] for c in cards]
    bonus_colors = [c['bonus'] for c in cards]
    requirements = [tuple(n['requirements']) for n in nobles]
    all_nobles = (1 << len(nobles)) - 1
    initial_res = sum(1 << j for j in range(len(market), len(cards)))
    initial_t = tuple(me['tokens'])
    initial_b = tuple(me['bonuses'])
    supply = tuple(observation['bank'][k] + initial_t[k] for k in range(6))
    target = observation['target']
    pressure = max(me['score'], opponent['score'])
    point_weight = 1.55 + .035 * pressure
    engine_weight = max(.30, 1.30 - .055 * pressure)
    noble_order = sorted(range(len(nobles)), key=lambda j: (
        sum(max(0, r-b) for r, b in zip(requirements[j], opponent['bonuses'])),
        nobles[j]['id']))
    # Leave most of the shared turn allowance for startup, I/O and auxiliaries.
    remaining = max(0., observation.get('time_remaining_ms', 3000.)) / 1000.
    allowance = min(.70, max(.0, (remaining - .65) * .40))
    deadline = started + allowance
    evaluate_cache = {}

    def engine(b, color):
        return engine_weight * max(.12, 1. - .20 * b[color])

    def evaluate(t, b, bought, reserved, nmask, score, reward, blinds):
        if score >= target:
            return 700. + 3 * score + reward
        key = (t, b, bought, reserved, nmask, blinds)
        cached = evaluate_cache.get(key)
        if cached is None:
            opportunities = []
            gold = t[5]
            for j, cost in enumerate(costs):
                if bought >> j & 1:
                    continue
                deficits = [max(0, cost[k] - b[k] - t[k]) for k in range(5)]
                missing = max(0, sum(deficits) - gold)
                largest = max(deficits)
                distance = max((missing + 2) // 3, max(0., largest - gold - .45))
                # A blocked color may require gold or a future opponent payment.
                blocked = sum(max(0, cost[k] - b[k] - supply[k]) for k in range(5))
                distance += max(0, blocked - gold) * 1.25
                worth = point_weight * pts[j] + engine(b, bonus_colors[j])
                opportunities.append(worth / (1 + distance) ** 1.32)
            opportunities.sort(reverse=True)
            potential = sum(v*w for v, w in zip(opportunities, (.60, .20, .09)))
            noble_progress = []
            for j, req in enumerate(requirements):
                if nmask >> j & 1:
                    gap = sum(max(0, req[k] - b[k]) for k in range(5))
                    noble_progress.append(3 * point_weight / (1 + gap * .65) ** 1.45)
            noble_progress.sort(reverse=True)
            potential += sum(v*w for v, w in zip(noble_progress, (.8, .28, .10)))
            # Gold is flexible, but capacity is scarce and reservations cannot
            # be discarded. Keeping an unproductive hand has a small cost.
            liquidity = .11 * t[5] + .022 * sum(min(t[k], max(0, 4-b[k])) for k in range(5))
            liability = .075 * (reserved.bit_count() + blinds)
            cached = potential + liquidity - liability
            evaluate_cache[key] = cached
        return reward + cached

    def award(b, nmask):
        for j in noble_order:
            if nmask >> j & 1 and all(b[k] >= requirements[j][k] for k in range(5)):
                return nmask ^ (1 << j), nobles[j]['points']
        return nmask, 0

    def finish(state, depth):
        t, b, bought, reserved, nmask, score, reward, blinds = state
        old_score = score
        nmask, noble_points = award(b, nmask)
        if noble_points:
            score += noble_points
            reward += (.94 ** depth) * noble_points * point_weight
        if old_score < target <= score:
            reward += 300 * (.94 ** depth)
        base = (t, b, bought, reserved, nmask, score, reward, blinds)
        overflow = sum(t) - 10
        if overflow <= 0:
            return base
        best = None
        best_value = -float('inf')
        for discard in _vectors(t, overflow):
            kept = tuple(t[k]-discard[k] for k in range(6))
            candidate = (kept,) + base[1:]
            value = evaluate(*candidate)
            if value > best_value:
                best, best_value = candidate, value
        return best

    def transition(state, kind, arg, depth):
        t, b, bought, reserved, nmask, score, reward, blinds = state
        if kind == 'buy':
            j, pay = arg
            t = tuple(t[k]-pay[k] for k in range(6))
            nb = list(b)
            nb[bonus_colors[j]] += 1
            reward += (.94 ** depth) * (pts[j]*point_weight + engine(b, bonus_colors[j]))
            if score < target <= score + pts[j]:
                reward += 300 * (.94 ** depth)
            score += pts[j]
            b = tuple(nb)
            bought |= 1 << j
            reserved &= ~(1 << j)
        elif kind == 'take':
            t = tuple(t[k]+arg[k] for k in range(6))
        elif kind == 'reserve':
            if arg is None:
                blinds += 1
            else:
                reserved |= 1 << arg
            if supply[5] > t[5]:
                t = t[:5] + (t[5]+1,)
        return finish((t,b,bought,reserved,nmask,score,reward,blinds),depth)

    initial = (initial_t, initial_b, 0, initial_res, all_nobles, me['score'], 0., 0)
    phase = observation['phase']
    if phase == 'noble':
        by_id = {n['id']: j for j, n in enumerate(nobles)}
        index = min(range(len(actions)), key=lambda i: noble_order.index(by_id[actions[i]['noble']]))
        return {'action': index, 'memory': None}
    if phase == 'discard':
        def discard_value(i):
            kept = tuple(initial_t[k]-actions[i]['tokens'][k] for k in range(6))
            return evaluate(kept, *initial[1:])
        return {'action': max(range(len(actions)), key=discard_value), 'memory': None}

    root = []
    for index, action in enumerate(actions):
        kind = action['type']
        if kind == 'buy':
            arg = (ids[action['card']], tuple(action['payment']))
        elif kind == 'take':
            arg = tuple(action['tokens'])
        elif kind == 'reserve':
            arg = ids[action['card']] if action['source'] == 'market' else None
        else:
            arg = None
        new = transition(initial, kind, arg, 0)
        root.append((evaluate(*new), -index, new, index))

    # Exact score/card ranking for the last personal turn, including a noble.
    last = observation.get('end_triggered',False)
    cap = observation.get('max_turns',0)
    if cap and observation['turn'] >= cap - 2:
        # Reaching a safety cap without reaching target is a draw, not a win.
        last = last or any(item[2][5] >= target for item in root)
    wins = [item for item in root if item[2][5] >= target]
    if last or (observation['you'] == 1 and wins):
        pool = root if last else wins
        best = max(pool, key=lambda item:(item[2][5],-item[2][2].bit_count(),item[0],item[1]))
        return {'action': best[3], 'memory': None}

    # Opponent response: exact affordability for visible cards, then a greedy
    # acquisition threat estimate. Opponent blind reservations remain unknown.
    public_op_res = [r['card'] for r in opponent['reserved'] if r.get('card') is not None]
    enemy_b = opponent['bonuses']
    enemy_t = opponent['tokens']

    def response(item):
        _, _, state, index = item
        t,b,bought,reserved,nmask,score,_,_ = state
        enemy_cards = [c for j,c in enumerate(market) if not ((bought|reserved) >> j & 1)] + public_op_res
        best_rank = (opponent['score'], -len(opponent['cards']))
        if any(nmask >> j & 1 and all(enemy_b[k] >= requirements[j][k] for k in range(5)) for j in range(len(nobles))):
            best_rank = (opponent['score']+3, -len(opponent['cards']))
        threat = 0.
        enemy_bank = [supply[k]-t[k] for k in range(6)]

        def enemy_potential(tokens, bonuses, removed=None):
            best = 0.
            for candidate in enemy_cards:
                if candidate is removed:
                    continue
                missing = [max(0,candidate['cost'][k]-bonuses[k]-tokens[k]) for k in range(5)]
                gap = max(0,sum(missing)-tokens[5])
                distance = max((gap+2)//3,max(0,max(missing)-tokens[5]-.45))
                worth = candidate['points']*point_weight+engine(bonuses,candidate['bonus'])
                best = max(best,worth/(1+distance)**1.32)
            return best + .07*tokens[5]

        # Enumerate the opponent's visible immediate purchases and coin takes.
        # This is a one-response model; deeper own search still freezes them.
        threat = enemy_potential(enemy_t,enemy_b)
        available = [k for k in range(5) if enemy_bank[k]>0]
        n = min(3,len(available))
        if n:
            for combo in itertools.combinations(available,n):
                after = tuple(enemy_t[k]+int(k in combo) for k in range(6))
                threat = max(threat,enemy_potential(after,enemy_b))
        for k in range(5):
            if enemy_bank[k]>=4:
                after = tuple(enemy_t[i]+(2 if k==i else 0) for i in range(6))
                threat = max(threat,enemy_potential(after,enemy_b))
        if len(opponent['reserved'])<3 and enemy_bank[5]>0:
            after = tuple(enemy_t[:5])+(enemy_t[5]+1,)
            threat = max(threat,enemy_potential(after,enemy_b)-.10)
        for c in enemy_cards:
            deficit = [max(0,c['cost'][k]-enemy_b[k]-enemy_t[k]) for k in range(5)]
            gap = max(0,sum(deficit)-enemy_t[5])
            if gap == 0:
                nb = [enemy_b[k]+int(c['bonus']==k) for k in range(5)]
                noble = 3 if any(nmask >> j & 1 and all(nb[k]>=requirements[j][k] for k in range(5)) for j in range(len(nobles))) else 0
                best_rank = max(best_rank,(opponent['score']+c['points']+noble,-len(opponent['cards'])-1))
                pay = [min(enemy_t[k],max(0,c['cost'][k]-enemy_b[k])) for k in range(5)]
                gold = sum(max(0,c['cost'][k]-enemy_b[k])-pay[k] for k in range(5))
                after = tuple(enemy_t[k]-pay[k] for k in range(5))+(enemy_t[5]-gold,)
                immediate = (c['points']+noble)*point_weight+engine(enemy_b,c['bonus'])
                threat = max(threat,immediate+.60*enemy_potential(after,nb,c))
        my_rank = (score,-len(me['cards'])-bought.bit_count())
        if observation['you'] == 0 and max(score,best_rank[0]) >= target and best_rank > my_rank:
            return -2000., threat
        return 0., threat

    adjusted = []
    for item in root:
        loss, threat = response(item)
        # Constant root penalty persists across hypothetical own turns.
        state = list(item[2])
        state[6] += loss - .18 * threat
        state = tuple(state)
        adjusted.append((evaluate(*state),item[1],state,item[3]))
    beam = heapq.nlargest(WIDTH, adjusted)
    best_index = beam[0][3]
    if allowance <= .025:
        return {'action': int(best_index), 'memory': None}

    for depth in range(1, DEPTH):
        expanded = {}
        interrupted = False
        for item in beam:
            if time.perf_counter() >= deadline:
                interrupted = True
                break
            _, _, state, first = item
            t,b,bought,reserved,nmask,score,reward,blinds = state
            moves = []
            if score < target:
                for j,cost in enumerate(costs):
                    if bought >> j & 1:
                        continue
                    need = tuple(max(0,cost[k]-b[k]) for k in range(5))
                    colored = tuple(min(need[k],t[k]) for k in range(5))
                    forced = sum(need)-sum(colored)
                    if forced <= t[5]:
                        moves.append(('buy',(j,colored+(forced,))))
                        # Limited voluntary substitutions retain useful colors;
                        # the root still evaluates every referee payment option.
                        if forced < t[5]:
                            for k in range(5):
                                if colored[k]:
                                    pay = list(colored)+( [forced] )
                                    pay[k] -= 1
                                    pay[5] += 1
                                    moves.append(('buy',(j,tuple(pay))))
                bank = [supply[k]-t[k] for k in range(6)]
                available = [k for k in range(5) if bank[k]>0]
                n = min(3,len(available))
                if n:
                    for combo in itertools.combinations(available,n):
                        moves.append(('take',tuple(int(k in combo) for k in range(6))))
                for k in range(5):
                    if bank[k]>=4:
                        moves.append(('take',tuple(2 if k==i else 0 for i in range(6))))
                if reserved.bit_count()+blinds < 3 and bank[5]>0:
                    for j in range(len(market)):
                        if not ((bought|reserved) >> j & 1):
                            moves.append(('reserve',j))
            if not moves:
                moves = [('pass',None)]
            for kind,arg in moves:
                new = transition(state,kind,arg,depth)
                key = new[:6]+new[7:]
                value = evaluate(*new)
                candidate = (value,-first,new,first)
                if key not in expanded or candidate[:2] > expanded[key][:2]:
                    expanded[key] = candidate
        # Only commit complete layers: partial layers bias action ordering.
        if interrupted or not expanded:
            break
        beam = heapq.nlargest(WIDTH,expanded.values())
        best_index = beam[0][3]
    return {'action': int(best_index), 'memory': None}
