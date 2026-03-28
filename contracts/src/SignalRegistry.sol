// SPDX-License-Identifier: MIT
pragma solidity ^0.8.30;

/**
 * @title SignalRegistry
 * @notice On-chain catalog of AI signal providers for the SignalPay marketplace.
 *         Providers register endpoints, pricing (nanopayment-scale), and signal metadata.
 *         Integrates with ERC-8004 IdentityRegistry for agent identity verification.
 *
 * @dev Deployed on Arc Testnet (Chain ID 5042002).
 *      Nanopayment pricing is in USDC with 6 decimals — $0.002 = 2000.
 *      Actual payments happen off-chain via Circle Nanopayments API (x402).
 *      This contract is the discovery layer, not the payment layer.
 */

interface IIdentityRegistry {
    function ownerOf(uint256 tokenId) external view returns (address);
}

contract SignalRegistry {
    // ── State ──────────────────────────────────────────────────────────

    address public owner;
    IIdentityRegistry public immutable identityRegistry;

    enum SignalCategory {
        WHALE_ALERT,       // 0 — Large wallet movements
        PRICE_ORACLE,      // 1 — Real-time price feeds
        SENTIMENT,         // 2 — Social/news sentiment scoring
        WALLET_SCORE,      // 3 — Wallet risk/alpha scoring
        TRADE_SIGNAL,      // 4 — Buy/sell recommendations
        ON_CHAIN_ANALYTICS // 5 — General on-chain data
    }

    struct Provider {
        uint256 agentId;          // ERC-8004 identity token ID
        address providerWallet;   // Gateway wallet receiving nanopayments
        string  endpoint;         // x402 API endpoint URL
        string  name;             // Human-readable name
        string  description;      // What this provider offers
        SignalCategory category;
        uint256 pricePerCall;     // USDC (6 decimals) — e.g. 2000 = $0.002
        uint256 totalCalls;       // Lifetime request count (updated by provider)
        uint256 registeredAt;
        bool    active;
    }

    mapping(uint256 => Provider) public providers;  // providerId => Provider
    uint256 public nextProviderId;

    // Category index: category => providerId[]
    mapping(SignalCategory => uint256[]) private categoryProviders;

    // Agent identity => providerId (one provider per agent identity)
    mapping(uint256 => uint256) public agentToProvider;
    // Tracks whether an agent has an active registration (avoids ID=0 sentinel ambiguity)
    mapping(uint256 => bool) private _agentRegistered;

    // ── Events ─────────────────────────────────────────────────────────

    event ProviderRegistered(
        uint256 indexed providerId,
        uint256 indexed agentId,
        string name,
        SignalCategory category,
        uint256 pricePerCall,
        string endpoint
    );

    event ProviderUpdated(uint256 indexed providerId);
    event ProviderDeactivated(uint256 indexed providerId);
    event PriceUpdated(uint256 indexed providerId, uint256 oldPrice, uint256 newPrice);
    event CallsRecorded(uint256 indexed providerId, uint256 newCalls, uint256 totalCalls);

    // ── Errors ─────────────────────────────────────────────────────────

    error NotOwner();
    error NotProviderOwner(uint256 providerId);
    error ProviderNotActive(uint256 providerId);
    error AgentAlreadyRegistered(uint256 agentId);
    error NotAgentOwner(uint256 agentId);
    error InvalidPrice();
    error EmptyEndpoint();

    // ── Modifiers ──────────────────────────────────────────────────────

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier onlyProviderOwner(uint256 providerId) {
        Provider storage p = providers[providerId];
        address agentOwner = identityRegistry.ownerOf(p.agentId);
        if (msg.sender != agentOwner) revert NotProviderOwner(providerId);
        _;
    }

    // ── Constructor ────────────────────────────────────────────────────

    constructor(address _identityRegistry) {
        owner = msg.sender;
        identityRegistry = IIdentityRegistry(_identityRegistry);
    }

    // ── Provider Registration ──────────────────────────────────────────

    /**
     * @notice Register a new signal provider. Caller must own the ERC-8004 agent identity.
     * @param agentId       ERC-8004 identity token ID
     * @param providerWallet Gateway wallet address for receiving nanopayments
     * @param endpoint      x402-enabled API endpoint URL
     * @param name          Human-readable provider name
     * @param description   What signals this provider offers
     * @param category      Signal category enum
     * @param pricePerCall  Price per API call in USDC (6 decimals)
     */
    function registerProvider(
        uint256 agentId,
        address providerWallet,
        string calldata endpoint,
        string calldata name,
        string calldata description,
        SignalCategory category,
        uint256 pricePerCall
    ) external returns (uint256 providerId) {
        // Verify caller owns the agent identity
        address agentOwner = identityRegistry.ownerOf(agentId);
        if (msg.sender != agentOwner) revert NotAgentOwner(agentId);

        // One provider per agent identity
        if (_agentRegistered[agentId]) revert AgentAlreadyRegistered(agentId);

        if (pricePerCall == 0) revert InvalidPrice();
        if (bytes(endpoint).length == 0) revert EmptyEndpoint();

        providerId = nextProviderId++;
        providers[providerId] = Provider({
            agentId: agentId,
            providerWallet: providerWallet,
            endpoint: endpoint,
            name: name,
            description: description,
            category: category,
            pricePerCall: pricePerCall,
            totalCalls: 0,
            registeredAt: block.timestamp,
            active: true
        });

        categoryProviders[category].push(providerId);
        agentToProvider[agentId] = providerId;
        _agentRegistered[agentId] = true;

        emit ProviderRegistered(providerId, agentId, name, category, pricePerCall, endpoint);
    }

    // ── Provider Management ────────────────────────────────────────────

    function updateEndpoint(
        uint256 providerId,
        string calldata newEndpoint
    ) external onlyProviderOwner(providerId) {
        if (bytes(newEndpoint).length == 0) revert EmptyEndpoint();
        providers[providerId].endpoint = newEndpoint;
        emit ProviderUpdated(providerId);
    }

    function updatePrice(
        uint256 providerId,
        uint256 newPrice
    ) external onlyProviderOwner(providerId) {
        if (newPrice == 0) revert InvalidPrice();
        uint256 oldPrice = providers[providerId].pricePerCall;
        providers[providerId].pricePerCall = newPrice;
        emit PriceUpdated(providerId, oldPrice, newPrice);
    }

    function updateDescription(
        uint256 providerId,
        string calldata newDescription
    ) external onlyProviderOwner(providerId) {
        providers[providerId].description = newDescription;
        emit ProviderUpdated(providerId);
    }

    function deactivate(uint256 providerId) external onlyProviderOwner(providerId) {
        providers[providerId].active = false;
        _agentRegistered[providers[providerId].agentId] = false;
        emit ProviderDeactivated(providerId);
    }

    /**
     * @notice Provider self-reports call count. In production, this could be
     *         verified via Nanopayments settlement receipts or an oracle.
     */
    function recordCalls(
        uint256 providerId,
        uint256 newCalls
    ) external onlyProviderOwner(providerId) {
        if (!providers[providerId].active) revert ProviderNotActive(providerId);
        providers[providerId].totalCalls += newCalls;
        emit CallsRecorded(providerId, newCalls, providers[providerId].totalCalls);
    }

    // ── Discovery Views ────────────────────────────────────────────────

    function getProvider(uint256 providerId) external view returns (
        uint256 agentId,
        address providerWallet,
        string memory endpoint,
        string memory name,
        string memory description,
        SignalCategory category,
        uint256 pricePerCall,
        uint256 totalCalls,
        uint256 registeredAt,
        bool active
    ) {
        Provider storage p = providers[providerId];
        return (
            p.agentId, p.providerWallet, p.endpoint, p.name, p.description,
            p.category, p.pricePerCall, p.totalCalls, p.registeredAt, p.active
        );
    }

    function getProvidersByCategory(SignalCategory category)
        external view returns (uint256[] memory)
    {
        return categoryProviders[category];
    }

    function getActiveProvidersByCategory(SignalCategory category)
        external view returns (uint256[] memory)
    {
        uint256[] storage all = categoryProviders[category];
        uint256 count;
        for (uint256 i; i < all.length; i++) {
            if (providers[all[i]].active) count++;
        }

        uint256[] memory result = new uint256[](count);
        uint256 idx;
        for (uint256 i; i < all.length; i++) {
            if (providers[all[i]].active) {
                result[idx++] = all[i];
            }
        }
        return result;
    }

    /// @notice Get the cheapest active provider in a category
    function getCheapestProvider(SignalCategory category)
        external view returns (uint256 providerId, uint256 price)
    {
        uint256[] storage all = categoryProviders[category];
        price = type(uint256).max;

        for (uint256 i; i < all.length; i++) {
            Provider storage p = providers[all[i]];
            if (p.active && p.pricePerCall < price) {
                price = p.pricePerCall;
                providerId = all[i];
            }
        }
    }

    function totalProviders() external view returns (uint256) {
        return nextProviderId;
    }

    // ── Admin ──────────────────────────────────────────────────────────

    function transferOwnership(address newOwner) external onlyOwner {
        owner = newOwner;
    }
}
