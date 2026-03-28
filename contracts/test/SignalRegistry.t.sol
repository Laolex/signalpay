// SPDX-License-Identifier: MIT
pragma solidity ^0.8.30;

import "forge-std/Test.sol";
import "../src/SignalRegistry.sol";

/**
 * @title MockIdentityRegistry
 * @notice Minimal mock for ERC-8004 IdentityRegistry used in tests.
 */
contract MockIdentityRegistry {
    mapping(uint256 => address) private _owners;

    function mint(address to, uint256 tokenId) external {
        _owners[tokenId] = to;
    }

    function ownerOf(uint256 tokenId) external view returns (address) {
        address owner = _owners[tokenId];
        require(owner != address(0), "token does not exist");
        return owner;
    }
}

contract SignalRegistryTest is Test {
    SignalRegistry public registry;
    MockIdentityRegistry public identityRegistry;

    address public alice = makeAddr("alice");
    address public bob   = makeAddr("bob");

    uint256 constant AGENT_ID_ALICE = 1001;
    uint256 constant AGENT_ID_BOB   = 1002;

    function setUp() public {
        identityRegistry = new MockIdentityRegistry();
        registry = new SignalRegistry(address(identityRegistry));

        // Mint ERC-8004 agent identities
        identityRegistry.mint(alice, AGENT_ID_ALICE);
        identityRegistry.mint(bob,   AGENT_ID_BOB);
    }

    // ── Registration ───────────────────────────────────────────────────

    function test_RegisterProvider() public {
        vm.prank(alice);
        uint256 id = registry.registerProvider(
            AGENT_ID_ALICE,
            alice,
            "https://api.example.com/signals/whale-alert",
            "Whale Tracker Alpha",
            "Large wallet movements on Solana",
            SignalRegistry.SignalCategory.WHALE_ALERT,
            2000
        );

        assertEq(id, 0);
        assertEq(registry.totalProviders(), 1);
        assertEq(registry.agentToProvider(AGENT_ID_ALICE), 0);

        (
            uint256 agentId,,
            string memory endpoint,
            string memory name,,
            SignalRegistry.SignalCategory category,
            uint256 price,,,
            bool active
        ) = registry.getProvider(0);

        assertEq(agentId, AGENT_ID_ALICE);
        assertEq(name, "Whale Tracker Alpha");
        assertEq(price, 2000);
        assertEq(uint(category), uint(SignalRegistry.SignalCategory.WHALE_ALERT));
        assertTrue(active);
        assertEq(endpoint, "https://api.example.com/signals/whale-alert");
    }

    function test_RegisterProvider_EmitsEvent() public {
        vm.prank(alice);
        vm.expectEmit(true, true, false, true);
        emit SignalRegistry.ProviderRegistered(
            0,
            AGENT_ID_ALICE,
            "Whale Tracker Alpha",
            SignalRegistry.SignalCategory.WHALE_ALERT,
            2000,
            "https://api.example.com/signals/whale-alert"
        );

        registry.registerProvider(
            AGENT_ID_ALICE, alice,
            "https://api.example.com/signals/whale-alert",
            "Whale Tracker Alpha", "",
            SignalRegistry.SignalCategory.WHALE_ALERT,
            2000
        );
    }

    function test_Register_NotAgentOwner_Reverts() public {
        vm.prank(bob);
        vm.expectRevert(abi.encodeWithSelector(SignalRegistry.NotAgentOwner.selector, AGENT_ID_ALICE));
        registry.registerProvider(
            AGENT_ID_ALICE, bob, "https://api.example.com/signals/test",
            "Fake Provider", "", SignalRegistry.SignalCategory.PRICE_ORACLE, 1000
        );
    }

    function test_Register_ZeroPrice_Reverts() public {
        vm.prank(alice);
        vm.expectRevert(SignalRegistry.InvalidPrice.selector);
        registry.registerProvider(
            AGENT_ID_ALICE, alice, "https://api.example.com/signals/test",
            "Bad Provider", "", SignalRegistry.SignalCategory.PRICE_ORACLE, 0
        );
    }

    function test_Register_EmptyEndpoint_Reverts() public {
        vm.prank(alice);
        vm.expectRevert(SignalRegistry.EmptyEndpoint.selector);
        registry.registerProvider(
            AGENT_ID_ALICE, alice, "",
            "Bad Provider", "", SignalRegistry.SignalCategory.PRICE_ORACLE, 1000
        );
    }

    function test_Register_DuplicateAgent_Reverts() public {
        vm.startPrank(alice);
        registry.registerProvider(
            AGENT_ID_ALICE, alice, "https://api.example.com/signals/first",
            "First Provider", "", SignalRegistry.SignalCategory.WHALE_ALERT, 2000
        );

        vm.expectRevert(abi.encodeWithSelector(SignalRegistry.AgentAlreadyRegistered.selector, AGENT_ID_ALICE));
        registry.registerProvider(
            AGENT_ID_ALICE, alice, "https://api.example.com/signals/second",
            "Second Provider", "", SignalRegistry.SignalCategory.PRICE_ORACLE, 1000
        );
        vm.stopPrank();
    }

    // ── Provider Management ────────────────────────────────────────────

    function test_UpdatePrice() public {
        vm.startPrank(alice);
        uint256 id = registry.registerProvider(
            AGENT_ID_ALICE, alice, "https://api.example.com/signals/test",
            "Test Provider", "", SignalRegistry.SignalCategory.SENTIMENT, 3000
        );

        registry.updatePrice(id, 5000);
        vm.stopPrank();

        (,,,,,, uint256 price,,,) = registry.getProvider(id);
        assertEq(price, 5000);
    }

    function test_UpdatePrice_NotOwner_Reverts() public {
        vm.prank(alice);
        uint256 id = registry.registerProvider(
            AGENT_ID_ALICE, alice, "https://api.example.com/signals/test",
            "Test Provider", "", SignalRegistry.SignalCategory.SENTIMENT, 3000
        );

        vm.prank(bob);
        vm.expectRevert(abi.encodeWithSelector(SignalRegistry.NotProviderOwner.selector, id));
        registry.updatePrice(id, 9999);
    }

    function test_Deactivate() public {
        vm.startPrank(alice);
        uint256 id = registry.registerProvider(
            AGENT_ID_ALICE, alice, "https://api.example.com/signals/test",
            "Test Provider", "", SignalRegistry.SignalCategory.WALLET_SCORE, 5000
        );

        registry.deactivate(id);
        vm.stopPrank();

        (,,,,,,,,, bool active) = registry.getProvider(id);
        assertFalse(active);
    }

    function test_RecordCalls() public {
        vm.startPrank(alice);
        uint256 id = registry.registerProvider(
            AGENT_ID_ALICE, alice, "https://api.example.com/signals/test",
            "Test Provider", "", SignalRegistry.SignalCategory.WHALE_ALERT, 2000
        );

        registry.recordCalls(id, 100);
        registry.recordCalls(id, 50);
        vm.stopPrank();

        (,,,,,,,uint256 totalCalls,,) = registry.getProvider(id);
        assertEq(totalCalls, 150);
    }

    // ── Discovery ──────────────────────────────────────────────────────

    function test_GetProvidersByCategory() public {
        vm.prank(alice);
        registry.registerProvider(
            AGENT_ID_ALICE, alice, "https://api.example.com/signals/whale-alert",
            "Whale Alpha", "", SignalRegistry.SignalCategory.WHALE_ALERT, 2000
        );

        vm.prank(bob);
        registry.registerProvider(
            AGENT_ID_BOB, bob, "https://api.example.com/signals/price",
            "Price Oracle", "", SignalRegistry.SignalCategory.PRICE_ORACLE, 1000
        );

        uint256[] memory whaleProviders = registry.getProvidersByCategory(
            SignalRegistry.SignalCategory.WHALE_ALERT
        );
        assertEq(whaleProviders.length, 1);
        assertEq(whaleProviders[0], 0);

        uint256[] memory priceProviders = registry.getProvidersByCategory(
            SignalRegistry.SignalCategory.PRICE_ORACLE
        );
        assertEq(priceProviders.length, 1);
    }

    function test_GetCheapestProvider() public {
        vm.prank(alice);
        registry.registerProvider(
            AGENT_ID_ALICE, alice, "https://api.example.com/signals/whale-alert",
            "Whale Alpha", "", SignalRegistry.SignalCategory.WHALE_ALERT, 2000
        );

        (uint256 providerId, uint256 price) = registry.getCheapestProvider(
            SignalRegistry.SignalCategory.WHALE_ALERT
        );
        assertEq(providerId, 0);
        assertEq(price, 2000);
    }

    function test_GetActiveProvidersByCategory_ExcludesDeactivated() public {
        vm.prank(alice);
        uint256 id = registry.registerProvider(
            AGENT_ID_ALICE, alice, "https://api.example.com/signals/whale-alert",
            "Whale Alpha", "", SignalRegistry.SignalCategory.WHALE_ALERT, 2000
        );

        vm.prank(alice);
        registry.deactivate(id);

        uint256[] memory active = registry.getActiveProvidersByCategory(
            SignalRegistry.SignalCategory.WHALE_ALERT
        );
        assertEq(active.length, 0);
    }
}
