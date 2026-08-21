import time
from arena.observability.timing import time_block

def test_time_block_measures_duration():
    with time_block() as t:
        time.sleep(0.01)
    assert t.duration_seconds >= 0.009
    assert t.duration_ms >= 9.0
