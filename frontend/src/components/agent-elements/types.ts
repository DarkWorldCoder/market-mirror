// The status contract used by Agent Elements, kept local because this host uses a Vue API client.
export type ChatStatus = "submitted" | "streaming" | "ready" | "error";

// The registry's ModelOption contract, extended with optional provider details from the host.
export type ModelOption = { id: string; name: string; version?: string; provider?: string; description?: string; available?: boolean; connection_required?: boolean; connection_backend?: string };
