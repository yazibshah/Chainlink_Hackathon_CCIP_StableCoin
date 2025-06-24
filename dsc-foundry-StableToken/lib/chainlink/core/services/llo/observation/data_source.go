package observation

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"sort"
	"strconv"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"golang.org/x/exp/maps"

	ocrtypes "github.com/smartcontractkit/libocr/offchainreporting2plus/types"

	"github.com/smartcontractkit/chainlink-common/pkg/logger"
	llotypes "github.com/smartcontractkit/chainlink-common/pkg/types/llo"
	"github.com/smartcontractkit/chainlink-data-streams/llo"

	"github.com/smartcontractkit/chainlink/v2/core/services/pipeline"
	"github.com/smartcontractkit/chainlink/v2/core/services/streams"
)

var (
	promMissingStreamCount = promauto.NewCounterVec(prometheus.CounterOpts{
		Namespace: "llo",
		Subsystem: "datasource",
		Name:      "stream_missing_count",
		Help:      "Number of times we tried to observe a stream, but it was missing",
	},
		[]string{"streamID"},
	)
	promObservationErrorCount = promauto.NewCounterVec(prometheus.CounterOpts{
		Namespace: "llo",
		Subsystem: "datasource",
		Name:      "stream_observation_error_count",
		Help:      "Number of times we tried to observe a stream, but it failed with an error",
	},
		[]string{"streamID"},
	)
)

type ErrObservationFailed struct {
	inner    error
	reason   string
	streamID streams.StreamID
	run      *pipeline.Run
}

func (e *ErrObservationFailed) Error() string {
	s := fmt.Sprintf("StreamID: %d; Reason: %s", e.streamID, e.reason)
	if e.inner != nil {
		s += fmt.Sprintf("; Err: %v", e.inner)
	}
	if e.run != nil {
		// NOTE: Could log more info about the run here if necessary
		s += fmt.Sprintf("; RunID: %d; RunErrors: %v", e.run.ID, e.run.AllErrors)
	}
	return s
}

func (e *ErrObservationFailed) String() string {
	return e.Error()
}

func (e *ErrObservationFailed) Unwrap() error {
	return e.inner
}

var _ llo.DataSource = &dataSource{}

type dataSource struct {
	lggr        logger.Logger
	registry    Registry
	t           Telemeter
	shouldCache bool
}

func NewDataSource(lggr logger.Logger, registry Registry, t Telemeter) llo.DataSource {
	return newDataSource(lggr, registry, t, true)
}

func newDataSource(lggr logger.Logger, registry Registry, t Telemeter, shouldCache bool) *dataSource {
	return &dataSource{
		lggr:        logger.Named(lggr, "DataSource"),
		registry:    registry,
		t:           t,
		shouldCache: shouldCache,
	}
}

// Observe looks up all streams in the registry and populates a map of stream ID => value
func (d *dataSource) Observe(ctx context.Context, streamValues llo.StreamValues, opts llo.DSOpts) error {
	now := time.Now()
	lggr := logger.With(d.lggr, "observationTimestamp", opts.ObservationTimestamp(), "configDigest", opts.ConfigDigest(), "seqNr", opts.OutCtx().SeqNr)

	if opts.VerboseLogging() {
		streamIDs := make([]streams.StreamID, 0, len(streamValues))
		for streamID := range streamValues {
			streamIDs = append(streamIDs, streamID)
		}
		sort.Slice(streamIDs, func(i, j int) bool { return streamIDs[i] < streamIDs[j] })
		lggr = logger.With(lggr, "streamIDs", streamIDs)
		lggr.Debugw("Observing streams")
	}

	var wg sync.WaitGroup
	wg.Add(len(streamValues))

	var mu sync.Mutex
	successfulStreamIDs := make([]streams.StreamID, 0, len(streamValues))
	var errs []ErrObservationFailed

	// oc only lives for the duration of this Observe call
	oc := NewObservationContext(lggr, d.registry, d.t)

	// Telemetry
	{
		// Size needs to accommodate the max number of telemetry events that could be generated
		// Standard case might be about 3 bridge requests per spec and one stream<=>spec
		// Overallocate for safety (to avoid dropping packets)
		telemCh := d.t.MakeObservationScopedTelemetryCh(opts, 10*len(streamValues))
		if telemCh != nil {
			if d.t.CaptureEATelemetry() {
				ctx = pipeline.WithTelemetryCh(ctx, telemCh)
			}
			if d.t.CaptureObservationTelemetry() {
				ctx = WithObservationTelemetryCh(ctx, telemCh)
			}
			// After all Observations have returned, nothing else will be sent to the
			// telemetry channel, so it can safely be closed
			defer close(telemCh)
		}
	}

	// Observe all streams concurrently
	for _, streamID := range maps.Keys(streamValues) {
		go func(streamID llotypes.StreamID) {
			defer wg.Done()
			var val llo.StreamValue
			var err error

			// check for valid cached value before observing
			if val = d.fromCache(opts.ConfigDigest(), streamID); val == nil {
				// no valid cached value, observe the stream
				if val, err = oc.Observe(ctx, streamID, opts); err != nil {
					strmIDStr := strconv.FormatUint(uint64(streamID), 10)
					if errors.As(err, &MissingStreamError{}) {
						promMissingStreamCount.WithLabelValues(strmIDStr).Inc()
					}
					promObservationErrorCount.WithLabelValues(strmIDStr).Inc()
					mu.Lock()
					errs = append(errs, ErrObservationFailed{inner: err, streamID: streamID, reason: "failed to observe stream"})
					mu.Unlock()
					return
				}

				// cache the observed value
				d.toCache(opts.ConfigDigest(), streamID, val, opts.OutCtx().SeqNr)
			}

			mu.Lock()
			defer mu.Unlock()

			successfulStreamIDs = append(successfulStreamIDs, streamID)
			if val != nil {
				streamValues[streamID] = val
			}
		}(streamID)
	}

	// Wait for all Observations to complete
	wg.Wait()

	// Only log on errors or if VerboseLogging is turned on
	if len(errs) > 0 || opts.VerboseLogging() {
		elapsed := time.Since(now)

		slices.Sort(successfulStreamIDs)
		sort.Slice(errs, func(i, j int) bool { return errs[i].streamID < errs[j].streamID })

		failedStreamIDs := make([]streams.StreamID, len(errs))
		errStrs := make([]string, len(errs))
		for i, e := range errs {
			errStrs[i] = e.String()
			failedStreamIDs[i] = e.streamID
		}

		lggr = logger.With(lggr, "elapsed", elapsed, "nSuccessfulStreams",
			len(successfulStreamIDs), "nFailedStreams", len(failedStreamIDs), "errs", errStrs)

		if opts.VerboseLogging() {
			lggr = logger.With(lggr, "streamValues", streamValues)
		}

		if len(errs) == 0 && opts.VerboseLogging() {
			lggr.Infow("Observation succeeded for all streams")
		} else if len(errs) > 0 {
			lggr.Warnw("Observation failed for streams")
		}
	}

	return nil
}

func (d *dataSource) fromCache(configDigest ocrtypes.ConfigDigest, streamID llotypes.StreamID) llo.StreamValue {
	if d.shouldCache {
		if streamValue, found := GetCache(configDigest).Get(streamID); found && streamValue != nil {
			return streamValue
		}
	}
	return nil
}

func (d *dataSource) toCache(configDigest ocrtypes.ConfigDigest, streamID llotypes.StreamID, val llo.StreamValue, seqNr uint64) {
	if d.shouldCache && val != nil {
		// Use the current sequence number as the cache key
		GetCache(configDigest).Add(streamID, val, seqNr)
	}
}
