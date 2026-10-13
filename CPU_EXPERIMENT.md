# A completed CPU experiment

On 2026-10-13 we ran a real handwritten digit classification experiment using scikit-learn's bundled UCI digits dataset. This is a bounded local baseline with actual fitted model weights, not an LLM simulation, cat/dog model, or completed general conversational training backend.

| Item | Measured result |
| --- | --- |
| Dataset | 1,797 grayscale images, 8×8, digits 0–9 |
| Split | 1,078 training / 359 development / 360 test |
| Model | Multiclass logistic regression on pixels divided by 16 |
| Candidate C values | 0.1, 1, 10 |
| Development accuracies | 94.43%, 95.82%, 95.26% |
| Selected C | 1, using development data only |
| Held-out accuracy | **344 / 360 = 95.56%** |
| GPU / API calls | 0 / 0 |
| Export reload | Predictions agree with the fitted scikit-learn model |
| Sample | Expected 5, predicted 5, confidence 0.99635 |

The target was to measure a baseline, so no user acceptance threshold was invented. A 95.56% result on this small held-out split does not establish production performance. The first development attempt failed at inference output writing; its artifact directory was retained. The final run used the same preselected split/recipe in a fresh directory and completed successfully.

## Run on your server

Python 3.11+ is required by the pinned scikit-learn version. In the repository, using your chosen virtual environment:

```sh
python3 -m pip install -e '.[cpu]'
python3 -m vision_rsi.cpu_experiment run --output ./runs/digits-baseline-001
```

Use a new output directory for each run. The experiment uses bundled data and needs no API key, SSH, dataset download or GPU. It uses one numerical-computation thread and three bounded training candidates. It creates a task session and runs the project's interface harness, then trains, selects, exports and scores through a dedicated trusted CPU driver. It does not claim the interactive `training start` flow can perform arbitrary training.

The directory contains the frozen split IDs and image hashes, candidate metrics, a JSON model, label-free test inputs, held-out labels, predictions, interface check receipt, artifact hashes and `report.json`. Training convergence, split overlap, prediction coverage, output schema and export equivalence are checked. The test set is scored after model selection and is not used to choose C.

Reload the trained model in a new process:

```sh
python3 -m vision_rsi.cpu_experiment predict \
  --model ./runs/digits-baseline-001/model.json \
  --input ./runs/digits-baseline-001/sample-input.json \
  --output ./runs/digits-baseline-001/reloaded-prediction.json
```

Inference requires only the project and Python standard library; it does not load a pickle or require scikit-learn. Input is the dedicated experiment format: sample ID and 64 pixel intensities in 0–16. This is not a general image-file inference adapter.

## Saved outputs and tests

Measured outputs, the trained model and a sample are in [examples/results/digits-cpu-20261013](examples/results/digits-cpu-20261013). The full local run is under `/workspace/vision-rsi-dev/digits-experiment-20261013-v2` in the validation workspace.

```sh
python3 -m unittest discover -s tests -p test_cpu_experiment.py -v
```

The real-training test is skipped if the CPU extra is not installed. It was separately run here with scikit-learn 1.8.0 installed and passed; exported sample inference was also run using the project's environment without scikit-learn.
