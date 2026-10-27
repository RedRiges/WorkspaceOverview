# Project instructions

## AI commit attribution

- Every commit created by an AI agent must explicitly identify the agent and the model in the commit message, including commits made through GitHub APIs or the web interface.
- Use these trailers, replacing the values with the actual agent and model for that session:

  ```text
  AI-Agent: OpenAI Codex
  AI-Model: <actual model>
  ```

- Report the most specific model identity reliably available. Never infer the active model from a default configuration or invent a version. If only the model family is known, state that and note that the exact identifier is unavailable.
- Do not present an AI-created commit as solely human-authored. Preserve existing human attribution and do not change global Git identity settings.

## License

- This project uses GNU GPL version 3 only (`GPL-3.0-only`); see `LICENSE`.
- Preserve the license and consider dependency license compatibility when adding dependencies.
