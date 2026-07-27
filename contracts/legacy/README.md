# Legacy Agent Contract Evidence

These schemas freeze the JSON compatibility surface used while replacing the Java
`agent-service`.

Source evidence in `../langchain4j-platform`:

- `platform-protocol/.../agent/AgentRunRequest.java`
- `platform-protocol/.../agent/AgentRunReply.java`
- `platform-protocol/.../agent/AgentStep.java`
- `agent-service/.../AgentController.java`

The Java records define camelCase JSON fields:

- Request: `goal`, optional `webhookUrl`.
- Step: `n`, `thought`, `action`, `actionInput`, `observation`.
- Reply: `goal`, `steps`, `finalAnswer`, `stopReason`, `depth`, `tenantId`.

Run `uv run python scripts/export_contracts.py` after an intentional contract change and
`uv run python scripts/export_contracts.py --check` in verification/CI.

The generated schemas describe the new compatibility models. A later integration stage must also
capture the running legacy Spring OpenAPI document before traffic cutover.
