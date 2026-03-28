// SPDX-License-Identifier: MIT
pragma solidity ^0.8.30;

import "forge-std/Script.sol";
import "../src/SignalRegistry.sol";

/**
 * @title DeploySignalRegistry
 * @dev Deploys SignalRegistry on Arc Testnet, wired to the existing ERC-8004 IdentityRegistry.
 *
 * Usage:
 *   source .env
 *   forge script script/Deploy.s.sol:DeploySignalRegistry \
 *     --rpc-url $ARC_TESTNET_RPC_URL \
 *     --private-key $PRIVATE_KEY \
 *     --broadcast
 */
contract DeploySignalRegistry is Script {
    // ERC-8004 IdentityRegistry — already deployed on Arc Testnet
    address constant IDENTITY_REGISTRY = 0x8004A818BFB912233c491871b3d84c89A494BD9e;

    function run() external {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(deployerKey);

        console.log("Deployer:", deployer);
        console.log("IdentityRegistry:", IDENTITY_REGISTRY);

        vm.startBroadcast(deployerKey);

        SignalRegistry registry = new SignalRegistry(IDENTITY_REGISTRY);
        console.log("SignalRegistry deployed to:", address(registry));

        vm.stopBroadcast();
    }
}
