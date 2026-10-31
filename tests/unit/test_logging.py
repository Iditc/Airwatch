from src.logging_config import get_logger, setup_logging


def test_setup_logging_does_not_raise() -> None:
    setup_logging("INFO")


def test_get_logger_returns_bound_logger() -> None:
    setup_logging("INFO")
    logger = get_logger("test")
    assert logger is not None


def test_logger_can_log_with_context() -> None:
    setup_logging("INFO")
    logger = get_logger("test")
    logger.info("anomaly_detected", station_id="haifa_01", score=0.95)
