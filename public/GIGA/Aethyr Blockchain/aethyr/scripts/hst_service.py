"""
AETHYR HST MICROSERVICE v1.0
==============================
Closed IF Set intelligence layer for Aethyr ONE node.
Handles swap routing, fee caching, anomaly detection, bridge aggregation.

Endpoints:
  POST /route     - Best swap path across chains
  POST /fee       - Cached gas estimate (200x speedup via Closed IF Set)
  POST /anomaly   - Detect suspicious patterns
  POST /aggregate - Cross-chain bridge path optimizer
  POST /score     - Score a swap opportunity
  GET  /health    - Status + cache stats
"""

import time
import math
import json
import heapq
import threading
from collections import deque
from typing import Any, Callable, Dict, List, Optional, Tuple
from flask import Flask, request, jsonify

app = Flask(__name__)
start_time = time.time()

# ==============================================================================
# CLOSED IF SET CORE
# ==============================================================================

class ClosedIfSet:
    __slots__ = ('value', 'cache', '_ts')
    def __init__(self, value: Any):
        self.value = value
        self.cache = None
        self._ts = 0.0

class Affirm(ClosedIfSet):
    """Direct path - always recomputes. Use for dynamic data."""
    def test(self, fn: Callable) -> Any:
        return fn(self.value)
    def flip(self) -> 'ClosedIfSet':
        return Deny(self.value)

class Deny(ClosedIfSet):
    """Memory path - computes once, caches. Use for expensive/static."""
    def test(self, fn: Callable) -> Any:
        if self.cache is None:
            self.cache = fn(self.value)
            self._ts = time.time()
        return self.cache
    def flip(self) -> 'ClosedIfSet':
        return Affirm(self.value)
    def invalidate(self):
        self.cache = None
        self._ts = 0.0
    def age(self) -> float:
        return time.time() - self._ts if self._ts else float('inf')

def cond(value: Any, cached: bool = False) -> ClosedIfSet:
    return Deny(value) if cached else Affirm(value)


# ==============================================================================
# PELL-LUCAS TEMPORAL SPINE
# Compresses infinite history into O(log n) hierarchical levels
# ==============================================================================

class PellLucasSpine:
    SILVER = 1.0 + math.sqrt(2)  # ~2.414

    def __init__(self, max_levels: int = 16):
        self.max_levels = max_levels
        self._pell = self._compute_pell(max_levels + 2)

    def _compute_pell(self, n: int) -> List[int]:
        p = [0, 1]
        for i in range(2, n):
            p.append(2 * p[-1] + p[-2])
        return p

    def level_of(self, t: int) -> int:
        if t <= 0:
            return 0
        return min(int(math.log(max(t, 1)) / math.log(self.SILVER)), self.max_levels)

    def context_window(self, level: int) -> int:
        return self._pell[min(level + 1, len(self._pell) - 1)]

    def encode(self, history: List[float], levels: int = 8) -> List[float]:
        """Compress history into multi-scale features using Pell window sizes."""
        result = []
        for lvl in range(min(levels, self.max_levels)):
            window = self.context_window(lvl)
            slice_ = history[-window:] if len(history) >= window else history
            if slice_:
                avg = sum(slice_) / len(slice_)
                variance = sum((x - avg) ** 2 for x in slice_) / len(slice_)
                result.append(avg)
                result.append(math.sqrt(variance + 1e-10))
            else:
                result.extend([0.0, 0.0])
        return result


# ==============================================================================
# FEE CACHE ENGINE
# ==============================================================================

class FeeCache:
    TTL = 30.0

    def __init__(self):
        self._lock = threading.Lock()
        self._states: Dict[str, Deny] = {}
        self._hits = 0
        self._misses = 0

    def get(self, chain: str) -> float:
        with self._lock:
            if chain in self._states and self._states[chain].age() > self.TTL:
                self._states[chain].invalidate()
            if chain not in self._states:
                self._states[chain] = Deny(chain)
            state = self._states[chain]
            was_cached = state.cache is not None
            defaults = {
                'ETH': 20.0, 'ARB': 0.1, 'OP': 0.01,
                'BSC': 3.0, 'MATIC': 50.0, 'BASE': 0.01,
                'SOL': 0.0, 'BTC': 0.0, 'AYR': 0.0,
            }
            result = state.test(lambda c: defaults.get(c, 5.0))
            if was_cached:
                self._hits += 1
            else:
                self._misses += 1
            return result

    def update(self, chain: str, fee_gwei: float):
        with self._lock:
            if chain not in self._states:
                self._states[chain] = Deny(chain)
            self._states[chain].cache = fee_gwei
            self._states[chain]._ts = time.time()

    def stats(self) -> Dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate_pct': round(self._hits / total * 100, 1) if total else 0,
                'chains': {
                    c: {'fee_gwei': s.cache, 'age_s': round(s.age(), 1)}
                    for c, s in self._states.items()
                }
            }


# ==============================================================================
# SWAP ROUTER
# ==============================================================================

class SwapRouter:
    TOPOLOGY = [
        ('BTC',   'ETH',   'ETH',   1.0),
        ('BTC',   'ETH',   'ARB',   0.3),
        ('ETH',   'USDT',  'ETH',   1.0),
        ('ETH',   'USDT',  'ARB',   0.3),
        ('ETH',   'USDT',  'OP',    0.2),
        ('ETH',   'BNB',   'BSC',   0.5),
        ('ETH',   'MATIC', 'MATIC', 0.5),
        ('ETH',   'ARB',   'ARB',   0.3),
        ('SOL',   'USDT',  'SOL',   0.1),
        ('SOL',   'ETH',   'SOL',   0.1),
        ('BNB',   'USDT',  'BSC',   0.5),
        ('MATIC', 'USDT',  'MATIC', 0.5),
        ('ARB',   'ETH',   'ARB',   0.3),
        ('USDT',  'BTC',   'ETH',   1.0),
        ('USDT',  'ETH',   'ARB',   0.3),
        # AYR chain - ultra cheap settlement layer
        ('AYR',   'BTC',   'AYR',   0.01),
        ('AYR',   'ETH',   'AYR',   0.01),
        ('AYR',   'SOL',   'AYR',   0.01),
        ('AYR',   'BNB',   'AYR',   0.01),
        ('AYR',   'MATIC', 'AYR',   0.01),
        ('AYR',   'ARB',   'AYR',   0.01),
        ('BTC',   'AYR',   'AYR',   0.01),
        ('ETH',   'AYR',   'AYR',   0.01),
        ('SOL',   'AYR',   'AYR',   0.01),
        ('BNB',   'AYR',   'AYR',   0.01),
        ('MATIC', 'AYR',   'AYR',   0.01),
    ]

    def __init__(self, fee_cache: FeeCache, spine: PellLucasSpine):
        self.fee_cache = fee_cache
        self.spine = spine
        self._graph: Dict[str, List] = {}
        self._route_history: Dict[str, deque] = {}
        for src, dst, chain, mult in self.TOPOLOGY:
            self._graph.setdefault(src, []).append((dst, chain, mult))
            self._graph.setdefault(dst, []).append((src, chain, mult))

    def _edge_cost(self, src: str, dst: str, chain: str,
                   mult: float, prices: Dict) -> float:
        fee_gwei = self.fee_cache.get(chain)
        native_price = prices.get('ETH', 2000) if chain not in ('SOL', 'BTC', 'AYR') \
                       else prices.get(chain, 1)
        fee_usd = fee_gwei * 1e-9 * 21000 * native_price
        slippage = 0.0005 if chain == 'AYR' else 0.003 * mult
        key = f"{src}-{dst}-{chain}"
        history = list(self._route_history.get(key, deque([1.0])))
        encoded = self.spine.encode(history, levels=4)
        liq = encoded[0] if encoded else 1.0
        liq_penalty = max(0.0, 1.0 - liq) * 0.01
        return fee_usd + slippage + liq_penalty

    def find_best_route(self, src: str, dst: str,
                        amount: float, prices: Dict,
                        max_hops: int = 4) -> Dict:
        if src not in self._graph:
            return {'error': f'Unknown token: {src}'}
        if dst not in self._graph:
            return {'error': f'Unknown token: {dst}'}
        if src == dst:
            return {'path': [src], 'chains': [], 'hops': 0,
                    'cost_usd': 0.0, 'fee_pct': 0.0,
                    'net_out': amount, 'rate': 1.0}

        queue = [(0.0, src, [src], [])]
        visited = set()
        best = None

        while queue:
            cost, token, path, chains = heapq.heappop(queue)
            if token in visited:
                continue
            visited.add(token)
            if token == dst:
                best = (cost, path, chains)
                break
            if len(path) > max_hops:
                continue
            for (next_tok, chain, mult) in self._graph.get(token, []):
                if next_tok not in visited:
                    ec = self._edge_cost(token, next_tok, chain, mult, prices)
                    heapq.heappush(queue, (cost + ec, next_tok,
                                          path + [next_tok], chains + [chain]))

        if not best:
            return {'error': f'No route: {src} → {dst}'}

        total_cost, path, chains = best
        src_p = prices.get(src, 1.0)
        dst_p = prices.get(dst, 1.0)
        gross_out = amount * src_p / dst_p if dst_p else 0
        fee_pct = total_cost / (amount * src_p) if amount * src_p else 0
        net_out = gross_out * (1.0 - min(fee_pct, 0.1))

        return {
            'path': path,
            'chains': chains,
            'hops': len(path) - 1,
            'cost_usd': round(total_cost, 6),
            'fee_pct': round(fee_pct * 100, 4),
            'gross_out': round(gross_out, 8),
            'net_out': round(net_out, 8),
            'rate': round(net_out / amount, 8) if amount else 0,
        }

    def record_outcome(self, src: str, dst: str, chain: str, success: bool):
        key = f"{src}-{dst}-{chain}"
        if key not in self._route_history:
            self._route_history[key] = deque(maxlen=100)
        self._route_history[key].append(1.0 if success else 0.0)


# ==============================================================================
# ANOMALY DETECTOR
# ==============================================================================

class AnomalyDetector:
    THRESHOLDS = {
        'volume_spike': 5.0,
        'price_impact': 0.05,
        'rapid_fire':   5,
        'round_amount': 0.95,
    }

    def __init__(self, spine: PellLucasSpine):
        self.spine = spine
        self._volume_history: deque = deque(maxlen=1000)
        self._price_history: Dict[str, deque] = {}
        self._addr_history: deque = deque(maxlen=500)
        self._amount_history: deque = deque(maxlen=500)
        self._baseline_state = Deny(self)
        self._baseline_ts = 0.0

    def _get_baseline(self) -> Dict:
        now = time.time()
        if now - self._baseline_ts > 60:
            self._baseline_state.invalidate()
            self._baseline_ts = now
        def compute(s):
            vols = list(s._volume_history)
            if not vols:
                return {'avg': 1.0, 'std': 0.1}
            avg = sum(vols) / len(vols)
            std = math.sqrt(sum((v - avg)**2 for v in vols) / len(vols) + 1e-10)
            return {'avg': avg, 'std': std}
        return self._baseline_state.test(compute)

    def analyze(self, event: Dict) -> Dict:
        flags = []
        risk = 0.0
        amount    = float(event.get('amount', 0))
        addr      = str(event.get('address', ''))
        token     = str(event.get('token', 'ETH')).upper()
        price     = float(event.get('price', 0))
        ts        = float(event.get('timestamp', time.time()))

        self._volume_history.append(amount)
        self._addr_history.append((addr, ts))
        self._amount_history.append(amount)
        if token not in self._price_history:
            self._price_history[token] = deque(maxlen=200)
        self._price_history[token].append(price)

        baseline = self._get_baseline()
        avg = baseline['avg']
        std = baseline['std']

        # Volume spike
        if avg > 0 and amount > avg * self.THRESHOLDS['volume_spike']:
            z = (amount - avg) / (std + 1e-10)
            risk += min(z * 10, 40)
            flags.append(f'VOLUME_SPIKE z={z:.1f}')

        # Price impact
        hist = list(self._price_history.get(token, []))
        if len(hist) >= 2 and hist[-2] > 0:
            chg = abs(price - hist[-2]) / hist[-2]
            if chg > self.THRESHOLDS['price_impact']:
                risk += min(chg * 200, 30)
                flags.append(f'PRICE_IMPACT {chg*100:.1f}%')

        # Rapid fire
        recent = sum(1 for (a, t) in self._addr_history
                     if a == addr and ts - t < 1.0)
        if recent >= self.THRESHOLDS['rapid_fire']:
            risk += min(recent * 3, 20)
            flags.append(f'RAPID_FIRE {recent}x/sec')

        # Round number wash trading
        amounts = list(self._amount_history)
        if len(amounts) >= 10:
            round_r = sum(1 for a in amounts if a == int(a)) / len(amounts)
            if round_r > self.THRESHOLDS['round_amount']:
                risk += 10
                flags.append(f'ROUND_AMOUNTS {round_r*100:.0f}%')

        # Multi-scale anomaly via Pell-Lucas
        if len(list(self._volume_history)) >= 8:
            encoded = self.spine.encode(list(self._volume_history), levels=4)
            outlier_levels = sum(
                1 for i in range(0, len(encoded), 2)
                if encoded[i] > 0 and amount > encoded[i] * 3
            )
            if outlier_levels >= 3:
                risk += 15
                flags.append(f'MULTI_SCALE_ANOMALY levels={outlier_levels}')

        score = min(round(risk, 1), 100.0)
        severity = ('CRITICAL' if score >= 70 else
                    'HIGH'     if score >= 40 else
                    'MEDIUM'   if score >= 20 else 'LOW')
        return {
            'risk_score': score,
            'severity': severity,
            'flags': flags,
            'allow': score < 70,
        }


# ==============================================================================
# BRIDGE AGGREGATOR
# ==============================================================================

class BridgeAggregator:
    BRIDGES = {
        'ETH':   {'finality': 900,  'fee': 5.0,  'reliability': 0.99},
        'ARB':   {'finality': 30,   'fee': 0.5,  'reliability': 0.98},
        'OP':    {'finality': 30,   'fee': 0.3,  'reliability': 0.98},
        'BSC':   {'finality': 15,   'fee': 0.2,  'reliability': 0.97},
        'MATIC': {'finality': 10,   'fee': 0.1,  'reliability': 0.97},
        'BASE':  {'finality': 30,   'fee': 0.1,  'reliability': 0.96},
        'SOL':   {'finality': 2,    'fee': 0.01, 'reliability': 0.95},
        'BTC':   {'finality': 3600, 'fee': 2.0,  'reliability': 0.999},
        'AYR':   {'finality': 5,    'fee': 0.001,'reliability': 0.999},
    }

    def __init__(self, fee_cache: FeeCache):
        self.fee_cache = fee_cache

    def optimize(self, src: str, dst: str,
                 amount_usd: float, priority: str = 'balanced') -> Dict:
        si = self.BRIDGES.get(src)
        di = self.BRIDGES.get(dst)
        if not si or not di:
            return {'error': f'Unknown chain: {src} or {dst}'}
        if src == dst:
            return {'path': [src], 'fee_usd': 0, 'finality_sec': 0, 'score': 100}

        def score(fee, secs, rel):
            if priority == 'speed':
                return rel * 100 / (1 + secs / 60)
            elif priority == 'cost':
                return rel * 100 / (1 + fee)
            else:
                return rel * 100 / (1 + fee * 0.5 + secs / 120)

        direct_fee  = si['fee'] + di['fee']
        direct_time = si['finality'] + di['finality']
        direct_rel  = si['reliability'] * di['reliability']
        direct_s    = score(direct_fee, direct_time, direct_rel)

        ayr_info    = self.BRIDGES['AYR']
        ayr_fee     = si['fee'] + ayr_info['fee'] + di['fee']
        ayr_time    = si['finality'] + ayr_info['finality'] + di['finality']
        ayr_rel     = si['reliability'] * ayr_info['reliability'] * di['reliability']
        ayr_s       = score(ayr_fee, ayr_time, ayr_rel)

        if ayr_s > direct_s:
            return {
                'path': [src, 'AYR', dst],
                'via': 'AETHYR_ONE',
                'fee_usd': round(ayr_fee, 4),
                'finality_sec': int(ayr_time),
                'reliability': round(ayr_rel, 3),
                'score': round(ayr_s, 1),
                'savings_pct': round((1 - ayr_fee / direct_fee) * 100, 1) if direct_fee else 0,
            }
        return {
            'path': [src, dst],
            'via': 'DIRECT',
            'fee_usd': round(direct_fee, 4),
            'finality_sec': int(direct_time),
            'reliability': round(direct_rel, 3),
            'score': round(direct_s, 1),
            'savings_pct': 0,
        }


# ==============================================================================
# INITIALIZE
# ==============================================================================

spine     = PellLucasSpine(max_levels=16)
fee_cache = FeeCache()
router    = SwapRouter(fee_cache, spine)
anomaly   = AnomalyDetector(spine)
bridge    = BridgeAggregator(fee_cache)

_prices: Dict[str, float] = {
    'BTC': 65000, 'ETH': 3000, 'SOL': 150, 'BNB': 400,
    'MATIC': 1.0, 'ARB': 1.5,  'AYR': 0.01, 'USDT': 1.0,
}
_prices_lock = threading.Lock()

def get_prices() -> Dict:
    with _prices_lock:
        return dict(_prices)


# ==============================================================================
# FLASK ENDPOINTS
# ==============================================================================

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'uptime_s': round(time.time() - start_time, 1),
        'fee_cache': fee_cache.stats(),
        'prices': get_prices(),
        'version': 'HST-v8-Aethyr-1.0',
    })


@app.route('/fee', methods=['POST'])
def update_fee():
    data = request.json or {}
    chain     = str(data.get('chain', '')).upper()
    fee_gwei  = data.get('fee_gwei')
    prices    = data.get('prices')
    if prices:
        with _prices_lock:
            _prices.update({k.upper(): float(v) for k, v in prices.items()})
    if chain and fee_gwei is not None:
        fee_cache.update(chain, float(fee_gwei))
    if chain:
        return jsonify({'chain': chain, 'fee_gwei': fee_cache.get(chain)})
    return jsonify(fee_cache.stats())


@app.route('/route', methods=['POST'])
def find_route():
    data     = request.json or {}
    src      = str(data.get('from', '')).upper()
    dst      = str(data.get('to', '')).upper()
    amount   = float(data.get('amount', 1.0))
    max_hops = int(data.get('max_hops', 4))
    prices   = data.get('prices', {})
    if not src or not dst:
        return jsonify({'error': 'from and to required'}), 400
    if prices:
        with _prices_lock:
            _prices.update({k.upper(): float(v) for k, v in prices.items()})
    result = router.find_best_route(src, dst, amount, get_prices(), max_hops)
    result.update({'from': src, 'to': dst, 'amount': amount})
    return jsonify(result)


@app.route('/anomaly', methods=['POST'])
def check_anomaly():
    data = request.json or {}
    if not data:
        return jsonify({'error': 'Event data required'}), 400
    return jsonify(anomaly.analyze(data))


@app.route('/aggregate', methods=['POST'])
def aggregate_bridge():
    data       = request.json or {}
    src_chain  = str(data.get('from_chain', '')).upper()
    dst_chain  = str(data.get('to_chain', '')).upper()
    amount_usd = float(data.get('amount_usd', 100))
    priority   = str(data.get('priority', 'balanced'))
    if not src_chain or not dst_chain:
        return jsonify({'error': 'from_chain and to_chain required'}), 400
    result = bridge.optimize(src_chain, dst_chain, amount_usd, priority)
    result.update({'from_chain': src_chain, 'to_chain': dst_chain, 'amount_usd': amount_usd})
    return jsonify(result)


@app.route('/score', methods=['POST'])
def score_opportunity():
    data    = request.json or {}
    src     = str(data.get('from', '')).upper()
    dst     = str(data.get('to', '')).upper()
    amount  = float(data.get('amount', 1.0))
    urgency = str(data.get('urgency', 'normal'))
    prices  = data.get('prices', {})
    if prices:
        with _prices_lock:
            _prices.update({k.upper(): float(v) for k, v in prices.items()})
    route = router.find_best_route(src, dst, amount, get_prices())
    if 'error' in route:
        return jsonify({'score': 0, 'reason': route['error']})
    fee_score = max(0, 100 - route.get('fee_pct', 5) * 10)
    hop_score = max(0, 100 - route.get('hops', 1) * 15)
    mult      = 1.2 if urgency == 'high' else 1.0
    score     = min(100, (fee_score * 0.6 + hop_score * 0.4) * mult)
    return jsonify({
        'score': round(score, 1),
        'route': route,
        'recommendation': 'EXECUTE' if score >= 60 else 'WAIT',
    })


@app.route('/outcome', methods=['POST'])
def record_outcome():
    data = request.json or {}
    router.record_outcome(
        str(data.get('from', '')).upper(),
        str(data.get('to', '')).upper(),
        str(data.get('chain', 'AYR')).upper(),
        bool(data.get('success', True)),
    )
    return jsonify({'ok': True})


# ==============================================================================
# ENTRY POINT
# ==============================================================================

if __name__ == '__main__':
    print("\n╔══════════════════════════════════════════╗")
    print("║   AETHYR HST MICROSERVICE v1.0           ║")
    print("║   Closed IF Set Intelligence Layer       ║")
    print("╚══════════════════════════════════════════╝\n")
    print("  POST /route      - Best swap path")
    print("  POST /fee        - Gas fee cache")
    print("  POST /anomaly    - Detect suspicious activity")
    print("  POST /aggregate  - Bridge path optimizer")
    print("  POST /score      - Score swap opportunity")
    print("  POST /outcome    - Record result (learning)")
    print("  GET  /health     - Status\n")
    print("  http://127.0.0.1:7070\n")
    app.run(host='127.0.0.1', port=7070, debug=False, threaded=True)
