package changeset

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io/fs"

	workflowUtils "github.com/smartcontractkit/chainlink-common/pkg/workflows"

	cldf "github.com/smartcontractkit/chainlink-deployments-framework/deployment"

	"github.com/smartcontractkit/chainlink/deployment"
	"github.com/smartcontractkit/chainlink/deployment/data-feeds/shared"
)

func FeedIDsToBytes16(feedIDs []string) ([][16]byte, error) {
	dataIDs := make([][16]byte, len(feedIDs))
	for i, feedID := range feedIDs {
		err := shared.ValidateFeedID(feedID)
		if err != nil {
			return nil, err
		}
		dataIDs[i], err = ConvertHexToBytes16(feedID)
		if err != nil {
			return nil, err
		}
	}

	return dataIDs, nil
}

func FeedIDsToBytes(feedIDs []string) ([][]byte, error) {
	dataIDs16, err := FeedIDsToBytes16(feedIDs)
	if err != nil {
		return nil, err
	}

	dataSlices := make([][]byte, len(dataIDs16))
	for i, v := range dataIDs16 {
		b := make([]byte, 16)
		copy(b, v[:])
		dataSlices[i] = b
	}

	return dataSlices, nil
}

func ConvertHexToBytes16(hexStr string) ([16]byte, error) {
	if hexStr[:2] == "0x" {
		hexStr = hexStr[2:] // Remove "0x" prefix
	}
	decodedBytes, err := hex.DecodeString(hexStr)
	if err != nil {
		return [16]byte{}, fmt.Errorf("failed to decode hex string: %w", err)
	}

	var result [16]byte
	copy(result[:], decodedBytes[:16])

	return result, nil
}

// HashedWorkflowName returns first 10 bytes of the sha256(workflow_name)
func HashedWorkflowName(name string) [10]byte {
	nameHash := workflowUtils.HashTruncateName(name)
	var result [10]byte
	copy(result[:], nameHash)
	return result
}

func LoadJSON[T any](pth string, fs fs.ReadFileFS) (T, error) {
	var dflt T
	f, err := fs.ReadFile(pth)
	if err != nil {
		return dflt, fmt.Errorf("failed to read %s: %w", pth, err)
	}
	var v T
	err = json.Unmarshal(f, &v)
	if err != nil {
		return dflt, fmt.Errorf("failed to unmarshal JSON: %w", err)
	}
	return v, nil
}

func GetDecimalsFromFeedID(feedID string) (uint8, error) {
	err := shared.ValidateFeedID(feedID)
	if err != nil {
		return 0, fmt.Errorf("invalid feed ID: %w", err)
	}
	feedIDBytes, err := ConvertHexToBytes16(feedID)
	if err != nil {
		return 0, fmt.Errorf("failed to convert feed ID to bytes: %w", err)
	}

	if feedIDBytes[7] >= 0x20 && feedIDBytes[7] <= 0x60 {
		return feedIDBytes[7] - 32, nil
	}

	return 0, nil
}

func GetDataFeedsCacheAddress(ab cldf.AddressBook, chainSelector uint64, label *string) string {
	dataFeedsCacheAddress := ""
	cacheTV := cldf.NewTypeAndVersion(DataFeedsCache, deployment.Version1_0_0)
	if label != nil {
		cacheTV.Labels.Add(*label)
	} else {
		cacheTV.Labels.Add("data-feeds")
	}

	address, err := ab.AddressesForChain(chainSelector)
	if err != nil {
		return ""
	}

	for addr, tv := range address {
		if tv.String() == cacheTV.String() {
			dataFeedsCacheAddress = addr
		}
	}

	return dataFeedsCacheAddress
}
