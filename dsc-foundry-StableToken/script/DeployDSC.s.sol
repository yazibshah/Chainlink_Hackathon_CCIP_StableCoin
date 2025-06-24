// SPDX-License-Identifier: MIT

pragma solidity ^0.8.18;

import {Script} from "forge-std/Script.sol";
import {DSCEngine} from "../src/DSCEngine.sol";
import {DecentralizedStableCoin} from "../src/DecentralizedStableCoin.sol";
import {HelperConfig} from "./HelperConfig.s.sol";

contract DeployDSC is Script {
    address[] public tokenAddresses;
    address[] public priceFeedAddresses;

    function run() external returns (DecentralizedStableCoin, DSCEngine, HelperConfig) {
        // Create an instance of HelperConfig
        HelperConfig config = new HelperConfig();

        // Destructure the network configuration
        (address wethUsdPriceFeed, address wAvaxUsdPriceFeed, address weth, address wAvax, uint256 deployerKey) =
            config.activeNetworkConfig();

        tokenAddresses = [weth, wAvax];
        priceFeedAddresses = [wethUsdPriceFeed, wAvaxUsdPriceFeed];
        vm.startBroadcast();
        DecentralizedStableCoin dsc = new DecentralizedStableCoin();
        DSCEngine engine = new DSCEngine(tokenAddresses, priceFeedAddresses, address(dsc));

        dsc.transferOwnership(address(engine));
        vm.stopBroadcast();

        return (dsc, engine, config);
    }
}
