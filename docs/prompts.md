# Prompt Strategy

The content pipeline is intentionally split into small JSON-producing steps:

1. Intent extraction
2. Prompt refinement
3. Title generation
4. Body generation
5. Hashtag generation
6. Image prompt generation
7. Safety review

Each step can be retried, traced, and eventually swapped for a different model or prompt without changing the rest of the workflow.

The default model IDs are configurable:

- `DOUBAO_TEXT_MODEL=doubao-seed-2-0-lite-260215`
- `DOUBAO_IMAGE_MODEL=doubao-seedream-5-0-260128`

