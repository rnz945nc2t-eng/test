"""
Io v1.4 PRO EDITION (Colab Ready)
Official Google Colab Training Script (ULTIMATE CONVERGENCE V2.3)
Optimized for Tesla T4 (16GB VRAM)

Key Fixes & Optimizations:
- BUG FIX: Fixed `permute` error in Hebbian Weights (was duplicating dim index).
- CAUSAL INTEGRITY: Strict Causal Linear-Hebbian implementation via cumulative summation.
- LOSS ALIGNMENT: Guaranteed tokens [0...N-1] predict [1...N].
- SCALE: 145M Parameters (D_MODEL=768, N_LAYERS=20, N_HEADS=12).
- MONITORING: Real-time loss, TPS, and VRAM logging.
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
# 1.  CONFIG
# ══════════════════════════════════════════════════════════════════════
@dataclass
class IoConfig:
    vocab_size:        int   = 50257
    d_model:           int   = 768
    n_heads:           int   = 12
    n_layers:          int   = 20
    max_seq_len:       int   = 512
    dropout:           float = 0.1
    max_horizon:       int   = 8
    fb_iterations:     int   = 1
    hebbian_decay:     float = 0.95
    lr:                float = 1e-4
    weight_decay:      float = 0.1
    max_steps:         int   = 1000
    batch_size:        int   = 4
    grad_accum:        int   = 16
    grad_clip:         float = 1.0
    warmup_steps:      int   = 100
    horizon_warmup:    int   = 200
    temperature:       float = 0.8
    top_k:             int   = 40
    top_p:             float = 0.9

# ══════════════════════════════════════════════════════════════════════
# 2.  ARCHITECTURE
# ══════════════════════════════════════════════════════════════════════
class LatticePositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_seq_len: int):
        super().__init__()
        half = d_model // 2
        pe = torch.zeros(max_seq_len, half)
        pos = torch.arange(max_seq_len).unsqueeze(1).float()
        div = torch.exp(torch.arange(0, half, 2).float() * -(math.log(10000.0) / half))
        pe[:, 0::2] = torch.sin(pos * div); pe[:, 1::2] = torch.cos(pos * div)
        self.register_buffer("abs_pe", pe)
        self.lattice_enc = nn.Sequential(nn.Linear(3, half), nn.LayerNorm(half), nn.GELU(), nn.Linear(half, half))
        s = [0, 2, 4]; [s.append(2*s[-1]+s[-2]) for _ in range(15) if s[-1]<max_seq_len]
        self.register_buffer("spine_t", torch.tensor([v for v in s if v < max_seq_len], dtype=torch.float32))
    def forward(self, positions: torch.Tensor) -> torch.Tensor:
        abs_p = self.abs_pe[positions.clamp(max=self.abs_pe.size(0)-1)]
        pf = positions.float().unsqueeze(-1); sp = self.spine_t
        mask = (sp.view(1,1,-1) <= pf); l_idx = mask.sum(dim=-1).clamp(min=1) - 1
        l_val, r_val = sp[l_idx], sp[(l_idx + 1).clamp(max=sp.size(0)-1)]
        feats = torch.stack([pf.squeeze(-1) - l_val, r_val - pf.squeeze(-1), l_idx.float()], dim=-1)
        return torch.cat([abs_p, self.lattice_enc(feats)], dim=-1)

class HyperbolicEmbedding(nn.Module):
    def __init__(self, vocab_size: int, d_model: int):
        super().__init__()
        self.embed = nn.Embedding(vocab_size, d_model)
        nn.init.normal_(self.embed.weight, 0, 0.02)
    def forward(self, ids: torch.Tensor) -> torch.Tensor:
        x = self.embed(ids); norm = x.norm(dim=-1, keepdim=True).clamp(min=1e-6)
        return x * (torch.tanh(norm) / norm)

class FlashAttention(nn.Module):
    def __init__(self, d_model: int, n_heads: int, dropout: float = 0.1):
        super().__init__()
        self.nh, self.hd = n_heads, d_model // n_heads
        self.qkv, self.proj, self.norm, self.drop = nn.Linear(d_model, d_model * 3, bias=False), nn.Linear(d_model, d_model, bias=False), nn.LayerNorm(d_model), nn.Dropout(dropout)
    def forward(self, x: torch.Tensor, layer_past: Optional[Tuple] = None) -> Tuple[torch.Tensor, Tuple]:
        B, S, D = x.shape; h = self.norm(x)
        qkv = self.qkv(h).reshape(B, S, 3, self.nh, self.hd).permute(2, 0, 3, 1, 4)
        q, k, v = qkv.unbind(0) # Each is [B, nh, S, hd]
        if layer_past: k, v = torch.cat([layer_past[0], k], dim=2), torch.cat([layer_past[1], v], dim=2)
        present = (k.detach(), v.detach())
        out = F.scaled_dot_product_attention(q, k, v, is_causal=(layer_past is None), dropout_p=self.drop.p if self.training else 0.0)
        return x + self.proj(out.transpose(1, 2).reshape(B, S, D)), present

class DiamondMixer(nn.Module):
    def __init__(self, d_model: int, dropout: float = 0.1):
        super().__init__()
        self.norm, self.split, self.merge = nn.LayerNorm(d_model), nn.Linear(d_model, d_model * 2), nn.Linear(d_model * 2, d_model)
        self.drop = nn.Dropout(dropout)
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.norm(x); a, b = self.split(h).chunk(2, dim=-1)
        merged = self.merge(torch.cat([F.gelu(a + b), F.gelu(b - a)], dim=-1))
        return x + self.drop(merged)

class FeedbackLoop(nn.Module):
    def __init__(self, d_model: int, iters: int):
        super().__init__()
        self.iters, self.norm, self.cell, self.err = iters, nn.LayerNorm(d_model), nn.GRUCell(d_model, d_model), nn.Linear(d_model, 1)
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, S, D = x.shape; h_orig = self.norm(x); h = h_orig.reshape(-1, D)
        for _ in range(self.iters):
            g = torch.sigmoid(self.err(h)); h = (1 - g) * h + g * self.cell(h, h)
        return x + (h.reshape(B, S, D) - h_orig)

class HebbianFastWeights(nn.Module):
    def __init__(self, d_model: int, n_heads: int = 8, decay: float = 0.95):
        super().__init__()
        self.nh, self.hd = n_heads, d_model // n_heads
        self.decay, self.norm, self.qkv, self.out = decay, nn.LayerNorm(d_model), nn.Linear(d_model, d_model * 3, bias=False), nn.Linear(d_model, d_model, bias=False)
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, S, D = x.shape; h = self.norm(x)
        # Fix: permute(2, 0, 3, 1, 4) matches FlashAttention
        qkv = self.qkv(h).reshape(B, S, 3, self.nh, self.hd).permute(2, 0, 3, 1, 4)
        q, k, v = qkv.unbind(0) # Each is [B, nh, S, hd]
        # Strict Causal Recurrent Plasticity
        k_s = F.softmax(k, dim=-1)
        # kv_causal: [B, nh, S, hd, hd]
        kv_causal = torch.cumsum(k_s.unsqueeze(-1) * v.unsqueeze(-2), dim=2) * self.decay
        ctx = torch.einsum("bnhd,bnhde->bnhe", q, kv_causal)
        lr = torch.sigmoid((q * k_s).sum(-1, keepdim=True))
        ctx = (ctx * lr).transpose(1, 2).reshape(B, S, D)
        return x + self.out(ctx)

class Block(nn.Module):
    def __init__(self, d_model: int, n_heads: int, dropout: float = 0.1):
        super().__init__()
        self.attn, self.mixer = FlashAttention(d_model, n_heads, dropout), DiamondMixer(d_model, dropout)
    def forward(self, x, layer_past=None):
        x, pres = self.attn(x, layer_past)
        return self.mixer(x), pres

class Io(nn.Module):
    def __init__(self, cfg: IoConfig):
        super().__init__()
        self.cfg = cfg
        self.embed = HyperbolicEmbedding(cfg.vocab_size, cfg.d_model)
        self.pos_enc = LatticePositionalEncoding(cfg.d_model, cfg.max_seq_len)
        self.blocks = nn.ModuleList([Block(cfg.d_model, cfg.n_heads, cfg.dropout) for _ in range(cfg.n_layers)])
        self.feedback = FeedbackLoop(cfg.d_model, cfg.fb_iterations)
        self.hebbian = HebbianFastWeights(cfg.d_model, cfg.n_heads, cfg.hebbian_decay)
        self.out_norm, self.lm_head = nn.LayerNorm(cfg.d_model), nn.Linear(cfg.d_model, cfg.vocab_size, bias=False)
        self.lm_head.weight = self.embed.embed.weight
    def forward(self, ids: torch.Tensor, cache=None) -> Dict:
        B, S = ids.shape; past = cache[0][0].size(2) if cache else 0
        x = self.embed(ids) + self.pos_enc(torch.arange(past, past+S, device=ids.device).unsqueeze(0).expand(B,-1))
        new_cache = []
        for i, blk in enumerate(self.blocks):
            x, pres = blk(x, cache[i] if cache else None)
            new_cache.append(pres)
        h = self.out_norm(self.hebbian(self.feedback(x)))
        return {"logits": self.lm_head(h), "cache": new_cache}
    @torch.no_grad()
    def generate(self, prompt_ids: torch.Tensor, max_new: int = 100, temperature: float = 0.8):
        self.eval(); ids, cache = prompt_ids.clone(), None
        for _ in range(max_new):
            out = self(ids[:, -1:] if cache else ids, cache=cache)
            logits = out["logits"][:, -1, :] / (temperature + 1e-10)
            v, _ = torch.topk(logits, min(40, logits.size(-1))); logits[logits < v[..., -1:]] = float("-inf")
            next_t = torch.multinomial(F.softmax(logits, dim=-1), 1)
            ids, cache = torch.cat([ids, next_t], dim=1), out["cache"]
            if next_t.item() == self.cfg.vocab_size - 1: break
        return ids

# ══════════════════════════════════════════════════════════════════════
# 3.  TRAINING PIPELINE
# ══════════════════════════════════════════════════════════════════════
def train():
    cfg = IoConfig(); dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {dev}"); enc = tiktoken.get_encoding("gpt2"); cfg.vocab_size = enc.n_vocab
    model = Io(cfg).to(dev); print(f"Parameters: {sum(p.numel() for p in model.parameters()):,}")

    dataset = load_dataset("HuggingFaceFW/fineweb-edu", "sample-10BT", split="train", streaming=True)
    def get_batches():
        batch_ids = []
        for ex in dataset:
            tokens = enc.encode(ex['text'])
            if len(tokens) > cfg.max_seq_len + 1:
                idx = np.random.randint(0, len(tokens) - cfg.max_seq_len - 1)
                batch_ids.append(torch.tensor(tokens[idx : idx + cfg.max_seq_len + 1]))
                if len(batch_ids) == cfg.batch_size: yield torch.stack(batch_ids); batch_ids = []

    batches = get_batches(); opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    sched = get_linear_schedule_with_warmup(opt, cfg.warmup_steps, cfg.max_steps); scaler = GradScaler()
    pbar = tqdm(total=cfg.max_steps, desc="Io v1.4 PRO Training")
    step, all_tps = 1, []

    try:
        while step <= cfg.max_steps:
            opt.zero_grad(); step_loss = 0.0; t0 = time.time()
            for _ in range(cfg.grad_accum):
                try: batch = next(batches).to(dev)
                except StopIteration: break
                with autocast(device_type=dev.type):
                    # PRECISE ALIGNMENT: Tokens [0...S-1] predict [1...S]
                    logits = model(batch[:, :-1])["logits"]
                    loss = F.cross_entropy(logits.reshape(-1, cfg.vocab_size), batch[:, 1:].reshape(-1)) / cfg.grad_accum
                scaler.scale(loss).backward(); step_loss += loss.item() * cfg.grad_accum
            scaler.unscale_(opt); torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
            scaler.step(opt); scaler.update(); sched.step(); step += 1
            dt = time.time() - t0; tps = (cfg.batch_size * cfg.grad_accum * cfg.max_seq_len) / dt
            vram = torch.cuda.memory_allocated(dev) / 1e9 if dev.type == "cuda" else 0
            all_tps.append(tps); pbar.set_postfix({"loss": f"{step_loss:.4f}", "tps": f"{tps:.0f}", "vram": f"{vram:.1f}G"}); pbar.update(1)
            if step % 500 == 0: torch.save(model.state_dict(), "io_v1_4_ultimate.pt")
    except KeyboardInterrupt: pass
    pbar.close(); prompt = "Artificial intelligence will enable a future where"
    ids = torch.tensor([enc.encode(prompt)], dtype=torch.long, device=dev); res = enc.decode(model.generate(ids, max_new=100).tolist()[0])
    avg_tps = sum(all_tps) / len(all_tps) if all_tps else 0; print(f"\n[AI]: {res}\nTPS: {avg_tps:.2f}")
    with open("io_v1_4_report.txt", "w") as f: f.write(f"TPS: {avg_tps:.2f}\n\n{res}")

if __name__ == "__main__":
    train()
