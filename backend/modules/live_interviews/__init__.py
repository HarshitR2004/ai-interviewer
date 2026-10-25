"""Provider-independent runtime interview engine.

service coordinates guarded session operations and answer submission.
The voice agent submits finalized text through authenticated HTTP.
assessment handles provider failures, timeouts, and decision validation.
reasoning builds model requests; transitions owns deterministic interview rules.
sessions stores state and rejects overlapping operations; models defines data contracts.
"""
