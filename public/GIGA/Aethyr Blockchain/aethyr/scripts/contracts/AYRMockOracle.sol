// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// ================================================================
// AYRMockOracle — Price Oracle for AYR Swap Router
//
// Stores USD prices for each supported asset (8 decimal precision,
// matching Chainlink's format). Owner updates prices from the node
// process which polls CoinGecko every 60s.
//
// In production this would be replaced with a decentralised oracle
// (Chainlink / Pyth). For now it's owner-controlled.
//
// Prices: USD value with 8 decimals
//   e.g. BTC = $84,000 → stored as 8_400_000_000_000 (84000 * 1e8)
// ================================================================

contract AYRMockOracle {

    address public owner;

    // symbol => USD price (8 decimals)
    mapping(string => uint256) private prices;
    // symbol => last update timestamp
    mapping(string => uint256) public lastUpdated;
    // Authorized updaters (node hot wallet)
    mapping(address => bool)   public updaters;

    // Staleness threshold: 10 minutes
    uint256 public constant STALE_AFTER = 600;

    event PriceUpdated(string indexed symbol, uint256 price, uint256 timestamp);
    event UpdaterChanged(address updater, bool status);

    modifier onlyOwner() {
        require(msg.sender == owner, "Oracle: not owner");
        _;
    }

    modifier onlyUpdater() {
        require(updaters[msg.sender] || msg.sender == owner, "Oracle: not updater");
        _;
    }

    constructor() {
        owner = msg.sender;
        updaters[msg.sender] = true;

        // Seed reasonable initial prices so SwapRouter works immediately
        // Node process will overwrite these with live data within 60s
        _setPrice("BTC",   8_400_000_000_000); // $84,000
        _setPrice("ETH",   2_000_000_000_000); // $2,000
        _setPrice("SOL",      14_000_000_000); // $140
        _setPrice("BNB",     600_000_000_000); // $600
        _setPrice("MATIC",     100_000_000_0); // $0.10 — note: 8 decimals, $0.10 = 10_000_000
        _setPrice("ARB",       100_000_000_0); // $1.00 = 100_000_000
        _setPrice("AYR",       100_000_000_0); // $1.00 synthetic peg
    }

    function _setPrice(string memory symbol, uint256 price) internal {
        prices[symbol]      = price;
        lastUpdated[symbol] = block.timestamp;
    }

    // ── Admin ──────────────────────────────────────────────────────

    function setUpdater(address updater, bool status) external onlyOwner {
        updaters[updater] = status;
        emit UpdaterChanged(updater, status);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "Oracle: zero address");
        owner = newOwner;
    }

    // ── Price updates ─────────────────────────────────────────────

    function setPrice(string calldata symbol, uint256 price) external onlyUpdater {
        require(price > 0, "Oracle: zero price");
        _setPrice(symbol, price);
        emit PriceUpdated(symbol, price, block.timestamp);
    }

    // Batch update — used by node process to push all prices in one tx
    function setPrices(
        string[]  calldata symbols,
        uint256[] calldata newPrices
    ) external onlyUpdater {
        require(symbols.length == newPrices.length, "Oracle: length mismatch");
        for (uint i = 0; i < symbols.length; i++) {
            require(newPrices[i] > 0, "Oracle: zero price");
            _setPrice(symbols[i], newPrices[i]);
            emit PriceUpdated(symbols[i], newPrices[i], block.timestamp);
        }
    }

    // ── Read ──────────────────────────────────────────────────────

    // Returns price in USD with 8 decimals.
    // Returns 0 if price is stale (> STALE_AFTER seconds old).
    function getPrice(string calldata symbol) external view returns (uint256) {
        if (block.timestamp - lastUpdated[symbol] > STALE_AFTER) return 0;
        return prices[symbol];
    }

    // Returns price without staleness check (for read-only display)
    function getPriceRaw(string calldata symbol) external view returns (uint256 price, uint256 age) {
        price = prices[symbol];
        age   = block.timestamp - lastUpdated[symbol];
    }

    function isStale(string calldata symbol) external view returns (bool) {
        return block.timestamp - lastUpdated[symbol] > STALE_AFTER;
    }
}
