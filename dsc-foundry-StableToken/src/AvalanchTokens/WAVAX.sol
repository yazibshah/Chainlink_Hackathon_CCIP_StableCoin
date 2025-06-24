// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

// solhint-disable no-unused-import
import {BurnMintERC20} from "@chainlink/contracts/src/v0.8/shared/token/ERC20/BurnMintERC20.sol";
import {BurnMintTokenPool} from "@chainlink/contracts/src/v0.8/ccip/pools/BurnMintTokenPool.sol";
import {LockReleaseTokenPool} from "@chainlink/contracts/src/v0.8/ccip//pools/LockReleaseTokenPool.sol";
import {RegistryModuleOwnerCustom} from "@chainlink/contracts/src/v0.8/ccip//tokenAdminRegistry/RegistryModuleOwnerCustom.sol";
import {TokenAdminRegistry} from "@chainlink/contracts/src/v0.8/ccip//tokenAdminRegistry/TokenAdminRegistry.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/security/ReentrancyGuard.sol";

contract WAVAX is BurnMintERC20, ReentrancyGuard {
    // -------------Custom Errors----------------------
    error InvalidUser();
    error InvalidAmount(uint256 deposited, uint256 requested);
    error InsufficientContractBalance(uint256 available, uint256 requested);
    error InsufficientWAVAXBalance(uint256 available, uint256 requested);
    error ZeroAmount();

    // -------------Events----------------------
    event DepositedEth(address indexed user, uint256 amount);
    event BurnedAndWithdrawn(address indexed user, uint256 amount, string message);

    // ------------- Variables and Constants---------------
    mapping(address => uint256) public depositedEth;

    constructor() BurnMintERC20("Wrapped Ethereum", "WAVAX", 18, 0, 0) {}

    /* -----------Internal Functions------------ */
    function _deposit(address user, uint256 amountOfEth) internal {
        unchecked {
            depositedEth[user] += amountOfEth;
        }
    }

    function _withdraw(address user, uint256 amountOfEth) internal {
        unchecked {
            depositedEth[user] -= amountOfEth;
        }
    }

    /* -----------External Functions------------ */
    function depositEthAndMintWAVAX() public payable {
        if (msg.sender == address(0)) revert InvalidUser();
        if (msg.value == 0) revert ZeroAmount();
        _deposit(msg.sender, msg.value);
        _mint(msg.sender, msg.value);
        emit DepositedEth(msg.sender, msg.value);
    }

    function withdraWAVAXAndBurnWAVAX(uint256 amountToBurn) external nonReentrant {
        if (amountToBurn == 0) revert ZeroAmount();
        if (balanceOf(msg.sender) < amountToBurn) revert InsufficientWAVAXBalance(balanceOf(msg.sender), amountToBurn);
        if (address(this).balance < amountToBurn) revert InsufficientContractBalance(address(this).balance, amountToBurn);
        // Allow for minor precision differences (1 wei tolerance)
        uint256 depositedAmount=depositedEth[msg.sender];
        if ( depositedAmount < amountToBurn) {
            revert InvalidAmount(depositedEth[msg.sender], amountToBurn);
        }
        _withdraw(msg.sender, amountToBurn);
        _burn(msg.sender, amountToBurn);
        (bool success, ) = msg.sender.call{value: amountToBurn}("");
        if (!success) revert("ETH transfer failed");
        emit BurnedAndWithdrawn(msg.sender, amountToBurn, "Successful");
    }

    // Allow contract to receive ETH
    
    receive() external payable {
        if (msg.sender == address(0)) revert InvalidUser();
        if (msg.value == 0) revert ZeroAmount();
        _deposit(msg.sender, msg.value);
        _mint(msg.sender, msg.value);
        emit DepositedEth(msg.sender, msg.value);
    }


    // Fallback function for safety
    fallback() external payable {}
}