package example_test

import (
	"fmt"
	"testing"
	"time"

	"github.com/gagliardetto/solana-go"
	"github.com/gagliardetto/solana-go/rpc"
	"github.com/stretchr/testify/require"
	"go.uber.org/zap/zapcore"

	cldf_solana "github.com/smartcontractkit/chainlink-deployments-framework/chain/solana"

	cldf_chain "github.com/smartcontractkit/chainlink-deployments-framework/chain"

	chainselectors "github.com/smartcontractkit/chain-selectors"
	mcmsSolana "github.com/smartcontractkit/mcms/sdk/solana"

	cldf "github.com/smartcontractkit/chainlink-deployments-framework/deployment"

	"github.com/smartcontractkit/chainlink/deployment"
	"github.com/smartcontractkit/chainlink/deployment/ccip/changeset/testhelpers"

	"github.com/smartcontractkit/chainlink/deployment/common/changeset"
	"github.com/smartcontractkit/chainlink/deployment/common/changeset/example"
	"github.com/smartcontractkit/chainlink/deployment/common/changeset/state"
	"github.com/smartcontractkit/chainlink/deployment/common/proposalutils"
	"github.com/smartcontractkit/chainlink/deployment/common/types"
	"github.com/smartcontractkit/chainlink/deployment/environment/memory"
	"github.com/smartcontractkit/chainlink/v2/core/logger"
)

// setupFundingTestEnv deploys all required contracts for the funding test
func setupFundingTestEnv(t *testing.T) cldf.Environment {
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

func TestTransferFromTimelockConfig_VerifyPreconditions(t *testing.T) {
	t.Parallel()
	lggr := logger.TestLogger(t)
	validEnv := memory.NewMemoryEnvironment(t, lggr, zapcore.InfoLevel, memory.MemoryEnvironmentConfig{SolChains: 1})
	validSolChainSelector := validEnv.BlockChains.ListChainSelectors(cldf_chain.WithFamily(chainselectors.FamilySolana))[0]
	receiverKey := solana.NewWallet().PublicKey()
	cs := example.TransferFromTimelock{}
	timelockID := mcmsSolana.ContractAddress(
		solana.NewWallet().PublicKey(),
		[32]byte{'t', 'e', 's', 't'},
	)
	err := validEnv.ExistingAddresses.Save(validSolChainSelector, timelockID, cldf.TypeAndVersion{
		Type:    types.RBACTimelock,
		Version: deployment.Version1_0_0,
	})
	require.NoError(t, err)

	// Create an environment that simulates a chain where the MCMS contracts have not been deployed,
	// e.g. missing the required addresses so that the state loader returns empty seeds.
	noTimelockEnv := memory.NewMemoryEnvironment(t, lggr, zapcore.InfoLevel, memory.MemoryEnvironmentConfig{})
	noTimelockEnv.BlockChains = cldf_chain.NewBlockChains(map[uint64]cldf_chain.BlockChain{
		chainselectors.SOLANA_DEVNET.Selector: cldf_solana.Chain{},
	})
	err = noTimelockEnv.ExistingAddresses.Save(chainselectors.SOLANA_DEVNET.Selector, "dummy", cldf.TypeAndVersion{
		Type:    "Sometype",
		Version: deployment.Version1_0_0,
	})
	require.NoError(t, err)

	// Create an environment with a Solana chain that has an invalid (zero) underlying chain.
	invalidSolChainEnv := memory.NewMemoryEnvironment(t, lggr, zapcore.InfoLevel, memory.MemoryEnvironmentConfig{
		SolChains: 0,
	})
	invalidSolChainEnv.BlockChains = cldf_chain.NewBlockChains(map[uint64]cldf_chain.BlockChain{
		validSolChainSelector: cldf_solana.Chain{},
	})

	tests := []struct {
		name          string
		env           cldf.Environment
		config        example.TransferFromTimelockConfig
		expectedError string
	}{
		{
			name: "All preconditions satisfied",
			env:  validEnv,
			config: example.TransferFromTimelockConfig{
				AmountsPerChain: map[uint64]example.TransferData{validSolChainSelector: {
					Amount: 100,
					To:     receiverKey,
				}},
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
			config: example.TransferFromTimelockConfig{
				AmountsPerChain: map[uint64]example.TransferData{validSolChainSelector: {
					Amount: 100,
					To:     receiverKey,
				}},
			},
			expectedError: fmt.Sprintf("solana chain not found for selector %d", validSolChainSelector),
		},
		{
			name: "Chain selector not found in environment",
			env:  validEnv,
			config: example.TransferFromTimelockConfig{AmountsPerChain: map[uint64]example.TransferData{99999: {
				Amount: 100,
				To:     receiverKey,
			}}},
			expectedError: "solana chain not found for selector 99999",
		},
		{
			name: "timelock contracts not deployed (empty seeds)",
			env:  noTimelockEnv,
			config: example.TransferFromTimelockConfig{
				AmountsPerChain: map[uint64]example.TransferData{chainselectors.SOLANA_DEVNET.Selector: {
					Amount: 100,
					To:     receiverKey,
				}},
			},
			expectedError: "timelock seeds are empty, please deploy MCMS contracts first",
		},
		{
			name: "Insufficient deployer balance",
			env:  validEnv,
			config: example.TransferFromTimelockConfig{
				AmountsPerChain: map[uint64]example.TransferData{
					validSolChainSelector: {
						Amount: 999999999999999999,
						To:     receiverKey,
					},
				},
			},
			expectedError: "deployer balance is insufficient",
		},
		{
			name: "Insufficient deployer balance",
			env:  validEnv,
			config: example.TransferFromTimelockConfig{
				AmountsPerChain: map[uint64]example.TransferData{
					validSolChainSelector: {
						Amount: 999999999999999999,
						To:     receiverKey,
					},
				},
			},
			expectedError: "deployer balance is insufficient",
		},
		{
			name: "Invalid Solana chain in environment",
			env:  invalidSolChainEnv,
			config: example.TransferFromTimelockConfig{
				AmountsPerChain: map[uint64]example.TransferData{validSolChainSelector: {
					Amount: 100,
					To:     receiverKey,
				}},
			},
			expectedError: "failed to get existing addresses: chain selector 12463857294658392847: chain not found",
		},
		{
			name: "empty from field",
			env:  invalidSolChainEnv,
			config: example.TransferFromTimelockConfig{
				AmountsPerChain: map[uint64]example.TransferData{validSolChainSelector: {
					Amount: 100,
					To:     solana.PublicKey{},
				}},
			},
			expectedError: "destination address is empty",
		},
	}

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

func TestTransferFromTimelockConfig_Apply(t *testing.T) {
	t.Parallel()
	env := setupFundingTestEnv(t)
	cfgAmounts := example.TransferData{
		Amount: 100 * solana.LAMPORTS_PER_SOL,
		To:     solana.NewWallet().PublicKey(),
	}
	amountsPerChain := make(map[uint64]example.TransferData)
	solChains := env.BlockChains.SolanaChains()
	for chainSelector := range solChains {
		amountsPerChain[chainSelector] = cfgAmounts
	}
	config := example.TransferFromTimelockConfig{
		TimelockCfg:     proposalutils.TimelockConfig{MinDelay: 1 * time.Second},
		AmountsPerChain: amountsPerChain,
	}
	solChainSelector := env.BlockChains.ListChainSelectors(cldf_chain.WithFamily(chainselectors.FamilySolana))[0]
	addresses, err := env.ExistingAddresses.AddressesForChain(solChainSelector)
	require.NoError(t, err)
	mcmState, err := state.MaybeLoadMCMSWithTimelockChainStateSolana(solChains[solChainSelector], addresses)
	require.NoError(t, err)
	timelockSigner := state.GetTimelockSignerPDA(mcmState.TimelockProgram, mcmState.TimelockSeed)
	mcmSigner := state.GetMCMSignerPDA(mcmState.McmProgram, mcmState.ProposerMcmSeed)
	chainSelector := env.BlockChains.ListChainSelectors(cldf_chain.WithFamily(chainselectors.FamilySolana))[0]
	solChain := solChains[chainSelector]
	err = memory.FundSolanaAccounts(env.GetContext(), []solana.PublicKey{timelockSigner, mcmSigner, solChain.DeployerKey.PublicKey()}, 150, solChain.Client)
	require.NoError(t, err)

	changesetInstance := example.TransferFromTimelock{}

	env, _, err = changeset.ApplyChangesets(t, env, []changeset.ConfiguredChangeSet{
		changeset.Configure(changesetInstance, config),
	})
	require.NoError(t, err)

	balance, err := solChain.Client.GetBalance(env.GetContext(), cfgAmounts.To, rpc.CommitmentConfirmed)
	require.NoError(t, err)
	t.Logf("Account: %s, Balance: %d", cfgAmounts.To, balance.Value)

	require.Equal(t, cfgAmounts.Amount, balance.Value)
}
