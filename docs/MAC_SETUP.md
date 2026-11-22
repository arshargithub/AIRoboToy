# Mac development setup

From the repository root, create the environments from their locks using Python 3.11 and uv:

```sh
UV_PROJECT_ENVIRONMENT="$PWD/.venv-tavi" uv sync --frozen --extra audio --extra local-asr --extra conversation --extra memory-pilot --extra speaker-id
UV_PROJECT_ENVIRONMENT="$PWD/.venv-asr-mlx" uv sync --frozen --project experiments/asr-mlx
UV_PROJECT_ENVIRONMENT="$PWD/.venv-k-speech" uv sync --frozen --project experiments/k-speech
```

For the speech files, see `tavi.setup_audio`, `tavi.setup_live_wake`, `tavi.setup_asr_comparison`, `tavi.setup_neural_voice`, `tavi.kokoro_k` and `tavi.setup_k_speech`. These modules record or check model paths under `.tavi/models`. Read their options before downloading an optional voice or comparison model.

From `desktop/`, run `npm ci` and `npm run build`. The development bundle is written under `.tavi/mac/build`. It is tied to the checkout it was built from. Ongoing household work also depends on machine-local storage and qualification artifacts from the original installation. For a new machine, start with the offline simulator to verify the source and dependencies before configuring a desk app installation.
