"""
Label generators for ML training.

- triple_barrier: Lopez de Prado triple-barrier method (TP/SL/timeout).
- r_multiple: continuous R-multiple regression target.
- binary: legacy 0/1 label (kept for back-compat).
"""

from src.learning.labels.triple_barrier import triple_barrier_labels
from src.learning.labels.r_multiple import r_multiple_labels

__all__ = ["triple_barrier_labels", "r_multiple_labels"]
