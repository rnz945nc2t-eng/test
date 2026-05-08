// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// ================================================================
// AYRSwapRouter — Oracle-Priced Cross-Chain Swap Router
//
// Architecture:
//   - No liquidity pools. Oracle prices everything.
//   - Swaps burn fromAsset wrapped token and mint toAsset.
//   - bridgeIn/bridgeOut are called by the relayer node.
//   - All assets are wrapped ERC-20 tokens (wETH, wSOL, etc.)
//   - Bitcoin uses the UTXORegistry (native, no wrapping).
//
// Frontend ABI (matching AYR.tsx handleSwap):
//   swap(fromAsset, toAsset, amountIn, minAmountOut) — ERC20→ERC20
//   bridgeIn(asset, recipient, amount, sourceTxHash) — relayer only
//   bridgeOut(asset, amount, destinationAddress)     — user exits
//   getQuote(fromAsset, toAsset, amountIn)           — view
// ================================================================

interface IERC20Mintable {
    function mint(address to, uint256 amount) external;
    function burn(address from, uint256 amount) external;
    function balanceOf(address) external view returns (uint256);
    function transfer(address, uint256) external returns (bool);
    function transferFrom(address, address, uint256) external returns (bool);
    function approve(address, uint256) external returns (bool);
}

interface IOracle {
    function getPrice(string calldata symbol) external view returns (uint256);
}

contract AYRSwapRouter {

    address public owner;
    IOracle public oracle;

    // Fee: 0.1% = 10 basis points
    uint256 public feeBps = 10;
    address public feeCollector;

    mapping(string  => address) public wrappedTokens;
    mapping(string  => bool)    public supportedAssets;
    mapping(bytes32 => bool)    public processedTxs;
    mapping(address => bool)    public relayers;

    uint256 private _lock = 1;

    modifier onlyOwner()    { require(msg.sender == owner, "Router: not owner"); _; }
    modifier onlyRelayer()  { require(relayers[msg.sender], "Router: not relayer"); _; }
    modifier nonReentrant() { require(_lock == 1, "Router: reentrant"); _lock = 2; _; _lock = 1; }

    event SwapExecuted(address indexed user, string fromAsset, string toAsset, uint256 amountIn, uint256 amountOut);
    event BridgeIn(address indexed to, string asset, uint256 amount, bytes32 sourceTxHash);
    event BridgeOut(address indexed from, string asset, uint256 amount, string destinationAddress);
    event AssetRegistered(string symbol, address token);
    event RelayerUpdated(address relayer, bool status);

    // ── Constructor ───────────────────────────────────────────────
    // _oracle:       AYRMockOracle address
    // _feeCollector: address that receives swap fees
    constructor(address _oracle, address _feeCollector) {
        require(_oracle != address(0),       "Router: zero oracle");
        require(_feeCollector != address(0), "Router: zero feeCollector");
        owner        = msg.sender;
        oracle       = IOracle(_oracle);
        feeCollector = _feeCollector;
        relayers[msg.sender] = true;
    }

    // ── Admin ──────────────────────────────────────────────────────

    function registerAsset(string calldata symbol, address tokenContract) external onlyOwner {
        wrappedTokens[symbol]   = tokenContract;
        supportedAssets[symbol] = true;
        emit AssetRegistered(symbol, tokenContract);
    }

    function setRelayer(address relayer, bool status) external onlyOwner {
        relayers[relayer] = status;
        emit RelayerUpdated(relayer, status);
    }

    function setFee(uint256 bps) external onlyOwner {
        require(bps <= 100, "Router: max 1%");
        feeBps = bps;
    }

    function setOracle(address _oracle) external onlyOwner {
        oracle = IOracle(_oracle);
    }

    function setFeeCollector(address _fc) external onlyOwner {
        feeCollector = _fc;
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "Router: zero address");
        owner = newOwner;
    }

    // ── Bridge In ─────────────────────────────────────────────────
    // Relayer confirms deposit on source chain and mints wrapped token.
    function bridgeIn(
        string  calldata asset,
        address          recipient,
        uint256          amount,
        bytes32          sourceTxHash
    ) external onlyRelayer nonReentrant {
        require(supportedAssets[asset],         "Router: asset not supported");
        require(!processedTxs[sourceTxHash],    "Router: already processed");
        require(amount > 0,                     "Router: zero amount");
        processedTxs[sourceTxHash] = true;

        uint256 fee       = (amount * feeBps) / 10_000;
        uint256 netAmount = amount - fee;

        IERC20Mintable token = IERC20Mintable(wrappedTokens[asset]);
        token.mint(recipient, netAmount);
        if (fee > 0) token.mint(feeCollector, fee);

        emit BridgeIn(recipient, asset, netAmount, sourceTxHash);
    }

    // ── Swap ──────────────────────────────────────────────────────
    // Burns fromAsset, mints toAsset at oracle price.
    // User must have approved the fromAsset token first.
    // Called by frontend: router.swap(fromAsset, toAsset, amountIn, minAmountOut)
    function swap(
        string  calldata fromAsset,
        string  calldata toAsset,
        uint256          amountIn,
        uint256          minAmountOut
    ) external nonReentrant returns (uint256 amountOut) {
        require(supportedAssets[fromAsset], "Router: from not supported");
        require(supportedAssets[toAsset],   "Router: to not supported");
        require(amountIn > 0,               "Router: zero amount");

        uint256 fromPrice = oracle.getPrice(fromAsset);
        uint256 toPrice   = oracle.getPrice(toAsset);
        require(fromPrice > 0, "Router: stale fromAsset price");
        require(toPrice   > 0, "Router: stale toAsset price");

        // Burn fromAsset from user
        IERC20Mintable fromToken = IERC20Mintable(wrappedTokens[fromAsset]);
        fromToken.burn(msg.sender, amountIn);

        // amountOut = amountIn * fromPrice / toPrice
        uint256 raw  = (amountIn * fromPrice) / toPrice;
        uint256 fee  = (raw * feeBps) / 10_000;
        amountOut    = raw - fee;

        require(amountOut >= minAmountOut, "Router: slippage exceeded");

        // Mint toAsset to user
        IERC20Mintable toToken = IERC20Mintable(wrappedTokens[toAsset]);
        toToken.mint(msg.sender, amountOut);
        if (fee > 0) toToken.mint(feeCollector, fee);

        emit SwapExecuted(msg.sender, fromAsset, toAsset, amountIn, amountOut);
    }

    // ── Bridge Out ────────────────────────────────────────────────
    // Burns wrapped token. Relayer watches this event and releases
    // real asset on the destination chain.
    function bridgeOut(
        string  calldata asset,
        uint256          amount,
        string  calldata destinationAddress
    ) external nonReentrant {
        require(supportedAssets[asset], "Router: asset not supported");
        require(amount > 0,             "Router: zero amount");

        IERC20Mintable token = IERC20Mintable(wrappedTokens[asset]);
        token.burn(msg.sender, amount);

        uint256 fee       = (amount * feeBps) / 10_000;
        uint256 netAmount = amount - fee;

        emit BridgeOut(msg.sender, asset, netAmount, destinationAddress);
    }

    // ── View ──────────────────────────────────────────────────────
    function getQuote(
        string calldata fromAsset,
        string calldata toAsset,
        uint256         amountIn
    ) external view returns (uint256 amountOut, uint256 fee) {
        uint256 fromPrice = oracle.getPrice(fromAsset);
        uint256 toPrice   = oracle.getPrice(toAsset);
        if (fromPrice == 0 || toPrice == 0) return (0, 0);
        uint256 raw = (amountIn * fromPrice) / toPrice;
        fee       = (raw * feeBps) / 10_000;
        amountOut = raw - fee;
    }
}
