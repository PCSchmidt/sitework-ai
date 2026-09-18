from __future__ import annotations

import numpy as np
import pandas as pd
from evaluation.eval_tracking import (
    GT_PEDESTRIAN_CLASS,
    _iou_dist_matrix,
    _load_gt,
    _score_sequence,
)


def test_iou_dist_matrix_perfect_overlap_is_zero_distance() -> None:
    boxes = np.array([[0.0, 0.0, 10.0, 10.0]])
    dist = _iou_dist_matrix(boxes, boxes, max_iou=0.5)
    assert dist.shape == (1, 1)
    assert dist[0, 0] == 0.0


def test_iou_dist_matrix_no_overlap_is_nan() -> None:
    a = np.array([[0.0, 0.0, 10.0, 10.0]])
    b = np.array([[100.0, 100.0, 10.0, 10.0]])
    dist = _iou_dist_matrix(a, b, max_iou=0.5)
    assert np.isnan(dist[0, 0])


def test_iou_dist_matrix_empty_inputs() -> None:
    empty = np.empty((0, 4))
    boxes = np.array([[0.0, 0.0, 10.0, 10.0]])
    assert _iou_dist_matrix(empty, boxes, max_iou=0.5).shape == (0, 0)
    assert _iou_dist_matrix(boxes, empty, max_iou=0.5).shape == (0, 0)


def test_score_sequence_perfect_hypothesis_is_mota_idf1_one(tmp_path) -> None:
    # 2 frames, 1 pedestrian each, hypothesis exactly matches ground truth.
    gt = pd.DataFrame(
        {
            "frame": [1, 2],
            "id": [1, 1],
            "x": [0.0, 1.0],
            "y": [0.0, 1.0],
            "w": [10.0, 10.0],
            "h": [10.0, 10.0],
        }
    )
    hyp = gt.copy()
    result = _score_sequence(gt, hyp, "smoke_test_seq", n_frames=2)
    assert result.mota == 1.0
    assert result.idf1 == 1.0
    assert result.num_switches == 0
    assert result.num_misses == 0
    assert result.num_false_positives == 0


def test_score_sequence_missed_detection_lowers_mota() -> None:
    gt = pd.DataFrame({"frame": [1], "id": [1], "x": [0.0], "y": [0.0], "w": [10.0], "h": [10.0]})
    hyp = pd.DataFrame(columns=["frame", "id", "x", "y", "w", "h"])
    result = _score_sequence(gt, hyp, "smoke_test_seq", n_frames=1)
    assert result.mota < 1.0
    assert result.num_misses == 1


def test_load_gt_filters_to_considered_pedestrians(tmp_path) -> None:
    seq_dir = tmp_path / "MOT17-99-TEST"
    (seq_dir / "gt").mkdir(parents=True)
    # frame,id,x,y,w,h,conf,class,vis -- one real pedestrian (class 1, conf 1),
    # one ignore-region row (class 7, conf 0) that must be filtered out.
    (seq_dir / "gt" / "gt.txt").write_text(
        "1,1,10,10,20,20,1,1,0.9\n"
        "1,2,50,50,20,20,0,7,0.0\n",
        encoding="utf-8",
    )
    gt = _load_gt(seq_dir)
    assert len(gt) == 1
    assert gt.iloc[0]["id"] == 1
    assert gt.iloc[0]["cls"] == GT_PEDESTRIAN_CLASS
