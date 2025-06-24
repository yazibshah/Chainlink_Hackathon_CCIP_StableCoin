package webapi

import (
	"github.com/pkg/errors"

	libjobs "github.com/smartcontractkit/chainlink/system-tests/lib/cre/don/jobs"
	libnode "github.com/smartcontractkit/chainlink/system-tests/lib/cre/don/node"
	"github.com/smartcontractkit/chainlink/system-tests/lib/cre/flags"
	"github.com/smartcontractkit/chainlink/system-tests/lib/cre/types"
)

var WebAPITriggerJobSpecFactoryFn = func(input *types.JobSpecFactoryInput) (types.DonsToJobSpecs, error) {
	return GenerateWebAPITriggerJobSpecs(input.DonTopology)
}

func GenerateWebAPITriggerJobSpecs(donTopology *types.DonTopology) (types.DonsToJobSpecs, error) {
	if donTopology == nil {
		return nil, errors.New("topology is nil")
	}
	donToJobSpecs := make(types.DonsToJobSpecs)

	for _, donWithMetadata := range donTopology.DonsWithMetadata {
		workflowNodeSet, err := libnode.FindManyWithLabel(donWithMetadata.NodesMetadata, &types.Label{Key: libnode.NodeTypeKey, Value: types.WorkerNode}, libnode.EqualLabels)
		if err != nil {
			return nil, errors.Wrap(err, "failed to find worker nodes")
		}

		for _, workerNode := range workflowNodeSet {
			nodeID, nodeIDErr := libnode.FindLabelValue(workerNode, libnode.NodeIDKey)
			if nodeIDErr != nil {
				return nil, errors.Wrap(nodeIDErr, "failed to get node id from labels")
			}

			if flags.HasFlag(donWithMetadata.Flags, types.WebAPITriggerCapability) {
				if _, ok := donToJobSpecs[donWithMetadata.ID]; !ok {
					donToJobSpecs[donWithMetadata.ID] = make(types.DonJobs, 0)
				}
				donToJobSpecs[donWithMetadata.ID] = append(donToJobSpecs[donWithMetadata.ID], libjobs.WorkerStandardCapability(nodeID, types.WebAPITriggerCapability, "__builtin_web-api-trigger", libjobs.EmptyStdCapConfig))
			}
		}
	}

	return donToJobSpecs, nil
}
