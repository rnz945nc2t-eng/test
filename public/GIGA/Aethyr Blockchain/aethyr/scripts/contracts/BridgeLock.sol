// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract BridgeLock {
    address public owner;
    bool    public paused;

    event Locked(address indexed sender, uint256 amount);

    modifier onlyOwner() { require(msg.sender == owner, "Not owner"); _; }
    modifier notPaused() { require(!paused, "Paused"); _; }

    constructor() { owner = msg.sender; }

    function lock() external payable notPaused {
        require(msg.value > 0, "Zero amount");
        emit Locked(msg.sender, msg.value);
    }

    function pause() external onlyOwner { paused = true; }
    function unpause() external onlyOwner { paused = false; }
    function withdraw(address payable to, uint256 amount) external onlyOwner {
        require(address(this).balance >= amount, "Insufficient");
        to.transfer(amount);
    }

    receive() external payable { if (msg.value > 0) emit Locked(msg.sender, msg.value); }
}
