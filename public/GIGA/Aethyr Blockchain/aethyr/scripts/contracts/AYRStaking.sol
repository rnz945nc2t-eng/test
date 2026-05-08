// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// ================================================================
// AYRStaking — Native AYR Validator Staking
//
// AYR is the NATIVE currency of chain 210078, not an ERC-20.
// Validators stake native AYR via msg.value (no approval needed).
//
// Rules:
//   - Minimum stake: 1,000 AYR
//   - Max validators: 21
//   - Unbond period: 7 days (enforced via block.timestamp)
//   - Slash penalty: 50% of stake, locked in contract
//   - Only owner can slash (the authority node)
//
// Frontend call:
//   staking.stake({ value: ethers.parseEther(amount), gasLimit: 200000 })
// ================================================================

contract AYRStaking {

    uint256 public constant MIN_STAKE      = 1_000 ether;  // 1000 AYR
    uint256 public constant MAX_VALIDATORS = 21;
    uint256 public constant UNBOND_PERIOD  = 7 days;

    address public owner;

    struct Validator {
        uint256 stake;
        uint256 since;          // block number when staked
        uint256 unbondAt;       // timestamp after which can withdraw (0 = not unbonding)
        bool    active;
        bool    slashed;
    }

    address[]                        public validatorList;
    mapping(address => Validator)    public validators;
    // Slashed AYR accumulates here (not withdrawable — effectively burned)
    uint256                          public slashedPool;

    event ValidatorRegistered(address indexed validator, uint256 stake, uint256 blockNumber);
    event UnbondRequested(address indexed validator, uint256 unlockAt);
    event Withdrawn(address indexed validator, uint256 amount);
    event Slashed(address indexed validator, uint256 penalty);
    event TopUpStake(address indexed validator, uint256 added, uint256 total);

    modifier onlyOwner() {
        require(msg.sender == owner, "Staking: not owner");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    // ── Core: Stake ───────────────────────────────────────────────
    // Send native AYR as msg.value to register/top-up as validator.
    // Matches frontend: staking.stake({ value: parseEther(amount) })
    function stake() external payable {
        require(msg.value > 0, "Staking: zero value");
        require(!validators[msg.sender].slashed, "Staking: address is slashed");

        Validator storage v = validators[msg.sender];
        uint256 newTotal = v.stake + msg.value;
        require(newTotal >= MIN_STAKE, "Staking: below minimum 1000 AYR");

        bool isNew = (v.stake == 0);
        if (isNew) {
            require(activeCount() < MAX_VALIDATORS, "Staking: validator slots full");
            validatorList.push(msg.sender);
            v.since = block.number;
            emit ValidatorRegistered(msg.sender, newTotal, block.number);
        } else {
            emit TopUpStake(msg.sender, msg.value, newTotal);
        }

        v.stake   = newTotal;
        v.active  = true;
        v.unbondAt = 0; // cancel any pending unbond
    }

    // ── Core: Request Unbond ──────────────────────────────────────
    // Starts the 7-day countdown. Validator stays active until
    // withdraw() is called after the period.
    function requestUnbond() external {
        Validator storage v = validators[msg.sender];
        require(v.active, "Staking: not active");
        require(v.unbondAt == 0, "Staking: unbond already requested");
        v.unbondAt = block.timestamp + UNBOND_PERIOD;
        v.active   = false;
        emit UnbondRequested(msg.sender, v.unbondAt);
    }

    // ── Core: Withdraw ────────────────────────────────────────────
    // Sends stake back after unbond period has elapsed.
    function withdraw() external {
        Validator storage v = validators[msg.sender];
        require(!v.active, "Staking: still active - call requestUnbond first");
        require(!v.slashed, "Staking: slashed");
        require(v.unbondAt > 0, "Staking: no unbond pending");
        require(block.timestamp >= v.unbondAt, "Staking: unbond period not over");
        require(v.stake > 0, "Staking: nothing to withdraw");

        uint256 amount = v.stake;
        v.stake   = 0;
        v.unbondAt = 0;

        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "Staking: transfer failed");
        emit Withdrawn(msg.sender, amount);
    }

    // ── Admin: Slash ──────────────────────────────────────────────
    // Owner (authority node) slashes 50% of a misbehaving validator.
    // Slashed AYR stays locked in contract.
    function slash(address validator) external onlyOwner {
        Validator storage v = validators[validator];
        require(v.active || v.unbondAt > 0, "Staking: not staked");
        require(!v.slashed, "Staking: already slashed");

        uint256 penalty = v.stake / 2;
        v.stake   -= penalty;
        v.active   = false;
        v.slashed  = true;
        v.unbondAt = 0;
        slashedPool += penalty;

        emit Slashed(validator, penalty);
    }

    // ── Views ─────────────────────────────────────────────────────

    function activeCount() public view returns (uint256 count) {
        for (uint i = 0; i < validatorList.length; i++) {
            if (validators[validatorList[i]].active) count++;
        }
    }

    function getActiveValidators() external view returns (address[] memory addrs, uint256[] memory stakes) {
        uint256 n = activeCount();
        addrs  = new address[](n);
        stakes = new uint256[](n);
        uint256 idx;
        for (uint i = 0; i < validatorList.length; i++) {
            address a = validatorList[i];
            if (validators[a].active) {
                addrs[idx]  = a;
                stakes[idx] = validators[a].stake;
                idx++;
            }
        }
    }

    function validatorCount() external view returns (uint256) {
        return activeCount();
    }

    // Total AYR locked in this contract
    function totalStaked() external view returns (uint256) {
        return address(this).balance - slashedPool;
    }

    receive() external payable {}
}
