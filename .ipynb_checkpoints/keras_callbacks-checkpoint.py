import logging
import os
from pathlib import Path
from time import sleep
from typing import Callable, List, Optional, Union

import numpy as np
import tensorflow as tf
from packaging.version import parse
from tensorflow.keras.callbacks import Callback

logger = logging.getLogger(__name__)


class KerasMetricCallback(Callback):
    """
    Callback to compute metrics at the end of every epoch. Unlike normal Keras metrics, these do not need to be
    compilable by TF. It is particularly useful for common NLP metrics like BLEU and ROUGE that require string
    operations or generation loops that cannot be compiled. Predictions (or generations) will be computed on the
    `eval_dataset` before being passed to the `metric_fn` in `np.ndarray` format. The `metric_fn` should compute
    metrics and return a dict mapping metric names to metric values.

    We provide an example of a suitable metric_fn that computes ROUGE scores for a summarization model below. Note that
    this example skips some post-processing for readability and simplicity, and should probably not be used as-is!

    ```py
    from datasets import load_metric

    rouge_metric = load_metric("rouge")


    def rouge_fn(predictions, labels):
        decoded_predictions = tokenizer.batch_decode(predictions, skip_special_tokens=True)
        decoded_labels = tokenizer.batch_decode(labels, skip_special_tokens=True)
        result = rouge_metric.compute(predictions=decoded_predictions, references=decoded_labels)
        return {key: value.mid.fmeasure * 100 for key, value in result.items()}
    ```

    The above function will return a dict containing values which will be logged like any other Keras metric:

    ```
    {'rouge1': 37.4199, 'rouge2': 13.9768, 'rougeL': 34.361, 'rougeLsum': 35.0781
    ```

    Args:
        metric_fn (`Callable`):
            Metric function provided by the user. It will be called with two arguments - `predictions` and `labels`.
            These contain the model's outputs and matching labels from the dataset. It should return a dict mapping
            metric names to numerical values.
        eval_dataset (`tf.data.Dataset` or `dict` or `tuple` or `np.ndarray` or `tf.Tensor`):
            Validation data to be used to generate predictions for the `metric_fn`.
        output_cols (`List[str], *optional*):
            A list of columns to be retained from the model output as the predictions. Defaults to all.
        label_cols ('`List[str]`, *optional*'):
            A list of columns to be retained from the input dataset as the labels. Will be autodetected if this is not
            supplied.
        batch_size (`int`, *optional*):
            Batch size. Only used when the data is not a pre-batched `tf.data.Dataset`.
        predict_with_generate (`bool`, *optional*, defaults to `False`):
            Whether we should use `model.generate()` to get outputs for the model.

    """

    def __init__(
        self,
        metric_fn: Callable,
        eval_dataset: Union[tf.data.Dataset, np.ndarray, tf.Tensor, tuple, dict],
        output_cols: Optional[List[str]] = None,
        label_cols: Optional[List[str]] = None,
        batch_size: Optional[int] = None,
        predict_with_generate: Optional[bool] = False,
    ):
        super().__init__()
        self.metric_fn = metric_fn
        self.batch_size = batch_size
        if not isinstance(eval_dataset, tf.data.Dataset):
            if batch_size is None:
                raise ValueError(
                    "When passing data to KerasMetricCallback that is not a pre-batched tf.data.Dataset "
                    "the batch_size argument must be set."
                )
            # Wrap a tf.data.Dataset around it
            eval_dataset = tf.data.Dataset.from_tensor_slices(eval_dataset).batch(batch_size, drop_remainder=False)
        self.eval_dataset = eval_dataset
        self.predict_with_generate = predict_with_generate
        self.output_cols = output_cols

        # This next block attempts to parse out which elements of the dataset should be appended to the labels list
        # that is passed to the metric_fn
        if isinstance(eval_dataset.element_spec, tuple) and len(eval_dataset.element_spec) == 2:
            input_spec, label_spec = eval_dataset.element_spec
        else:
            input_spec = eval_dataset.element_spec
            label_spec = None
        if label_cols is not None:
            for label in label_cols:
                if label not in input_spec:
                    raise ValueError(f"Label {label} is in label_cols but could not be found in the dataset inputs!")
            self.label_cols = label_cols
            self.use_keras_label = False
        elif label_spec is not None:
            # If the dataset inputs are split into a 2-tuple of inputs and labels,
            # assume the second element is the labels
            self.label_cols = None
            self.use_keras_label = True
        elif "labels" in input_spec:
            self.label_cols = ["labels"]
            self.use_keras_label = False
            logging.warning("No label_cols specified for KerasMetricCallback, assuming you want the 'labels' key.")
        elif "start_positions" in input_spec and "end_positions" in input_spec:
            self.label_cols = ["start_positions", "end_positions"]
            self.use_keras_label = False
            logging.warning(
                "No label_cols specified for KerasMetricCallback, assuming you want the "
                "start_positions and end_positions keys."
            )
        else:
            raise ValueError("Could not autodetect label_cols for KerasMetricCallback, please specify them!")
        if parse(tf.__version__) < parse("2.7"):
            logging.warning("TF versions less than 2.7 may encounter issues with KerasMetricCallback!")

    @staticmethod
    def _concatenate_batches(batches, padding_index=-100):
        # If all batches are unidimensional or same length, do a simple concatenation
        if batches[0].ndim == 1 or all([batch.shape[1] == batches[0].shape[1] for batch in batches]):
            return np.concatenate(batches, axis=0)

        # Welp, they're not the same length. Let's do some padding
        max_len = max([batch.shape[1] for batch in batches])
        num_samples = sum([batch.shape[0] for batch in batches])
        output = np.full_like(
            batches[0], fill_value=padding_index, shape=[num_samples, max_len] + list(batches[0].shape[2:])
        )
        # i keeps track of which part of the concatenated array we're writing the next batch to
        i = 0
        for batch in batches:
            output[i : i + len(batch), : batch.shape[1]] = batch
            i += len(batch)
        return output

    def _postprocess_predictions_or_labels(self, inputs):
        if isinstance(inputs[0], dict):
            outputs = dict()
            for key in inputs[0].keys():
                outputs[key] = self._concatenate_batches([batch[key] for batch in inputs])
            # If it's a dict with only one key, just return the array
            if len(outputs) == 1:
                outputs = list(outputs.values())[0]
        elif isinstance(inputs[0], list) or isinstance(inputs[0], tuple):
            outputs = []
            for input_list in zip(*inputs):
                outputs.append(self._concatenate_batches(input_list))
            if len(outputs) == 1:
                outputs = outputs[0]  # If it's a list with only one element, just return the array
        elif isinstance(inputs[0], np.ndarray):
            outputs = self._concatenate_batches(inputs)
        elif isinstance(inputs[0], tf.Tensor):
            outputs = self._concatenate_batches([tensor.numpy() for tensor in inputs])
        else:
            raise TypeError(f"Couldn't handle batch of type {type(inputs[0])}!")
        return outputs

    def on_epoch_end(self, epoch, logs=None):
        if hasattr(self.model, "config"):
            ignore_keys = getattr(self.model.config, "keys_to_ignore_at_inference", [])
        else:
            ignore_keys = []

        main_input_name = None
        if self.predict_with_generate:
            # This dense conditional recognizes the case where we have an encoder-decoder model, but
            # avoids getting tangled up when we just have a model with a layer called 'encoder'
            if hasattr(self.model, "encoder") and hasattr(self.model.encoder, "main_input_name"):
                if self.model.encoder.main_input_name != self.model.main_input_name:
                    main_input_name = self.model.encoder.main_input_name
            else:
                main_input_name = getattr(self.model, "main_input_name", "input_ids")

        prediction_list = []
        label_list = []

        # The whole predict/generate loop is handled inside this method
        for batch in self.eval_dataset:
            if isinstance(batch, tuple):
                batch, labels = batch
            else:
                labels = None
            if self.predict_with_generate:
                if isinstance(batch, dict):
                    generation_inputs = batch[main_input_name]
                    attention_mask = batch.get("attention_mask", None)
                else:
                    generation_inputs = batch
                    attention_mask = None

                predictions = self.model.generate(generation_inputs, attention_mask=attention_mask)
            else:
                predictions = self.model.predict(batch)
                if isinstance(predictions, dict):
                    # This converts any dict-subclass to a regular dict
                    # Keras REALLY doesn't like it when we pass around a BatchEncoding or other derived class
                    predictions = dict(predictions)
                if self.output_cols is not None:
                    predictions = {key: predictions[key] for key in self.output_cols}
                else:
                    predictions = {key: val for key, val in predictions.items() if key not in ignore_keys + ["loss"]}
            prediction_list.append(predictions)
            if not self.use_keras_label:
                labels = {key: batch[key].numpy() for key in self.label_cols}
            elif isinstance(labels, dict):
                labels = {key: array.numpy() for key, array in labels.items()}
            elif isinstance(labels, list) or isinstance(labels, tuple):
                labels = [array.numpy() for array in labels]
            elif isinstance(labels, tf.Tensor):
                labels = labels.numpy()
            else:
                raise TypeError(f"Confused by labels of type {type(labels)}")
            label_list.append(labels)

        all_preds = self._postprocess_predictions_or_labels(prediction_list)
        all_labels = self._postprocess_predictions_or_labels(label_list)

        metric_output = self.metric_fn((all_preds, all_labels))
        if not isinstance(metric_output, dict):
            raise TypeError(
                f"metric_fn should return a dict mapping metric names to values but instead returned {metric_output}"
            )
        # This is the critical bit - Keras passes a dict containing the loss and standard metric values for this epoch
        # in the logs argument. Ordinarily, this is so the callback can read them, but in this case we write a bunch of
        # new keys in there, which will then get read by the History callback and treated like any other metric value.
        # I promise that I have it in writing from Chollet that this is okay.
        logs.update(metric_output)