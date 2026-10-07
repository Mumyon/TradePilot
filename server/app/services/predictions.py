def get_prediction(symbol: str) -> dict:
    # TODO(ai): inject a trained model/service; preserve model/version/as-of metadata.
    # Never manufacture confidence or label stale predictions as current.
    return {"status": "unavailable", "reason": "prediction_provider_not_configured"}
