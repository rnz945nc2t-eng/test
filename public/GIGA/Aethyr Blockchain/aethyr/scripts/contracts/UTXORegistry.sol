// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// ================================================================
// UTXORegistry — Bitcoin Containment Protocol
//
// Tracks Bitcoin UTXOs that have been activated as native AYR
// objects. The Bitcoin UTXO stays on Bitcoin — this contract
// records that it has been claimed and extended into AYR's state.
//
// FUNCTION SIGNATURES (must match utxo_native.js hardcoded selectors):
//   activateUTXO(bytes32,uint16,address,uint256)  → selector: a4f17e42
//   deactivateUTXO(bytes32,uint16)                → selector: c3f44c5a
//
// Access:
//   - Only authorized relayers can activate/deactivate.
//   - Owner can add/remove relayers.
//   - Anyone can query UTXO status.
// ================================================================

contract UTXORegistry {

    address public owner;

    struct UTXO {
        address owner;       // AYR address that activated this UTXO
        uint256 valueSats;   // Value in satoshis (stays on Bitcoin)
        uint64  activatedAt; // Block number when activated
        bool    active;      // false = deactivated (spent on Bitcoin)
    }

    // txid ++ vout → UTXO
    mapping(bytes32 => UTXO) public utxos;
    // Authorized relayers (node's hot wallet)
    mapping(address => bool) public relayers;
    // Total active UTXOs
    uint256 public activeCount;
    // Total satoshis contained (informational)
    uint256 public totalSats;

    event UTXOActivated(
        bytes32 indexed txid,
        uint16  indexed vout,
        address         owner,
        uint256         valueSats,
        uint256         blockNumber
    );
    event UTXODeactivated(
        bytes32 indexed txid,
        uint16  indexed vout,
        address         owner,
        string          reason
    );
    event RelayerUpdated(address relayer, bool status);

    modifier onlyOwner() {
        require(msg.sender == owner, "UTXORegistry: not owner");
        _;
    }

    modifier onlyRelayer() {
        require(relayers[msg.sender] || msg.sender == owner, "UTXORegistry: not relayer");
        _;
    }

    constructor(address _owner) {
        owner = _owner;
        relayers[_owner] = true;
    }

    // ── Admin ──────────────────────────────────────────────────────

    function setRelayer(address relayer, bool status) external onlyOwner {
        relayers[relayer] = status;
        emit RelayerUpdated(relayer, status);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "UTXORegistry: zero address");
        owner = newOwner;
    }

    // ── Internal key ──────────────────────────────────────────────

    function _key(bytes32 txid, uint16 vout) internal pure returns (bytes32) {
        return keccak256(abi.encodePacked(txid, vout));
    }

    // ── Core: Activate ────────────────────────────────────────────
    // Called by the AYR node after full SPV verification.
    // selector: keccak256("activateUTXO(bytes32,uint16,address,uint256)")[0:4] = a4f17e42
    //
    // Parameters:
    //   txid       — Bitcoin transaction ID (bytes32, big-endian)
    //   vout       — Output index
    //   owner      — AYR address receiving this UTXO as a native object
    //   valueSats  — Value in satoshis (read-only, stays on Bitcoin)
    function activateUTXO(
        bytes32 txid,
        uint16  vout,
        address utxoOwner,
        uint256 valueSats
    ) external onlyRelayer {
        bytes32 key = _key(txid, vout);
        require(!utxos[key].active, "UTXORegistry: already active");
        require(utxoOwner != address(0), "UTXORegistry: zero owner");
        require(valueSats > 0, "UTXORegistry: zero value");

        utxos[key] = UTXO({
            owner:       utxoOwner,
            valueSats:   valueSats,
            activatedAt: uint64(block.number),
            active:      true
        });

        activeCount++;
        totalSats += valueSats;

        emit UTXOActivated(txid, vout, utxoOwner, valueSats, block.number);
    }

    // ── Core: Deactivate ──────────────────────────────────────────
    // Called when the UTXO is detected as spent on Bitcoin.
    // The double-spend watchdog in utxo_native.js triggers this.
    // selector: keccak256("deactivateUTXO(bytes32,uint16)")[0:4] = c3f44c5a
    function deactivateUTXO(
        bytes32 txid,
        uint16  vout
    ) external onlyRelayer {
        bytes32 key = _key(txid, vout);
        UTXO storage u = utxos[key];
        require(u.active, "UTXORegistry: not active");

        address prevOwner = u.owner;
        totalSats -= u.valueSats;
        u.active = false;
        activeCount--;

        emit UTXODeactivated(txid, vout, prevOwner, "spent on Bitcoin");
    }

    // ── Views ─────────────────────────────────────────────────────

    function isActive(bytes32 txid, uint16 vout) external view returns (bool) {
        return utxos[_key(txid, vout)].active;
    }

    function getUTXO(bytes32 txid, uint16 vout) external view returns (
        address utxoOwner,
        uint256 valueSats,
        uint64  activatedAt,
        bool    active
    ) {
        UTXO storage u = utxos[_key(txid, vout)];
        return (u.owner, u.valueSats, u.activatedAt, u.active);
    }

    // Returns total BTC value contained in satoshis and BTC
    function totalContainedBTC() external view returns (uint256 sats, uint256 btcWhole, uint256 btcFrac) {
        sats     = totalSats;
        btcWhole = totalSats / 1e8;
        btcFrac  = totalSats % 1e8;
    }
}
