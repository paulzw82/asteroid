import json
import warnings
import traceback
from pprint import pprint

from .utils import average_arrays_in_dic
from pb_bss_eval import InputMetrics, OutputMetrics


from typing import List, Union
import numpy as np
import pandas as pd
from dataclasses import dataclass, asdict

ALL_METRICS = ["si_sdr", "sdr", "sir", "sar", "stoi", "pesq"]


def get_metrics(
    mix,
    clean,
    estimate,
    sample_rate=16000,
    metrics_list="all",
    average=True,
    compute_permutation=False,
    ignore_metrics_errors=False,
    filename=None,
):
    r"""Get speech separation/enhancement metrics from mix/clean/estimate.

    Args:
        mix (np.array): mixture array.
        clean (np.array): reference array.
        estimate (np.array): estimate array.
        sample_rate (int): sampling rate of the audio clips.
        metrics_list (Union[List[str], str): List of metrics to compute.
            Defaults to 'all' (['si_sdr', 'sdr', 'sir', 'sar', 'stoi', 'pesq']).
        average (bool): Return dict([float]) if True, else dict([array]).
        compute_permutation (bool): Whether to compute the permutation on
            estimate sources for the output metrics (default False)
        ignore_metrics_errors (bool): Whether to ignore errors that occur in
            computing the metrics. A warning will be printed instead.
        filename (str, optional): If computing a metric fails, print this
            filename along with the exception/warning message for debugging purposes.

    Shape:
        - mix: :math:`(D, N)` or `(N, )`.
        - clean: :math:`(K\_source, N)` or `(N, )`.
        - estimate: :math:`(K\_target, N)` or `(N, )`.

    Returns:
        dict: Dictionary with all requested metrics, with `'input_'` prefix
        for metrics at the input (mixture against clean), no prefix at the
        output (estimate against clean). Output format depends on average.

    Examples
        >>> import numpy as np
        >>> import pprint
        >>> from asteroid.metrics import get_metrics
        >>> mix = np.random.randn(1, 16000)
        >>> clean = np.random.randn(2, 16000)
        >>> est = np.random.randn(2, 16000)
        >>> metrics_dict = get_metrics(mix, clean, est, sample_rate=8000,
        ...                            metrics_list='all')
        >>> pprint.pprint(metrics_dict)
        {'input_pesq': 1.924380898475647,
         'input_sar': -11.67667585294225,
         'input_sdr': -14.88667106190552,
         'input_si_sdr': -52.43849784881705,
         'input_sir': -0.10419427290163795,
         'input_stoi': 0.015112115177091223,
         'pesq': 1.7713886499404907,
         'sar': -11.610963379923195,
         'sdr': -14.527246041125844,
         'si_sdr': -46.26557128489802,
         'sir': 0.4799929272243427,
         'stoi': 0.022023073540350643}

    """
    if metrics_list == "all":
        metrics_list = ALL_METRICS
    if isinstance(metrics_list, str):
        metrics_list = [metrics_list]
    # For each utterance, we get a dictionary with the input and output metrics
    input_metrics = InputMetrics(
        observation=mix, speech_source=clean, enable_si_sdr=True, sample_rate=sample_rate
    )
    output_metrics = OutputMetrics(
        speech_prediction=estimate,
        speech_source=clean,
        enable_si_sdr=True,
        sample_rate=sample_rate,
        compute_permutation=compute_permutation,
    )
    utt_metrics = {}
    for src, prefix in [(input_metrics, "input_"), (output_metrics, "")]:
        for metric in metrics_list:
            # key: eg. "input_pesq" or "pesq"
            key = prefix + metric
            try:
                utt_metrics[key] = src[metric]
            except Exception as err:
                if ignore_metrics_errors:
                    warnings.warn(
                        f"Error computing {key} for {filename or '<unknown file>'}, ignoring. Error was: {err}",
                        RuntimeWarning,
                    )
                    traceback.print_stack()
                    utt_metrics[key] = None
                else:
                    raise RuntimeError(
                        f"Error computing {key} for {filename or '<unknown file>'}"
                    ) from err
    if average:
        return average_arrays_in_dic(utt_metrics)
    else:
        return utt_metrics


class MetricTracker:
    def __init__(
        self,
        sample_rate,
        metrics_list=tuple(ALL_METRICS),
        average=True,
        compute_permutation=False,
        ignore_metrics_errors=False,
    ):
        self.sample_rate = sample_rate
        # TODO: support WER in metrics_list when merged.
        self.metrics_list = metrics_list
        self.average = average
        self.compute_permutation = compute_permutation
        self.ignore_metrics_errors = ignore_metrics_errors

        self.series_list = []

    def __call__(
        self, *, mix: np.ndarray, clean: np.ndarray, estimate: np.ndarray, filename=None, **kwargs
    ):
        utt_metrics = get_metrics(
            mix,
            clean,
            estimate,
            sample_rate=self.sample_rate,
            metrics_list=self.metrics_list,
            average=self.average,
            compute_permutation=self.compute_permutation,
            ignore_metrics_errors=self.ignore_metrics_errors,
            filename=filename,
        )
        utt_metrics.update(kwargs)
        self.series_list.append(pd.Series(utt_metrics))

    def to_csv(self, path_or_buf):
        """Dump to metrics to csv"""
        all_metrics_df = pd.DataFrame(self.series_list)
        all_metrics_df.to_csv(path_or_buf)

    def final_report(self, dump_path: str = None):
        """Should we make a markdown table? Or JSON. Anyway go through pandas."""
        all_metrics_df = pd.DataFrame(self.series_list)
        # Print and save summary metrics
        final_results = {}
        for metric_name in self.metrics_list:
            input_metric_name = "input_" + metric_name
            ldf = all_metrics_df[metric_name] - all_metrics_df[input_metric_name]
            final_results[metric_name] = all_metrics_df[metric_name].mean()
            final_results[metric_name + "_imp"] = ldf.mean()
        if dump_path is not None:
            dump_path = dump_path + ".json" if not dump_path.endswith(".json") else dump_path
            with open(dump_path, "w") as f:
                json.dump(final_results, f, indent=0)
        return final_results
