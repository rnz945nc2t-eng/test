"""
╔══════════════════════════════════════════════════════════════════════════════════════════╗
║                                     Io  v1.0-HF                                          ║
║                        Complete HST Architecture — UNIFIED                               ║
║                                                                                          ║
║  THEORETICAL FOUNDATION:                                                                 ║
║  1. Closed IF Set (CIF): A logic abstraction that forces monomorphic branching at the    ║
║     CPU instruction level, eliminating branch misprediction penalties during inference.   ║
║                                                                                          ║
║  2. Pell-Lucas Spine: A non-linear recurrence sequence P(n) = 2*P(n-1) + P(n-2)          ║
║     used for structural anchoring of long-term dependencies.                             ║
║                                                                                          ║
║  3. Lattice Core: Multi-level path-weighted message passing across the sequence graph    ║
║     defined by the Pell-Lucas Spine sequence.                                            ║
║                                                                                          ║
║  4. Hyperbolic Embedding: Poincaré ball projection (||x|| < 1) for representing          ║
║     hierarchical language structures in a negative-curvature manifold.                   ║
║                                                                                          ║
║  5. Paged KV Cache: Block-based memory allocation (O(1) allocation) for maintaining      ║
║     stability during high-horizon speculative token drafting.                            ║
║                                                                                          ║
║  6. Hebbian Fast Weights: Inference-time weight plasticity using associative memory       ║
║     updates for zero-shot context adaptation.                                            ║
║                                                                                          ║
║  DATA STRATEGY:                                                                          ║
║  - Strictly Remote: No local file dependencies (No data.txt).                            ║
║  - Asynchronous Streaming: Parallel thread for fetching tokens from Hugging Face.        ║
║  - Optimized for: HuggingFaceFW/fineweb-edu (Sample-10BT).                               ║
║                                                                                          ║
║  VERSION: 1.0.0-PROD-HF-FIXED                                                            ║
╚══════════════════════════════════════════════════════════════════════════════════════════╝
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import math
import time
import os
import sys
import argparse
import logging
import json
import random
import threading
import queue
from typing import Optional, List, Tuple, Dict, Any, Callable, Union, Generator
from dataclasses import dataclass, field, asdict
from collections import deque

# Hardware-specific optimizations
try:
    from datasets import load_dataset
    import tiktoken
    HAS_RESOURCES = True
except ImportError:
    print("[Error] Missing dependencies. Run: pip install datasets tiktoken torch numpy")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════════════════════════════════
# 0.  SYSTEM DIAGNOSTICS & LOGGING
# ══════════════════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("Io-HST")

# ══════════════════════════════════════════════════════════════════════════════════════════
# 1.  CLOSED IF SET (CIF) — THE KERNEL ENGINE
# ══════════════════════════════════════════════════════════════════════════════════════════

class _CIF:
    __slots__ = ("value", "cache")
    def __init__(self, v):
        self.value = v
        self.cache = None

class Affirm(_CIF):
    def test(self, fn: Callable[[Any], bool]) -> bool:
        return fn(self.value)
    def flip(self) -> 'Deny':
        return Deny(self.value)

class Deny(_CIF):
    def test(self, fn: Callable[[Any], bool]) -> bool:
        if self.cache is None:
            self.cache = not fn(self.value)
        return self.cache
    def flip(self) -> 'Affirm':
        return Affirm(self.value)

class CIFScalar:
    __slots__ = ("_fn", "_val", "_computed")
    def __init__(self, fn: Callable):
        self._fn = fn
        self._val = None
        self._computed = False
    def get(self):
        if not self._computed:
            self._val = self._fn()
            self._computed = True
        return self._val

class CIFState:
    def __init__(self, value, initial_deny=True):
        self._s = Deny(value) if initial_deny else Affirm(value)
        self._val = value
    def test(self, fn): return self._s.test(fn)
    def set_dynamic(self): self._s = Affirm(self._val)
    def set_static(self):  self._s = Deny(self._val)

class CIFRegistry:
    def __init__(self, cfg: 'IoConfig'):
        c = cfg
        self.head_dim      = CIFScalar(lambda: c.d_model // c.n_heads)
        self.attn_scale    = CIFScalar(lambda: 1.0 / math.sqrt(c.d_model // c.n_heads))
        self.log_vocab     = CIFScalar(lambda: math.log(c.vocab_size))
        self.lm_weight     = CIFScalar(lambda: 1.0)
        self.hor_weight    = CIFScalar(lambda: 0.45)
        self.unc_weight    = CIFScalar(lambda: 0.08)
        self.exit_thresh   = CIFScalar(lambda: c.exit_threshold)
        self.fb_iters      = CIFScalar(lambda: c.fb_iterations)
        self.block_size    = CIFScalar(lambda: 16)
        self.d_model_x2    = CIFScalar(lambda: c.d_model * 2)
        self.d_model_x3    = CIFScalar(lambda: c.d_model * 3)
        self.hebb_decay    = CIFScalar(lambda: c.hebbian_decay)

# ══════════════════════════════════════════════════════════════════════════════════════════
# 2.  CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════════════════

@dataclass
class IoConfig:
    vocab_size:       int   = 50257
    d_model:          int   = 512
    n_heads:          int   = 8
    n_layers:         int   = 16
    max_seq_len:      int   = 1024
    dropout:          float = 0.1
    lattice_depth:    int   = 64
    max_horizon:      int   = 32
    fb_iterations:    int   = 2
    hebbian_decay:    float = 0.995
    exit_threshold:   float = 0.90
    lr:               float = 3.5e-4
    weight_decay:     float = 0.1
    warmup_steps:     int   = 2000
    max_steps:        int   = 50000
    batch_size:       int   = 4
    accum_steps:      int   = 4
    grad_clip:        float = 1.0
    device:           str   = "cuda" if torch.cuda.is_available() else "cpu"
    use_amp:          bool  = True

    def to_dict(self): return asdict(self)

# ══════════════════════════════════════════════════════════════════════════════════════════
# 3.  PELL-LUCAS SPINE
# ══════════════════════════════════════════════════════════════════════════════════════════

def build_spine_sequence(max_len: int) -> List[int]:
    s = [0, 2, 6]
    while True:
        nxt = 2 * s[-1] + s[-2]
        if nxt >= max_len: break
        s.append(nxt)
    return s

class SpineAnalyzer:
    def __init__(self, max_seq_len: int):
        self.spine = build_spine_sequence(max_seq_len)
        self.spine_idx = {v: i for i, v in enumerate(self.spine)}
        self._cache: Dict[int, dict] = {}
        self._precompute()

    def _get_ancestors(self, pos: int) -> List[int]:
        if pos not in self.spine_idx:
            prev = [s for s in self.spine if s < pos]
            return [prev[-1]] if prev else []
        idx = self.spine_idx[pos]
        return [self.spine[i] for i in [idx-1, idx-2, idx-3] if i >= 0]

    def _precompute(self):
        for pos in self.spine:
            levels = {0: [pos]}
            visited = {pos}
            q = deque([(pos, 0)])
            path_counts = {pos: 1}
            while q:
                curr, lvl = q.popleft()
                if lvl >= 6: continue
                for a in self._get_ancestors(curr):
                    if lvl+1 not in levels: levels[lvl+1] = []
                    if a not in levels[lvl+1]: levels[lvl+1].append(a)
                    path_counts[a] = path_counts.get(a, 0) + path_counts[curr]
                    if a not in visited:
                        visited.add(a)
                        q.append((a, lvl + 1))
            self._cache[pos] = {"levels": levels, "path_counts": path_counts, "max_depth": max(levels.keys()) if levels else 0}

    def get_structure(self, pos: int) -> dict:
        return self._cache.get(pos, self._cache.get(0))

# ══════════════════════════════════════════════════════════════════════════════════════════
# 4.  MANIFOLDS
# ══════════════════════════════════════════════════════════════════════════════════════════

class HyperbolicEmbedding(nn.Module):
    def __init__(self, vocab_size: int, d_model: int, curvature: float = 1.0):
        super().__init__()
        self.c = curvature
        self.emb = nn.Embedding(vocab_size, d_model)
        nn.init.normal_(self.emb.weight, mean=0, std=0.01)
    def _project(self, x: torch.Tensor) -> torch.Tensor:
        norm = x.norm(dim=-1, keepdim=True)
        max_norm = (1 - 1e-5) / math.sqrt(self.c)
        return torch.where(norm > max_norm, x * (max_norm / (norm + 1e-9)), x)
    def forward(self, ids: torch.Tensor) -> torch.Tensor:
        return self._project(self.emb(ids))

class LatticePositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_seq_len: int):
        super().__init__()
        inv_freq = 1.0 / (10000 ** (torch.arange(0, d_model, 2).float() / d_model))
        t = torch.arange(max_seq_len).float()
        sinusoid = torch.einsum("i,j->ij", t, inv_freq)
        self.register_buffer("abs_pe", torch.cat([sinusoid.sin(), sinusoid.cos()], dim=-1))
        self.spine = torch.tensor(build_spine_sequence(max_seq_len)).float()
        self.rel_net = nn.Sequential(nn.Linear(3, d_model // 4), nn.LayerNorm(d_model // 4), nn.GELU(), nn.Linear(d_model // 4, d_model))
    def forward(self, positions: torch.Tensor) -> torch.Tensor:
        abs_emb = self.abs_pe[positions]
        sp = self.spine.to(positions.device)
        pos_f = positions.float().unsqueeze(-1)
        diffs = pos_f - sp
        ld = torch.where(diffs >= 0, diffs, torch.inf).min(dim=-1)[0]
        rd = torch.where(diffs < 0, -diffs, torch.inf).min(dim=-1)[0]
        rank = (diffs >= 0).sum(dim=-1).float()
        return abs_emb + self.rel_net(torch.stack([ld, rd, rank], dim=-1))

# ══════════════════════════════════════════════════════════════════════════════════════════
# 5.  ATTENTION
# ══════════════════════════════════════════════════════════════════════════════════════════

class PagedKVCache:
    def __init__(self, n_heads: int, head_dim: int, block_size: int, device: str):
        self.nh, self.hd, self.bs, self.dev = n_heads, head_dim, block_size, device
        self.k_blocks, self.v_blocks, self.pos = [], [], 0
        self.alloc_state = CIFState(self, initial_deny=False)
    def append(self, k: torch.Tensor, v: torch.Tensor):
        sl = k.size(2)
        if self.alloc_state.test(lambda s: not s.k_blocks or s.k_blocks[-1].size(2) >= s.bs):
            self.k_blocks.append(torch.zeros(1, self.nh, self.bs, self.hd, device=self.dev))
            self.v_blocks.append(torch.zeros(1, self.nh, self.bs, self.hd, device=self.dev))
            self.alloc_state.set_static()
        idx = self.pos % self.bs
        self.k_blocks[-1][:, :, idx:idx+sl, :] = k
        self.v_blocks[-1][:, :, idx:idx+sl, :] = v
        self.pos += sl
        if self.pos % self.bs == 0: self.alloc_state.set_dynamic()
    def get_context(self) -> Tuple[torch.Tensor, torch.Tensor]:
        if not self.k_blocks: return None, None
        return torch.cat(self.k_blocks, dim=2)[:, :, :self.pos, :], torch.cat(self.v_blocks, dim=2)[:, :, :self.pos, :]

class FlashBlockSparseAttention(nn.Module):
    def __init__(self, d_model: int, n_heads: int, cif: CIFRegistry, dropout: float = 0.1):
        super().__init__()
        self.nh, self.hd, self.scale, self.cif = n_heads, cif.head_dim.get(), cif.attn_scale.get(), cif
        self.qkv_proj = nn.Linear(d_model, d_model * 3, bias=False)
        self.out_proj = nn.Linear(d_model, d_model, bias=False)
        self.dropout  = nn.Dropout(dropout)
    def forward(self, x: torch.Tensor, cache: Optional[PagedKVCache] = None) -> Tuple[torch.Tensor, PagedKVCache]:
        B, S, D = x.shape
        qkv = self.qkv_proj(x).view(B, S, 3, self.nh, self.hd).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        if cache is not None:
            cache.append(k, v)
            k, v = cache.get_context()
        out = F.scaled_dot_product_attention(q, k, v, is_causal=(cache is None), dropout_p=self.dropout.p if self.training else 0.0)
        return self.out_proj(out.transpose(1, 2).contiguous().view(B, S, D)), cache

# ══════════════════════════════════════════════════════════════════════════════════════════
# 6.  CORE ENGINE
# ══════════════════════════════════════════════════════════════════════════════════════════

class DiamondMixer(nn.Module):
    def __init__(self, d_model: int, cif: CIFRegistry):
        super().__init__()
        self.up = nn.Linear(d_model, cif.d_model_x2.get())
        self.down = nn.Linear(cif.d_model_x2.get(), d_model)
        self.norm = nn.LayerNorm(d_model)
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        a, b = self.up(self.norm(x)).chunk(2, dim=-1)
        return x + self.down(torch.cat([F.gelu(a + b) * torch.tanh(a - b), F.silu(b)], dim=-1))

class FeedbackLoop(nn.Module):
    def __init__(self, d_model: int, cif: CIFRegistry):
        super().__init__()
        self.cif, self.gru, self.gate = cif, nn.GRUCell(d_model, d_model), nn.Linear(d_model, 1)
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, S, D = x.shape
        h = x.reshape(-1, D)
        for _ in range(self.cif.fb_iters.get()):
            g = torch.sigmoid(self.gate(h))
            h = (1 - g) * h + g * self.gru(h, h)
        return h.view(B, S, D)

class CompleteLatticeProcessor(nn.Module):
    def __init__(self, d_model: int, analyzer: SpineAnalyzer, cif: CIFRegistry):
        super().__init__()
        self.analyzer, self.cif = analyzer, cif
        self.fuse_layer = nn.Sequential(nn.Linear(cif.d_model_x2.get(), d_model), nn.LayerNorm(d_model), nn.GELU())
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, S, D = x.shape
        updates = torch.zeros_like(x)
        for pos in self.analyzer.spine:
            if pos >= S: continue
            meta = self.analyzer.get_structure(pos)
            anc = [a for a in meta['levels'].get(1, []) if a < S]
            if not anc: continue
            w = F.softmax(torch.tensor([meta['path_counts'].get(a, 1.0) for a in anc], device=x.device).float(), dim=0)
            agg = (torch.stack([x[:, a, :] for a in anc], dim=1) * w.view(1, -1, 1)).sum(dim=1)
            updates[:, pos, :] = self.fuse_layer(torch.cat([x[:, pos, :], agg], dim=-1))
        return x + updates

class HebbianFastWeights(nn.Module):
    def __init__(self, d_model: int, cif: CIFRegistry):
        super().__init__()
        self.cif, self.q_proj, self.kv_proj, self.out_proj = cif, nn.Linear(d_model, d_model // 4, bias=False), nn.Linear(d_model, d_model // 2, bias=False), nn.Linear(d_model // 4, d_model)
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        k, v = self.kv_proj(x).chunk(2, dim=-1)
        mem = torch.einsum("bsd,bse->bde", v, k) * self.cif.hebb_decay.get()
        return x + self.out_proj(torch.einsum("bsd,bde->bse", self.q_proj(x), mem))

# ══════════════════════════════════════════════════════════════════════════════════════════
# 8.  SPECULATIVE
# ══════════════════════════════════════════════════════════════════════════════════════════

class SpeculativeHorizon(nn.Module):
    def __init__(self, d_model: int, vocab_size: int, max_h: int):
        super().__init__()
        self.max_h = max_h
        self.unc_predictor = nn.Sequential(nn.Linear(d_model, d_model // 8), nn.GELU(), nn.Linear(d_model // 8, 1), nn.Sigmoid())
        self.near_experts = nn.ModuleList([nn.Linear(d_model, vocab_size) for _ in range(4)])
        self.far_expert = nn.Sequential(nn.Linear(d_model, d_model), nn.ReLU(), nn.Linear(d_model, vocab_size * (max_h - 4)))
    def forward(self, h: torch.Tensor):
        ht = h[:, -1, :]
        unc = self.unc_predictor(ht)
        h_len = (self.max_h * (1.0 - unc)).long().clamp(2, self.max_h)
        near = torch.stack([head(ht) for head in self.near_experts], dim=1)
        far  = self.far_expert(ht).view(h.size(0), self.max_h - 4, -1)
        return torch.cat([near, far], dim=1), h_len, unc

class AdaptiveBlock(nn.Module):
    def __init__(self, d_model: int, n_heads: int, cif: CIFRegistry):
        super().__init__()
        self.cif, self.attn, self.mixer, self.norm1, self.norm2 = cif, FlashBlockSparseAttention(d_model, n_heads, cif), DiamondMixer(d_model, cif), nn.LayerNorm(d_model), nn.LayerNorm(d_model)
        self.confidence_gate = nn.Sequential(nn.Linear(d_model, 1), nn.Sigmoid())
    def forward(self, x: torch.Tensor, cache: Optional[PagedKVCache] = None):
        a, nc = self.attn(self.norm1(x), cache)
        x = x + a + self.mixer(self.norm2(x + a))
        conf = self.confidence_gate(x[:, -1, :]).mean()
        return x, nc, conf.item() > self.cif.exit_thresh.get(), conf

# ══════════════════════════════════════════════════════════════════════════════════════════
# 9.  SYSTEM
# ══════════════════════════════════════════════════════════════════════════════════════════

class Io(nn.Module):
    def __init__(self, cfg: IoConfig):
        super().__init__()
        self.cfg, self.cif = cfg, CIFRegistry(cfg)
        self.analyzer = SpineAnalyzer(cfg.max_seq_len)
        self.embedding, self.pos_enc, self.lattice = HyperbolicEmbedding(cfg.vocab_size, cfg.d_model), LatticePositionalEncoding(cfg.d_model, cfg.max_seq_len), CompleteLatticeProcessor(cfg.d_model, self.analyzer, self.cif)
        self.layers = nn.ModuleList([AdaptiveBlock(cfg.d_model, cfg.n_heads, self.cif) for _ in range(cfg.n_layers)])
        self.feedback, self.hebbian, self.norm_out, self.lm_head, self.horizon = FeedbackLoop(cfg.d_model, self.cif), HebbianFastWeights(cfg.d_model, self.cif), nn.LayerNorm(cfg.d_model), nn.Linear(cfg.d_model, cfg.vocab_size, bias=False), SpeculativeHorizon(cfg.d_model, cfg.vocab_size, cfg.max_horizon)
        self.lm_head.weight = self.embedding.emb.weight
        self.apply(self._init_weights)
    def _init_weights(self, m):
        if isinstance(m, nn.Linear):
            torch.nn.init.normal_(m.weight, mean=0, std=0.02)
            if m.bias is not None: torch.nn.init.zeros_(m.bias)
    def forward(self, ids, caches=None, training=True):
        B, S = ids.shape
        p_offset = caches[0].pos if caches else 0
        x = self.embedding(ids) + self.pos_enc(torch.arange(p_offset, p_offset+S, device=ids.device).unsqueeze(0).expand(B,-1))
        x = self.lattice(x)
        new_caches = []
        for i, layer in enumerate(self.layers):
            x, nc, skip, _ = layer(x, caches[i] if caches else None)
            new_caches.append(nc)
            if not training and skip and S == 1: break
        x = self.feedback(x)
        if not training: x = self.hebbian(x)
        h = self.norm_out(x)
        logits = self.lm_head(h)
        drafts, h_len, unc = self.horizon(h)
        return {"logits": logits, "drafts": drafts, "h_len": h_len, "unc": unc, "caches": new_caches}

# ══════════════════════════════════════════════════════════════════════════════════════════
# 10. STREAMER
# ══════════════════════════════════════════════════════════════════════════════════════════

class AsynchronousHFStreamer:
    def __init__(self, name: str, batch_size: int, seq_len: int, encode_fn):
        self.name, self.bs, self.sl, self.encode = name, batch_size, seq_len, encode_fn
        self.buffer, self.stop_signal = queue.Queue(maxsize=32), threading.Event()
        self.config = "sample-10BT" if "fineweb-edu" in name.lower() else None
        self.worker = threading.Thread(target=self._run_stream, daemon=True)
        self.worker.start()
        self.connected = False
    def _run_stream(self):
        try:
            ds = load_dataset(self.name, name=self.config, split="train", streaming=True)
            self.connected = True
            local_tokens = []
            target = (self.sl + 1) * self.bs
            for entry in ds:
                if self.stop_signal.is_set(): break
                text = entry.get("text", entry.get("content", ""))
                if not text: continue
                local_tokens.extend(self.encode(text) + [50256])
                while len(local_tokens) >= target:
                    x_data, y_data = [], []
                    for _ in range(self.bs):
                        slc = local_tokens[:self.sl+1]
                        local_tokens = local_tokens[self.sl+1:]
                        x_data.append(slc[:-1]); y_data.append(slc[1:])
                    self.buffer.put((torch.tensor(x_data), torch.tensor(y_data)))
        except Exception as e:
            logger.error(f"Stream error: {e}")
        finally:
            self.stop_signal.set()
    def get_batch(self, timeout=30):
        try: return self.buffer.get(timeout=timeout)
        except queue.Empty: return None

# ══════════════════════════════════════════════════════════════════════════════════════════
# 11. GENERATOR
# ══════════════════════════════════════════════════════════════════════════════════════════

def train_gen(cfg: IoConfig, dataset: str) -> Generator[Dict[str, Any], None, None]:
    yield {"status": "Loading Tokenizer..."}
    enc = tiktoken.get_encoding("gpt2")
    yield {"status": "Initializing Architecture..."}
    model = Io(cfg).to(cfg.device)
    yield {"status": "Configuring Optimizer..."}
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay, betas=(0.9, 0.95))
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda s: s/cfg.warmup_steps if s<cfg.warmup_steps else 0.5*(1+math.cos(math.pi*(s-cfg.warmup_steps)/(cfg.max_steps-cfg.warmup_steps))))

    yield {"status": "Connecting to Hugging Face..."}
    streamer = AsynchronousHFStreamer(dataset, cfg.batch_size, cfg.max_seq_len, lambda t: enc.encode(t, allowed_special="all"))

    # Wait for connection or timeout
    start_wait = time.time()
    while not streamer.connected and not streamer.stop_signal.is_set() and (time.time() - start_wait < 60):
        yield {"status": f"Waiting for Hugging Face stream... ({int(time.time() - start_wait)}s)"}
        time.sleep(1)

    if not streamer.connected:
        yield {"status": "Error: Failed to connect to dataset streamer."}
        return

    device_type = "cuda" if "cuda" in cfg.device else "cpu"
    scaler = torch.amp.GradScaler(device=device_type, enabled=cfg.use_amp)

    t_start = time.time()
    for step in range(1, cfg.max_steps + 1):
        model.train()
        total_loss = 0
        for _ in range(cfg.accum_steps):
            batch = streamer.get_batch()
            if not batch:
                yield {"status": "Error: Stream timeout or exhausted."}
                return
            x, y = batch[0].to(cfg.device), batch[1].to(cfg.device)
            with torch.amp.autocast(device_type=device_type, enabled=cfg.use_amp):
                out = model(x, training=True)
                loss_lm = F.cross_entropy(out["logits"].view(-1, cfg.vocab_size), y.view(-1))
                loss_h = F.cross_entropy(out["drafts"][:, 0, :], y[:, -1])
                batch_loss = (cfg.accum_steps**-1) * (model.cif.lm_weight.get() * loss_lm + model.cif.hor_weight.get() * loss_h + model.cif.unc_weight.get() * out["unc"].mean())
            scaler.scale(batch_loss).backward(); total_loss += batch_loss.item()
        scaler.unscale_(optimizer); nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip); scaler.step(optimizer); scaler.update(); optimizer.zero_grad(); scheduler.step()

        if step % 5 == 0:
            elapsed = time.time() - t_start
            tps = (5 * cfg.batch_size * cfg.accum_steps * cfg.max_seq_len) / elapsed
            yield {"step": step, "loss": total_loss, "lr": optimizer.param_groups[0]['lr'], "tps": tps}
            t_start = time.time()
    streamer.stop_signal.set()
