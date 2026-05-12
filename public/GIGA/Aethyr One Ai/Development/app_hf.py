import gradio as gr
import torch
import time
import sys
import logging
from io_v1_hf import IoConfig, train_gen

# Configure UI Logging
class UIHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
    def emit(self, record):
        msg = self.format(record)
        self.callback(msg)

def start_training():
    # Use small config for demonstration if CPU
    device = "cuda" if torch.cuda.is_available() else "cpu"
    cfg = IoConfig(
        device=device,
        batch_size=1 if device == "cpu" else 4,
        n_layers=4 if device == "cpu" else 16,
        d_model=128 if device == "cpu" else 512,
        max_seq_len=128 if device == "cpu" else 1024,
        max_steps=500
    )

    logs = []

    def log_callback(msg):
        logs.append(msg)

    ui_handler = UIHandler(log_callback)
    ui_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
    logging.getLogger("Io-HST").addHandler(ui_handler)

    yield "Initializing extension modules...\n"
    # Simulating the log entry seen in the screenshot
    yield "Extension modules: numpy.core._multiarray_umath, numpy.core._multiarray_tests, numpy.linalg._umath_linalg, ...\n"

    generator = train_gen(cfg, "HuggingFaceFW/fineweb-edu")

    for update in generator:
        if "status" in update:
            logs.append(f">>> {update['status']}")
        else:
            logs.append(f"Step {update['step']:4d} | Loss: {update['loss']:.4f} | TPS: {update['tps']:.1f}")

        yield "\n".join(logs[-20:]) # Show last 20 lines

with gr.Blocks(title="Io v1.0 HST Trainer", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🪐 Io v1.0 — High-Speculative Topology")
    gr.Markdown("Training Unified HST Architecture optimized for Hugging Face servers.")

    with gr.Column():
        training_logs = gr.Code(
            label="Training Logs",
            value="Ready to start training...",
            language="shell",
            lines=15
        )

        start_btn = gr.Button("Start CPU Training", variant="primary")

    start_btn.click(
        fn=start_training,
        outputs=training_logs
    )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
