package solana_test

import (
	"testing"
	"time"

	"github.com/gagliardetto/solana-go"
	"github.com/stretchr/testify/require"
	"go.uber.org/zap/zapcore"

	cldf_solana "github.com/smartcontractkit/chainlink-deployments-framework/chain/solana"

	cldf_chain "github.com/smartcontractkit/chainlink-deployments-framework/chain"

	timelockBindings "github.com/smartcontractkit/chainlink-ccip/chains/solana/gobindings/timelock"
	"github.com/smartcontractkit/chainlink-common/pkg/utils/tests"

	chainselectors "github.com/smartcontractkit/chain-selectors"
	mcmsSolana "github.com/smartcontractkit/mcms/sdk/solana"

	cldf "github.com/smartcontractkit/chainlink-deployments-framework/deployment"

	"github.com/smartcontractkit/chainlink/deployment"
	"github.com/smartcontractkit/chainlink/deployment/ccip/changeset/testhelpers"

	"github.com/smartcontractkit/chainlink/deployment/common/changeset"
	commonSolana "github.com/smartcontractkit/chainlink/deployment/common/changeset/solana"
	"github.com/smartcontractkit/chainlink/deployment/common/changeset/state"
	"github.com/smartcontractkit/chainlink/deployment/common/proposalutils"
	"github.com/smartcontractkit/chainlink/deployment/common/types"
	"github.com/smartcontractkit/chainlink/deployment/environment/memory"
	"github.com/smartcontractkit/chainlink/v2/core/logger"
)

// setupUpdateDelayTestEnv deploys all required contracts for set \delay test
func setupUpdateDelayTestEnv(t *testing.T) cldf.Environment {
	lggr := logger.TestLogger(t)
	cfg := memory.MemoryEnvironmentConfig{
		SolChains: 1,
	}
	env := memory.NewMemoryEnvironment(t, lggr, zapcore.DebugLevel, cfg)
	chainSelector := env.BlockChains.ListChainSelectors(cldf_chain.WithFamily(chainselectors.FamilySolana))[0]

	config := proposalutils.SingleGroupTimelockConfigV2(t)
	err := testhelpers.SavePreloadedSolAddresses(env, chainSelector)
	require.NoError(t, err)
	// Initialize the address book with a dummy address to avoid deploy precondition errors.
	//nolint:staticcheck // will wait till we can migrate from address book before using data store
	err = env.ExistingAddresses.Save(chainSelector, "dummyAddress", cldf.TypeAndVersion{Type: "dummy", Version: deployment.Version1_0_0})
	require.NoError(t, err)

	// Deploy MCMS and Timelock
	env, err = changeset.Apply(t, env,
		changeset.Configure(
			cldf.CreateLegacyChangeSet(changeset.DeployMCMSWithTimelockV2),
			map[uint64]types.MCMSWithTimelockConfigV2{
				chainSelector: config,
			},
		),
	)
	require.NoError(t, err)

	return env
}

func TestUpdateTimelockDelaySolana_VerifyPreconditions(t *testing.T) {
	t.Parallel()
	lggr := logger.TestLogger(t)
	validEnv := memory.NewMemoryEnvironment(t, lggr, zapcore.InfoLevel, memory.MemoryEnvironmentConfig{SolChains: 1})
	validSolChainSelector := validEnv.BlockChains.ListChainSelectors(cldf_chain.WithFamily(chainselectors.FamilySolana))[0]

	timelockID := mcmsSolana.ContractAddress(
		solana.NewWallet().PublicKey(),
		[32]byte{'t', 'e', 's', 't'},
	)
	mcmDummyProgram := solana.NewWallet().PublicKey()

	//nolint:staticcheck // will wait till we can migrate from address book before using data store
	err := validEnv.ExistingAddresses.Save(validSolChainSelector, timelockID, cldf.TypeAndVersion{
		Type:    types.RBACTimelock,
		Version: deployment.Version1_0_0,
	})
	require.NoError(t, err)
	mcmsProposerIDEmpty := mcmsSolana.ContractAddress(
		mcmDummyProgram,
		[32]byte{},
	)

	// Create an environment that simulates a chain where the timelock program has not been deployed,
	// e.g. missing the required addresses so that the state loader returns empty seeds.
	noTimelockEnv := memory.NewMemoryEnvironment(t, lggr, zapcore.InfoLevel, memory.MemoryEnvironmentConfig{})
	noTimelockEnv.BlockChains = cldf_chain.NewBlockChains(map[uint64]cldf_chain.BlockChain{
		chainselectors.SOLANA_DEVNET.Selector: cldf_solana.Chain{},
	})

	//nolint:staticcheck // will wait till we can migrate from address book before using data store
	err = noTimelockEnv.ExistingAddresses.Save(chainselectors.SOLANA_DEVNET.Selector, mcmsProposerIDEmpty, cldf.TypeAndVersion{
		Type:    types.BypasserManyChainMultisig,
		Version: deployment.Version1_0_0,
	})
	require.NoError(t, err)

	// Create an environment with a Solana chain that has an invalid (zero) underlying chain.
	invalidSolChainEnv := memory.NewMemoryEnvironment(t, lggr, zapcore.InfoLevel, memory.MemoryEnvironmentConfig{})
	invalidSolChainEnv.BlockChains = cldf_chain.NewBlockChains(map[uint64]cldf_chain.BlockChain{
		validSolChainSelector: cldf_solana.Chain{},
	})

	tests := []struct {
		name          string
		env           cldf.Environment
		config        commonSolana.UpdateTimelockDelaySolanaCfg
		expectedError string
	}{
		{
			name: "All preconditions satisfied",
			env:  validEnv,
			config: commonSolana.UpdateTimelockDelaySolanaCfg{
				DelayPerChain: map[uint64]time.Duration{validSolChainSelector: 5 * time.Minute},
			},
			expectedError: "",
		},
		{
			name: "No Solana chains found in environment",
			env: memory.NewMemoryEnvironment(t, lggr, zapcore.InfoLevel, memory.MemoryEnvironmentConfig{
				Bootstraps: 1,
				Chains:     1,
				SolChains:  0,
				Nodes:      1,
			}),
			config: commonSolana.UpdateTimelockDelaySolanaCfg{
				DelayPerChain: map[uint64]time.Duration{validSolChainSelector: 5 * time.Minute},
			},
			expectedError: "no solana chains provided",
		},
		{
			name: "Chain selector not found in environment",
			env:  validEnv,
			config: commonSolana.UpdateTimelockDelaySolanaCfg{
				DelayPerChain: map[uint64]time.Duration{9999: 5 * time.Minute},
			},
			expectedError: "solana chain not found for selector 9999",
		},
		{
			name: "Timelock not deployed (empty seeds)",
			env:  noTimelockEnv,
			config: commonSolana.UpdateTimelockDelaySolanaCfg{
				DelayPerChain: map[uint64]time.Duration{chainselectors.SOLANA_DEVNET.Selector: 5 * time.Minute},
			},
			expectedError: "timelock program not deployed for chain 16423721717087811551",
		},
		{
			name:          "empty config provided",
			env:           invalidSolChainEnv,
			config:        commonSolana.UpdateTimelockDelaySolanaCfg{},
			expectedError: "no delay configs provided",
		},
	}

	cs := commonSolana.UpdateTimelockDelaySolana{}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := cs.VerifyPreconditions(tt.env, tt.config)
			if tt.expectedError == "" {
				require.NoError(t, err)
			} else {
				require.Error(t, err)
				require.Contains(t, err.Error(), tt.expectedError)
			}
		})
	}
}

func TestUpdateTimelockDelaySolana_Apply(t *testing.T) {
	tests.SkipFlakey(t, "https://smartcontract-it.atlassian.net/browse/DX-762")
	t.Parallel()
	env := setupUpdateDelayTestEnv(t)
	newDelayDuration := 5 * time.Minute
	solChainSel := env.BlockChains.ListChainSelectors(cldf_chain.WithFamily(chainselectors.FamilySolana))[0]
	config := commonSolana.UpdateTimelockDelaySolanaCfg{
		DelayPerChain: map[uint64]time.Duration{
			solChainSel: newDelayDuration,
		},
	}

	changesetInstance := commonSolana.UpdateTimelockDelaySolana{}

	env, _, err := changeset.ApplyChangesets(t, env, []changeset.ConfiguredChangeSet{
		changeset.Configure(changesetInstance, config),
	})
	require.NoError(t, err)

	chainSelector := env.BlockChains.ListChainSelectors(cldf_chain.WithFamily(chainselectors.FamilySolana))[0]
	solChain := env.BlockChains.SolanaChains()[chainSelector]
	//nolint:staticcheck // will wait till we can migrate from address book before using data store
	addresses, err := env.ExistingAddresses.AddressesForChain(chainSelector)
	require.NoError(t, err)

	// Check new delay config value
	mcmState, err := state.MaybeLoadMCMSWithTimelockChainStateSolana(solChain, addresses)
	require.NoError(t, err)

	timelockConfigPDA := state.GetTimelockConfigPDA(mcmState.TimelockProgram, mcmState.TimelockSeed)
	var timelockConfig timelockBindings.Config
	err = solChain.GetAccountDataBorshInto(env.GetContext(), timelockConfigPDA, &timelockConfig)
	require.NoError(t, err)
	require.Equal(t, timelockConfig.MinDelay, uint64(newDelayDuration.Seconds()))
}
