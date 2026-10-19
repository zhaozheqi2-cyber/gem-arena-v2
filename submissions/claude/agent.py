"""gem-arena-2.0 agent: iterative-deepening alpha-beta + transposition table.

Single file, Python 3.12 standard library only; no I/O. Every call is a fresh
process, so the whole state is rebuilt from the observation (memory unused).
The search models a full turn (main action + same-turn discard + noble pick)
as one move. Card refills and the opponent's blind reservations are unknown,
so refilled slots are treated as empty inside the search.
"""
import itertools
import time

T0 = time.perf_counter()        # process start (harness may reset this)
BUDGET_MAIN = 0.55              # seconds of search for the main action
BUDGET_AUX = 0.06               # discard / noble phases
RESERVE_MS = 1300.0             # time kept back for later calls of the same turn
DEBUG = False                   # re-raise internal errors (development only)

# ----------------------------------------------------------------- parameters
PT = 100.0        # value of one victory point
TOKV = 20.0       # value of one token still missing for a target card
TOKB = 6.0        # base value of holding a token
GOLDV = 14.0      # extra value of a gold token (flexible)
DISC = 90.0       # value of the first discount in a colour (early game)
NOBLEV = 300.0    # value of a noble at zero distance (scaled by progress)
RESB = 25.0       # bonus for a target that is already safely reserved
FLEX = 12.0       # penalty per token held above 8 (forces discards)
SHORT = 1.5       # extra missing-token cost for needs the bank cannot cover
SECOND = 0.35     # weight of the second-best target
TAKE_K_ROOT = 7
TAKE_K = 4
BIG = 100000.0
G = [0, 1.0, 1.8, 2.4, 2.8, 3.0] + [3.1] * 30

# state layout (flat list of ints); side 0 = the player we choose for
#  0-5 bank | 6-11 tokens0 | 12-17 tokens1 | 18-22 bonus0 | 23-27 bonus1
#  28,29 score | 30,31 #dev cards | 32-43 market slots (card idx / -1)
#  44-46 reserved0 | 47-49 reserved1 (card idx, -1 empty, -2 unknown blind)
#  50-52 nobles left (noble idx / -1) | 53 ply | 54 done (1 target, 2 limit)
#  55 end triggered
MKT = 32
RES = 44
NOB = 50
PLY = 53
DONE = 54
END = 55

# per-call tables
PTS = []
BON = []
COST = []
VALUE = []
NREQ = []
NR0 = []
ROOT_TURN = 0
MAXT = 0
DEADLINE = 0.0
NODES = 0
TT = {}
USE_TT = True
LAST_INFO = {}

COMBOS = {}
for _mask in range(32):
    _av = [i for i in range(5) if _mask >> i & 1]
    _n = min(3, len(_av))
    COMBOS[_mask] = list(itertools.combinations(_av, _n)) if _n else []


class _Timeout(Exception):
    pass


# --------------------------------------------------------------- state / moves
def _auto_discard(t, m, n):
    """Remove n tokens: surplus colours first, gold last."""
    tb = 6 + 6 * m
    bb = 18 + 5 * m
    need = [0, 0, 0, 0, 0]
    cards = [t[MKT + k] for k in range(12)] + [t[RES + 3 * m + r] for r in range(3)]
    for ci in cards:
        if ci >= 0:
            c = COST[ci]
            for i in range(5):
                d = c[i] - t[bb + i]
                if d > need[i]:
                    need[i] = d
    for _ in range(n):
        bi = -1
        bk = -99
        for i in range(5):
            if t[tb + i] > 0:
                k = t[tb + i] - need[i]
                if k > bk:
                    bk = k
                    bi = i
        if bi >= 0:
            t[tb + bi] -= 1
            t[bi] += 1
        elif t[tb + 5] > 0:
            t[tb + 5] -= 1
            t[5] += 1


def _pick_noble(t, m, cand):
    """Among eligible noble slots choose the one the opponent is closest to."""
    ob = 18 + 5 * (1 - m)
    best = cand[0]
    bk = 99
    for j in cand:
        req = NREQ[t[j]]
        r = 0
        for i in range(5):
            d = req[i] - t[ob + i]
            if d > 0:
                r += d
        if r < bk:
            bk = r
            best = j
    return best


def apply(s, mv):
    t = s[:]
    ply = s[PLY]
    m = ply & 1
    tb = 6 + 6 * m
    bb = 18 + 5 * m
    kind = mv[0]
    if kind <= 1:
        if kind == 0:
            slot = MKT + mv[1]
        else:
            slot = RES + 3 * m + mv[1]
        ci = t[slot]
        t[slot] = -1
        cost = COST[ci]
        gold = 0
        for i in range(5):
            need = cost[i] - t[bb + i]
            if need > 0:
                have = t[tb + i]
                p = need if need <= have else have
                t[tb + i] = have - p
                t[i] += p
                gold += need - p
        if gold:
            t[tb + 5] -= gold
            t[5] += gold
        t[28 + m] += PTS[ci]
        t[bb + BON[ci]] += 1
        t[30 + m] += 1
    elif kind == 2:
        for i in mv[1]:
            t[tb + i] += 1
            t[i] -= 1
    elif kind == 3:
        i = mv[1]
        t[tb + i] += 2
        t[i] -= 2
    elif kind == 4:  # reserve a market card
        slot = MKT + mv[1]
        ci = t[slot]
        t[slot] = -1
        for r in range(3):
            if t[RES + 3 * m + r] == -1:
                t[RES + 3 * m + r] = ci
                break
        if t[5] > 0:
            t[5] -= 1
            t[tb + 5] += 1
    tot = t[tb] + t[tb + 1] + t[tb + 2] + t[tb + 3] + t[tb + 4] + t[tb + 5]
    if tot > 10:
        _auto_discard(t, m, tot - 10)
    if True:  # nobles are resolved after ANY main action
        cand = []
        for j in (NOB, NOB + 1, NOB + 2):
            ni = t[j]
            if ni >= 0:
                req = NREQ[ni]
                if (t[bb] >= req[0] and t[bb + 1] >= req[1] and t[bb + 2] >= req[2]
                        and t[bb + 3] >= req[3] and t[bb + 4] >= req[4]):
                    cand.append(j)
        if cand:
            j = cand[0] if len(cand) == 1 else _pick_noble(t, m, cand)
            t[j] = -1
            t[28 + m] += 3
    if t[28 + m] >= 15:
        t[END] = 1
    t[PLY] = ply + 1
    new_turn = ROOT_TURN + ply + 1
    if new_turn % 2 == 0:
        if t[END]:
            t[DONE] = 1
        elif MAXT and new_turn >= MAXT:
            t[DONE] = 2
    return t


def terminal_value(s):
    """Value for side 0 of a finished game (faster wins preferred)."""
    if s[DONE] == 2:
        return 0.0
    a = (s[28], -s[30])
    b = (s[29], -s[31])
    if a > b:
        return BIG - s[PLY]
    if b > a:
        return -BIG + s[PLY]
    return 0.0


def _targets(s, m):
    """Best two targets of side m: list of (net, card, need-vector)."""
    tb = 6 + 6 * m
    bb = 18 + 5 * m
    e = [s[tb + i] + s[bb + i] for i in range(5)]
    gold = s[tb + 5]
    score = s[28 + m]
    ph = 1.0 - score / 15.0
    if ph < 0.2:
        ph = 0.2
    dw = [DISC * ph * (G[s[bb + i] + 1] - G[s[bb + i]]) for i in range(5)]
    out = []
    cards = [(s[MKT + k], 0.0) for k in range(12)] + [(s[RES + 3 * m + r], RESB) for r in range(3)]
    for ci, bonus in cards:
        if ci < 0:
            continue
        cost = COST[ci]
        need = [cost[i] - e[i] if cost[i] > e[i] else 0 for i in range(5)]
        miss = need[0] + need[1] + need[2] + need[3] + need[4] - gold
        if miss < 0:
            miss = 0
        net = VALUE[ci] + dw[BON[ci]] + bonus - TOKV * miss
        out.append((net, ci, need))
    out.sort(key=lambda x: -x[0])
    return out[:2]


def _slot_of(s, ci):
    for k in range(12):
        if s[MKT + k] == ci:
            return k
    return -1


def gen_moves(s, take_k):
    m = s[PLY] & 1
    tb = 6 + 6 * m
    bb = 18 + 5 * m
    toks = s[tb:tb + 6]
    gold = toks[5]
    moves = []
    buys = []
    for src in range(15):
        if src < 12:
            ci = s[MKT + src]
            mv = (0, src)
        else:
            ci = s[RES + 3 * m + src - 12]
            mv = (1, src - 12)
        if ci < 0:
            continue
        cost = COST[ci]
        short = 0
        paid = 0
        for i in range(5):
            p = cost[i] - s[bb + i]
            if p > 0:
                paid += p
                if p > toks[i]:
                    short += p - toks[i]
        if short <= gold:
            buys.append((-(PTS[ci] * 10 - paid - 3 * short), mv))
    buys.sort()
    moves.extend(b[1] for b in buys)

    mask = 0
    for i in range(5):
        if s[i] > 0:
            mask |= 1 << i
    tgt = _targets(s, m)
    w = [0.1] * 5
    if tgt:
        n1 = tgt[0][2]
        for i in range(5):
            w[i] += 3.0 * n1[i]
        if len(tgt) > 1:
            n2 = tgt[1][2]
            for i in range(5):
                w[i] += 1.5 * n2[i]
    o = 1 - m
    otgt = _targets(s, o)
    if otgt:
        on = otgt[0][2]
        for i in range(5):
            if on[i] > 0 and s[i] <= 2:
                w[i] += 0.8
    takes = []
    for cmb in COMBOS[mask]:
        sc = 0.0
        for i in cmb:
            sc += w[i]
        takes.append((-sc, (2, cmb)))
    for i in range(5):
        if s[i] >= 4:
            takes.append((-(1.6 * w[i] + 0.3), (3, i)))
    takes.sort(key=lambda x: x[0])
    moves.extend(x[1] for x in takes[:take_k])

    # reservations of market cards: my own best target, or the opponent's
    if s[5] > 0 and (s[RES + 3 * m + 2] == -1 or s[RES + 3 * m] == -1 or s[RES + 3 * m + 1] == -1):
        seen = []
        for src in (tgt, otgt):
            if src:
                k = _slot_of(s, src[0][1])
                if k >= 0 and k not in seen:
                    seen.append(k)
                    moves.append((4, k))
    if not moves:
        moves.append((6,))
    return moves


def evaluate(s):
    """Heuristic value from side 0's point of view."""
    total = 0.0
    bank = s[0:5]
    b0, b1, b2, b3, b4 = bank
    mkt = [s[k] for k in range(MKT, MKT + 12) if s[k] >= 0]
    for m in (0, 1):
        tb = 6 + 6 * m
        bb = 18 + 5 * m
        t = s[tb:tb + 5]
        gold = s[tb + 5]
        b = s[bb:bb + 5]
        score = s[28 + m]
        tok = t[0] + t[1] + t[2] + t[3] + t[4] + gold
        ph = 1.0 - score / 15.0
        if ph < 0.2:
            ph = 0.2
        val = PT * score + TOKB * tok + GOLDV * gold
        dw = [0.0] * 5
        for i in range(5):
            bi = b[i]
            val += DISC * ph * G[bi]
            dw[i] = DISC * ph * (G[bi + 1] - G[bi])
        if tok > 8:
            val -= FLEX * (tok - 8)
        for j in (NOB, NOB + 1, NOB + 2):
            ni = s[j]
            if ni >= 0:
                req = NREQ[ni]
                r = 0
                for i in range(5):
                    d = req[i] - b[i]
                    if d > 0:
                        r += d
                f = 1.0 - r / NR0[ni]
                if f > 0:
                    val += NOBLEV * f * f
        e0 = t[0] + b[0]
        e1 = t[1] + b[1]
        e2 = t[2] + b[2]
        e3 = t[3] + b[3]
        e4 = t[4] + b[4]
        best1 = 0.0
        best2 = 0.0
        cards = mkt
        rs = [s[RES + 3 * m + r] for r in range(3)]
        for pass_no in (0, 1):
            if pass_no == 0:
                seq = cards
                rb = 0.0
            else:
                seq = [c for c in rs if c >= 0]
                rb = RESB
            for ci in seq:
                k0, k1, k2, k3, k4 = COST[ci]
                n0 = k0 - e0
                n1 = k1 - e1
                n2 = k2 - e2
                n3 = k3 - e3
                n4 = k4 - e4
                miss = 0
                blk = 0
                if n0 > 0:
                    miss += n0
                    if n0 > b0:
                        blk += n0 - b0
                if n1 > 0:
                    miss += n1
                    if n1 > b1:
                        blk += n1 - b1
                if n2 > 0:
                    miss += n2
                    if n2 > b2:
                        blk += n2 - b2
                if n3 > 0:
                    miss += n3
                    if n3 > b3:
                        blk += n3 - b3
                if n4 > 0:
                    miss += n4
                    if n4 > b4:
                        blk += n4 - b4
                miss -= gold
                if miss < 0:
                    miss = 0
                blk -= gold
                if blk < 0:
                    blk = 0
                net = VALUE[ci] + dw[BON[ci]] + rb - TOKV * (miss + SHORT * blk)
                if net > best1:
                    best2 = best1
                    best1 = net
                elif net > best2:
                    best2 = net
        val += best1 + SECOND * best2
        total += val if m == 0 else -val
    return total


# ---------------------------------------------------------------------- search
def negamax(s, depth, alpha, beta):
    global NODES
    NODES += 1
    if not (NODES & 127) and time.perf_counter() > DEADLINE:
        raise _Timeout()
    m = s[PLY] & 1
    if s[DONE]:
        v = terminal_value(s)
        return v if m == 0 else -v
    if depth == 0:
        v = evaluate(s)
        return v if m == 0 else -v
    ttmv = None
    key = None
    if USE_TT:
        key = tuple(s)
        ent = TT.get(key)
        if ent is not None:
            ed, flag, ev, ttmv = ent
            if ed >= depth:
                if flag == 0:
                    return ev
                if flag == 1:
                    if ev >= beta:
                        return ev
                elif ev <= alpha:
                    return ev
    alpha0 = alpha
    moves = gen_moves(s, TAKE_K)
    if ttmv is not None and ttmv in moves:
        moves.remove(ttmv)
        moves.insert(0, ttmv)
    best = -BIG * 2
    bmv = None
    for mv in moves:
        v = -negamax(apply(s, mv), depth - 1, -beta, -alpha)
        if v > best:
            best = v
            bmv = mv
            if v > alpha:
                alpha = v
                if alpha >= beta:
                    break
    if USE_TT and len(TT) < 150000:
        flag = 2 if best <= alpha0 else (1 if best >= beta else 0)
        TT[key] = (depth, flag, best, bmv)
    return best


def build_root(obs):
    """Return (state, info) with info = dict(ids, rids, nids) for mapping actions back."""
    global PTS, BON, COST, VALUE, NREQ, NR0, ROOT_TURN, MAXT
    you = obs['you']
    opp = 1 - you
    P = obs['players']
    s = [0] * 56
    s[0:6] = obs['bank']
    s[6:12] = P[you]['tokens']
    s[12:18] = P[opp]['tokens']
    s[18:23] = P[you]['bonuses']
    s[23:28] = P[opp]['bonuses']
    s[28] = P[you]['score']
    s[29] = P[opp]['score']
    s[30] = len(P[you]['cards'])
    s[31] = len(P[opp]['cards'])
    PTS, BON, COST = [], [], []
    ids = []
    idx = {}

    def reg(c):
        if c['id'] not in idx:
            idx[c['id']] = len(ids)
            ids.append(c['id'])
            PTS.append(c['points'])
            BON.append(c['bonus'])
            COST.append(tuple(c['cost']))
        return idx[c['id']]

    slots = [None] * 12
    for t in range(3):
        row = obs['market'][t]
        for k in range(4):
            if k < len(row):
                s[MKT + 4 * t + k] = reg(row[k])
                slots[4 * t + k] = row[k]['id']
            else:
                s[MKT + 4 * t + k] = -1
    rids = [[None] * 3, [None] * 3]
    for side, seat in ((0, you), (1, opp)):
        for r, e in enumerate(P[seat]['reserved'][:3]):
            base = RES + 3 * side + r
            if e.get('card'):
                s[base] = reg(e['card'])
                rids[side][r] = e['card']['id']
            else:
                s[base] = -2
        for r in range(len(P[seat]['reserved']), 3):
            s[RES + 3 * side + r] = -1
    VALUE = [PT * p for p in PTS]
    NREQ, NR0 = [], []
    nids = [None] * 3
    for j in range(3):
        if j < len(obs['nobles']):
            n = obs['nobles'][j]
            NREQ.append(tuple(n['requirements']))
            NR0.append(float(max(1, sum(n['requirements']))))
            s[NOB + j] = len(NREQ) - 1
            nids[j] = n['id']
        else:
            s[NOB + j] = -1
    s[END] = 1 if obs.get('end_triggered') else 0
    ROOT_TURN = obs['turn']
    MAXT = obs.get('max_turns') or 0
    return s, dict(slots=slots, rids=rids, nids=nids)


def _budget(obs, base):
    rem = obs.get('time_remaining_ms')
    if rem is None:
        return base
    spare = (rem - RESERVE_MS) / 1000.0
    return max(0.03, min(base, spare))


def _gold_of(a):
    return a['payment'][5] if a['type'] == 'buy' else 0


def choose(observation, memory):
    global DEADLINE, NODES
    actions = observation['legal_actions']
    try:
        phase = observation.get('phase', 'main')
        s, info = build_root(observation)
        if phase == 'discard':
            return {'action': _choose_discard(observation, s), 'memory': memory}
        if phase == 'noble':
            return {'action': _choose_noble(observation, s, info), 'memory': memory}
        DEADLINE = T0 + _budget(observation, BUDGET_MAIN)
        NODES = 0
        TT.clear()
        slots = info['slots']
        rids = info['rids'][0]
        index = {}
        for i, a in enumerate(actions):
            k = a['type']
            if k == 'buy':
                if a['source'] == 'market':
                    mv = (0, slots.index(a['card']))
                else:
                    mv = (1, rids.index(a['card']))
            elif k == 'take':
                tk = a['tokens']
                mv = (3, tk.index(2)) if 2 in tk else (2, tuple(j for j in range(5) if tk[j]))
            elif k == 'reserve':
                if a['source'] == 'market':
                    mv = (4, slots.index(a['card']))
                else:
                    mv = (5, a['tier'])
            else:
                mv = (6,)
            index.setdefault(mv, []).append(i)
        cand = [mv for mv in gen_moves(s, TAKE_K_ROOT) if mv in index]
        if not cand:
            cand = list(index)
        best_mv = cand[0]
        if len(cand) > 1:
            scores = {}
            depth = 1
            try:
                while depth <= 24:
                    order = sorted(cand, key=lambda mv: -scores.get(mv, 0.0)) if scores else cand
                    alpha = -BIG * 2
                    cur_best = None
                    cur = {}
                    for mv in order:
                        if mv[0] > 4:
                            cur[mv] = -BIG
                            continue
                        v = -negamax(apply(s, mv), depth - 1, -BIG * 2, -alpha)
                        cur[mv] = v
                        if cur_best is None or v > cur_best[0]:
                            cur_best = (v, mv)
                            alpha = v
                    scores = cur
                    best_mv = cur_best[1]
                    if abs(cur_best[0]) > BIG / 2:
                        break
                    depth += 1
            except _Timeout:
                pass
            LAST_INFO.update(depth=depth, nodes=NODES)
        ids = index[best_mv]
        pick = min(ids, key=lambda i: _gold_of(actions[i]))
        return {'action': pick, 'memory': memory}
    except Exception:
        if DEBUG:
            raise
        return {'action': _fallback(observation), 'memory': memory}


def _choose_discard(obs, s):
    m = 0
    tb = 6
    best = None
    for i, a in enumerate(obs['legal_actions']):
        t = s[:]
        for j, n in enumerate(a['tokens']):
            t[tb + j] -= n
            t[j] += n
        v = evaluate(t)
        if best is None or v > best[0]:
            best = (v, i)
    return best[1]


def _choose_noble(obs, s, info):
    nids = info['nids']
    best = None
    for i, a in enumerate(obs['legal_actions']):
        t = s[:]
        j = nids.index(a['noble'])
        t[NOB + j] = -1
        t[28] += 3
        v = evaluate(t)
        if best is None or v > best[0]:
            best = (v, i)
    return best[1]


def _fallback(obs):
    """Dependency-free heuristic, used only if the main logic fails."""
    try:
        acts = obs['legal_actions']
        phase = obs.get('phase', 'main')
        if phase == 'noble':
            return 0
        me = obs['players'][obs['you']]
        cards = {c['id']: c for row in obs['market'] for c in row}
        for e in me['reserved']:
            if e.get('card'):
                cards[e['card']['id']] = e['card']
        best = (-1e9, 0)
        for i, a in enumerate(acts):
            if a['type'] == 'buy':
                c = cards[a['card']]
                v = 100 + 12 * c['points'] - 3 * a['payment'][5] - 0.1 * sum(c['cost'])
            elif a['type'] == 'take':
                v = 10 + sum(a['tokens'])
            elif a['type'] == 'discard':
                v = -10 * a['tokens'][5]
            elif a['type'] == 'reserve':
                v = 0
            else:
                v = -100
            if v > best[0]:
                best = (v, i)
        return best[1]
    except Exception:
        return 0
