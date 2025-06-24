// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {IRouterClient} from "@chainlink/contracts/src/v0.8/ccip/interfaces/IRouterClient.sol";
import {OwnerIsCreator} from "@chainlink/contracts/src/v0.8/shared/access/OwnerIsCreator.sol";
import {Client} from "@chainlink/contracts/src/v0.8/ccip/libraries/Client.sol";
import {IERC20} from "@chainlink/contracts/src/v0.8/vendor/openzeppelin-solidity/v4.8.3/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@chainlink/contracts/src/v0.8/vendor/openzeppelin-solidity/v4.8.3/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/security/ReentrancyGuard.sol";

contract DSCTransferHub is OwnerIsCreator,ReentrancyGuard {
    using SafeERC20 for IERC20;

    IRouterClient private s_router;
    IERC20 private s_linkToken; // For fee payments
    address[] public supportedTokens; // e.g., DAI, DSC, wrapped BTC
    mapping(address => bool) public isSupportedToken;
    mapping(address USER=> mapping(address tokenAddress=> uint256)) public userTokenDeposits; // user => token => amount
    mapping(address => uint256) public userEthDeposits; // user => ETH amount

    // Allowlisted chains
    mapping(uint64 => bool) public allowlistedChains;

    // Events
    event TokensDeposited(address indexed from, address indexed token, uint256 amount);
    event TokensTransferred(bytes32 messageId, uint64 destinationChainSelector, address receiver, address token, uint256 tokenAmount, uint256 fees);
    // 0x8063f5D0659CBC5698916e19f3F8c0Aa8B608cF7
    constructor(address _router, address _link, address[] memory _initialTokens) {
        s_router = IRouterClient(_router);
        s_linkToken = IERC20(_link);
        for (uint i = 0; i < _initialTokens.length; i++) {
            supportedTokens.push(_initialTokens[i]);
            isSupportedToken[_initialTokens[i]] = true;
        }
    }

    // Receive ETH for fees
    receive() external payable {
        userEthDeposits[msg.sender] += msg.value;
    }

    // Deposit tokens using approval (pull model)
    function depositTokens(address _token, uint256 _amount) external {
        require(isSupportedToken[_token], "Unsupported token");
        IERC20(_token).safeTransferFrom(msg.sender, address(this), _amount);
        userTokenDeposits[msg.sender][_token] += _amount;
        emit TokensDeposited(msg.sender, _token, _amount);
    }

    // Transfer tokens cross-chain
    function transferTokens(
        uint64 _destinationChainSelector,
        address _receiver,
        address _token,
        uint256 _amount
    ) external onlyAllowlistedChain(_destinationChainSelector) nonReentrant returns (bytes32) {
        require(isSupportedToken[_token], "Unsupported token");
        require(userTokenDeposits[msg.sender][_token] >= _amount, "Insufficient token deposit");
        uint256 fees = s_router.getFee(_destinationChainSelector, _buildCCIPMessage(_receiver, _token, _amount));
        require(userEthDeposits[msg.sender] >= fees, "Insufficient ETH for fees");

        userTokenDeposits[msg.sender][_token] -= _amount;
        userEthDeposits[msg.sender] -= fees;

        IERC20(_token).approve(address(s_router), _amount);
        bytes32 messageId = s_router.ccipSend{value: fees}(_destinationChainSelector, _buildCCIPMessage(_receiver, _token, _amount));

        emit TokensTransferred(messageId, _destinationChainSelector, _receiver, _token, _amount, fees);
        return messageId;
    }

    // Build CCIP message
    function _buildCCIPMessage(address _receiver, address _token, uint256 _amount) private pure returns (Client.EVM2AnyMessage memory) {
        Client.EVMTokenAmount[] memory tokenAmounts = new Client.EVMTokenAmount[](1);
        tokenAmounts[0] = Client.EVMTokenAmount({token: _token, amount: _amount});
        return Client.EVM2AnyMessage({
            receiver: abi.encode(_receiver),
            data: "",
            tokenAmounts: tokenAmounts,
            extraArgs: Client._argsToBytes(Client.GenericExtraArgsV2({gasLimit: 0, allowOutOfOrderExecution: true})),
            feeToken: address(0)
        });
    }

    // Allowlist chains
    function allowlistDestinationChain(uint64 _destinationChainSelector, bool _allowed) external onlyOwner {
        allowlistedChains[_destinationChainSelector] = _allowed;
    }

    // Withdraw deposits
    function withdrawDeposits(address _token) external nonReentrant{
        uint256 tokenBalance = userTokenDeposits[msg.sender][_token];
        uint256 ethBalance = userEthDeposits[msg.sender];
        require(tokenBalance > 0 || ethBalance > 0, "Nothing to withdraw");
        if (tokenBalance > 0) {
            userTokenDeposits[msg.sender][_token] = 0; // Update state first
            IERC20(_token).safeTransfer(msg.sender, tokenBalance); // External call after
        }
        if (ethBalance > 0) {
            userEthDeposits[msg.sender] = 0; // Update state first
            (bool sent, ) = payable(msg.sender).call{value: ethBalance}(""); // Use call with success check
            require(sent, "Failed to send ETH");
        }    }

    modifier onlyAllowlistedChain(uint64 _destinationChainSelector) {
        require(allowlistedChains[_destinationChainSelector], "Chain not allowlisted");
        _;
    }
}