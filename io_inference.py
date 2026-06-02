import torch
import sys
import os

# Add the directory containing the model to the path
sys.path.append(os.path.join(os.getcwd(), "public/GIGA/Aethyr One Ai"))
from hst_v8_pytorch_closed_if import HSTv8Crystalline, HSTv8Config

def run_inference():
    # 1. Same configuration as training
    config = HSTv8Config(
        vocab_size=256,
        d_model=64,
        n_heads=4,
        n_layers=2,
        d_ffn=128,
        lattice_depth=16,
        max_seq_len=64
    )

    device = torch.device("cpu")
    model = HSTv8Crystalline(config).to(device)

    # 2. Load the trained weights
    model.load_state_dict(torch.load("io_small_model.pt", map_location=device))
    model.eval()

    # 3. Test generation: start with [10, 11, 12] and expect [13, 14, 15, ...]
    prompt = torch.tensor([[10, 11, 12]], device=device)
    print(f"Prompt: {prompt.tolist()[0]}")

    generated = model.generate(prompt, max_new_tokens=10, temperature=0.1) # low temp for consistency
    print(f"Generated sequence: {generated.tolist()[0]}")

    # Verify if it roughly follows the counting pattern
    gen_list = generated.tolist()[0]
    is_counting = all(gen_list[i] < gen_list[i+1] for i in range(len(gen_list)-1))

    if is_counting:
        print("✓ Model successfully learned the counting pattern!")
    else:
        print("⚠ Model output doesn't perfectly follow the pattern, but generation is functional.")

if __name__ == "__main__":
    run_inference()
