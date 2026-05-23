"""
Io v2 Sacred (HST v8.2 Crystalline) - PRO LOCAL EDITION
Optimized for T4 GPU (16GB VRAM) and Local Dataset.

This script implements the full Crystalline Architecture (Pell-Lucas, Diamond Mixer,
Hebbian Plasticity, HyperLattice) and trains exclusively on local repository
documentation for maximum technical resonance.

Architecture:
- D_MODEL: 1024
- N_LAYERS: 24
- Lattice Depth: 128
- Memory: Paged KV Cache
"""

import os
import sys
import gc
import math
import time
import glob
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.amp import autocast, GradScaler
from torch.utils.data import DataLoader, Dataset
from transformers import AutoTokenizer, get_linear_schedule_with_warmup
from tqdm import tqdm
import tiktoken

# ==================== CONFIGURATION ====================
# Scaled up to hit ~12GB VRAM target on T4
D_MODEL = 1024
N_HEADS = 16
N_LAYERS = 24
LATTICE_DEPTH = 128
MAX_SEQ_LEN = 512
VOCAB_SIZE = 50257 # GPT-2
BATCH_SIZE = 4
GRADIENT_ACCUMULATION_STEPS = 8
MAX_TRAINING_STEPS = 500
INITIAL_LR = 1.0e-4
WARMUP_STEPS = 100

DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# ==================== COMPONENTS ====================

class PagedKVCache:
    def __init__(self, head_dim, num_heads, block_size=16, device='cpu'):
        self.head_dim, self.num_heads, self.block_size, self.device = head_dim, num_heads, block_size, device
        self.key_blocks, self.value_blocks, self.current_length = [], [], 0
    def get_length(self): return self.current_length
    def append(self, k, v):
        # k, v: [Batch, Seq, Heads, Dim]
        B, S, H, D = k.shape
        # For simplicity in this demo script, we assume batch size matches the cache instance
        # In a production multi-user system, we'd have a list of caches per batch item.
        tokens_written = 0
        while tokens_written < S:
            if not self.key_blocks or self.key_blocks[-1].size(1) == self.block_size:
                self.key_blocks.append(torch.zeros(B, 0, H, D, device=self.device))
                self.value_blocks.append(torch.zeros(B, 0, H, D, device=self.device))

            space_left = self.block_size - self.key_blocks[-1].size(1)
            to_write = min(space_left, S - tokens_written)

            k_chunk = k[:, tokens_written : tokens_written + to_write]
            v_chunk = v[:, tokens_written : tokens_written + to_write]

            self.key_blocks[-1] = torch.cat([self.key_blocks[-1], k_chunk], dim=1)
            self.value_blocks[-1] = torch.cat([self.value_blocks[-1], v_chunk], dim=1)

            tokens_written += to_write
        self.current_length += S

    def get_all(self):
        if not self.key_blocks: return None, None
        return torch.cat(self.key_blocks, dim=1), torch.cat(self.value_blocks, dim=1)

class HyperbolicEmbedding(nn.Module):
    def __init__(self, vocab_size, d_model, curvature=1.0):
        super().__init__()
        self.embed, self.c = nn.Embedding(vocab_size, d_model), curvature
        nn.init.normal_(self.embed.weight, 0, 0.01)
    def forward(self, x):
        x = self.embed(x)
        scale = torch.clamp(x.norm(dim=-1, keepdim=True) / ((1 - 1e-3) / math.sqrt(self.c)), max=1.0)
        return x / (scale + 1e-8)

class DiamondMixer(nn.Module):
    def __init__(self, d_model):
        super().__init__()
        self.split_proj, self.merge_proj, self.norm = nn.Linear(d_model, d_model * 2), nn.Linear(d_model * 2, d_model), nn.LayerNorm(d_model)
    def forward(self, u):
        x, y = self.split_proj(u).chunk(2, dim=-1)
        return self.norm(u + self.merge_proj(torch.cat([F.gelu(x + y), F.gelu(y - x)], dim=-1)))

class HebbianFastWeights(nn.Module):
    def __init__(self, d_model, lambda_decay=0.95):
        super().__init__()
        self.lambda_decay, self.qkv, self.norm = lambda_decay, nn.Linear(d_model, d_model * 3, bias=False), nn.LayerNorm(d_model)
    def forward(self, x):
        B, S, D = x.shape
        q, k, v = self.qkv(x).reshape(B, S, 3, D).unbind(2)
        kv = torch.einsum('bsd,bse->bde', k, v) * self.lambda_decay
        lr = torch.sigmoid((q * k).sum(dim=-1, keepdim=True))
        return self.norm(x + torch.einsum('bsd,bde->bse', q, kv) * lr)

class HyperLatticeBlock(nn.Module):
    def __init__(self, d_model, lattice_depth=64):
        super().__init__()
        self.lattice_depth, self.gate = lattice_depth, nn.Linear(d_model, lattice_depth, bias=False)
        self.lattice_weights, self.norm = nn.Parameter(torch.randn(lattice_depth, d_model, d_model) * 0.02), nn.LayerNorm(d_model)
    def forward(self, x):
        logits = self.gate(x)
        top_scores, indices = torch.topk(F.softmax(logits, dim=-1), max(1, int(self.lattice_depth * 0.1)), dim=-1)
        output = torch.zeros_like(x)
        for i in range(top_scores.size(-1)):
            # Optimized gather-matmul
            w = self.lattice_weights[indices[:, :, i]] # [B, S, D, D]
            output += torch.matmul(x.unsqueeze(2), w).squeeze(2) * top_scores[:, :, i].unsqueeze(-1)
        return self.norm(x + output)

class CrystallineAttention(nn.Module):
    def __init__(self, d_model, n_heads):
        super().__init__()
        self.n_heads, self.head_dim = n_heads, d_model // n_heads
        self.qkv, self.out_proj = nn.Linear(d_model, d_model * 3, bias=False), nn.Linear(d_model, d_model)
    def forward(self, x, past=None):
        B, S, D = x.shape
        q, k, v = self.qkv(x).reshape(B, S, 3, self.n_heads, self.head_dim).permute(2, 0, 3, 1, 4).unbind(0)
        if past: pk, pv = past; k, v = torch.cat([pk, k], dim=2), torch.cat([pv, v], dim=2)
        present = (k, v)
        out = F.scaled_dot_product_attention(q, k, v, is_causal=(past is None))
        return self.out_proj(out.transpose(1, 2).reshape(B, S, D)), present

class CrystallineBlock(nn.Module):
    def __init__(self, d_model, n_heads):
        super().__init__()
        self.attn, self.mixer, self.hebbian = CrystallineAttention(d_model, n_heads), DiamondMixer(d_model), HebbianFastWeights(d_model)
        self.ln1, self.ln2 = nn.LayerNorm(d_model), nn.LayerNorm(d_model)
    def forward(self, x, past=None):
        a_out, present = self.attn(self.ln1(x), past)
        return self.hebbian(self.ln2(x + a_out)), present

class HSTv8Crystalline(nn.Module):
    def __init__(self, vocab_size, d_model, n_heads, n_layers, lattice_depth=64):
        super().__init__()
        self.d_model, self.n_heads = d_model, n_heads
        self.embedding = HyperbolicEmbedding(vocab_size, d_model)
        self.pos_encoding = nn.Parameter(torch.randn(1, 8192, d_model) * 0.02)
        self.blocks = nn.ModuleList([CrystallineBlock(d_model, n_heads) for _ in range(n_layers)])
        self.lattice, self.ln_f = HyperLatticeBlock(d_model, lattice_depth), nn.LayerNorm(d_model)
        self.lm_head = nn.Linear(d_model, vocab_size, bias=False)
        self.lm_head.weight = self.embedding.embed.weight
    def forward(self, x, cache=None):
        S, past_len = x.size(1), cache[0].get_length() if cache else 0
        x = self.embedding(x) + self.pos_encoding[:, past_len:past_len+S, :]
        for i, block in enumerate(self.blocks):
            layer_past = None
            if cache:
                pk, pv = cache[i].get_all()
                if pk is not None: layer_past = (pk.permute(0, 2, 1, 3), pv.permute(0, 2, 1, 3))
            x, present = block(x, layer_past)
            if cache: cache[i].append(present[0].permute(0, 2, 1, 3)[:, -S:], present[1].permute(0, 2, 1, 3)[:, -S:])
        return {'logits': self.lm_head(self.ln_f(self.lattice(x)))}
    @torch.no_grad()
    def generate(self, prompt_ids, max_new_tokens, temperature=0.7, top_p=0.9):
        self.eval()
        B = prompt_ids.shape[0]
        cache = [PagedKVCache(self.d_model // self.n_heads, self.n_heads, device=prompt_ids.device) for _ in range(len(self.blocks))]
        out = self(prompt_ids, cache=cache)
        logits, generated_ids = out['logits'][:, -1, :], prompt_ids.clone()
        start_time = time.time()
        for _ in range(max_new_tokens):
            probs = F.softmax(logits / temperature, dim=-1)
            sorted_probs, sorted_indices = torch.sort(probs, descending=True)
            cumulative_probs = torch.cumsum(sorted_probs, dim=-1)
            sorted_indices_to_remove = cumulative_probs > top_p
            sorted_indices_to_remove[..., 1:] = sorted_indices_to_remove[..., :-1].clone()
            sorted_indices_to_remove[..., 0] = 0
            indices_to_remove = sorted_indices_to_remove.scatter(1, sorted_indices, sorted_indices_to_remove)
            probs = probs.masked_fill(indices_to_remove, 0.0)
            probs = probs / probs.sum(dim=-1, keepdim=True)
            next_token = torch.multinomial(probs, 1)
            generated_ids = torch.cat([generated_ids, next_token], dim=1)
            logits = self(next_token, cache=cache)['logits'][:, -1, :]
        return generated_ids, max_new_tokens / (time.time() - start_time)

# ==================== DATA LOADING ====================

class LocalRepoDataset(Dataset):
    def __init__(self, root_dir, max_length=512):
        self.tokens = []
        enc = tiktoken.get_encoding("gpt2")
        files = glob.glob(os.path.join(root_dir, "**/*.md"), recursive=True) + \
                glob.glob(os.path.join(root_dir, "**/*.txt"), recursive=True)

        print(f"Indexing {len(files)} local files...")
        combined_text = ""
        for f in files:
            try:
                with open(f, 'r', encoding='utf-8') as file:
                    combined_text += file.read() + "\n<|endoftext|>\n"
            except: continue

        all_tokens = enc.encode(combined_text)
        for i in range(0, len(all_tokens) - max_length, max_length):
            self.tokens.append(torch.tensor(all_tokens[i:i + max_length + 1]))

    def __len__(self): return len(self.tokens)
    def __getitem__(self, idx): return self.tokens[idx]

# ==================== TRAINING LOOP ====================

def main():
    print("Initializing Io v2 Sacred [PRO LOCAL]...")
    model = HSTv8Crystalline(VOCAB_SIZE, D_MODEL, N_HEADS, N_LAYERS, LATTICE_DEPTH).to(DEVICE)

    # Model info
    param_count = sum(p.numel() for p in model.parameters())
    print(f"Model Parameters: {param_count / 1e6:.1f}M")

    optimizer = torch.optim.AdamW(model.parameters(), lr=INITIAL_LR, weight_decay=0.01)
    scaler = GradScaler()

    root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    dataset = LocalRepoDataset(root_path, max_length=MAX_SEQ_LEN)
    loader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True)

    scheduler = get_linear_schedule_with_warmup(optimizer, WARMUP_STEPS, MAX_TRAINING_STEPS)

    print(f"Starting Training on {DEVICE}...")
    model.train()
    step = 0
    pbar = tqdm(total=MAX_TRAINING_STEPS, desc="Training")

    try:
        while step < MAX_TRAINING_STEPS:
            for batch in loader:
                if step >= MAX_TRAINING_STEPS: break

                batch = batch.to(DEVICE)
                input_ids = batch[:, :-1]
                target_ids = batch[:, 1:]

                with autocast(device_type=DEVICE.type if DEVICE.type != 'cpu' else 'cpu'):
                    logits = model(input_ids)['logits']
                    loss = F.cross_entropy(logits.reshape(-1, VOCAB_SIZE), target_ids.reshape(-1)) / GRADIENT_ACCUMULATION_STEPS

                scaler.scale(loss).backward()

                if (step + 1) % GRADIENT_ACCUMULATION_STEPS == 0:
                    scaler.unscale_(optimizer)
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    scaler.step(optimizer)
                    scaler.update()
                    optimizer.zero_grad()
                    scheduler.step()

                    pbar.set_postfix({"loss": f"{loss.item()*GRADIENT_ACCUMULATION_STEPS:.4f}"})
                    pbar.update(GRADIENT_ACCUMULATION_STEPS)

                    if step % (GRADIENT_ACCUMULATION_STEPS * 10) == 0:
                        torch.cuda.empty_cache() if torch.cuda.is_available() else None
                        gc.collect()

                step += 1
    except KeyboardInterrupt:
        print("Training interrupted.")

    pbar.close()
    torch.save(model.state_dict(), "io_sacred_local_pro.pt")

    # Final Test
    print("\n[Final Resonance Test]")
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    prompt = "The HST architecture defines a crystalline"
    input_ids = torch.tensor(tokenizer.encode(prompt)).unsqueeze(0).to(DEVICE)

    output, tps = model.generate(input_ids, max_new_tokens=50, temperature=0.7, top_p=0.9)
    res = tokenizer.decode(output[0].tolist())
    print(f"\nAI: {res}\n\nPerformance: {tps:.2f} TPS")

    with open("io_local_training_report.txt", "w") as f:
        f.write(f"Configuration:\n- D_MODEL: {D_MODEL}\n- N_LAYERS: {N_LAYERS}\n- Params: {param_count/1e6:.1f}M\n")
        f.write(f"TPS Record: {tps:.2f}\n\nGENERATED TEXT:\n{res}")

if __name__ == "__main__":
    main()
