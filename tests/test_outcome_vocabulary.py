def test_duplicate_maps_to_duplicates():
    from source_run_reporting import SourceRunReporter
    r = SourceRunReporter("x"); r.record_submission_outcomes(duplicates=2)
    assert r.metrics.duplicates == 2 and r.metrics.reactivated == 0

def test_opportunity_metrics_have_no_reactivation():
    from source_run_reporting import SourceRunReporter
    r = SourceRunReporter("op"); r.record_submission_outcomes(inserted=1, duplicates=1)
    assert r.metrics.reactivated == 0
