// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// ================================================================
// AYROracle — Live price feed, pushed by the AYR node
//
// The node process already fetches prices from CoinGecko and
// exchange APIs via the observer feed. This contract receives
// those prices on-chain. No mock values, no hardcoding.
//
// The node calls setPrices() after every price poll (~60s).
// Prices are USD with 8 decimals (Chainlink standard format).
//
// Staleness: getPrice() returns 0 if price is >10min old.
// The SwapRouter treats a 0 price as a revert — protecting users
// from trading on stale data.
// ================================================================
contract AYROracle {

    address public owner;
    mapping(address => bool) public feeders;  // authorised price pushers (node hot wallet)

    struct Price {
        uint256 value;      // USD price, 8 decimals
        uint256 updatedAt;  // block.timestamp of last push
    }

    mapping(string => Price) private _prices;
    uint256 public constant STALE_AFTER = 600; // 10 minutes

    event PricePushed(string indexed symbol, uint256 price, uint256 timestamp);
    event FeederUpdated(address feeder, bool status);

    modifier onlyOwner()  { require(msg.sender == owner,           "Oracle: not owner");  _; }
    modifier onlyFeeder() { require(feeders[msg.sender] || msg.sender == owner, "Oracle: not feeder"); _; }

    constructor() {
        owner = msg.sender;
        feeders[msg.sender] = true;
    }

    function setFeeder(address feeder, bool status) external onlyOwner {
        feeders[feeder] = status;
        emit FeederUpdated(feeder, status);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "Oracle: zero address");
        owner = newOwner;
    }

    // Called by the node process after each price poll.
    // symbols: ["ETH","AYR"]   prices: [200000000000, 100000000]
    function setPrices(
        string[]  calldata symbols,
        uint256[] calldata prices
    ) external onlyFeeder {
        require(symbols.length == prices.length, "Oracle: length mismatch");
        for (uint i = 0; i < symbols.length; i++) {
            require(prices[i] > 0, "Oracle: zero price rejected");
            _prices[symbols[i]] = Price({ value: prices[i], updatedAt: block.timestamp });
            emit PricePushed(symbols[i], prices[i], block.timestamp);
        }
    }

    // Returns 0 if price is stale — SwapRouter treats 0 as revert
    function getPrice(string calldata symbol) external view returns (uint256) {
        Price memory p = _prices[symbol];
        if (block.timestamp - p.updatedAt > STALE_AFTER) return 0;
        return p.value;
    }

    // For display — returns price + age regardless of staleness
    function getPriceWithAge(string calldata symbol) external view returns (uint256 price, uint256 age, bool stale) {
        Price memory p = _prices[symbol];
        price = p.value;
        age   = p.updatedAt > 0 ? block.timestamp - p.updatedAt : type(uint256).max;
        stale = age > STALE_AFTER;
    }
}
