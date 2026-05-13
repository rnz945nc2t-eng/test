"""
Io v1.4 PRO EDITION (Colab Ready)
Official Google Colab Training Script (BUG-FIXED & OPTIMIZED)
Optimized for Tesla T4 (16GB VRAM)

Architecture: Io v1.4 (Sacred Crystalline)
- Pell-Lucas Time Spine (Lattice PE)
- Diamond Mixer (Lossless Logic)
- Feedback Loop (Self-Correction)
- Hebbian Fast Weights (Plasticity)
- Closed IF Set (CIF) Optimizations

Hardware Target: ~12GB VRAM Utilization
Dataset: HuggingFaceFW/fineweb-edu (Sample-10BT)
"""

import os
import gc
import math
import time
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from typing import Optional, List, Tuple, Dict, Callable
from dataclasses import dataclass
from torch.amp import autocast, GradScaler
from transformers import get_linear_schedule_with_warmup
from datasets import load_dataset
from tqdm import tqdm
import tiktoken

# ══════════════════════════════════════════════════════════════════════
# 0.  CLOSED IF SET (CIF)
# ══════════════════════════════════════════════════════════════════════
class _CIF:
    __slots__ = ("value", "cache")
    def __init__(self, v): self.value = v; self.cache = None

class Affirm(_CIF):
    def test(self, fn): return fn(self.value)
    def flip(self): return Deny(self.value)

class Deny(_CIF):
    def test(self, fn):
        if self.cache is None: self.cache = not fn(self.value)
        return self.cache
    def flip(self): return Affirm(self.value)

class CIFScalar:
    __slots__ = ("_fn", "_val", "_done")
    def __init__(self, fn: Callable):
        self._fn = fn; self._val = None; self._done = False
    def get(self):
        if not self._done: self._val = self._fn(); self._done = True
        return self._val

class CIFRegistry:
    def __init__(self, cfg):
        c = cfg
        self.head_dim   = CIFScalar(lambda: c.d_model // c.n_heads)
        self.attn_scale = CIFScalar(lambda: 1.0 / math.sqrt(c.d_model // c.n_heads))
        self.lm_w       = CIFScalar(lambda: 1.0)
        self.hor_w      = CIFScalar(lambda: 0.1)
        self.unc_w      = CIFScalar(lambda: 0.005)
        self.hebb_decay = CIFScalar(lambda: c.hebbian_decay)
        self.fb_iters   = CIFScalar(lambda: c.fb_iterations)
        self.top_k      = CIFScalar(lambda: min(c.top_k, c.vocab_size))
        self.log_vocab  = CIFScalar(lambda: math.log(c.vocab_size))

# ══════════════════════════════════════════════════════════════════════
# 1.  CONFIG
# ══════════════════════════════════════════════════════════════════════
@dataclass
class IoConfig:
    vocab_size:        int   = 50257
    d_model:           int   = 768   # Balanced for T4
    n_heads:           int   = 12    # d_model // n_heads = 64
    n_layers:          int   = 20    # Balanced for T4
    max_seq_len:       int   = 512
    dropout:           float = 0.1
    max_horizon:       int   = 8
    fb_iterations:     int   = 1
    hebbian_decay:     float = 0.95
    lr:                float = 2e-4
    weight_decay:      float = 0.1
    max_steps:         int   = 1000
    batch_size:        int   = 4
    grad_accum:        int   = 8     # effective batch = 32
    grad_clip:         float = 1.0
    warmup_steps:      int   = 100
    horizon_warmup:    int   = 200
    temperature:       float = 0.85
    top_k:             int   = 40
    top_p:             float = 0.9

# ══════════════════════════════════════════════════════════════════════
# 2.  COMPONENTS
# ══════════════════════════════════════════════════════════════════════
def build_spine(max_len: int) -> List[int]:
    s = [0, 2, 4]
    while s[-1] < max_len:
        next_val = 2 * s[-1] + s[-2]
        if next_val >= max_len: break
        s.append(next_val)
    return [v for v in s if v < max_len]

class LatticePositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_seq_len: int):
        super().__init__()
        half = d_model // 2
        pe = torch.zeros(max_seq_len, half)
        pos = torch.arange(max_seq_len).unsqueeze(1).float()
        div = torch.exp(torch.arange(0, half, 2).float() * -(math.log(10000.0) / half))
        pe[:, 0::2] = torch.sin(pos * div)
        pe[:, 1::2] = torch.cos(pos * div[:half//2] if half % 2 else div)
        self.register_buffer("abs_pe", pe)
        self.lattice_enc = nn.Sequential(nn.Linear(3, half), nn.LayerNorm(half), nn.GELU(), nn.Linear(half, half))
        spine = build_spine(max_seq_len)
        self.register_buffer("spine_t", torch.tensor(spine, dtype=torch.float32))

    def forward(self, positions: torch.Tensor) -> torch.Tensor:
        B, S = positions.shape
        abs_p = self.abs_pe[positions.clamp(max=self.abs_pe.size(0)-1)]
        pf = positions.float().unsqueeze(-1)
        sp = self.spine_t
        mask = (sp.view(1,1,-1) <= pf)
        l_idx = mask.sum(dim=-1).clamp(min=1) - 1
        l_val = sp[l_idx]
        r_idx = (l_idx + 1).clamp(max=sp.size(0)-1)
        r_val = sp[r_idx]
        feats = torch.stack([pf.squeeze(-1) - l_val, r_val - pf.squeeze(-1), l_idx.float()], dim=-1)
        lat_p = self.lattice_enc(feats)
        return torch.cat([abs_p, lat_p], dim=-1)

class HyperbolicEmbedding(nn.Module):
    def __init__(self, vocab_size: int, d_model: int):
        super().__init__()
        self.embed = nn.Embedding(vocab_size, d_model)
        self.scale = nn.Parameter(torch.ones(d_model))
        self.norm = nn.LayerNorm(d_model)
        nn.init.normal_(self.embed.weight, 0, 0.02)
    def forward(self, ids: torch.Tensor) -> torch.Tensor:
        x = self.embed(ids) * self.scale
        x = self.norm(x)
        nrm = x.norm(dim=-1, keepdim=True).clamp(min=1e-6)
        return x * (torch.tanh(nrm) / nrm)

class FlashAttention(nn.Module):
    def __init__(self, d_model: int, n_heads: int, cif: CIFRegistry, dropout: float = 0.1):
        super().__init__()
        self._cif, self.nh = cif, n_heads
        # Robust head_dim check
        if d_model % n_heads != 0:
            raise ValueError(f"d_model ({d_model}) must be divisible by n_heads ({n_heads})")
        self.hd = d_model // n_heads
        self.scale = 1.0 / math.sqrt(self.hd)
        self.qkv = nn.Linear(d_model, d_model * 3, bias=False)
        self.proj = nn.Linear(d_model, d_model, bias=False)
        self.norm = nn.LayerNorm(d_model)
        self.drop = nn.Dropout(dropout)
    def forward(self, x: torch.Tensor, layer_past: Optional[Tuple] = None) -> Tuple[torch.Tensor, Tuple]:
        B, S, D = x.shape
        h = self.norm(x)
        qkv = self.qkv(h).reshape(B, S, 3, self.nh, self.hd)
        q, k, v = qkv.permute(2, 0, 3, 1, 4)
        if layer_past: k, v = torch.cat([layer_past[0], k], dim=2), torch.cat([layer_past[1], v], dim=2)
        present = (k.detach(), v.detach())
        out = F.scaled_dot_product_attention(q, k, v, is_causal=(layer_past is None), dropout_p=self.drop.p if self.training else 0.0)
        return x + self.proj(out.transpose(1, 2).reshape(B, S, D)), present

class DiamondMixer(nn.Module):
    def __init__(self, d_model: int, cif: CIFRegistry):
        super().__init__()
        self.norm, self.split, self.merge = nn.LayerNorm(d_model), nn.Linear(d_model, d_model * 2), nn.Linear(d_model * 2, d_model)
        self.drop = nn.Dropout(0.1)
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.norm(x)
        a, b = self.split(h).chunk(2, dim=-1)
        return x + self.drop(self.merge(torch.cat([F.gelu(a + b), F.gelu(b - a)], dim=-1)))

class FeedbackLoop(nn.Module):
    def __init__(self, d_model: int, cif: CIFRegistry):
        super().__init__()
        self._iters, self.norm, self.cell, self.err = cif.fb_iters.get(), nn.LayerNorm(d_model), nn.GRUCell(d_model, d_model), nn.Linear(d_model, 1)
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, S, D = x.shape
        h = self.norm(x).reshape(-1, D)
        for _ in range(self._iters):
            g = torch.sigmoid(self.err(h))
            h = (1 - g) * h + g * self.cell(h, h)
        return x + h.view(B, S, D) - self.norm(x)

class HebbianFastWeights(nn.Module):
    def __init__(self, d_model: int, cif: CIFRegistry):
        super().__init__()
        self.decay, self.norm, self.qkv, self.out = cif.hebb_decay.get(), nn.LayerNorm(d_model), nn.Linear(d_model, d_model * 3, bias=False), nn.Linear(d_model, d_model, bias=False)
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, S, D = x.shape
        h = self.norm(x)
        q, k, v = self.qkv(h).reshape(B, S, 3, D).permute(2,0,1,3)
        kv = torch.einsum("bsd,bse->bde", k, v) * self.decay
        ctx = torch.einsum("bsd,bde->bse", q, kv)
        lr = torch.sigmoid((q * k).sum(-1, keepdim=True))
        return x + self.out(ctx * lr)

class HorizonHead(nn.Module):
    def __init__(self, d_model: int, vocab_size: int, max_horizon: int):
        super().__init__()
        self.max_h, self.vs, bot = max_horizon, vocab_size, 128
        self.unc = nn.Sequential(nn.Linear(d_model, 64), nn.GELU(), nn.Linear(64, 1), nn.Sigmoid())
        self.enc = nn.Sequential(nn.Linear(d_model, bot), nn.LayerNorm(bot), nn.GELU())
        self.proj = nn.Linear(bot, vocab_size, bias=False)
        self.step_emb = nn.Embedding(max_horizon, bot)
    def forward(self, h: torch.Tensor):
        ht = h[:, -1, :].detach()
        u = self.unc(ht)
        bh = self.enc(ht).unsqueeze(1) + self.step_emb(torch.arange(self.max_h, device=h.device)).unsqueeze(0)
        return self.proj(bh), (self.max_h * (1-u)).long().clamp(2, self.max_h).squeeze(-1), u

class Block(nn.Module):
    def __init__(self, d_model: int, n_heads: int, cif: CIFRegistry, dropout: float = 0.1):
        super().__init__()
        self.attn, self.mixer = FlashAttention(d_model, n_heads, cif, dropout), DiamondMixer(d_model, cif)
    def forward(self, x, layer_past=None):
        x, pres = self.attn(x, layer_past)
        return self.mixer(x), pres

class Io(nn.Module):
    def __init__(self, cfg: IoConfig):
        super().__init__()
        self.cfg, self.cif = cfg, CIFRegistry(cfg)
        self.embed, self.pos_enc, self.drop = HyperbolicEmbedding(cfg.vocab_size, cfg.d_model), LatticePositionalEncoding(cfg.d_model, cfg.max_seq_len), nn.Dropout(cfg.dropout)
        self.blocks = nn.ModuleList([Block(cfg.d_model, cfg.n_heads, self.cif, cfg.dropout) for _ in range(cfg.n_layers)])
        self.feedback, self.hebbian = FeedbackLoop(cfg.d_model, self.cif), HebbianFastWeights(cfg.d_model, self.cif)
        self.out_norm, self.lm_head = nn.LayerNorm(cfg.d_model), nn.Linear(cfg.d_model, cfg.vocab_size, bias=False)
        self.lm_head.weight, self.horizon = self.embed.embed.weight, HorizonHead(cfg.d_model, cfg.vocab_size, cfg.max_horizon)
        self._log_vs = self.cif.log_vocab.get()
        self._init_weights()
    def _init_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Linear): nn.init.normal_(m.weight, 0, 0.02); nn.init.zeros_(m.bias) if m.bias is not None else None
    def forward(self, ids: torch.Tensor, cache=None, training: bool = True) -> Dict:
        B, S = ids.shape
        past = cache[0][0].size(2) if cache else 0
        x = self.drop(self.embed(ids) + self.pos_enc(torch.arange(past, past+S, device=ids.device).unsqueeze(0).expand(B,-1)))
        new_cache = []
        for i, blk in enumerate(self.blocks):
            x, pres = blk(x, cache[i] if cache else None)
            new_cache.append(pres)
        h = self.out_norm(self.hebbian(self.feedback(x)))
        lgts, hor_lgts, hor_len, unc = self.lm_head(h), *self.horizon(h)
        with torch.no_grad():
            p = lgts.detach().softmax(-1)
            ent = -(p * (p + 1e-10).log()).sum(-1) / (self._log_vs + 1e-10)
        return {"logits": lgts, "horizon_logits": hor_lgts, "horizon_len": hor_len, "uncertainty": ent, "cache": new_cache}
    @torch.no_grad()
    def generate(self, prompt_ids: torch.Tensor, max_new: int = 100, temperature: float = 0.85, top_k: int = 40, top_p: float = 0.9) -> Tuple[torch.Tensor, dict]:
        self.eval(); ids, cache, generated, tkc = prompt_ids.clone(), None, 0, self.cif.top_k.get()
        out = self(ids, training=False); cache = out["cache"]
        for _ in range(max_new):
            logits = _top_kp(out["logits"][:, -1, :] / (temperature + 1e-10), tkc, top_p)
            next_t = torch.multinomial(logits.softmax(-1), 1)
            ids, generated = torch.cat([ids, next_t], dim=1), generated + 1
            out = self(next_t, cache=cache, training=False); cache = out["cache"]
            if next_t.item() == self.cfg.vocab_size - 1: break
        return ids, {"tokens": generated}

def _top_kp(logits: torch.Tensor, top_k: int, top_p: float) -> torch.Tensor:
    out = logits.clone()
    if top_k > 0: v, _ = torch.topk(out, min(top_k, out.size(-1))); out[out < v[..., -1:]] = float("-inf")
    if top_p < 1.0:
        sl, si = torch.sort(out, descending=True); cum = sl.softmax(-1).cumsum(-1); rem = cum > top_p
        rem[..., 1:], rem[..., 0] = rem[..., :-1].clone(), False
        out.scatter_(-1, si, out.masked_fill(rem, float("-inf")))
    return out

# ══════════════════════════════════════════════════════════════════════
# 3.  LOSS & TRAINING
# ══════════════════════════════════════════════════════════════════════
def compute_loss(out: Dict, targets: torch.Tensor, cif: CIFRegistry, step: int, horizon_warmup: int) -> Tuple[torch.Tensor, Dict]:
    B, S, V = out["logits"].shape
    lm = F.cross_entropy(out["logits"][:, :-1, :].reshape(-1, V), targets[:, 1:].reshape(-1), ignore_index=-1)
    hor = lm.new_tensor(0.0)
    if step >= horizon_warmup:
        H = min(out["horizon_logits"].size(1), S - 1)
        for k in range(H):
            if k + 1 < targets.size(1):
                tgt, mask = targets[:, k+1:k+2].reshape(-1), targets[:, k+1:k+2].reshape(-1) != -1
                if mask.any(): hor = hor + F.cross_entropy(out["horizon_logits"][:, k, :][mask], tgt[mask])
        hor = hor / max(H, 1)
    total = lm + (cif.hor_w.get() * min(1.0, (step - horizon_warmup) / 5000) if step >= horizon_warmup else 0.0) * hor + cif.unc_w.get() * out["uncertainty"].mean()
    return total, {"lm": lm.item(), "hor": hor.item(), "unc": out["uncertainty"].mean().item(), "total": total.item()}

def train():
    cfg = IoConfig()
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {dev}")

    enc = tiktoken.get_encoding("gpt2")
    cfg.vocab_size = enc.n_vocab

    model = Io(cfg).to(dev)
    print(f"Parameters: {sum(p.numel() for p in model.parameters()):,}")

    print("Loading Bulletproof Dataset (FineWeb-Edu)...")
    dataset = load_dataset("HuggingFaceFW/fineweb-edu", "sample-10BT", split="train", streaming=True)

    def get_batches():
        batch_ids = []
        for ex in dataset:
            ids = enc.encode(ex['text'])
            if len(ids) > cfg.max_seq_len + 1:
                start = np.random.randint(0, len(ids) - cfg.max_seq_len - 1)
                batch_ids.append(torch.tensor(ids[start : start + cfg.max_seq_len + 1]))
                if len(batch_ids) == cfg.batch_size:
                    yield torch.stack(batch_ids)
                    batch_ids = []

    batches = get_batches()
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    sched = get_linear_schedule_with_warmup(opt, cfg.warmup_steps, cfg.max_steps)
    scaler = GradScaler()

    pbar = tqdm(total=cfg.max_steps, desc="Io v1.4 PRO Training")
    step, all_tps = 1, []

    try:
        while step <= cfg.max_steps:
            opt.zero_grad()
            step_t0, accum_losses = time.time(), {"total":0., "lm":0.}

            for _ in range(cfg.grad_accum):
                try: batch = next(batches).to(dev)
                except StopIteration: break

                with autocast(device_type=dev.type):
                    out = model(batch[:, :-1])
                    loss, bd = compute_loss(out, batch[:, 1:], model.cif, step, cfg.horizon_warmup)
                    loss = loss / cfg.grad_accum

                scaler.scale(loss).backward()
                accum_losses["total"] += bd["total"] / cfg.grad_accum
                accum_losses["lm"] += bd["lm"] / cfg.grad_accum

            scaler.unscale_(opt); torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
            scaler.step(opt); scaler.update(); opt.zero_grad(); sched.step()

            tps = (cfg.batch_size * cfg.grad_accum * cfg.max_seq_len) / (time.time() - step_t0)
            all_tps.append(tps)
            pbar.set_postfix({"loss": f"{accum_losses['total']:.3f}", "lm": f"{accum_losses['lm']:.3f}", "tps": f"{tps:.1f}"})
            pbar.update(1); step += 1
            if step % 500 == 0: torch.save(model.state_dict(), "io_v1_4_pro.pt")

    except KeyboardInterrupt: pass
    pbar.close(); torch.save(model.state_dict(), "io_v1_4_pro.pt")

    # Final Generation
    prompt = "Artificial intelligence will enable a future where"
    ids = torch.tensor([enc.encode(prompt)], dtype=torch.long, device=dev)
    out_ids, _ = model.generate(ids, max_new=100, temperature=cfg.temperature)
    res_text = enc.decode(out_ids[0].tolist())
    avg_tps = sum(all_tps) / len(all_tps) if all_tps else 0
    print(f"\n[Final Coherence Test]\nAI: {res_text}\nPerformance: {avg_tps:.2f} TPS")

    with open("io_v1_4_report.txt", "w") as f:
        f.write(f"TPS Record: {avg_tps:.2f}\n\nGENERATED TEXT:\n{res_text}")

if __name__ == "__main__":
    train()
