import sys
import os
from pathlib import Path
import shutil
import base64
import json

# Add current dir to sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from aura_folder import FolderAura
from aura_field import AuraField, MSG_ROUTE, MSG_ANNOUNCE, _enc, _dec

def test_production_readiness():
    test_root = Path("./prod_test")
    if test_root.exists(): shutil.rmtree(test_root)
    test_root.mkdir()

    node1_path = test_root / "node1"
    node2_path = test_root / "node2"
    node1_path.mkdir()
    node2_path.mkdir()

    # 1. Identity & Encryption
    fa1 = FolderAura(str(node1_path)).scan()
    fa2 = FolderAura(str(node2_path)).scan()

    field1 = AuraField(str(node1_path), channel="prod")
    field2 = AuraField(str(node2_path), channel="prod")

    # Verify node_id derivation
    assert len(field1.node_id) == 16

    # Verify logging
    field1._log("Test log entry")
    log_file = node1_path / ".aura" / "field.log"
    assert log_file.exists()
    assert "Test log entry" in log_file.read_text()
    print("✓ Logging works")

    # 2. Encrypted Routing
    field1.peers[field2.node_id] = {
        "name": "node2",
        "x_pub": base64.b64encode(fa2.get_x_public_key_bytes()).decode(),
        "summary": {"path": str(node2_path)}
    }

    secret_file = node1_path / "top_secret.txt"
    secret_file.write_text("ChaCha20-Poly1305 is cool")

    # Capture packet
    captured_pkt = None

    def mock_send(mtype, payload):
        nonlocal captured_pkt
        captured_pkt = _enc(mtype, payload, fa1.get_private_key())

    field1._send = mock_send

    field1.route_file(field2.node_id, str(secret_file))

    # Decrypt and verify
    mtype, payload = _dec(captured_pkt)
    assert mtype == MSG_ROUTE
    assert payload["encrypted"] == True
    print("✓ Packet encrypted and signed")

    # Manually populate peer in field2 as well
    field2.peers[field1.node_id] = {
        "name": "node1",
        "x_pub": base64.b64encode(fa1.get_x_public_key_bytes()).decode(),
        "summary": {"path": str(node1_path)}
    }

    field2._handle(MSG_ROUTE, payload, "127.0.0.1")
    received = node2_path / "in" / "top_secret.txt"
    if not received.exists():
        print(f"DEBUG: {list( (node2_path / 'in').iterdir() )}")
    assert received.exists()
    assert received.read_text() == "ChaCha20-Poly1305 is cool"
    print("✓ Packet verified and decrypted")

    # 3. Channels
    assert field1.field_group != "239.77.77.77" # default
    print("✓ Custom channels work")

if __name__ == "__main__":
    try:
        test_production_readiness()
        print("\nALL PRODUCTION TESTS PASSED")
    except Exception as e:
        print(f"\nTESTS FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
