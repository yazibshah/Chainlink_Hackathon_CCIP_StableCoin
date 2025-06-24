// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

// solhint-disable no-unused-import
import {BurnMintERC20} from "@chainlink/contracts/src/v0.8/shared/token/ERC20/BurnMintERC20.sol";
import {BurnMintTokenPool} from "@chainlink/contracts/src/v0.8/ccip/pools/BurnMintTokenPool.sol";
import {LockReleaseTokenPool} from "@chainlink/contracts/src/v0.8/ccip//pools/LockReleaseTokenPool.sol";
import {RegistryModuleOwnerCustom} from "@chainlink/contracts/src/v0.8/ccip//tokenAdminRegistry/RegistryModuleOwnerCustom.sol";
import {TokenAdminRegistry} from "@chainlink/contracts/src/v0.8/ccip//tokenAdminRegistry/TokenAdminRegistry.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/security/ReentrancyGuard.sol";

contract WAVAX is BurnMintERC20 {
    // -------------Custom Errors----------------------
    error NotAllowedToDepositAndMint();
    error NotAllowedToWithdrawAndBurn();

    // ------------- Variables and Constants---------------
    mapping(address => uint256) public depositedEth;

    constructor() BurnMintERC20("Wrapped Ethereum", "WAVAX", 18, 0, 0) {}

    /* -----------External Functions------------ */
    function depositEthAndMintWAVAX() public {
       revert NotAllowedToDepositAndMint();
    }

    function withdraWAVAXAndBurnWAVAX(uint256 amountToBurn) external {
        revert NotAllowedToWithdrawAndBurn();
    }

    // Allow contract to receive ETH
    
    receive() external payable {}

    // Fallback function for safety
    fallback() external payable {}
}
