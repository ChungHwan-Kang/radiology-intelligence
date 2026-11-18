# Foreground worker boundary

The inbox in approval_worker.py implements durable local replay protection,
one active article across event IDs, restart persistence, explicit partial
recovery and an idempotent completion outbox. Its loop runs only when a host
starts it. No scheduled task or server is installed.

## Human approval

A future Windows approval surface must display the locally validated identity,
payload/source digests, source contract, component scope and recovery
delegation before accepting one direct user decision. The Windows user SID and
an immutable local acceptance record belong in its provenance. A document
editor ID belongs in separate provider provenance fields. The worker must never
derive WINDOWS_DIRECT from a Drive edit, Notion property or chat phrase.

Inbox.accept takes provenance from that trusted host. The module cannot prove
that a dictionary came from a human. It has no production ingestion or approval
UI, and must not be exposed to arbitrary remote JSON as a privileged endpoint.
Current_Handoff remains the proposed remote event/status record. Local
recovery permission must match the recovery scope shown in the actual UI.

## Existing scheduled writer capability probe

Both existing automation view calls returned only a rendered card acknowledgment.
No machine-readable prompt, run capability manifest, CAS execution receipt or
ENTER/EXIT/ACK trace was returned. No matching local automation.toml was found.
The Docs connector does expose write_control.requiredRevisionId. This proves
the available API can express a conditional document write, but does not
establish that either scheduled sandbox can invoke it or comply.

Actual support for the two jobs is therefore NOT VERIFIED. A live protocol
probe would write control records and needs operational authorization.

If both jobs can call conditional Docs writes, a shared helper and approved
changes to their existing prompts can add ENTER/EXIT/ACK without another server.
If they cannot, prompt-only editing cannot implement atomic coordination.
Options are an authorized common writer in the existing Windows process, with
the discovery jobs producing queued intents, or another separately approved
execution environment. Relocating writes changes the existing operational
workflow and is not done here.

## Publisher boundary

run_once invokes an injected existing publisher only after claim and an external
writer guard. This guard must enforce ownership for every remote mutation,
including recovery; a context manager by itself is not that enforcement.
The production adapter and guard remain unwired. The host must bind event
identity to read_inputs and the original prepared snapshot before invoking
windows_ri_release.run_release. It must preserve the original receipt and
snapshot digest, never mint approval flags, scope evidence or writer evidence.

Only a durable successful provider result moves to DONE. Exceptions become
PARTIAL without exception text in the inbox. SIGKILL leaves RUNNING ownership
blocked for reconciliation. No lease timeout silently clears that ownership.
After external verification of process death and remote outcome, a future
reconciler can mark the interrupted attempt recoverable. No blind lock reset
command is provided.

Pending unstarted expiry blocks. A started PARTIAL identity may recover after
expiry only with previously recorded recovery delegation and current revocation
and writer checks. The host must verify the original snapshot content on every
retry. A DONE replay cannot call the publisher again.

## Next candidate

DONE atomically creates a PENDING outbox state. continue_candidate calls a host
notifier that conditionally upserts NEXT_CANDIDATE_PENDING in Current_Handoff
using completion event ID, then marks ACK after persistence is acknowledged.
That ACK is only delivery acknowledgment. The existing 07:40 evaluator must
separately record evaluation completion. No new article ID is allocated.
The notifier must tolerate a lost response after commit and repeated calls.
Publication remains DONE when notification fails.

Tests use a temporary private inbox and synthetic provenance and publisher
callbacks. They do not demonstrate direct-user capture, scheduled writer
participation, remote CAS, or a live release.
