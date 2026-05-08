// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// ============================================================
// Wrapped Token (wETH, wSOL, wBNB, wMATIC, wARB)
// Only the authorised minter can mint/burn.
// Owner can transfer minter role — deploy.js calls setMinter()
// after SwapRouter is deployed to point minting rights at it.
// ============================================================
contract WrappedToken {
    string  public name;
    string  public symbol;
    uint8   public constant decimals = 18;
    uint256 public totalSupply;

    address public owner;
    address public minter;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    event Mint(address indexed to, uint256 amount);
    event Burn(address indexed from, uint256 amount);
    event MinterChanged(address indexed oldMinter, address indexed newMinter);

    modifier onlyOwner() {
        require(msg.sender == owner, "WrappedToken: not owner");
        _;
    }

    modifier onlyMinter() {
        require(msg.sender == minter, "WrappedToken: not minter");
        _;
    }

    constructor(string memory _name, string memory _symbol, address _minter) {
        name   = _name;
        symbol = _symbol;
        owner  = _minter;  // deployer is owner
        minter = _minter;  // deployer starts as minter, updated to router in deploy.js
    }

    // Called by deploy.js step 13 to hand minting rights to SwapRouter
    function setMinter(address newMinter) external onlyOwner {
        require(newMinter != address(0), "WrappedToken: zero address");
        emit MinterChanged(minter, newMinter);
        minter = newMinter;
    }

    // Called by bridge/router when deposit confirmed on source chain
    function mint(address to, uint256 amount) external onlyMinter {
        totalSupply   += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
        emit Mint(to, amount);
    }

    // Called by bridge/router when user exits back to source chain
    function burn(address from, uint256 amount) external onlyMinter {
        require(balanceOf[from] >= amount, "WrappedToken: insufficient balance");
        balanceOf[from] -= amount;
        totalSupply     -= amount;
        emit Transfer(from, address(0), amount);
        emit Burn(from, amount);
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _transfer(msg.sender, to, amount);
        return true;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        require(allowance[from][msg.sender] >= amount, "WrappedToken: insufficient allowance");
        allowance[from][msg.sender] -= amount;
        _transfer(from, to, amount);
        return true;
    }

    function _transfer(address from, address to, uint256 amount) internal {
        require(to != address(0), "WrappedToken: zero address");
        require(balanceOf[from] >= amount, "WrappedToken: insufficient balance");
        balanceOf[from] -= amount;
        balanceOf[to]   += amount;
        emit Transfer(from, to, amount);
    }
}
