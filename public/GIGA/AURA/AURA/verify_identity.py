import sys
import os
from pathlib import Path

# Add current dir to sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from aura_folder import FolderAura
from aura_field import _enc, _dec, MSG_ANNOUNCE

def test_identity():
    # 1. Test key generation
    test_node = Path("./test_node")
    if test_node.exists():
        import shutil
        shutil.rmtree(test_node)
    test_node.mkdir()
    
    fa = FolderAura(str(test_node))
    fa.scan()
    
    identity_dir = test_node / ".aura"
    assert identity_dir.exists()
    assert (identity_dir / "identity.key").exists()
    assert (identity_dir / "aura.pub").exists()
    print("✓ Keys generated and stored")
    
    priv = fa.get_private_key()
    pub_bytes = fa.get_public_key_bytes()
    
    # 2. Test signing and verification
    payload = {"hello": "world"}
    pkt = _enc(MSG_ANNOUNCE, payload, priv)
    
    mtype, decoded_payload = _dec(pkt)
    assert mtype == MSG_ANNOUNCE
    assert decoded_payload["hello"] == "world"
    assert decoded_payload["_verified"] == True
    print("✓ Signature verified")
    
    # 3. Test verification failure
    # Tamper with the body
    magic = pkt[:2]
    ver = pkt[2:3]
    mtype = pkt[3:4]
    lengths = pkt[4:8]
    sig_len = 64 # Ed25519 sig is 64 bytes
    sig = pkt[8:8+sig_len]
    body = pkt[8+sig_len:]
    
    tampered_body = body[:-1] + (b'\0' if body[-1] != 0 else b'\1')
    tampered_pkt = magic + ver + mtype + lengths + sig + tampered_body
    
    res = _dec(tampered_pkt)
    # _dec returns None if verification fails because public_key.verify raises InvalidSignature
    assert res is None
    print("✓ Tampered message rejected")

if __name__ == "__main__":
    try:
        test_identity()
        print("\nALL IDENTITY TESTS PASSED")
    except Exception as e:
        print(f"\nTESTS FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
