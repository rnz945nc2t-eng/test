import sys
import os
import base64
from pathlib import Path
import shutil

# Add current dir to sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from aura_folder import FolderAura
from aura_field import AuraField, MSG_ROUTE

def test_encryption():
    # Setup two nodes
    node1_path = Path("./node1")
    node2_path = Path("./node2")
    
    for p in [node1_path, node2_path]:
        if p.exists(): shutil.rmtree(p)
        p.mkdir()
    
    fa1 = FolderAura(str(node1_path)).scan()
    fa2 = FolderAura(str(node2_path)).scan()
    
    field1 = AuraField(str(node1_path))
    field2 = AuraField(str(node2_path))
    
    # Manually populate peers so they know each other's x_pub
    field1.peers[field2.node_id] = {
        "name": "node2",
        "x_pub": base64.b64encode(fa2.get_x_public_key_bytes()).decode(),
        "summary": {"path": str(node2_path)}
    }
    field2.peers[field1.node_id] = {
        "name": "node1",
        "x_pub": base64.b64encode(fa1.get_x_public_key_bytes()).decode(),
        "summary": {"path": str(node1_path)}
    }
    
    # Test file
    secret_file = node1_path / "secret.txt"
    secret_file.write_text("TOP SECRET CONTENT")
    
    # Route file (should be encrypted)
    field1.route_file(field2.node_id, str(secret_file))
    
    # In a real field, MSG_ROUTE is broadcasted and handled by _handle
    # Here we simulate the packet flow
    # We need to capture the packet sent by field1
    
    # Let's mock _send to capture the payload
    captured_payload = None
    def mock_send(mtype, payload):
        nonlocal captured_payload
        if mtype == MSG_ROUTE:
            captured_payload = payload
            # Manually add pub and x_pub as _enc would do
            priv = fa1.get_private_key()
            pub_bytes = priv.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw
            )
            captured_payload["pub"] = base64.b64encode(pub_bytes).decode()
            captured_payload["x_pub"] = base64.b64encode(fa1.get_x_public_key_bytes()).decode()

    from cryptography.hazmat.primitives import serialization
    field1._send = mock_send
    field1.route_file(field2.node_id, str(secret_file))
    
    assert captured_payload["encrypted"] == True
    assert captured_payload["content"] != "TOP SECRET CONTENT"
    print("✓ Content is encrypted in transit")
    
    # Now let field2 handle it
    field2._handle(MSG_ROUTE, captured_payload, "127.0.0.1")
    
    received_file = node2_path / "in" / "secret.txt"
    assert received_file.exists()
    assert received_file.read_text() == "TOP SECRET CONTENT"
    print("✓ Content correctly decrypted by recipient")

if __name__ == "__main__":
    try:
        test_encryption()
        print("\nALL ENCRYPTION TESTS PASSED")
    except Exception as e:
        print(f"\nTESTS FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
