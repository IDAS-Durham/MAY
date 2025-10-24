import numpy as np
from scipy import stats

class StatMaker:
    def __init__(self):
        self.stats = {}
        self._next_stat_id = 0

    def _generate_stat_id(self):
        self._next_stat_id += 1
        return self._next_stat_id

    def collect_statistics(self,data):
        """Returns some common statistics from a distribution.

        Args:
          data (array-like): The data to analyse.

        Returns:
          (dict): Dict containing statistical properties. 
        """
        arr = np.array(data)
        
        # Remove NaN values if present
        arr = arr[~np.isnan(arr)]

        if len(arr) == 0:
            return {"error": "Empty array or all NaN values"}

        return {
            # Central tendency
            "mean": np.mean(arr),
            "median": np.median(arr),
            "mode": stats.mode(arr, keepdims=True).mode[0],

            # Spread/Dispersion
            "std": np.std(arr, ddof=1),  # sample std
            "variance": np.var(arr, ddof=1),  # sample variance
            "range": np.ptp(arr),  # peak-to-peak (max - min)
            "iqr": stats.iqr(arr),  # interquartile range
            "mad": stats.median_abs_deviation(arr),  # median absolute deviation

            # Position
            "min": np.min(arr),
            "max": np.max(arr),
            "q1": np.percentile(arr, 25),  # 1st quartile
            "q3": np.percentile(arr, 75),  # 3rd quartile

            # Shape
            "skewness": stats.skew(arr),
            "kurtosis": stats.kurtosis(arr),

            # Sample properties
            "count": len(arr),
            "sum": np.sum(arr),

            # Coefficient of variation (relative std)
            "cv": np.std(arr, ddof=1) / np.mean(arr) if np.mean(arr) != 0 else np.inf
        }


