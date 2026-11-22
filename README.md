# AIRoboToy and Paprika

Paprika is a Mac voice companion built around a local Python core and an Electron window. The companion listens for its name, transcribes locally with Whisper, and speaks with Kokoro. Online replies are optional and use accepted conversation text. The `robo_core` directory retains the earlier prototype.

The branch contains the app source, dependency locks, model setup scripts and synthetic test fixtures. Household roles use example identifiers. Saved household profiles, recordings, private experiment records and local service configuration belong to the installation that created them. Some experiment scripts require separately retained inputs and will stop without them.

## Offline simulator

From the repository root, use Python 3.11 to start a simulator with typed input:

```sh
python3.11 -m tavi
```

Open `http://127.0.0.1:8765/`. Use the simulator with fictional inputs. The simulator settings and its ledger are local to the checkout.

## Mac development build

The desktop code is in `desktop/`. Use the root `uv.lock` for the `.venv-tavi` environment and the locks in `experiments/asr-mlx/` and `experiments/k-speech/` for `.venv-asr-mlx` and `.venv-k-speech`. The associated extras and provisioning notes are in the [Mac setup guide](docs/MAC_SETUP.md).

The Electron development bundle starts the core from the checkout recorded at build time. The Mac app expects an existing local spending ledger, local model files and the configured external volume. Restore an existing installation's ledger before enabling online replies. Model setup scripts download pinned weights separately from source control.
