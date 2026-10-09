"""Task-neutral, finite-space research fixture for testing strategy comparisons."""
import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    name: str = 'coco_detection_fixture'
    metric: str = 'synthetic_box_ap'
    direction: str = 'maximize'

    def utility(self, value):
        if self.direction not in ('maximize', 'minimize'):
            raise ValueError('Unknown metric direction')
        return value if self.direction == 'maximize' else -value


RECIPES = tuple({'learning_rate_scale': lr, 'augmentation_strength': aug}
                for lr in (1.0, 0.5, 1.5) for aug in (1.0, 0.8, 1.2))


def fingerprint(recipe):
    return hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()


def propose(history, strategy, task):
    if strategy not in ('sequential', 'adaptive'):
        raise ValueError('Unknown strategy')
    seen = {fingerprint(row['recipe']) for row in history}
    remaining = [recipe for recipe in RECIPES if fingerprint(recipe) not in seen]
    if not remaining:
        return None
    if strategy == 'sequential' or not history:
        return remaining[0]
    best = max(history, key=lambda row: task.utility(row['metric_value']))['recipe']
    # Local search around the incumbent, with deterministic tie breaking.
    return min(remaining, key=lambda recipe: sum(abs(recipe[k] - best[k]) for k in best))


def evaluate(recipe, seed):
    # Common seed/recipe fixture across strategies; no real training or evaluation.
    noise = int(hashlib.sha256(f'{seed}:{fingerprint(recipe)}'.encode()).hexdigest()[:8], 16) % 101 / 1000
    return round(31 - (recipe['learning_rate_scale'] - 0.5) ** 2
                 - (recipe['augmentation_strength'] - 0.8) ** 2 + noise, 4)


def study(strategy, seed, budget, task=None):
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
        raise ValueError('Fixture budget must be a nonnegative integer')
    task = task or Task()
    history = []
    for _ in range(budget):
        recipe = propose(history, strategy, task)
        if recipe is None:
            break
        history.append({'id': fingerprint(recipe), 'recipe': recipe,
                        'metric_value': evaluate(recipe, seed), 'status': 'completed',
                        'simulated_gpu_hours': 1})
    values = [row['metric_value'] for row in history]
    best = max(values, key=task.utility) if values else None
    return {'strategy': strategy, 'seed': seed, 'task': task.__dict__,
            'synthetic': True, 'budget_gpu_hours': budget,
            'spent_gpu_hours': len(history), 'best_metric': best, 'experiments': history}


def compare(budget=4, seeds=(11, 22, 33)):
    return {'synthetic': True, 'interpretation': 'Program fixture only; not evidence of RSI improvement.',
            'paired_runs': [{'seed': seed, 'sequential': study('sequential', seed, budget),
                             'adaptive': study('adaptive', seed, budget)} for seed in seeds]}
