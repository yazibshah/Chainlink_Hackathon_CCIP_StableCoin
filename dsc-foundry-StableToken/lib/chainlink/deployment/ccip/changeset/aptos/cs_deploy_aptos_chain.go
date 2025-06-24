package aptos

import (
	"errors"
	"fmt"

	"github.com/aptos-labs/aptos-go-sdk"
	"github.com/smartcontractkit/mcms"
	mcmstypes "github.com/smartcontractkit/mcms/types"

	cldf "github.com/smartcontractkit/chainlink-deployments-framework/deployment"
	"github.com/smartcontractkit/chainlink-deployments-framework/operations"
	"github.com/smartcontractkit/chainlink/deployment"
	"github.com/smartcontractkit/chainlink/deployment/ccip/changeset/aptos/config"
	"github.com/smartcontractkit/chainlink/deployment/ccip/changeset/aptos/operation"
	seq "github.com/smartcontractkit/chainlink/deployment/ccip/changeset/aptos/sequence"
	"github.com/smartcontractkit/chainlink/deployment/ccip/changeset/aptos/utils"
	"github.com/smartcontractkit/chainlink/deployment/ccip/shared"
	"github.com/smartcontractkit/chainlink/deployment/ccip/shared/stateview"
	aptosstate "github.com/smartcontractkit/chainlink/deployment/ccip/shared/stateview/aptos"
	contracttypes "github.com/smartcontractkit/chainlink/deployment/common/types"
)

var _ cldf.ChangeSetV2[config.DeployAptosChainConfig] = DeployAptosChain{}

// DeployAptosChain deploys Aptos chain packages and modules
type DeployAptosChain struct{}

func (cs DeployAptosChain) VerifyPreconditions(env cldf.Environment, config config.DeployAptosChainConfig) error {
	// Validate env and prerequisite contracts
	state, err := aptosstate.LoadOnchainStateAptos(env)
	if err != nil {
		return fmt.Errorf("failed to load existing Aptos onchain state: %w", err)
	}
	aptosChains := env.BlockChains.AptosChains()
	var errs []error
	for chainSel := range config.ContractParamsPerChain {
		if err := config.Validate(); err != nil {
			errs = append(errs, fmt.Errorf("invalid config for Aptos chain %d: %w", chainSel, err))
			continue
		}
		if _, ok := aptosChains[chainSel]; !ok {
			errs = append(errs, fmt.Errorf("aptos chain %d not found in env", chainSel))
		}
		chainState, ok := state[chainSel]
		if !ok {
			errs = append(errs, fmt.Errorf("aptos chain %d not found in state", chainSel))
			continue
		}
		if chainState.MCMSAddress == (aptos.AccountAddress{}) {
			mcmsConfig := config.MCMSDeployConfigPerChain[chainSel]
			for _, cfg := range []mcmstypes.Config{mcmsConfig.Bypasser, mcmsConfig.Canceller, mcmsConfig.Proposer} {
				if err := cfg.Validate(); err != nil {
					errs = append(errs, fmt.Errorf("invalid mcms configs for Aptos chain %d: %w", chainSel, err))
				}
			}
		}
	}

	return errors.Join(errs...)
}

func (cs DeployAptosChain) Apply(env cldf.Environment, cfg config.DeployAptosChainConfig) (cldf.ChangesetOutput, error) {
	state, err := stateview.LoadOnchainState(env)
	if err != nil {
		return cldf.ChangesetOutput{}, fmt.Errorf("failed to load Aptos onchain state: %w", err)
	}

	ab := cldf.NewMemoryAddressBook()
	seqReports := make([]operations.Report[any, any], 0)
	proposals := make([]mcms.TimelockProposal, 0)

	aptosChains := env.BlockChains.AptosChains()
	// Deploy CCIP on each Aptos chain in config
	for chainSel := range cfg.ContractParamsPerChain {
		var mcmsOperations []mcmstypes.BatchOperation
		aptosChain := aptosChains[chainSel]

		deps := operation.AptosDeps{
			AB:               ab,
			AptosChain:       aptosChain,
			CCIPOnChainState: state,
		}

		// MCMS Deploy operations
		mcmsSeqReport, err := operations.ExecuteSequence(env.OperationsBundle, seq.DeployMCMSSequence, deps, cfg.MCMSDeployConfigPerChain[chainSel])
		if err != nil {
			return cldf.ChangesetOutput{}, err
		}
		seqReports = append(seqReports, mcmsSeqReport.ExecutionReports...)
		mcmsOperations = append(mcmsOperations, mcmsSeqReport.Output.MCMSOperation)

		// Save MCMS address
		typeAndVersion := cldf.NewTypeAndVersion(shared.AptosMCMSType, deployment.Version1_6_0)
		err = deps.AB.Save(deps.AptosChain.Selector, mcmsSeqReport.Output.MCMSAddress.String(), typeAndVersion)
		if err != nil {
			return cldf.ChangesetOutput{}, fmt.Errorf("failed to save MCMS address %s for Aptos chain %d: %w", mcmsSeqReport.Output.MCMSAddress.String(), chainSel, err)
		}

		// Deploy Link token if not already deployed
		linkTokenAddress := state.AptosChains[chainSel].LinkTokenAddress
		if linkTokenAddress == (aptos.AccountAddress{}) {
			// Deploy Link token
			deployTokenIn := seq.DeployTokenSeqInput{
				TokenParams: config.TokenParams{
					MaxSupply: nil,
					Name:      "ChainLink Token",
					Symbol:    "LINK",
					Decimals:  8,
					Icon:      "https://raw.githubusercontent.com/smartcontractkit/documentation/main/public/assets/icons/link.svg",
					Project:   "https://chain.link",
				},
				MCMSAddress: mcmsSeqReport.Output.MCMSAddress,
			}
			linkSeqReport, err := operations.ExecuteSequence(env.OperationsBundle, seq.DeployAptosTokenSequence, deps, deployTokenIn)
			if err != nil {
				return cldf.ChangesetOutput{}, fmt.Errorf("failed to deploy Link token for Aptos chain %d: %w", chainSel, err)
			}
			seqReports = append(seqReports, linkSeqReport.ExecutionReports...)
			mcmsOperations = append(mcmsOperations, linkSeqReport.Output.MCMSOperations...)

			// Save Link token address
			typeAndVersion = cldf.NewTypeAndVersion(contracttypes.LinkToken, deployment.Version1_6_0)
			err = deps.AB.Save(deps.AptosChain.Selector, linkSeqReport.Output.TokenAddress.String(), typeAndVersion)
			if err != nil {
				return cldf.ChangesetOutput{}, fmt.Errorf("failed to save Link token address %s for Aptos chain %d: %w", linkSeqReport.Output.TokenAddress.String(), chainSel, err)
			}
			linkTokenAddress = linkSeqReport.Output.TokenAddress

			// Add token to config
			params := cfg.ContractParamsPerChain[chainSel]
			params.FeeQuoterParams.FeeTokens = append(params.FeeQuoterParams.FeeTokens, linkTokenAddress)
			cfg.ContractParamsPerChain[chainSel] = params
		}

		// CCIP Deploy operations
		ccipSeqInput := seq.DeployCCIPSeqInput{
			MCMSAddress:      mcmsSeqReport.Output.MCMSAddress,
			LinkTokenAddress: linkTokenAddress,
			CCIPConfig:       cfg.ContractParamsPerChain[chainSel],
		}
		ccipSeqReport, err := operations.ExecuteSequence(env.OperationsBundle, seq.DeployCCIPSequence, deps, ccipSeqInput)
		if err != nil {
			return cldf.ChangesetOutput{}, fmt.Errorf("failed to deploy CCIP for Aptos chain %d: %w", chainSel, err)
		}
		seqReports = append(seqReports, ccipSeqReport.ExecutionReports...)
		mcmsOperations = append(mcmsOperations, ccipSeqReport.Output.MCMSOperations...)

		// Save the address of the CCIP object
		typeAndVersion = cldf.NewTypeAndVersion(shared.AptosCCIPType, deployment.Version1_6_0)
		err = deps.AB.Save(deps.AptosChain.Selector, ccipSeqReport.Output.CCIPAddress.String(), typeAndVersion)
		if err != nil {
			return cldf.ChangesetOutput{}, fmt.Errorf("failed to save CCIP address %s for Aptos chain %d: %w", ccipSeqReport.Output.CCIPAddress.String(), chainSel, err)
		}

		// Generate MCMS proposals
		proposal, err := utils.GenerateProposal(
			aptosChain.Client,
			mcmsSeqReport.Output.MCMSAddress,
			chainSel,
			mcmsOperations,
			"Deploy Aptos MCMS and CCIP",
			cfg.MCMSTimelockConfigPerChain[chainSel],
		)
		if err != nil {
			return cldf.ChangesetOutput{}, fmt.Errorf("failed to generate MCMS proposal for Aptos chain %d: %w", chainSel, err)
		}
		proposals = append(proposals, *proposal)
	}
	return cldf.ChangesetOutput{
		AddressBook:           ab,
		MCMSTimelockProposals: proposals,
		Reports:               seqReports,
	}, nil
}
