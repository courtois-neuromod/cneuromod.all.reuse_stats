import pandas as pd
import random
from pathlib import Path

DEFAULT_SEED = 0


def simulation(output_dir: Path, seed: int = DEFAULT_SEED):
    """
    Generate a CSV file with random values.

    The generator is seeded, so a rerun reproduces the same table and the same
    figures. Without that, every `invoke run --force` would rewrite every
    output and fill PROVENANCE.json with checksum churn that says nothing
    about what actually changed.

    Args:
        output_dir (Path): The directory where the CSV will be saved.
        seed (int): Seed for the random generator. Defaults to DEFAULT_SEED.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    df = pd.DataFrame({
        "id": range(1, 6),
        "value": [rng.random() for _ in range(5)],
    })
    out_path = output_dir / "simulation_output.csv"
    df.to_csv(out_path, index=False)
    print(f"🧪 Simulation complete → {out_path}")

