# Single morning retailer retry

25 October 2026. The follow-up ran after the requested 09:00 IST threshold. Exact HTTP observation times and source URLs are recorded in `observations.json` (08:32 UTC, approximately 14:02 IST). The trigger timestamp is not the observation timestamp.

Read the previous three-store validation report and the current robots-aware client/parser before attempting the retry. Supported browser inventory and explicit Edge selection both failed with `transport closed before response`. No browser page, rendered product name, pack or selling price could therefore be freshly verified.

As a read-only fallback, made one bounded attempt per public source using the existing `PublicCatalogClient`, which requires a valid permitting robots policy before fetching a catalogue page. Instamart and Zepto returned HTTP 202; Blinkit returned HTTP 403. The client accepted no catalogue data. These responses do not establish that local stores are closed; this retry does not support the earlier hypothesis that opening hours explain access failures. The recorded status can occur at policy retrieval or catalogue retrieval; the client error does not identify that stage.

No location was entered, permissions accepted, login performed, cart modified or challenge bypassed. Previous fixture postcodes are not treated as customer authorization. Location-specific validation still needs an explicitly authorized research location once browser access is restored.

No parser or application changes are supported by these observations, so none were made. Existing evidence remains historical rather than newly verified. No application tests were rerun for this documentation-only result. The one-shot automation was deleted after the attempt so it will not repeat daily.
