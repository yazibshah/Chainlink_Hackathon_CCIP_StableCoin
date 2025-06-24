// SPDX-License-Identifier: MIT

pragma solidity ^0.8.18;

import {Script} from "forge-std/Script.sol";
import {MockV3Aggregator} from "../test/mocks/MockV3Aggregator.sol";
import {ERC20Mock} from "@openzeppelin/contracts/mocks/ERC20Mock.sol";

contract HelperConfig is Script {
    struct NetworkConfig {
        address wethUsdPriceFeed;
        address wAvaxUsdPriceFeed;
        address weth;
        address wAvax;
        uint256 deployerKey;
    }

    uint8 public constant DECIMALS = 8;
    int256 public constant ETH_USD_PRICE = 2000e8;
    int256 public constant BTC_USD_PRICE = 1000e8;
    uint256 public DEFAULT_ANVIL_KEY = 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80;

    NetworkConfig public activeNetworkConfig;

    constructor() {
        if (block.chainid == 11155111) {
            activeNetworkConfig = getSepoliaEthConfig();
        } 
        else if(block.chainid == 43113) {
            activeNetworkConfig = getAvalanchConfig();
        } 
        else {
            activeNetworkConfig = getOrCreateAnvilEthConfig();
        }
    }

    function getSepoliaEthConfig() public view returns (NetworkConfig memory) {
        return NetworkConfig({
            wethUsdPriceFeed: 0x694AA1769357215DE4FAC081bf1f309aDC325306,
            wAvaxUsdPriceFeed: 0x14866185B1962B63C3Ea9E03Bc1da838bab34C19,
            weth: 0x6e7a8Ae4DC6A5ef395a6Ddb5Ef7ac17159d163e7,
            wAvax: 0xF2FB9C3D0503BBcF0752559DE9280f3Fb0272284,
            deployerKey: vm.envUint("PRIVATE_KEY")
        });
    }


    function getAvalanchConfig() public view returns (NetworkConfig memory) {
        return NetworkConfig({
            wethUsdPriceFeed: 0x86d67c3D38D2bCeE722E601025C25a575021c6EA,
            wAvaxUsdPriceFeed: 0x5498BB86BC934c8D34FDA08E81D444153d0D06aD,
            weth: 0x675EFB502Bd57B46F7172c64Ed68C81B8030742E,
            wAvax: 0x436e9b927D385520E8Eb23065101220ceA693250,
            deployerKey: vm.envUint("PRIVATE_KEY")
        });
    }

    function getOrCreateAnvilEthConfig() public returns (NetworkConfig memory) {
        if (activeNetworkConfig.wethUsdPriceFeed != address(0)) {
            return activeNetworkConfig;
        }
        vm.startBroadcast();
        // Deploy mock price feeds for Anvil
        MockV3Aggregator ethUsdPriceFeed = new MockV3Aggregator(DECIMALS, ETH_USD_PRICE);
        MockV3Aggregator btcUsdPriceFeed = new MockV3Aggregator(DECIMALS, BTC_USD_PRICE);

        // Deploy mock tokens and mint to the deployer
        ERC20Mock wethMock = new ERC20Mock("WETH", "WETH", msg.sender, 1000e18);
        ERC20Mock wAvaxMock = new ERC20Mock("wAvax", "wAvax", msg.sender, 1000e18);
        vm.stopBroadcast();

        return NetworkConfig({
            wethUsdPriceFeed: address(ethUsdPriceFeed),
            wAvaxUsdPriceFeed: address(btcUsdPriceFeed),
            weth: address(wethMock),
            wAvax: address(wAvaxMock),
            deployerKey: DEFAULT_ANVIL_KEY
        });
    }
}
